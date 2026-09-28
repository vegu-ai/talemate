"""
game_state.changed from the player's writes, and the nodes that read and set
how a game state path is pinned.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import talemate.emit.async_signals as async_signals
from _node_test_helpers import run_node
from conftest import MockScene, bootstrap_scene
from talemate.events import GameStateChangedEvent
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.nodes.state import (
    GetGameStatePathSettings,
    PinGameStatePath,
)
from talemate.game.state import GameStatePathSettings
from talemate.server.devtools import DevToolsPlugin


async def settle():
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.attempt_auto_save = AsyncMock()
    scene.game_state.variables = {"player": {"health": 5}, "weather": "sun"}
    return scene


@pytest.fixture
def plugin(scene):
    websocket = SimpleNamespace(scene=scene, queue_put=Mock())
    plugin = DevToolsPlugin(websocket_handler=websocket)
    plugin.signal_operation_done = AsyncMock()
    plugin.signal_operation_failed = AsyncMock()
    return plugin


@pytest.fixture
def received():
    events = []

    async def listener(event):
        events.append(event)

    signal = async_signals.get("game_state.changed")
    signal.connect(listener)
    yield SimpleNamespace(events=events)
    signal.disconnect(listener)


class TestGameStateChanged:
    @pytest.mark.asyncio
    async def test_player_write_sends_path_value_and_previous_value(
        self, scene, plugin, received
    ):
        scene.game_state_knob_paths = ["player/health"]
        scene.game_state_path_settings = {
            "player/health": GameStatePathSettings(minimum=0, maximum=10)
        }
        scene.load_active_pins = AsyncMock()
        with patch.object(type(scene), "emit_status", autospec=True):
            await plugin.handle_set_game_state_variable(
                {"path": "player/health", "value": 42}
            )
        await settle()

        [event] = received.events
        assert isinstance(event, GameStateChangedEvent)
        assert event.scene is scene
        assert event.event_type == "game_state.changed"
        assert event.path == "player/health"
        assert event.value == 10
        assert event.previous_value == 5

    @pytest.mark.asyncio
    async def test_handler_does_not_wait_for_the_listener(self, scene, plugin):
        release = asyncio.Event()
        started = []

        async def slow(event):
            started.append(True)
            await release.wait()

        signal = async_signals.get("game_state.changed")
        signal.connect(slow)
        scene.load_active_pins = AsyncMock()
        try:
            with patch.object(type(scene), "emit_status", autospec=True):
                await asyncio.wait_for(
                    plugin.handle_set_game_state_variable(
                        {"path": "weather", "value": "rain"}
                    ),
                    timeout=2,
                )
            plugin.signal_operation_done.assert_awaited_once_with(signal_only=True)
            await settle()
            assert started == [True]
        finally:
            release.set()
            await settle()
            signal.disconnect(slow)

    @pytest.mark.asyncio
    async def test_listener_sees_the_written_value(self, scene, plugin):
        seen = []

        async def listener(event):
            seen.append(event.scene.game_state.variables["weather"])

        signal = async_signals.get("game_state.changed")
        signal.connect(listener)
        scene.load_active_pins = AsyncMock()
        try:
            with patch.object(type(scene), "emit_status", autospec=True):
                await plugin.handle_set_game_state_variable(
                    {"path": "weather", "value": "rain"}
                )
            await settle()
        finally:
            signal.disconnect(listener)
        assert seen == ["rain"]

    @pytest.mark.asyncio
    async def test_refused_write_sends_nothing(self, scene, plugin, received):
        scene.game_state_knob_paths = ["weather"]
        scene.game_state_path_settings = {
            "weather": GameStatePathSettings(choices=["sun", "rain"])
        }
        await plugin.handle_set_game_state_variable(
            {"path": "weather", "value": "snow"}
        )
        await settle()
        assert received.events == []
        assert scene.game_state.variables["weather"] == "sun"
        plugin.signal_operation_failed.assert_awaited_once()


class TestGetGameStatePathSettings:
    @pytest.mark.asyncio
    async def test_pinned_knob_with_settings(self, scene):
        scene.game_state_knob_paths = ["player"]
        scene.game_state_watch_paths = ["weather"]
        scene.game_state_path_settings = {
            "player": GameStatePathSettings(label="Player", read_only=True)
        }
        out = await run_node(
            GetGameStatePathSettings(), scene=scene, inputs={"path": "/player/"}
        )
        assert out["path"] == "player"
        assert out["pinned"] is True
        assert out["knob"] is True
        assert out["debug"] is False
        assert out["read_only"] is True
        assert out["settings"] == {"label": "Player", "read_only": True}

    @pytest.mark.asyncio
    async def test_read_only_is_inherited_from_a_pinned_container(self, scene):
        scene.game_state_knob_paths = ["player"]
        scene.game_state_path_settings = {
            "player": GameStatePathSettings(read_only=True)
        }
        out = await run_node(
            GetGameStatePathSettings(), scene=scene, inputs={"path": "player/health"}
        )
        assert out["pinned"] is False
        assert out["read_only"] is True
        assert out["settings"] == {}


class TestPinGameStatePath:
    @pytest.mark.asyncio
    async def test_pin_as_knob_with_settings(self, scene):
        with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
            out = await run_node(
                PinGameStatePath(),
                scene=scene,
                inputs={
                    "path": "player/health",
                    "settings": {"label": "Health", "minimum": 0, "maximum": 10},
                },
            )
        assert scene.game_state_knob_paths == ["player/health"]
        assert out["settings"] == {"label": "Health", "minimum": 0, "maximum": 10}
        emit_status.assert_called_once_with(scene)

    @pytest.mark.asyncio
    async def test_settings_merge_keeps_fields_not_given(self, scene):
        scene.game_state_knob_paths = ["player/health"]
        scene.game_state_path_settings = {
            "player/health": GameStatePathSettings(label="Health", maximum=10)
        }
        with patch.object(type(scene), "emit_status", autospec=True):
            out = await run_node(
                PinGameStatePath(),
                scene=scene,
                inputs={"path": "player/health", "settings": {"slider": True}},
            )
        assert out["settings"] == {"label": "Health", "maximum": 10, "slider": True}

    @pytest.mark.asyncio
    async def test_unpin_from_the_last_target_drops_settings(self, scene):
        scene.game_state_knob_paths = ["player/health"]
        scene.game_state_watch_paths = ["player/health"]
        scene.game_state_path_settings = {
            "player/health": GameStatePathSettings(label="Health")
        }
        with patch.object(type(scene), "emit_status", autospec=True):
            await run_node(
                PinGameStatePath(),
                scene=scene,
                inputs={"path": "player/health", "enabled": False},
            )
            assert scene.game_state_path_settings  # still pinned in Debug Tools
            out = await run_node(
                PinGameStatePath(),
                scene=scene,
                inputs={"path": "player/health", "enabled": False, "target": "debug"},
            )
        assert scene.pinned_game_state_paths == set()
        assert scene.game_state_path_settings == {}
        assert out["settings"] == {}

    @pytest.mark.asyncio
    async def test_invalid_settings_are_refused(self, scene):
        with pytest.raises(InputValueError) as exc:
            await run_node(
                PinGameStatePath(),
                scene=scene,
                inputs={"path": "score", "settings": {"minimum": 5, "maximum": 1}},
            )
        assert exc.value.input_name == "settings"
        assert scene.game_state_knob_paths == []
