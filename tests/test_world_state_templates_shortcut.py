"""
Unit tests for `talemate.world_state.templates.shortcut` and the manager
entry point that applies it.

Covers:
- registration / polymorphic deserialization through a Group yaml round-trip
- field defaults
- `WorldStateManager.apply_template_scene_tool_shortcut`: fresh-uid write into
  the app config, duplicate skip, orphan action refusal
"""

import pydantic
import pytest
import yaml

import talemate.config.state as config_state
from conftest import MockScene
from talemate.config.schema import Config, SceneToolShortcut
from talemate.emit.signals import handlers as emit_handlers
from talemate.world_state.manager import WorldStateManager
from talemate.world_state.templates.base import MODELS, Collection, Group
from talemate.world_state.templates.shortcut import SceneToolShortcutTemplate


def make_template(**overrides) -> SceneToolShortcutTemplate:
    defaults = dict(
        name="Push On",
        action_id="narrator.progress",
        label="Push on",
        icon="mdi-script-text",
        instructions="Keep it tense.",
    )
    defaults.update(overrides)
    return SceneToolShortcutTemplate(**defaults)


def make_group(name="g", templates=None) -> Group:
    group = Group(author="a", name=name, description="d")
    if templates:
        for template in templates:
            group.insert_template(template, save=False)
    return group


@pytest.fixture
def manager() -> WorldStateManager:
    """A manager on a bare scene - applying a shortcut never touches it."""
    return WorldStateManager(MockScene())


@pytest.fixture
def config(monkeypatch, tmp_path, isolate_signals):
    """A throwaway app config, written to a tmp_path config.yaml.

    Also drops the config.changed receivers so the broadcast the manager
    triggers does not dispatch into agents left behind by other tests.
    """
    isolate_signals("config.changed", "config.changed.follow", "config.saved")

    original = config_state.CONFIG
    cfg = Config()
    cfg.dirty = False
    config_state.CONFIG = cfg
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")

    yield cfg

    config_state.CONFIG = original


@pytest.fixture
def status_messages():
    captured = []

    def _receiver(emission):
        captured.append(emission)

    signal = emit_handlers["status"]
    signal.connect(_receiver, weak=False)
    try:
        yield captured
    finally:
        signal.disconnect(_receiver)


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------


class TestSceneToolShortcutTemplateModel:
    def test_registered(self):
        assert MODELS["scene_tool_shortcut"] is SceneToolShortcutTemplate

    def test_template_type_default(self):
        template = make_template()
        assert template.template_type == "scene_tool_shortcut"

    def test_instructions_default_to_none(self):
        template = SceneToolShortcutTemplate(
            name="X",
            action_id="narrator.progress",
            label="Push on",
            icon="mdi-script-text",
        )
        assert template.instructions is None
        assert template.favorite is False
        assert template.priority == 1
        assert template.uid

    @pytest.mark.parametrize("missing", ["action_id", "label", "icon"])
    def test_missing_required_field_raises(self, missing: str):
        fields = dict(
            name="X",
            action_id="narrator.progress",
            label="Push on",
            icon="mdi-script-text",
        )
        del fields[missing]

        with pytest.raises(pydantic.ValidationError):
            SceneToolShortcutTemplate(**fields)

    def test_yaml_roundtrip_deserializes_to_the_template_class(self, template_dir):
        template = make_template()
        group = make_group(name="Shortcuts", templates=[template])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)
        assert data["templates"][template.uid]["action_id"] == "narrator.progress"

        loaded = Group.load(group.path)
        restored = loaded.templates[template.uid]

        assert type(restored) is SceneToolShortcutTemplate
        assert restored.name == "Push On"
        assert restored.action_id == "narrator.progress"
        assert restored.label == "Push on"
        assert restored.icon == "mdi-script-text"
        assert restored.instructions == "Keep it tense."


class TestSceneToolShortcutTemplateValidation:
    @pytest.mark.parametrize("label", ["", "   ", "\t\n"])
    def test_blank_label_is_rejected(self, label: str):
        with pytest.raises(pydantic.ValidationError, match="must not be empty"):
            make_template(label=label)

    def test_label_is_stored_stripped(self):
        template = make_template(label="  Push on  ")
        assert template.label == "Push on"

    @pytest.mark.parametrize(
        "icon",
        [
            "",
            "script-text",
            "mdi-Bad_Icon",
            "mdi-",
            "mdi-script-",
            "mdi-script text",
            "mdi-heart\nmdi-close",
        ],
    )
    def test_bad_icon_is_rejected(self, icon: str):
        with pytest.raises(pydantic.ValidationError, match="mdi icon name"):
            make_template(icon=icon)

    @pytest.mark.parametrize(
        "icon", ["mdi-heart", "mdi-script-text", "mdi-weather-night", "mdi-account2"]
    )
    def test_good_icon_passes(self, icon: str):
        assert make_template(icon=icon).icon == icon

    @pytest.mark.parametrize("icon", ["mdi-heart\n", "  mdi-heart  "])
    def test_icon_is_stored_stripped(self, icon: str):
        """The frontend regex rejects surrounding whitespace, so the stored
        value must never carry any - a yaml block scalar appends a newline."""
        assert make_template(icon=icon).icon == "mdi-heart"

    def test_block_scalar_icon_in_yaml_survives_load(self, template_dir):
        template = make_template()
        group = make_group(name="Shortcuts", templates=[template])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)

        data["templates"][template.uid]["icon"] = "mdi-heart\n"

        with open(group.path, "w") as f:
            yaml.dump(data, f)

        loaded = Group.load(group.path)

        assert loaded.templates[template.uid].icon == "mdi-heart"

    def test_malformed_template_in_yaml_is_dropped_on_load(self, template_dir):
        valid = make_template(name="Valid")
        group = make_group(name="Shortcuts", templates=[valid])
        group.save(template_dir)

        with open(group.path, "r") as f:
            data = yaml.safe_load(f)

        data["templates"]["broken"] = dict(
            data["templates"][valid.uid],
            uid="broken",
            name="Broken",
            icon="script-text",
        )

        with open(group.path, "w") as f:
            yaml.dump(data, f)

        loaded = Group.load(group.path)

        assert "broken" not in loaded.templates
        assert loaded.templates[valid.uid].name == "Valid"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


