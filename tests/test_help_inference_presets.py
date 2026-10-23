import copy
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.agents.help.storage as storage
import talemate.instance as instance
from talemate.client.presets import get_inference_parameters
from talemate.agents.help import HelpAgent, inference_presets as presets
from talemate.agents.help.chat import SETTINGS_PERMISSION
from talemate.config.schema import Config, InferencePresetGroup, InferencePresets
from conftest import MockClient, MockClientContext, bootstrap_engine, client_responses


@pytest.fixture
def config(tmp_path, monkeypatch):
    config = Config()
    monkeypatch.setattr(config_state, "CONFIG", config)
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")
    for signal in ("config.changed", "config.changed.follow", "config.saved"):
        async_signals.get(signal).receivers.clear()
    rows = InferencePresets()
    for key in InferencePresets.model_fields:
        row = getattr(rows, key)
        row.temperature = 1.5
        row.top_k = 64
        row.dry_multiplier = 2.0
        row.extra_stopping_strings = ["UNRELATED"]
        row.changed = True
    config.presets.inference_groups["qwen"] = InferencePresetGroup(
        name="Qwen 3.8", presets=rows
    )
    config.presets.inference_groups["other"] = InferencePresetGroup(
        name="Other", presets=rows.model_copy(deep=True)
    )
    return config


def test_description_matches_every_editor_control():
    root = Path(__file__).parents[1]
    source = (
        root / "talemate_frontend/src/components/InferenceParamsForm.vue"
    ).read_text()
    controls = re.findall(
        r'v-model="preset\.(\w+)" min="([\d.\-]+)" max="([\d.\-]+)" step="([\d.\-]+)"',
        source,
    )
    assert {
        name: tuple(map(float, (low, high, step))) for name, low, high, step in controls
    } == presets.NUMERIC_PARAMETERS
    fields = set(re.findall(r'v-model="preset\.(\w+)"', source))
    description = presets.describe_inference_parameters()
    assert set(description["parameters"]) == fields
    assert "changed" not in fields


async def test_all_presets_reset_to_each_authoritative_default_and_persist(config):
    before = config.model_dump()
    values = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
    result = await presets.update_inference_presets(
        "Qwen 3.8", "all", values, reset_rest=True
    )
    assert result["applied"] is True
    assert result["group_key"] == "qwen"
    assert set(result["presets"]) == set(InferencePresets.model_fields)
    saved = yaml.safe_load(config_state.CONFIG_FILE.read_text())
    reloaded = Config.model_validate(saved)
    for key in InferencePresets.model_fields:
        expected = {
            **getattr(config.presets.inference_defaults, key).model_dump(),
            **values,
            "changed": True,
        }
        assert (
            getattr(config.presets.inference_groups["qwen"].presets, key).model_dump()
            == expected
        )
        assert (
            getattr(reloaded.presets.inference_groups["qwen"].presets, key).model_dump()
            == expected
        )
        assert result["values"][key] == {
            k: v for k, v in expected.items() if k != "changed"
        }
    assert (
        config.presets.inference_groups["other"].model_dump()
        == before["presets"]["inference_groups"]["other"]
    )
    assert config.presets.inference.model_dump() == before["presets"]["inference"]
    assert config.appearance.model_dump() == before["appearance"]
    assert (
        config.presets.inference_groups["qwen"].presets.analytical.presence_penalty == 0
    )
    assert (
        config.presets.inference_groups["qwen"].presets.creative.presence_penalty == 0.2
    )
    assert get_inference_parameters("analytical", "qwen")["top_k"] == 20
    assert get_inference_parameters("analytical", "qwen")["presence_penalty"] == 0


async def test_one_partial_update_preserves_every_other_field(config):
    before = config.presets.model_dump()
    result = await presets.update_inference_presets(
        "qwen", "creative instruction", {"top_k": 20}
    )
    assert result["applied"]
    expected = copy.deepcopy(before)
    expected["inference_groups"]["qwen"]["presets"]["creative_instruction"]["top_k"] = (
        20
    )
    assert config.presets.model_dump() == expected
    assert result["values"] == {"creative_instruction": {"top_k": 20}}


