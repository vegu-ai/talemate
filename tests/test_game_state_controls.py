import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

from conftest import MockScene, bootstrap_scene

from talemate.agents.base import background_processing
from talemate.game.state import (
    GameStatePathSettings,
    load_game_state_path_settings,
)
from talemate.server.devtools import DevToolsPlugin


def _plugin(scene):
    websocket = SimpleNamespace(scene=scene, queue_put=Mock())
    plugin = DevToolsPlugin(websocket_handler=websocket)
    plugin.signal_operation_done = AsyncMock()
    return plugin


def test_pinned_game_state_paths_combines_both_targets(scene):
    scene.game_state_watch_paths = ["player", "quest/active"]
    scene.game_state_control_paths = ["player", "score"]

    assert scene.pinned_game_state_paths == {"player", "quest/active", "score"}


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.attempt_auto_save = AsyncMock()
    return scene


@pytest.mark.parametrize(
    ("handler_name", "attribute", "action"),
    [
        (
            "handle_set_game_state_watch_paths",
            "game_state_watch_paths",
            "game_state_watch_paths_updated",
        ),
        (
            "handle_set_game_state_control_paths",
            "game_state_control_paths",
            "game_state_control_paths_updated",
        ),
    ],
)
async def test_game_state_paths_are_sanitized_and_persisted(
    scene, handler_name, attribute, action
):
    scene.game_state_watch_paths = ["player/health"]
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await getattr(plugin, handler_name)(
            {"paths": ["quest/active", "", "player/health", "quest/active"]}
        )

    assert getattr(scene, attribute) == ["player/health", "quest/active"]
    scene.attempt_auto_save.assert_awaited_once()
    emit_status.assert_called_once_with(scene)
    plugin.signal_operation_done.assert_awaited_once_with(signal_only=True)
    plugin.websocket_handler.queue_put.assert_called_once_with(
        {
            "type": "devtools",
            "action": action,
            "data": {"paths": ["player/health", "quest/active"]},
        }
    )


async def test_path_scoped_targets_do_not_restore_a_previous_toggle(scene):
    scene.game_state_watch_paths = ["player/health", "quest/active"]
    scene.game_state_control_paths = ["player/health", "quest/active"]
    scene.game_state_path_settings = {
        "player/health": GameStatePathSettings(label="Health"),
        "quest/active": GameStatePathSettings(label="Quest active"),
    }
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await plugin.handle_set_game_state_path_target(
            {"path": "player/health", "target": "debug", "enabled": False}
        )
        await plugin.handle_set_game_state_path_target(
            {"path": "quest/active", "target": "control", "enabled": False}
        )

    assert scene.game_state_watch_paths == ["quest/active"]
    assert scene.game_state_control_paths == ["player/health"]
    assert scene.serialized_game_state_path_settings == {
        "player/health": {"label": "Health"},
        "quest/active": {"label": "Quest active"},
    }
    assert scene.attempt_auto_save.await_count == 2
    assert emit_status.call_count == 2
    assert plugin.signal_operation_done.await_args_list == [
        call(signal_only=True),
        call(signal_only=True),
    ]


async def test_path_target_settings_are_trimmed_preserved_and_cleaned_up(scene):
    plugin = _plugin(scene)

    await plugin.handle_set_game_state_path_target(
        {
            "path": "player/health",
            "target": "debug",
            "enabled": True,
            "settings": {"label": "  Health  ", "minimum": 0, "maximum": 10},
        }
    )
    await plugin.handle_set_game_state_path_target(
        {"path": "player/health", "target": "control", "enabled": True}
    )

    assert scene.serialized_game_state_path_settings == {
        "player/health": {"label": "Health", "minimum": 0, "maximum": 10}
    }

    await plugin.handle_set_game_state_path_target(
        {"path": "player/health", "target": "debug", "enabled": False}
    )
    assert "player/health" in scene.game_state_path_settings

    await plugin.handle_set_game_state_path_target(
        {"path": "player/health", "target": "control", "enabled": False}
    )
    assert scene.game_state_path_settings == {}