class TestApplyTemplateSceneToolShortcut:
    async def test_creates_shortcut_in_config(self, manager, config):
        template = make_template()

        result = await manager.apply_template_scene_tool_shortcut(template)

        assert type(result) is SceneToolShortcut
        assert config.shortcuts.scene_tools == {result.uid: result}
        assert result.action_id == "narrator.progress"
        assert result.label == "Push on"
        assert result.icon == "mdi-script-text"
        assert result.instructions == "Keep it tense."

    async def test_emits_success_status(self, manager, config, status_messages):
        await manager.apply_template_scene_tool_shortcut(make_template())

        (emission,) = status_messages
        assert emission.message == "Shortcut 'Push on' added to scene tools"
        assert emission.status == "success"

    async def test_uid_is_fresh_not_the_template_uid(self, manager, config):
        template = make_template()

        result = await manager.apply_template_scene_tool_shortcut(template)

        assert result.uid != template.uid

    async def test_persists_the_config(self, manager, config):
        await manager.apply_template_scene_tool_shortcut(make_template())

        with open(config_state.CONFIG_FILE, "r") as f:
            saved = yaml.safe_load(f)

        (shortcut,) = saved["shortcuts"]["scene_tools"].values()
        assert shortcut["action_id"] == "narrator.progress"
        assert shortcut["label"] == "Push on"
        assert config.dirty is False

    async def test_instructions_none_becomes_empty_string(self, manager, config):
        template = make_template(instructions=None)

        result = await manager.apply_template_scene_tool_shortcut(template)

        assert result.instructions == ""

    async def test_applying_twice_only_writes_one_shortcut(
        self, manager, config, status_messages
    ):
        template = make_template()

        first = await manager.apply_template_scene_tool_shortcut(template)
        second = await manager.apply_template_scene_tool_shortcut(template)

        assert second is None
        assert config.shortcuts.scene_tools == {first.uid: first}
        assert any("already exists" in e.message for e in status_messages)

    async def test_differing_label_is_not_a_duplicate(self, manager, config):
        await manager.apply_template_scene_tool_shortcut(make_template())
        await manager.apply_template_scene_tool_shortcut(
            make_template(label="Push on harder")
        )

        assert len(config.shortcuts.scene_tools) == 2

    async def test_differing_instructions_are_not_a_duplicate(self, manager, config):
        await manager.apply_template_scene_tool_shortcut(make_template())
        await manager.apply_template_scene_tool_shortcut(
            make_template(instructions="Keep it calm.")
        )

        assert len(config.shortcuts.scene_tools) == 2

    async def test_unknown_action_is_refused(self, manager, config, status_messages):
        template = make_template(action_id="narrator.does_not_exist")

        result = await manager.apply_template_scene_tool_shortcut(template)

        assert result is None
        assert config.shortcuts.scene_tools == {}
        assert config.dirty is False
        assert any("no longer exists" in e.message for e in status_messages)

    async def test_unknown_action_does_not_write_the_config_file(self, manager, config):
        await manager.apply_template_scene_tool_shortcut(
            make_template(action_id="narrator.does_not_exist")
        )

        assert not config_state.CONFIG_FILE.exists()

    async def test_ignores_scene_specific_kwargs(self, manager, config):
        result = await manager.apply_template_scene_tool_shortcut(
            make_template(),
            character_name="",
            run_immediately=False,
            generation_options=None,
        )

        assert result.uid in config.shortcuts.scene_tools

    async def test_flat_uid_string_resolves_to_the_template(self, manager, config):
        template = make_template()
        group = make_group(name="Shortcuts", templates=[template])
        manager.scene._world_state_templates = Collection(groups=[group])

        result = await manager.apply_template_scene_tool_shortcut(
            f"{group.uid}__{template.uid}"
        )

        assert result.action_id == "narrator.progress"
        assert result.uid in config.shortcuts.scene_tools

    async def test_unknown_flat_uid_string_is_a_noop(self, manager, config):
        manager.scene._world_state_templates = Collection(groups=[])

        result = await manager.apply_template_scene_tool_shortcut("nope__nope")

        assert result is None
        assert config.shortcuts.scene_tools == {}

    async def test_dispatches_through_apply_template(self, manager, config):
        template = make_template()

        result = await manager.apply_template(template)

        assert result.uid in config.shortcuts.scene_tools