async def test_default_group_and_advanced_fields(config):
    result = await presets.update_inference_presets(
        "",
        "analytical",
        {
            "temperature_last": False,
            "dry_base": 1.9,
            "dry_multiplier": 0.2,
            "dry_allowed_length": 4,
            "dry_sequence_breakers": '"\\n", ":"',
            "xtc_threshold": 0.4,
            "xtc_probability": 0.3,
            "smoothing_factor": 0.25,
            "smoothing_curve": 0.65,
            "adaptive_target": -0.01,
            "adaptive_decay": 0.88,
            "repetition_penalty_range": 4096,
            "extra_stopping_strings": ["", "   ", "Stop: "],
        },
    )
    assert result["applied"]
    row = config.presets.inference.analytical
    assert row.temperature_last is False
    assert row.extra_stopping_strings == ["Stop: "]
    assert row.dry_base == 1.9
    assert result["values"]["analytical"]["extra_stopping_strings"] == ["Stop: "]
    reloaded = Config.model_validate(
        yaml.safe_load(config_state.CONFIG_FILE.read_text())
    )
    assert reloaded.presets.inference.analytical == row


@pytest.mark.parametrize(
    "parameters",
    [
        {"unknown": 1},
        {"changed": True},
        {"name": "Other"},
        {"temperature": True},
        {"temperature": "1.0"},
        {"temperature": None},
        {"temperature": float("nan")},
        {"temperature": float("inf")},
        {"temperature": 10**400},
        {"temperature": 0},
        {"temperature": 2.01},
        {"temperature": 1.001},
        {"top_k": 20.5},
        {"repetition_penalty_range": 100},
        {"dry_multiplier": 0.15},
        {"adaptive_target": -0.02},
        {"temperature_last": "false"},
        {"dry_sequence_breakers": []},
        {"extra_stopping_strings": "STOP"},
        {"extra_stopping_strings": [1]},
        {"top_k": 20, "temperature": 4.0},
        [],
        None,
    ],
)
async def test_invalid_parameters_make_no_changes(config, parameters):
    before = config.model_dump()
    result = await presets.update_inference_presets("qwen", "all", parameters)
    assert isinstance(result, str)
    assert config.model_dump() == before
    assert not config_state.CONFIG_FILE.exists()


@pytest.mark.parametrize(
    "group,preset,reset",
    [
        ("missing", "all", False),
        (None, "all", False),
        ("qwen", "missing", False),
        ("qwen", None, False),
        ("qwen", "all", "false"),
    ],
)
async def test_unknown_targets_and_invalid_reset(config, group, preset, reset):
    before = config.model_dump()
    assert isinstance(
        await presets.update_inference_presets(group, preset, {"top_k": 20}, reset), str
    )
    assert config.model_dump() == before


async def test_ambiguous_names_refuse_without_selecting_another_group(config):
    config.presets.inference_groups["other"].name = "Qwen 3.8"
    before = config.model_dump()
    result = await presets.update_inference_presets("Qwen 3.8", "all", {"top_k": 20})
    assert "Ambiguous" in result
    assert config.model_dump() == before
    assert (await presets.update_inference_presets("qwen", "all", {"top_k": 20}))[
        "applied"
    ]


@pytest.mark.parametrize("key", ["Qwen", "qwen", "collision", "Default", ""])
async def test_exact_keys_disambiguate_without_touching_other_groups(config, key):
    for group_key, name in [
        ("Qwen", "Qwen"),
        ("qwen", "qwen"),
        ("collision", "Distinct display name"),
        ("display-collision", "collision"),
        ("Default", "Default"),
    ]:
        config.presets.inference_groups[group_key] = InferencePresetGroup(
            name=name, presets=InferencePresets()
        )
    before = config.presets.model_dump()
    agent = HelpAgent(client=MockClient("test"))
    agent.actions["permissions"].config["allow_settings_changes"].value = True
    callback = next(
        cb
        for cb in agent._chat_settings_callbacks()
        if cb.name == "update_inference_presets"
    )
    result = await callback.fn(key, "analytical", {"top_k": 20}, group_is_key=True)
    assert result["applied"] and result["group_key"] == key
    scope = before["inference_groups"][key]["presets"] if key else before["inference"]
    scope["analytical"].update(top_k=20, changed=True)
    assert config.presets.model_dump() == before
    reloaded = Config.model_validate(
        yaml.safe_load(config_state.CONFIG_FILE.read_text())
    )
    assert reloaded.presets.model_dump() == before


@pytest.mark.parametrize("name", ["Qwen", "qwen", "QWEN", "collision", "Default"])
async def test_name_only_collisions_still_require_clarification(config, name):
    for key, display in [
        ("Qwen", "Qwen"),
        ("qwen", "qwen"),
        ("collision", "One"),
        ("another", "collision"),
        ("Default", "Default"),
    ]:
        config.presets.inference_groups[key] = InferencePresetGroup(
            name=display, presets=InferencePresets()
        )
    before = config.model_dump()
    result = await presets.update_inference_presets(name, "all", {"top_k": 20})
    assert "Ambiguous" in result
    assert config.model_dump() == before
    assert not config_state.CONFIG_FILE.exists()


