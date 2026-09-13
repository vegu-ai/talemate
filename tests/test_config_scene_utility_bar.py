from unittest.mock import AsyncMock, patch

import pytest

from talemate.config.schema import Config
from talemate.server import quick_settings


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)


class TestSceneUtilityBarConfig:
    def test_defaults(self):
        config = Config()
        bar = config.game.scene_utility_bar
        assert bar.enabled is True
        assert bar.slot_a == ["history_stats"]
        assert bar.slot_b == ["summarizer"]

    def test_missing_section_gets_defaults(self):
        config = Config(**{"game": {"general": {"auto_save": False}}})
        assert config.game.general.auto_save is False
        assert config.game.scene_utility_bar.enabled is True
        assert config.game.scene_utility_bar.slot_a == ["history_stats"]

    def test_values_round_trip(self):
        config = Config(
            **{
                "game": {
                    "scene_utility_bar": {
                        "enabled": False,
                        "slot_a": [],
                        "slot_b": ["summarizer", "history_stats"],
                    }
                }
            }
        )
        dumped = config.model_dump()["game"]["scene_utility_bar"]
        assert dumped == {
            "enabled": False,
            "slot_a": [],
            "slot_b": ["summarizer", "history_stats"],
        }
        assert Config(**config.model_dump()).game.scene_utility_bar == (
            config.game.scene_utility_bar
        )

    def test_unknown_item_ids_are_stored_as_given(self):
        config = Config(**{"game": {"scene_utility_bar": {"slot_a": ["later"]}}})
        assert config.game.scene_utility_bar.slot_a == ["later"]


@pytest.mark.asyncio
async def test_quick_setting_writes_enabled_and_marks_dirty():
    config = Config()
    handler = _MockWebsocketHandler()
    plugin = quick_settings.QuickSettingsPlugin(handler)

    with (
        patch.object(quick_settings, "get_config", return_value=config),
        patch.object(Config, "set_dirty", AsyncMock(return_value=[])) as set_dirty,
    ):
        await plugin.handle(
            {"action": "set", "setting": "scene_utility_bar_enabled", "value": False}
        )

    assert config.game.scene_utility_bar.enabled is False
    set_dirty.assert_awaited_once()
    assert handler.messages == [
        {
            "type": "quick_settings",
            "action": "set_done",
            "data": {"setting": "scene_utility_bar_enabled", "value": False},
        }
    ]
