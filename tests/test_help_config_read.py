import json
from types import SimpleNamespace

import pytest

from talemate.agents.help import settings
from talemate.agents.help.config_read import (
    MAX_RESPONSE_BYTES,
    read_value,
    response_size,
)
from talemate.config.schema import Config, InferencePresetGroup, InferencePresets


@pytest.fixture
def config(monkeypatch):
    config = Config()
    monkeypatch.setattr(settings, "get_config", lambda: config)
    return config


def reconstruct(value, **kwargs):
    chunks = []
    page = read_value(value, mode="value", **kwargs)
    for _ in range(1000):
        assert response_size(page) <= MAX_RESPONSE_BYTES
        assert page["mode"] == "value"
        assert page["offset"] == sum(map(len, chunks))
        chunks.append(page["chunk"])
        if page["next"] is None:
            assert page["complete"]
            return json.loads("".join(chunks))
        assert not page["complete"]
        page = read_value(value, **kwargs, **page["next"])
    pytest.fail("Paging did not finish")


def test_large_section_is_bounded_and_one_preset_is_exact(config):
    for i in range(80):
        config.presets.inference_groups[f"group.{i}"] = InferencePresetGroup(
            name=f"Group {i}", presets=InferencePresets()
        )
    broad = settings.read_app_config("presets")
    assert broad["mode"] == "index"
    assert response_size(broad) <= MAX_RESPONSE_BYTES
    assert "values" not in broad
    assert "inference_defaults" in {entry["key"] for entry in broad["entries"]}
    narrow = settings.read_app_config(
        "presets", ["inference_groups", "group.4", "presets", "analytical"]
    )
    assert narrow["values"] == config.presets.inference.analytical.model_dump()
    assert narrow["complete"]
    assert response_size(narrow) < 1500
    fields = settings.read_app_config(
        "presets", ["inference", "analytical"], ["top_k", "temperature"]
    )
    assert fields["values"] == {"top_k": 0, "temperature": 0.7}


def test_index_pages_recover_every_entry_and_detail():
    data = {
        f"item.{i:04}": {"n": i, "text": "exact\nvalue", "enabled": bool(i % 2)}
        for i in range(237)
    }
    recovered = {}
    page = read_value(data, mode="index", limit=17)
    for _ in range(20):
        assert response_size(page) <= MAX_RESPONSE_BYTES
        assert page["total_entries"] == len(data)
        for entry in page["entries"]:
            assert entry["key"] not in recovered
            recovered[entry["key"]] = read_value(data, path=[entry["key"]])["values"]
        if page["next"] is None:
            break
        page = read_value(data, limit=17, **page["next"])
    assert recovered == data


@pytest.mark.parametrize(
    "value",
    [
        '雪☃🙂\\"\n' * 9000,
        {
            "entries": [
                {"n": i, "float": 0.95, "null": None, "bool": False} for i in range(500)
            ]
        },
        {"k" * 20000: [1, True, None]},
        [],
        {},
        "",
        None,
        True,
        20,
        0.95,
    ],
)
def test_complete_json_chunk_reconstruction(value):
    assert reconstruct(value) == value
    assert type(reconstruct(value)) is type(value)


def test_oversized_key_has_retrieval_fallback():
    value = {"k" * 20000: "value"}
    page = read_value(value, mode="index")
    assert page["mode"] == "value"
    assert page["offset"] == 0
    assert response_size(page) <= MAX_RESPONSE_BYTES
    assert reconstruct(value) == value


@pytest.mark.parametrize("value", [{}, []])
def test_empty_index(value):
    page = read_value(value, mode="index")
    assert page["entries"] == []
    assert page["total_entries"] == 0
    assert page["complete"] and page["next"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"path": ["missing"]},
        {"path": "a.b"},
        {"path": ["items", -1]},
        {"path": ["items", True]},
        {"path": ["items", "0"]},
        {"fields": ["missing"]},
        {"fields": "items"},
        {"path": ["items"], "fields": []},
        {"offset": -1},
        {"offset": True},
        {"limit": 0},
        {"limit": 101},
        {"limit": 1.5},
        {"mode": "bad"},
        {"mode": "index", "offset": 100},
        {"mode": "value", "offset": 100},
    ],
)
def test_invalid_navigation(kwargs):
    assert "error" in read_value({"items": [1, 2]}, **kwargs)


