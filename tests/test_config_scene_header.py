from unittest.mock import AsyncMock, patch

import pydantic
import pytest

from talemate.config.schema import Config
from talemate.server import quick_settings


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)


class TestSceneHeaderConfig:
    def test_defaults(self):
        config = Config()
        header = config.game.scene_header
        assert header.enabled is True
        assert header.slot_a == ["history_stats", "active_characters"]
        assert header.slot_b == ["summarizer", "writing_style"]

    def test_missing_section_gets_defaults(self):
        config = Config(**{"game": {"general": {"auto_save": False}}})
        assert config.game.general.auto_save is False
        assert config.game.scene_header.enabled is True
        assert config.game.scene_header.slot_a == ["history_stats", "active_characters"]

    def test_values_round_trip(self):
        config = Config(
            **{
                "game": {
                    "scene_header": {
                        "enabled": False,
                        "slot_a": [],
                        "slot_b": ["summarizer", "history_stats"],
                    }
                }
            }
        )
        dumped = config.model_dump()["game"]["scene_header"]
        assert dumped == {
            "enabled": False,
            "slot_a": [],
            "slot_b": ["summarizer", "history_stats"],
        }
        assert Config(**config.model_dump()).game.scene_header == (
            config.game.scene_header
        )

    def test_unknown_item_ids_are_stored_as_given(self):
        config = Config(**{"game": {"scene_header": {"slot_a": ["later"]}}})
        assert config.game.scene_header.slot_a == ["later"]


async def _set(setting, value):
    config = Config()
    handler = _MockWebsocketHandler()
    plugin = quick_settings.QuickSettingsPlugin(handler)
    with (
        patch.object(quick_settings, "get_config", return_value=config),
        patch.object(Config, "set_dirty", AsyncMock(return_value=[])) as set_dirty,
    ):
        await plugin.handle({"action": "set", "setting": setting, "value": value})
    return config, handler, set_dirty


@pytest.mark.asyncio
async def test_quick_setting_writes_enabled_and_marks_dirty():
    config, handler, set_dirty = await _set("scene_header_enabled", False)

    assert config.game.scene_header.enabled is False
    set_dirty.assert_awaited_once()
    assert handler.messages == [
        {
            "type": "quick_settings",
            "action": "set_done",
            "data": {"setting": "scene_header_enabled", "value": False},
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["maybe", [1], None])
async def test_quick_setting_rejects_an_enabled_value_that_is_not_a_bool(value):
    config = Config()
    handler = _MockWebsocketHandler()
    plugin = quick_settings.QuickSettingsPlugin(handler)
    with (
        patch.object(quick_settings, "get_config", return_value=config),
        patch.object(Config, "set_dirty", AsyncMock(return_value=[])) as set_dirty,
        pytest.raises(pydantic.ValidationError),
    ):
        await plugin.handle(
            {"action": "set", "setting": "scene_header_enabled", "value": value}
        )

    assert config.game.scene_header.enabled is True
    set_dirty.assert_not_awaited()


class TestSetItemShown:
    def test_shows_a_missing_item_at_the_end(self):
        header = Config().game.scene_header
        header.set_item_shown("slot_a", "summarizer", True)
        assert header.slot_a == ["history_stats", "active_characters", "summarizer"]
        assert header.slot_b == ["summarizer", "writing_style"]

    def test_showing_a_shown_item_changes_nothing(self):
        header = Config().game.scene_header
        header.set_item_shown("slot_a", "history_stats", True)
        assert header.slot_a == ["history_stats", "active_characters"]

    def test_hides_an_item_and_keeps_the_others_in_order(self):
        header = Config(
            **{"game": {"scene_header": {"slot_b": ["later", "summarizer", "x"]}}}
        ).game.scene_header
        header.set_item_shown("slot_b", "summarizer", False)
        assert header.slot_b == ["later", "x"]
        header.set_item_shown("slot_b", "summarizer", False)
        assert header.slot_b == ["later", "x"]


async def _click(plugin, config, setting, item, shown):
    with (
        patch.object(quick_settings, "get_config", return_value=config),
        patch.object(Config, "set_dirty", AsyncMock(return_value=[])),
    ):
        await plugin.handle(
            {
                "action": "set",
                "setting": setting,
                "value": {"item": item, "shown": shown},
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setting, slot, other",
    [
        ("scene_header_slot_a", "slot_a", "slot_b"),
        ("scene_header_slot_b", "slot_b", "slot_a"),
    ],
)
async def test_quick_setting_edits_one_slot(setting, slot, other):
    value = {"item": "later", "shown": True}
    config, handler, set_dirty = await _set(setting, value)

    header = config.game.scene_header
    defaults = Config().game.scene_header
    assert getattr(header, slot) == [*getattr(defaults, slot), "later"]
    assert getattr(header, other) == getattr(defaults, other)
    assert header.enabled is True
    set_dirty.assert_awaited_once()
    assert handler.messages[0]["data"] == {"setting": setting, "value": value}


@pytest.mark.asyncio
async def test_clicks_apply_in_order_to_the_stored_list():
    config = Config(**{"game": {"scene_header": {"slot_a": [], "slot_b": []}}})
    plugin = quick_settings.QuickSettingsPlugin(_MockWebsocketHandler())

    # tick History stats, tick Summarizer, untick History stats: each click
    # carries only its own intent, so a client that has not seen the first
    # echo yet cannot drop an earlier click
    await _click(plugin, config, "scene_header_slot_a", "history_stats", True)
    await _click(plugin, config, "scene_header_slot_a", "summarizer", True)
    await _click(plugin, config, "scene_header_slot_a", "history_stats", False)
    assert config.game.scene_header.slot_a == ["summarizer"]

    await _click(plugin, config, "scene_header_slot_b", "summarizer", True)
    await _click(plugin, config, "scene_header_slot_b", "history_stats", True)
    assert config.game.scene_header.slot_b == ["summarizer", "history_stats"]


@pytest.mark.asyncio
async def test_set_done_follows_the_app_config_broadcast():
    config = Config()
    handler = _MockWebsocketHandler()
    plugin = quick_settings.QuickSettingsPlugin(handler)

    async def broadcast(self):
        handler.queue_put({"type": "app_config"})
        return []

    with (
        patch.object(quick_settings, "get_config", return_value=config),
        patch.object(Config, "set_dirty", broadcast),
    ):
        await plugin.handle(
            {
                "action": "set",
                "setting": "scene_header_slot_a",
                "value": {"item": "summarizer", "shown": True},
            }
        )

    assert [(m["type"], m.get("action")) for m in handler.messages] == [
        ("app_config", None),
        ("quick_settings", "set_done"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        ["history_stats"],
        "summarizer",
        None,
        {"item": "summarizer"},
        {"item": 1, "shown": True},
        {"item": "summarizer", "shown": "maybe"},
    ],
)
async def test_quick_setting_rejects_a_slot_value_that_is_not_an_edit(value):
    config = Config()
    handler = _MockWebsocketHandler()
    plugin = quick_settings.QuickSettingsPlugin(handler)
    with (
        patch.object(quick_settings, "get_config", return_value=config),
        patch.object(Config, "set_dirty", AsyncMock(return_value=[])) as set_dirty,
        pytest.raises(pydantic.ValidationError),
    ):
        await plugin.handle(
            {"action": "set", "setting": "scene_header_slot_a", "value": value}
        )

    assert config.game.scene_header.slot_a == Config().game.scene_header.slot_a
    set_dirty.assert_not_awaited()
    assert handler.messages == []
