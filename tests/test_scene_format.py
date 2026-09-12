import copy
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from typing import get_args

import pytest

import talemate.instance as instance
import talemate.knowledge.mode as knowledge_mode
from _changelog_test_helpers import make_changelog_scene
from conftest import MockScene, bootstrap_scene
from talemate.changelog import (
    fork_scene_at_revision,
    save_changelog,
    write_reconstructed_scene,
)
from talemate.export import ExportOptions, scene_export_json
from talemate.exceptions import TalemateError
from talemate.knowledge.mode import KnowledgeEligibility, character_knowledge_enabled
from talemate.load import (
    load_scene,
    load_scene_from_data,
    load_scene_from_zip,
    new_scene,
    SceneInitialization,
)
from talemate.scene.format import (
    SceneFormatError,
    normalize_scene_format,
    read_scene_format,
)
from talemate.tale_mate import Scene


FIXTURES = Path(__file__).parent / "data" / "scene_format"


def fixture_data(name="legacy"):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def load_env(tmp_path, monkeypatch):
    scene = MockScene()
    bootstrap_scene(scene)
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    memory = instance.get_agent("memory")
    monkeypatch.setattr(memory, "set_db", AsyncMock(), raising=False)
    monkeypatch.setattr(memory, "close_db", Mock(), raising=False)
    monkeypatch.setattr(
        memory, "get_document", AsyncMock(return_value={}), raising=False
    )
    return scene


@pytest.mark.parametrize("name", ["legacy", "versioned"])
async def test_load_save_reload_retains_legacy_eligibility(load_env, name):
    data = fixture_data(name)
    await load_scene_from_data(load_env, data, name="original.json")
    original_history = [message.to_dict() for message in load_env.history]
    assert not character_knowledge_enabled(load_env)

    await load_env.save()
    path = Path(load_env.save_dir) / "original.json"
    saved = json.loads(path.read_text())
    assert saved["format_version"] == 1
    assert saved["knowledge_eligibility"] == "legacy"
    assert saved["history"] == original_history

    await load_scene_from_data(load_env, saved, name=str(path))
    assert load_env.knowledge_eligibility == "legacy"
    assert [message.to_dict() for message in load_env.history] == original_history


@pytest.mark.parametrize("save_as", [False, True])
async def test_saving_never_promotes_legacy(load_env, monkeypatch, save_as):
    await load_scene_from_data(load_env, fixture_data(), name="original.json")
    await load_env.save(copy_name="copy.json" if save_as else None)
    saved = json.loads((Path(load_env.save_dir) / load_env.filename).read_text())
    assert saved["knowledge_eligibility"] == "legacy"
    assert not character_knowledge_enabled(load_env)


@pytest.mark.parametrize("name", ["legacy", "versioned", "perception"])
async def test_reset_preserves_eligibility(load_env, monkeypatch, name):
    data = fixture_data(name)
    expected = data.get("knowledge_eligibility", "legacy")
    await load_scene_from_data(load_env, data, reset=True, empty=True)
    assert load_env.knowledge_eligibility == expected
    assert load_env.serialize["knowledge_eligibility"] == expected


async def test_perception_fixture_round_trip(load_env, monkeypatch):
    await load_scene_from_data(
        load_env, fixture_data("perception"), name="perception.json"
    )
    assert character_knowledge_enabled(load_env)
    await load_env.save()
    saved = json.loads((Path(load_env.save_dir) / "perception.json").read_text())
    await load_scene_from_data(load_env, saved)
    assert saved["format_version"] == 1
    assert saved["knowledge_eligibility"] == "perception"
    assert character_knowledge_enabled(load_env)

    await load_scene_from_data(load_env, fixture_data())
    assert load_env.knowledge_eligibility == "legacy"
    assert not character_knowledge_enabled(load_env)


@pytest.mark.parametrize("gate", [None, "0", "true", "1"])
def test_public_mode_ignores_retired_development_flag(monkeypatch, gate):
    monkeypatch.delenv("TALEMATE_DEV_CHARACTER_KNOWLEDGE", raising=False)
    if gate is not None:
        monkeypatch.setenv("TALEMATE_DEV_CHARACTER_KNOWLEDGE", gate)
    scene = Scene()
    assert not character_knowledge_enabled(scene)
    scene.knowledge_eligibility = "perception"
    assert character_knowledge_enabled(scene)