def test_array_navigation_and_scalar_types():
    assert (
        read_value({"items": [None, False, 3.5]}, path=["items", 1])["values"] is False
    )
    assert (
        read_value({"items": [None, False, 3.5]}, path=["items", 0])["values"] is None
    )


def test_changed_value_refuses_mixed_pages():
    data = {str(i): i for i in range(30)}
    first = read_value(data, mode="index")
    data["0"] = 42
    assert "changed" in read_value(data, **first["next"])["error"]
    first = read_value("x" * 10000, mode="value")
    assert "changed" in read_value("y" * 10000, **first["next"])["error"]


@pytest.mark.parametrize("nested", [False, True])
def test_reordering_objects_between_chunks_preserves_every_key(nested):
    original = {"z": "Z" * 12000, "a": "A" * 12000}
    reordered = dict(reversed(list(original.items())))
    if nested:
        original = {"outer": [original]}
        reordered = {"outer": [reordered]}
    page = read_value(original, mode="value")
    chunks = [page["chunk"]]
    first_revision = page["revision"]
    assert page["next"] is not None
    while page["next"] is not None:
        page = read_value(reordered, **page["next"])
        assert response_size(page) <= MAX_RESPONSE_BYTES
        assert page["revision"] == first_revision
        assert page["offset"] == sum(map(len, chunks))
        chunks.append(page["chunk"])
    assert json.loads("".join(chunks)) == original


def test_reordered_field_selection_between_tool_chunks_is_exact(config):
    row = config.presets.inference.analytical
    row.dry_sequence_breakers = "Z" * 12000
    row.extra_stopping_strings = ["A" * 12000]
    fields = ["dry_sequence_breakers", "extra_stopping_strings"]
    path = ["inference", "analytical"]
    page = settings.read_app_config("presets", path, fields, mode="value")
    chunks = [page["chunk"]]
    while page["next"] is not None:
        page = settings.read_app_config("presets", path, fields[::-1], **page["next"])
        assert response_size(page) <= MAX_RESPONSE_BYTES
        chunks.append(page["chunk"])
    assert json.loads("".join(chunks)) == {
        field: getattr(row, field) for field in fields
    }


def test_redaction_precedes_detail_index_and_chunks(monkeypatch):
    data = {"nested": {"api_key": "synthetic-secret" * 2000, "safe": "x" * 20000}}
    config = SimpleNamespace(game=SimpleNamespace(model_dump=lambda: data))
    monkeypatch.setattr(settings, "get_config", lambda: config)
    assert (
        settings.read_app_config("game", ["nested", "api_key"])["values"]
        == settings.REDACTED
    )
    pages = []
    page = settings.read_app_config("game", mode="value")
    for _ in range(20):
        assert "synthetic-secret" not in json.dumps(page)
        assert response_size(page) <= MAX_RESPONSE_BYTES
        pages.append(page["chunk"])
        if page["next"] is None:
            break
        page = settings.read_app_config("game", **page["next"])
    restored = json.loads("".join(pages))
    assert restored == {
        "nested": {"api_key": settings.REDACTED, "safe": data["nested"]["safe"]}
    }
    assert "error" in settings.read_app_config("game", ["nested", "api_key", 0])


def test_read_section_permissions_and_defaults(config):
    assert settings.read_app_config()["sections"] == list(
        settings.READABLE_CONFIG_SECTIONS
    )
    for section in ("clients", "agents", "openrouter", "../config.yaml", "x" * 20000):
        result = settings.read_app_config(section, mode="value")
        assert "unavailable" in result
        assert response_size(result) <= MAX_RESPONSE_BYTES
    assert (
        settings.read_app_config("presets", ["inference_defaults", "analytical"])[
            "values"
        ]
        == config.presets.inference_defaults.analytical.model_dump()
    )