@pytest.mark.parametrize("key", ["QWEN", " qwen ", "Qwen 3.8", "missing"])
async def test_exact_key_never_falls_back_to_normalized_key_or_name(config, key):
    before = config.model_dump()
    result = await presets.update_inference_presets(
        key, "all", {"top_k": 20}, group_is_key=True
    )
    assert "Unknown group key" in result
    assert config.model_dump() == before


async def test_invalid_exact_key_flag_refuses(config):
    before = config.model_dump()
    result = await presets.update_inference_presets(
        "qwen", "all", {"top_k": 20}, group_is_key="false"
    )
    assert "must be a boolean" in result
    assert config.model_dump() == before


@pytest.mark.parametrize("group_is_key", [False, True])
async def test_dirty_settings_refuse(config, group_is_key):
    before = config.model_dump()
    result = await presets.update_inference_presets(
        "qwen", "all", {"top_k": 20}, app_settings_dirty=True, group_is_key=group_is_key
    )
    assert "unsaved edits" in result
    assert config.model_dump() == before


async def test_persistence_failure_is_not_success(config, monkeypatch):
    monkeypatch.setattr(
        presets,
        "commit_config",
        AsyncMock(side_effect=OSError("synthetic disk failure")),
    )
    result = await presets.update_inference_presets("qwen", "all", {"top_k": 20})
    assert result["applied"] is False
    assert result["in_memory_applied"] is True
    assert result["persistence"] == "unconfirmed"
    assert "OSError" in result["error"]
    assert config.presets.inference_groups["qwen"].presets.creative.top_k == 20
    assert not config_state.CONFIG_FILE.exists()


@pytest.mark.parametrize("group_is_key", [False, True])
async def test_callback_permission_revocation(config, group_is_key):
    agent = HelpAgent(client=MockClient("test"))
    assert "update_inference_presets" not in {
        cb.name for cb in agent._chat_settings_callbacks()
    }
    agent.actions["permissions"].config["allow_settings_changes"].value = True
    callback = next(
        cb
        for cb in agent._chat_settings_callbacks()
        if cb.name == "update_inference_presets"
    )
    agent.actions["permissions"].config["allow_settings_changes"].value = False
    before = config.model_dump()
    result = await callback.fn("qwen", "all", {"top_k": 20}, group_is_key=group_is_key)
    assert SETTINGS_PERMISSION in result and "was turned off" in result
    assert config.model_dump() == before


async def test_help_chat_tool_result_reports_actual_applied_values(
    config, tmp_path, monkeypatch
):
    bootstrap_engine()
    monkeypatch.setattr(storage, "HELP_CHATS_DIR", tmp_path)
    monkeypatch.setattr(storage, "HELP_CHATS_FILE", tmp_path / "help.json")
    agent = instance.AGENTS["help"]
    agent.client = MockClient("test")
    agent.actions["permissions"].config["allow_settings_changes"].value = True
    config.presets.inference_groups["QWEN"] = InferencePresetGroup(
        name="Qwen 3.8", presets=InferencePresets()
    )
    for signal in ("config.changed", "config.changed.follow", "config.saved"):
        async_signals.get(signal).receivers.clear()
    chat = agent.chat_create()
    chat.title = "Synthetic preset update"
    async with MockClientContext():
        client_responses.get().extend(
            [
                'I will update Top K in the group with exact key qwen, preserving other fields.\n```json\n{"function":"update_inference_presets","arguments":{"group":"qwen","group_is_key":true,"preset":"analytical","parameters":{"top_k":20}}}\n```',
                "The analytical preset now uses Top K 20.",
            ]
        )
        await agent.chat_send(
            chat.id, "Use exact group key qwen; set only its analytical Top K to 20."
        )
    result = next(m.result for m in chat.messages if m.type == "doc_result")
    assert result["applied"] and result["values"] == {"analytical": {"top_k": 20}}
    assert '"applied": true' in str(agent.client.prompt_history[-1]["prompt"])
    reloaded = Config.model_validate(
        yaml.safe_load(config_state.CONFIG_FILE.read_text())
    )
    assert reloaded.presets.inference_groups["qwen"].presets.analytical.top_k == 20
    assert reloaded.presets.inference_groups["QWEN"].presets.analytical.top_k == 0