@pytest.mark.parametrize("version", [None, True, False, "1", 1.0, 0, -1, [], {}])
def test_invalid_version_rejected(version):
    with pytest.raises(SceneFormatError, match="positive integer"):
        read_scene_format({"format_version": version})


@pytest.mark.parametrize("eligibility", [None, True, "unknown", [], {}])
def test_invalid_eligibility_rejected(eligibility):
    with pytest.raises(SceneFormatError, match="Invalid knowledge_eligibility"):
        read_scene_format({"format_version": 1, "knowledge_eligibility": eligibility})


def test_absent_eligibility_defaults_to_legacy():
    assert read_scene_format({"format_version": 1}).knowledge_eligibility == "legacy"


@pytest.mark.parametrize("data,version", [({}, 0), ({"format_version": 1}, 1)])
def test_parser_reports_source_version_and_normalizer_reports_write_version(
    data, version
):
    assert read_scene_format(data).format_version == version
    assert normalize_scene_format(data)["format_version"] == 1


def test_schema_eligibility_matches_runtime_definition():
    schema = json.loads(
        (FIXTURES.parents[2] / "docs/talemate-scene-schema.json").read_text()
    )
    assert schema["properties"]["knowledge_eligibility"]["enum"] == list(
        get_args(KnowledgeEligibility)
    )


async def test_parser_and_scene_serialization_do_not_consult_process_policy(
    load_env, monkeypatch
):
    data = fixture_data("perception")
    await load_scene_from_data(load_env, data)
    expected = load_env.json
    assert not hasattr(knowledge_mode, "os")
    assert read_scene_format(data).knowledge_eligibility == "perception"
    assert normalize_scene_format(data)["knowledge_eligibility"] == "perception"
    assert load_env.json == expected


def test_unversioned_data_cannot_claim_perception(monkeypatch):
    with pytest.raises(SceneFormatError, match="Unversioned scenes"):
        read_scene_format({"knowledge_eligibility": "perception"})


@pytest.mark.parametrize("data", [None, [], "scene"])
def test_non_object_data_rejected(data):
    with pytest.raises(SceneFormatError, match="JSON object"):
        normalize_scene_format(data)


def test_normalization_preserves_payload_without_mutating_input():
    data = fixture_data()
    before = copy.deepcopy(data)
    normalized = normalize_scene_format(data)
    assert data == before
    assert normalized == {
        **before,
        "format_version": 1,
        "knowledge_eligibility": "legacy",
    }


def test_new_scenes_default_to_legacy(monkeypatch):
    assert read_scene_format(new_scene()).knowledge_eligibility == "legacy"
    assert Scene().serialize["knowledge_eligibility"] == "legacy"


@pytest.mark.parametrize(
    "metadata,error",
    [
        ({"format_version": 2}, "Unsupported scene format version 2"),
        ({"format_version": "1"}, "positive integer"),
    ],
)
async def test_rejected_load_precedes_migrations_and_runtime_changes(
    load_env, tmp_path, metadata, error
):
    data = {**fixture_data(), **metadata}
    del data["character_data"]
    data["characters"] = [{"name": "Would migrate"}]
    before_data = copy.deepcopy(data)
    before_scene = load_env.json
    with pytest.raises(TalemateError, match=error):
        await load_scene_from_data(load_env, data)
    assert data == before_data
    assert load_env.json == before_scene
    instance.get_agent("memory").set_db.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("metadata", [{"format_version": 2}, {"format_version": None}])
