"""
game_state.changed from every writer of the game state: the write path in
talemate.game.state, the Debug Tools and World Editor handlers, the scripting
API, template renders and the state nodes.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import talemate.emit.async_signals as async_signals
from _node_test_helpers import run_node
from conftest import MockScene, bootstrap_scene
from talemate.context import ActiveScene
from talemate.game.engine.api.game_state import create as create_game_state_api
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.nodes.state import (
    CounterState,
    CounterStatePath,
    SetState,
    SetStatePath,
    UnsetState,
    UnsetStatePath,
    UpdateGameState,
)
from talemate.game.state import (
    GameState,
    game_state_leaves,
    replace_game_state_variables,
    set_game_state_value,
    unset_game_state_value,
    update_game_state,
)
from talemate.prompts.base import Prompt, signals_after_render
from talemate.server.devtools import DevToolsPlugin


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.attempt_auto_save = AsyncMock()
    scene.load_active_pins = AsyncMock()
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
def changes():
    events = []

    async def listener(event):
        events.append(event)

    signal = async_signals.get("game_state.changed")
    signal.connect(listener)
    yield events
    signal.disconnect(listener)


def triples(events) -> set:
    return {(e.path, repr(e.value), repr(e.previous_value)) for e in events}


class TestWritePath:
    def test_leaves_follow_nested_dicts(self):
        assert game_state_leaves({"a": {"b": 1, "c": {}}, "d": [1]}) == {
            "a/b": 1,
            "d": [1],
        }

    @pytest.mark.asyncio
    async def test_one_event_per_changed_leaf(self, scene, changes):
        update_game_state(scene, {"player": {"health": 6, "mana": 2}, "weather": "sun"})
        await settle()
        assert triples(changes) == {
            ("player/health", "6", "5"),
            ("player/mana", "2", "None"),
        }
        assert all(e.scene is scene for e in changes)

    @pytest.mark.asyncio
    async def test_same_value_sends_nothing(self, scene, changes):
        set_game_state_value(scene, "player/health", 5)
        replace_game_state_variables(scene, {"player": {"health": 5}, "weather": "sun"})
        await settle()
        assert changes == []

    @pytest.mark.asyncio
    async def test_a_different_type_is_a_change(self, scene, changes):
        set_game_state_value(scene, "player/health", 5.0)
        await settle()
        assert triples(changes) == {("player/health", "5.0", "5")}

    @pytest.mark.asyncio
    async def test_removed_paths_have_value_none(self, scene, changes):
        assert unset_game_state_value(scene, "player") == {"health": 5}
        await settle()
        assert triples(changes) == {("player/health", "None", "5")}

    @pytest.mark.asyncio
    async def test_replace_diffs_old_and_new(self, scene, changes):
        replace_game_state_variables(scene, {"player": 3, "turn": 1})
        await settle()
        assert triples(changes) == {
            ("player/health", "None", "5"),
            ("player", "3", "None"),
            ("turn", "1", "None"),
            ("weather", "None", "'sun'"),
        }

    @pytest.mark.asyncio
    async def test_a_change_emits_the_scene_status(self, scene):
        with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
            update_game_state(scene, {"player": {"health": 6, "mana": 2}})
            set_game_state_value(scene, "weather", "rain")
            unset_game_state_value(scene, "weather")
        assert emit_status.call_count == 3
        emit_status.assert_called_with(scene)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "before, after",
        [
            ({}, {"missing": None}),
            ({"missing": None}, {}),
            ({}, {"empty": {}}),
            ({"empty": {}}, {}),
            ({"player": {"health": 5}}, {"player": {"health": 5, "bag": {}}}),
        ],
    )
    async def test_a_structural_change_emits_the_scene_status_without_leaf_events(
        self, scene, changes, before, after
    ):
        scene.game_state.variables = before
        with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
            replace_game_state_variables(scene, after)
            await settle()
        emit_status.assert_called_once_with(scene)
        assert changes == []

    @pytest.mark.asyncio
    async def test_same_value_emits_no_scene_status(self, scene):
        with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
            set_game_state_value(scene, "player/health", 5)
            replace_game_state_variables(
                scene, {"player": {"health": 5}, "weather": "sun"}
            )
        emit_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_values_are_copies(self, scene, changes):
        items = ["sword"]
        set_game_state_value(scene, "items", items)
        items.append("shield")
        await settle()
        [event] = changes
        assert event.value == ["sword"]

    @pytest.mark.asyncio
    async def test_missing_parent_without_create_changes_nothing(self, scene, changes):
        with pytest.raises(ValueError):
            set_game_state_value(scene, "stats/luck", 1, create=False)
        await settle()
        assert changes == []
        assert "stats" not in scene.game_state.variables

    @pytest.mark.asyncio
    async def test_the_writer_does_not_wait_for_a_listener(self, scene):
        release = asyncio.Event()

        async def slow(event):
            await release.wait()

        signal = async_signals.get("game_state.changed")
        signal.connect(slow)
        try:
            # synchronous: the listener runs in a task after the write
            set_game_state_value(scene, "weather", "rain")
            assert scene.game_state.variables["weather"] == "rain"
        finally:
            release.set()
            await settle()
            signal.disconnect(slow)

    @pytest.mark.asyncio
    async def test_a_detached_game_state_sends_nothing(self, changes):
        GameState().set_var("weather", "rain")
        await settle()
        assert changes == []


class TestHandlers:
    @pytest.mark.asyncio
    async def test_world_editor_update_game_state(self, scene, plugin, changes):
        with patch.object(type(scene), "emit_status", autospec=True):
            await plugin.handle_update_game_state(
                {"variables": {"player": {"health": 7}, "turn": 2}}
            )
        await settle()
        assert triples(changes) == {
            ("player/health", "7", "5"),
            ("turn", "2", "None"),
            ("weather", "None", "'sun'"),
        }
        plugin.signal_operation_done.assert_awaited_once_with(signal_only=True)

    @pytest.mark.asyncio
    async def test_scene_state_editor(self, scene, plugin, changes):
        state = {
            "game_state": {
                "variables": {"player": {"health": 5}, "weather": "fog"},
                "ops": {"run_on_start": True},
            }
        }
        await plugin.handle_update_scene_state({"state": state})
        await settle()
        assert triples(changes) == {("weather", "'fog'", "'sun'")}
        assert scene.game_state.ops.run_on_start is True


class TestScriptsAndTemplates:
    @pytest.mark.asyncio
    async def test_scripting_api_set_and_unset(self, scene, changes):
        api = create_game_state_api(scene.game_state)
        with ActiveScene(scene):
            api.set_var("turn", 1)
            api.unset_var("weather")
            api.get_or_set_var("turn", 5)
        await settle()
        assert triples(changes) == {
            ("turn", "1", "None"),
            ("weather", "None", "'sun'"),
        }

    @pytest.mark.asyncio
    async def test_a_template_write(self, scene, changes):
        prompt = Prompt.from_text(
            "{%- set _ = game_state.set_var('turn', 1) -%}done",
            vars={"game_state": scene.game_state},
        )
        with ActiveScene(scene):
            assert prompt.render().strip() == "done"
        await settle()
        assert triples(changes) == {("turn", "1", "None")}

    @pytest.mark.asyncio
    async def test_a_write_in_a_render_is_sent_after_it(self, scene, changes):
        with ActiveScene(scene), signals_after_render():
            scene.game_state.set_var("turn", 1)
            await settle()
            assert changes == []
        await settle()
        assert triples(changes) == {("turn", "1", "None")}


class TestNodes:
    @pytest.mark.asyncio
    async def test_set_and_unset_state(self, scene, changes):
        await run_node(
            SetState(),
            scene=scene,
            inputs={"name": "turn", "value": 1, "scope": "game"},
        )
        await run_node(
            UnsetState(), scene=scene, inputs={"name": "weather", "scope": "game"}
        )
        await settle()
        assert triples(changes) == {
            ("turn", "1", "None"),
            ("weather", "None", "'sun'"),
        }

    @pytest.mark.asyncio
    async def test_local_scope_sends_nothing(self, scene, changes):
        await run_node(
            SetState(),
            scene=scene,
            inputs={"name": "turn", "value": 1, "scope": "local"},
        )
        await settle()
        assert changes == []

    @pytest.mark.asyncio
    async def test_counter_at_its_cap_changes_once(self, scene, changes):
        scene.game_state.variables["count"] = 2
        out = await run_node(
            CounterState(),
            scene=scene,
            inputs={"state": True, "name": "count", "scope": "game", "reset_cap": 3},
        )
        await settle()
        assert out["value"] == 0 and out["reset"] is True
        assert triples(changes) == {("count", "0", "2")}

    @pytest.mark.asyncio
    async def test_path_nodes(self, scene, changes):
        await run_node(
            SetStatePath(),
            scene=scene,
            inputs={"state": True, "name": "stats/luck", "value": 3, "scope": "game"},
        )
        await run_node(
            CounterStatePath(),
            scene=scene,
            inputs={"state": True, "name": "stats/rolls/total", "scope": "game"},
        )
        await run_node(
            UnsetStatePath(),
            scene=scene,
            inputs={"state": True, "name": "player/health", "scope": "game"},
        )
        await settle()
        assert triples(changes) == {
            ("stats/luck", "3", "None"),
            ("stats/rolls/total", "1", "None"),
            ("player/health", "None", "5"),
        }
        assert scene.game_state.variables["stats"] == {
            "luck": 3,
            "rolls": {"total": 1},
        }

    @pytest.mark.asyncio
    async def test_set_state_path_through_a_value_is_refused(self, scene, changes):
        with pytest.raises(InputValueError):
            await run_node(
                SetStatePath(),
                scene=scene,
                inputs={
                    "state": True,
                    "name": "weather/wind",
                    "value": 3,
                    "scope": "game",
                },
            )
        await settle()
        assert changes == []

    @pytest.mark.asyncio
    async def test_update_game_state_merges(self, scene, changes):
        scene.game_state.variables["log"] = {"day": 1}
        updates = [{"player": {"mana": 2}}, {"player": {"mana": 3}, "log": {}}]
        state = object()
        out = await run_node(
            UpdateGameState(),
            scene=scene,
            inputs={"state": state, "updates": updates},
        )
        await settle()
        assert out["state"] is state
        assert out["variables"] is scene.game_state.variables
        assert scene.game_state.variables["player"] == {"health": 5, "mana": 3}
        # the net change of the whole update, one event per path; the empty
        # dict clears log
        assert triples(changes) == {
            ("player/mana", "3", "None"),
            ("log/day", "None", "1"),
        }

    @pytest.mark.asyncio
    async def test_update_game_state_replaces_top_level_keys(self, scene, changes):
        await run_node(
            UpdateGameState(),
            scene=scene,
            inputs={"state": True, "updates": {"player": {"mana": 2}}, "merge": False},
        )
        await settle()
        assert scene.game_state.variables["player"] == {"mana": 2}
        assert triples(changes) == {
            ("player/health", "None", "5"),
            ("player/mana", "2", "None"),
        }

    @pytest.mark.asyncio
    async def test_update_game_state_refuses_non_dicts(self, scene, changes):
        with pytest.raises(InputValueError):
            await run_node(
                UpdateGameState(),
                scene=scene,
                inputs={"state": True, "updates": ["weather"]},
            )
        await settle()
        assert changes == []