async def test_path_settings_can_be_changed_and_cleared(scene):
    scene.game_state_control_paths = ["player/health"]
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await plugin.handle_set_game_state_path_settings(
            {
                "path": "player/health",
                "settings": {
                    "label": "  Hit points  ",
                    "description": "  How much punishment Ari can take  ",
                    "minimum": 0,
                    "maximum": 10,
                    "step": 1,
                    "slider": True,
                    "order": 2,
                },
            }
        )

    assert scene.serialized_game_state_path_settings == {
        "player/health": {
            "label": "Hit points",
            "description": "How much punishment Ari can take",
            "minimum": 0,
            "maximum": 10,
            "step": 1,
            "slider": True,
            "order": 2,
        }
    }
    scene.attempt_auto_save.assert_awaited_once()
    emit_status.assert_called_once_with(scene)
    plugin.websocket_handler.queue_put.assert_called_once_with(
        {
            "type": "devtools",
            "action": "game_state_path_settings_updated",
            "data": {
                "path": "player/health",
                "settings": {
                    "label": "Hit points",
                    "description": "How much punishment Ari can take",
                    "minimum": 0,
                    "maximum": 10,
                    "step": 1,
                    "slider": True,
                    "order": 2,
                },
            },
        }
    )

    await plugin.handle_set_game_state_path_settings({"path": "player/health"})
    assert scene.game_state_path_settings == {}


@pytest.mark.parametrize(
    "settings",
    [
        {"minimum": 10, "maximum": 1},
        {"step": 0},
        {"step": -1},
    ],
)
async def test_unusable_path_settings_are_refused(scene, settings):
    scene.game_state_control_paths = ["player/health"]
    plugin = _plugin(scene)
    plugin.signal_operation_failed = AsyncMock()

    await plugin.handle_set_game_state_path_settings(
        {"path": "player/health", "settings": settings}
    )

    plugin.signal_operation_failed.assert_awaited_once()
    assert scene.game_state_path_settings == {}
    scene.attempt_auto_save.assert_not_awaited()


def test_control_paths_and_settings_are_saved_and_reported_in_scene_status(scene):
    scene.game_state_control_paths = ["player/health"]
    scene.game_state_path_settings = {
        "player/health": GameStatePathSettings(label="Health", minimum=0, maximum=10)
    }
    expected = {"player/health": {"label": "Health", "minimum": 0, "maximum": 10}}

    assert scene.serialize["game_state_control_paths"] == ["player/health"]
    assert scene.serialize["game_state_path_settings"] == expected

    scene.active = True
    with patch("talemate.tale_mate.emit") as emit:
        scene._do_emit_status()

    (status,) = [call for call in emit.call_args_list if call.args[0] == "scene_status"]
    assert status.kwargs["data"]["game_state_control_paths"] == ["player/health"]
    assert status.kwargs["data"]["game_state_path_settings"] == expected


async def test_full_game_state_updates_are_persisted(scene):
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await plugin.handle_update_game_state({"variables": {"score": 2}})

    assert scene.game_state.variables == {"score": 2}
    scene.attempt_auto_save.assert_awaited_once()
    emit_status.assert_called_with(scene)
    plugin.signal_operation_done.assert_awaited_once_with(signal_only=True)


async def test_path_scoped_variable_updates_preserve_neighbouring_edits(scene):
    scene.game_state.variables = {"player": {"name": "Ari", "health": 8}}
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await plugin.handle_set_game_state_variable(
            {"path": "player/name", "value": "Aria"}
        )
        await plugin.handle_set_game_state_variable(
            {"path": "player/health", "value": 9}
        )

    assert scene.game_state.variables == {"player": {"name": "Aria", "health": 9}}
    assert scene.load_active_pins.await_count == 2
    assert scene.attempt_auto_save.await_count == 2
    assert emit_status.call_count == 4
    assert plugin.signal_operation_done.await_args_list == [
        call(signal_only=True),
        call(signal_only=True),
    ]
    assert plugin.websocket_handler.queue_put.call_args_list[-1].args[0] == {
        "type": "devtools",
        "action": "game_state_variable_updated",
        "data": {"path": "player/health", "value": 9},
    }