async def test_rejected_file_unchanged_and_no_import_writes(
    load_env, tmp_path, monkeypatch, archive, metadata
):
    data = {**fixture_data(), **metadata}
    path = tmp_path / ("future.zip" if archive else "future.json")
    if archive:
        with zipfile.ZipFile(path, "w") as zipf:
            zipf.writestr("scene.json", json.dumps(data))
            zipf.writestr("asset.txt", "must not be extracted")
    else:
        path.write_text(json.dumps(data))
    before_file = path.read_bytes()
    before_scene = load_env.json
    extract = Mock(side_effect=AssertionError("must validate before extraction"))
    monkeypatch.setattr(zipfile.ZipFile, "extractall", extract)
    loader = load_scene_from_zip if archive else load_scene
    with pytest.raises(SceneFormatError):
        await loader(load_env, str(path))
    assert path.read_bytes() == before_file
    assert list(tmp_path.iterdir()) == [path]
    assert load_env.json == before_scene
    extract.assert_not_called()
    load_env.commit_to_memory.assert_not_called()
    load_env.add_to_recent_scenes.assert_not_called()


@pytest.mark.parametrize("name", ["versioned", "perception"])
async def test_valid_zip_loads_and_writes_saved_mode(load_env, tmp_path, name):
    path = tmp_path / "versioned.zip"
    data = fixture_data("versioned")
    data["knowledge_eligibility"] = "perception" if name == "perception" else "legacy"
    with zipfile.ZipFile(path, "w") as zipf:
        zipf.writestr("scene.json", json.dumps(data))
        zipf.writestr("info/imported.md", "Imported archive content")
    original = path.read_bytes()
    scene = await load_scene_from_zip(load_env, str(path))
    assert scene.knowledge_eligibility == (
        "perception" if name == "perception" else "legacy"
    )
    assert [message.message for message in scene.history] == [
        message["message"] for message in data["history"]
    ]
    for filename in ["versioned.json", "initial.json"]:
        saved = json.loads((Path(scene.save_dir) / filename).read_text())
        assert saved["format_version"] == 1
        assert saved["knowledge_eligibility"] == (
            "perception" if name == "perception" else "legacy"
        )
    assert (
        Path(scene.save_dir) / "info/imported.md"
    ).read_text() == "Imported archive content"
    assert path.read_bytes() == original


@pytest.mark.parametrize("name", ["legacy", "perception"])
async def test_shallow_fork_retains_eligibility(load_env, monkeypatch, name):
    data = fixture_data()
    if name == "perception":
        data.update(format_version=1, knowledge_eligibility="perception")
    await load_scene_from_data(load_env, data)
    creator = instance.get_agent("creator")
    fork_path = await creator.fork_scene(load_env.history[0].id, save_name="shallow")
    forked = json.loads(Path(fork_path).read_text())
    assert forked["format_version"] == 1
    assert forked["knowledge_eligibility"] == name
    await load_scene_from_data(load_env, forked)
    assert load_env.knowledge_eligibility == name


@pytest.mark.parametrize("name", ["legacy", "versioned", "perception"])
async def test_reconstructed_fork_retains_snapshot_eligibility(
    load_env, tmp_path, monkeypatch, name
):
    data = fixture_data(name)
    source = make_changelog_scene(str(tmp_path / "chain"), initial_serialize=data)
    await save_changelog(source)
    before = {
        p: p.read_bytes() for p in Path(source.changelog_dir).rglob("*") if p.is_file()
    }
    source.knowledge_eligibility = "perception"
    fork_path = await fork_scene_at_revision(source, 0, "reconstructed")
    forked = json.loads(Path(fork_path).read_text())
    assert forked["format_version"] == 1
    assert forked["knowledge_eligibility"] == data.get(
        "knowledge_eligibility", "legacy"
    )
    assert {p: p.read_bytes() for p in before} == before
    await load_scene_from_data(load_env, forked)
    assert load_env.knowledge_eligibility == forked["knowledge_eligibility"]


