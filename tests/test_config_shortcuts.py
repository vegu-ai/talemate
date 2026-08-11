"""The persisted `shortcuts` config section and the eligible-action catalog
the frontend builds shortcuts from.
"""

from __future__ import annotations

import pydantic
import pytest

from talemate.config.schema import Config, SceneToolShortcut
from talemate.scene_tools import SCENE_TOOL_ACTIONS
from talemate.server.config import ConfigPlugin

PER_CHARACTER_IDS = {
    "narrator.look_at_character",
    "conversation.request_actor_action",
    "visual.visualize_character_card",
    "visual.visualize_character_portrait",
}


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)


class TestShortcutsConfigDefaults:
    def test_default_config_has_no_shortcuts(self):
        config = Config()
        assert config.shortcuts.scene_tools == {}

    def test_missing_shortcuts_key_gets_defaults(self):
        # configs saved before the shortcuts section existed come in without it
        config = Config(**{"agents": {}, "clients": {}})
        assert config.shortcuts.scene_tools == {}

    def test_values_are_preserved(self):
        config = Config(
            **{
                "shortcuts": {
                    "scene_tools": {
                        "abc": {
                            "uid": "abc",
                            "action_id": "narrator.progress",
                            "label": "Push on",
                            "icon": "mdi-script-text",
                            "instructions": "Keep it tense.",
                        }
                    }
                }
            }
        )

        shortcut = config.shortcuts.scene_tools["abc"]
        assert shortcut.uid == "abc"
        assert shortcut.action_id == "narrator.progress"
        assert shortcut.label == "Push on"
        assert shortcut.icon == "mdi-script-text"
        assert shortcut.instructions == "Keep it tense."

    def test_mismatched_uid_is_normalized_to_the_key(self):
        config = Config(
            **{
                "shortcuts": {
                    "scene_tools": {
                        "abc": {
                            "uid": "stale",
                            "action_id": "narrator.progress",
                            "label": "Push on",
                            "icon": "mdi-script-text",
                        }
                    }
                }
            }
        )

        assert config.shortcuts.scene_tools["abc"].uid == "abc"

    def test_instructions_default_to_empty(self):
        shortcut = SceneToolShortcut(
            uid="abc",
            action_id="narrator.progress",
            label="Push on",
            icon="mdi-script-text",
        )
        assert shortcut.instructions == ""

    def test_round_trips_through_model_dump(self):
        config = Config(
            **{
                "shortcuts": {
                    "scene_tools": {
                        "abc": {
                            "uid": "abc",
                            "action_id": "visual.visualize_character_card",
                            "label": "Portrait",
                            "icon": "mdi-brush",
                        }
                    }
                }
            }
        )

        restored = Config.model_validate(config.model_dump())
        assert restored.shortcuts == config.shortcuts

    @pytest.mark.parametrize("missing", ["uid", "action_id", "label", "icon"])
    def test_missing_required_field_raises(self, missing: str):
        fields = {
            "uid": "abc",
            "action_id": "narrator.progress",
            "label": "Push on",
            "icon": "mdi-script-text",
        }
        del fields[missing]

        with pytest.raises(pydantic.ValidationError):
            SceneToolShortcut(**fields)


class TestSceneToolActionsMessage:
    async def _actions(self) -> list[dict]:
        handler = _MockWebsocketHandler()
        await ConfigPlugin(handler).handle_request_scene_tool_actions({})

        (message,) = handler.messages
        assert message["type"] == "config"
        assert message["action"] == "scene_tool_actions"
        return message["data"]["actions"]

    async def test_ships_the_whole_catalog(self):
        actions = await self._actions()

        assert [action["id"] for action in actions] == [
            "narrator.progress",
            "narrator.narrate_environment",
            "narrator.look_at_scene",
            "narrator.look_at_character",
            "conversation.request_actor_action",
            "director.request_dynamic_choices",
            "director.scene_direction_turn",
            "visual.visualize_environment_card",
            "visual.visualize_environment_background",
            "visual.visualize_character_card",
            "visual.visualize_character_portrait",
        ]
        assert len(actions) == len(SCENE_TOOL_ACTIONS)

    async def test_every_action_is_labelled(self):
        actions = await self._actions()
        assert all(action["label"] for action in actions)

    async def test_per_character_flags(self):
        actions = await self._actions()

        per_character = {action["id"] for action in actions if action["per_character"]}
        assert per_character == PER_CHARACTER_IDS

    async def test_only_the_actor_action_renders_unbound(self):
        actions = await self._actions()

        unbound = {action["id"] for action in actions if action["include_unbound"]}
        assert unbound == {"conversation.request_actor_action"}