async def test_unsaved_autosave_still_emits_updated_paths(scene):
    async def real_attempt_auto_save():
        await type(scene).attempt_auto_save(scene)

    scene.attempt_auto_save = real_attempt_auto_save
    scene.filename = None
    scene.active = True
    plugin = _plugin(scene)

    assert scene.auto_save is True
    with patch("talemate.tale_mate.emit") as scene_emit:
        await scene.attempt_auto_save()
        await asyncio.sleep(0.05)
        assert not [
            call for call in scene_emit.call_args_list if call.args[0] == "scene_status"
        ]

        await plugin.handle_set_game_state_control_paths({"paths": ["player/health"]})
        await asyncio.sleep(0.05)

    (status,) = [
        call for call in scene_emit.call_args_list if call.args[0] == "scene_status"
    ]
    assert status.kwargs["data"]["game_state_control_paths"] == ["player/health"]


async def test_a_target_change_carrying_a_label_keeps_the_other_settings(scene):
    scene.game_state_control_paths = ["player/health"]
    scene.game_state_path_settings = {
        "player/health": GameStatePathSettings(
            minimum=0, maximum=10, step=1, slider=True, order=1
        )
    }
    plugin = _plugin(scene)

    await plugin.handle_set_game_state_path_target(
        {
            "path": "player/health",
            "target": "debug",
            "enabled": True,
            "settings": {"label": "Hit points"},
        }
    )

    assert scene.serialized_game_state_path_settings == {
        "player/health": {
            "label": "Hit points",
            "minimum": 0,
            "maximum": 10,
            "step": 1,
            "slider": True,
            "order": 1,
        }
    }


async def test_values_are_clamped_to_the_configured_bounds(scene):
    scene.game_state.variables = {"player": {"health": 8}}
    scene.game_state_control_paths = ["player/health"]
    scene.game_state_path_settings = {
        "player/health": GameStatePathSettings(minimum=0, maximum=10)
    }
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)

    await plugin.handle_set_game_state_variable({"path": "player/health", "value": 42})

    assert scene.game_state.variables == {"player": {"health": 10}}
    assert plugin.websocket_handler.queue_put.call_args_list[-1].args[0] == {
        "type": "devtools",
        "action": "game_state_variable_updated",
        "data": {"path": "player/health", "value": 10},
    }


async def test_a_value_outside_the_choices_is_refused(scene):
    scene.game_state.variables = {"weather": "rain"}
    scene.game_state_control_paths = ["weather"]
    scene.game_state_path_settings = {
        "weather": GameStatePathSettings(choices=["rain", "sun"])
    }
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)
    plugin.signal_operation_failed = AsyncMock()

    await plugin.handle_set_game_state_variable({"path": "weather", "value": "snow"})

    plugin.signal_operation_failed.assert_awaited_once()
    assert scene.game_state.variables == {"weather": "rain"}

    await plugin.handle_set_game_state_variable({"path": "weather", "value": "sun"})
    assert scene.game_state.variables == {"weather": "sun"}


@pytest.mark.parametrize(
    ("pinned_path", "written_path"),
    [
        ("player/health", "player/health"),
        ("player", "player/health"),
    ],
)
async def test_a_read_only_path_refuses_writes(scene, pinned_path, written_path):
    scene.game_state.variables = {"player": {"health": 8}}
    scene.game_state_control_paths = [pinned_path]
    scene.game_state_path_settings = {
        pinned_path: GameStatePathSettings(read_only=True)
    }
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)
    plugin.signal_operation_failed = AsyncMock()

    await plugin.handle_set_game_state_variable({"path": written_path, "value": 3})

    plugin.signal_operation_failed.assert_awaited_once()
    assert scene.game_state.variables == {"player": {"health": 8}}
    scene.attempt_auto_save.assert_not_awaited()


async def test_a_control_change_suppresses_busy_for_the_pin_reload_only(scene):
    scene.game_state.variables = {"player": {"health": 8}}
    reloaded = []
    saved = []

    scene.load_active_pins = AsyncMock(
        side_effect=lambda: reloaded.append(background_processing.get())
    )
    scene.attempt_auto_save = AsyncMock(
        side_effect=lambda: saved.append(background_processing.get())
    )
    plugin = _plugin(scene)

    await plugin.handle_set_game_state_variable({"path": "player/health", "value": 9})

    assert reloaded == [True]
    # the autosave can reach a re-embed through config.changed, which this
    # handler cannot claim is fast enough to hide
    assert saved == [False]
    assert background_processing.get() is False