async def test_reconstructed_write_rejects_future_before_mutation_or_write(tmp_path):
    source = make_changelog_scene(str(tmp_path))
    data = {**fixture_data(), "format_version": 2}
    data["history"][0]["rev"] = 10
    before = copy.deepcopy(data)
    with pytest.raises(SceneFormatError, match="Unsupported scene format"):
        await write_reconstructed_scene(
            source, 0, precomputed_data=data, zero_message_revs=True
        )
    assert data == before
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "metadata,overrides,error",
    [
        ({"format_version": 2}, {"format_version": 1}, "Unsupported scene format"),
        (
            {"format_version": 1, "knowledge_eligibility": "perception"},
            {"knowledge_eligibility": "legacy"},
            "overrides cannot change",
        ),
        ({}, {"knowledge_eligibility": "perception"}, "overrides cannot change"),
        ({}, {"format_version": 2}, "overrides cannot change"),
    ],
)
async def test_reconstruction_overrides_cannot_relabel_metadata(
    tmp_path, metadata, overrides, error
):
    source = make_changelog_scene(str(tmp_path))
    data = {**fixture_data(), **metadata}
    data["history"][0]["rev"] = 10
    before = copy.deepcopy(data)
    with pytest.raises(TalemateError, match=error):
        await write_reconstructed_scene(
            source,
            0,
            precomputed_data=data,
            overrides=overrides,
            zero_message_revs=True,
        )
    assert data == before
    assert list(tmp_path.iterdir()) == []


async def test_reconstruction_applies_history_override_after_zeroing(tmp_path):
    source = make_changelog_scene(str(tmp_path))
    data = fixture_data()
    data["history"][0]["rev"] = 10
    history_override = [{**data["history"][0], "rev": 7}]
    path = await write_reconstructed_scene(
        source,
        0,
        precomputed_data=data,
        overrides={"history": history_override},
        zero_message_revs=True,
    )
    assert json.loads(Path(path).read_text())["history"][0]["rev"] == 7
    assert history_override[0]["rev"] == 7


@pytest.mark.parametrize("name", ["legacy", "perception"])
async def test_restore_and_export_preserve_eligibility(load_env, monkeypatch, name):
    await load_scene_from_data(load_env, fixture_data(name))
    await load_env.save_restore("initial.json")
    restored = json.loads((Path(load_env.save_dir) / "initial.json").read_text())
    for data in [
        restored,
        json.loads(scene_export_json(load_env, ExportOptions(name="export"))),
    ]:
        assert data["format_version"] == 1
        assert data["knowledge_eligibility"] == name


@pytest.mark.parametrize("restore_save", [False, True])
async def test_save_boundary_supports_public_perception_scene(load_env, restore_save):
    await load_scene_from_data(load_env, fixture_data("perception"))
    if restore_save:
        await load_env.save_restore("public.json")
    else:
        await load_env.save(copy_name="public")
    data = json.loads((Path(load_env.save_dir) / "public.json").read_text())
    assert data["knowledge_eligibility"] == "perception"
    assert data["format_version"] == 1


async def test_restore_entry_point_retains_legacy_eligibility(load_env, monkeypatch):
    await load_scene_from_data(load_env, fixture_data())
    await load_env.save_restore("initial.json")
    load_env.restore_from = "initial.json"
    load_env.history.clear()
    monkeypatch.setattr(load_env, "reset_memory", AsyncMock())
    await load_env.restore(save_as="restored.json")
    assert load_env.knowledge_eligibility == "legacy"
    assert load_env.history[0].message == fixture_data()["history"][0]["message"]
    restored = json.loads((Path(load_env.save_dir) / "restored.json").read_text())
    assert restored["format_version"] == 1
    assert restored["knowledge_eligibility"] == "legacy"


@pytest.mark.parametrize("enabled", [False, True])
async def test_creation_opt_in_round_trip(load_env, enabled):
    data = new_scene(SceneInitialization(character_knowledge=enabled))
    assert "character_knowledge" not in data
    await load_scene_from_data(load_env, data, name="choice.json")
    assert character_knowledge_enabled(load_env) is enabled
    await load_env.save()
    saved = json.loads((Path(load_env.save_dir) / "choice.json").read_text())
    await load_scene_from_data(load_env, saved)
    assert character_knowledge_enabled(load_env) is enabled


def test_creation_payload_cannot_supply_history_or_relabel_legacy():
    payload = SceneInitialization(
        character_knowledge=True, history=["old"], knowledge_eligibility="legacy"
    )
    data = new_scene(payload)
    assert data["history"] == []
    assert data["knowledge_eligibility"] == "perception"


async def test_new_story_option_cannot_convert_loaded_legacy_file(load_env, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps(fixture_data()))
    await load_scene(
        load_env,
        str(path),
        scene_initialization=SceneInitialization(character_knowledge=True),
    )
    assert load_env.knowledge_eligibility == "legacy"
    assert not character_knowledge_enabled(load_env)


@pytest.mark.parametrize("extension", [".json", ".png", ".webp"])
@pytest.mark.parametrize("enabled", [None, False, True])
async def test_card_dispatch_forwards_creation_choice(
    load_env, tmp_path, monkeypatch, extension, enabled
):
    path = tmp_path / f"card{extension}"
    path.write_text(json.dumps({"spec": "chara_card_v2", "data": {"name": "Hero"}}))
    loader = AsyncMock(return_value=load_env)
    monkeypatch.setattr("talemate.load.load_scene_from_character_card", loader)
    initialization = (
        SceneInitialization(character_knowledge=enabled)
        if enabled is not None
        else None
    )
    await load_scene(load_env, str(path), scene_initialization=initialization)
    loader.assert_awaited_once()
    assert loader.await_args.kwargs["character_knowledge"] is (enabled is True)


@pytest.mark.parametrize("starting_mode", ["legacy", "perception"])
async def test_empty_scene_mode_switch_round_trip(load_env, starting_mode):
    from talemate.world_state.manager import WorldStateManager

    await load_scene_from_data(
        load_env,
        new_scene(
            SceneInitialization(character_knowledge=starting_mode == "perception")
        ),
        name="switch.json",
    )
    target = "perception" if starting_mode == "legacy" else "legacy"
    await WorldStateManager(load_env).update_scene_settings(
        knowledge_eligibility=target
    )
    await load_env.save()
    saved = json.loads((Path(load_env.save_dir) / "switch.json").read_text())
    assert saved["format_version"] == 1
    assert saved["knowledge_eligibility"] == target
    await load_scene_from_data(load_env, saved)
    assert load_env.knowledge_eligibility == target
    assert load_env.can_change_knowledge_eligibility


@pytest.mark.parametrize("with_sources", [False, True])
async def test_disclosure_scene_switch_off_save_reload(load_env, with_sources):
    from _world_state_helpers import make_actor
    from talemate.knowledge.disclosures import grant_disclosure
    from talemate.world_state.manager import WorldStateManager

    await load_scene_from_data(
        load_env,
        new_scene(SceneInitialization(character_knowledge=True)),
        name="switch-disclosure.json",
    )
    character = make_actor(load_env, "Alice")
    character.description = "The key is brass."
    grant_disclosure(load_env, "Alice", "Alice.description.0", whole_entry=True)
    assert load_env.knowledge.disclosures
    if with_sources:
        from talemate.knowledge.perspectives import set_source_perspectives
        from talemate.scene_message import ReinforcementMessage
        from talemate.world_state import Reinforcement

        source = ReinforcementMessage(message="The key is brass.", source="key")
        load_env.world_state.reinforce.append(
            Reinforcement(
                question="What is the key made of?",
                insert="all-context",
                perspective_source=source,
            )
        )
        views = [
            {"audience": ["Alice"], "text": "The key is brass.", "status": "ready"}
        ]
        set_source_perspectives(load_env, "message", source.id, views)
        load_env.layered_history = [
            [{"id": "key-summary", "text": "The key is brass."}]
        ]
        set_source_perspectives(load_env, "summary", "key-summary", views, layer=1)
    assert load_env.can_change_knowledge_eligibility
    await WorldStateManager(load_env).update_scene_settings(
        knowledge_eligibility="legacy"
    )
    await load_env.save()
    path = Path(load_env.save_dir) / "switch-disclosure.json"
    saved = json.loads(path.read_text())
    assert "knowledge" not in saved
    if with_sources:
        assert (
            "knowledge"
            not in saved["world_state"]["reinforce"][0]["perspective_source"]
        )
        assert "knowledge" not in saved["layered_history"][0][0]
    assert saved["format_version"] == 1
    assert saved["knowledge_eligibility"] == "legacy"
    await load_scene_from_data(load_env, saved)
    assert load_env.knowledge_eligibility == "legacy"
    assert load_env.knowledge is None