def test_persisted_path_settings_are_loaded_pruned_and_validated():
    settings = load_game_state_path_settings(
        {
            "player/health": {"label": "Health", "minimum": 0, "maximum": 10},
            "player/name": {},
            "quest/active": {"label": "Quest"},
            "weather": {"minimum": 10, "maximum": 1},
            "score": "not a mapping",
        },
        {"player/health", "player/name", "weather", "score"},
    )

    assert settings == {
        "player/health": GameStatePathSettings(label="Health", minimum=0, maximum=10)
    }


async def test_values_are_snapped_onto_the_configured_step(scene):
    scene.game_state.variables = {"player": {"health": 8}}
    scene.game_state_control_paths = ["player/health"]
    scene.game_state_path_settings = {
        "player/health": GameStatePathSettings(minimum=0, maximum=10, step=1)
    }
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)

    await plugin.handle_set_game_state_variable(
        {"path": "player/health", "value": 6.4732142857142856}
    )

    assert scene.game_state.variables == {"player": {"health": 6}}


@pytest.mark.parametrize("value", [7, True, ["snow"], None])
async def test_a_choices_path_refuses_a_value_that_is_not_one_of_them(scene, value):
    scene.game_state.variables = {"weather": "rain"}
    scene.game_state_control_paths = ["weather"]
    scene.game_state_path_settings = {
        "weather": GameStatePathSettings(choices=["rain", "sun"])
    }
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)
    plugin.signal_operation_failed = AsyncMock()

    await plugin.handle_set_game_state_variable({"path": "weather", "value": value})

    plugin.signal_operation_failed.assert_awaited_once()
    assert scene.game_state.variables == {"weather": "rain"}


@pytest.mark.parametrize("value", ["99", True, None, ["9"]])
async def test_a_bounded_path_refuses_a_value_that_is_not_a_number(scene, value):
    scene.game_state.variables = {"score": 3}
    scene.game_state_control_paths = ["score"]
    scene.game_state_path_settings = {
        "score": GameStatePathSettings(minimum=0, maximum=10)
    }
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)
    plugin.signal_operation_failed = AsyncMock()

    await plugin.handle_set_game_state_variable({"path": "score", "value": value})

    plugin.signal_operation_failed.assert_awaited_once()
    assert scene.game_state.variables == {"score": 3}


def test_choices_survive_a_forced_list_delta():
    settings = load_game_state_path_settings(
        {"weather": {"label": "Weather", "choices": {"1": "sun", "0": "rain"}}},
        {"weather"},
    )

    assert settings == {
        "weather": GameStatePathSettings(label="Weather", choices=["rain", "sun"])
    }


def test_the_constrained_value_type_follows_the_grid():
    integral = GameStatePathSettings(minimum=0, maximum=10, step=1)
    assert integral.constrain(3.7) == 4
    assert isinstance(integral.constrain(3.7), int)

    fractional = GameStatePathSettings(minimum=0.5, maximum=2.5, step=0.25)
    assert fractional.constrain(1.31) == 1.25
    assert isinstance(fractional.constrain(1.31), float)


async def test_a_refused_full_update_names_itself(scene):
    scene.game_state.variables = {"player": {"health": 8}}
    plugin = _plugin(scene)
    plugin.signal_operation_failed = AsyncMock()

    await plugin.handle_update_game_state({"variables": [1]})

    plugin.signal_operation_failed.assert_awaited_once()
    assert (
        plugin.signal_operation_failed.await_args.kwargs["failed_action"]
        == "update_game_state"
    )
    assert scene.game_state.variables == {"player": {"health": 8}}


async def test_a_full_update_without_a_scene_names_itself(scene):
    plugin = _plugin(scene)
    plugin.websocket_handler.scene = None
    plugin.signal_operation_failed = AsyncMock()

    await plugin.handle_update_game_state({"variables": {"score": 2}})

    plugin.signal_operation_failed.assert_awaited_once_with(
        "No active scene", failed_action="update_game_state"
    )
