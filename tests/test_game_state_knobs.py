import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

from conftest import MockScene, bootstrap_scene

from talemate.changelog import reconstruct_cleanup
from talemate.server.devtools import DevToolsPlugin


def _plugin(scene):
    websocket = SimpleNamespace(scene=scene, queue_put=Mock())
    plugin = DevToolsPlugin(websocket_handler=websocket)
    plugin.signal_operation_done = AsyncMock()
    return plugin


def test_pinned_game_state_paths_combines_both_targets(scene):
    scene.game_state_watch_paths = ["player", "quest/active"]
    scene.game_state_knob_paths = ["player", "score"]

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
            "handle_set_game_state_knob_paths",
            "game_state_knob_paths",
            "game_state_knob_paths_updated",
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
    scene.game_state_knob_paths = ["player/health", "quest/active"]
    scene.game_state_path_labels = {
        "player/health": "Health",
        "quest/active": "Quest active",
    }
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await plugin.handle_set_game_state_path_target(
            {"path": "player/health", "target": "debug", "enabled": False}
        )
        await plugin.handle_set_game_state_path_target(
            {"path": "quest/active", "target": "knob", "enabled": False}
        )

    assert scene.game_state_watch_paths == ["quest/active"]
    assert scene.game_state_knob_paths == ["player/health"]
    assert scene.game_state_path_labels == {
        "player/health": "Health",
        "quest/active": "Quest active",
    }
    assert scene.attempt_auto_save.await_count == 2
    assert emit_status.call_count == 2
    assert plugin.signal_operation_done.await_args_list == [
        call(signal_only=True),
        call(signal_only=True),
    ]


async def test_path_target_label_is_trimmed_preserved_and_cleaned_up(scene):
    plugin = _plugin(scene)

    await plugin.handle_set_game_state_path_target(
        {
            "path": "player/health",
            "target": "debug",
            "enabled": True,
            "label": "  Health  ",
        }
    )
    await plugin.handle_set_game_state_path_target(
        {"path": "player/health", "target": "knob", "enabled": True}
    )

    assert scene.game_state_path_labels == {"player/health": "Health"}

    await plugin.handle_set_game_state_path_target(
        {"path": "player/health", "target": "debug", "enabled": False}
    )
    assert scene.game_state_path_labels == {"player/health": "Health"}

    await plugin.handle_set_game_state_path_target(
        {"path": "player/health", "target": "knob", "enabled": False}
    )
    assert scene.game_state_path_labels == {}


async def test_path_label_can_be_changed_and_cleared(scene):
    scene.game_state_knob_paths = ["player/health"]
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await plugin.handle_set_game_state_path_label(
            {"path": "player/health", "label": "  Hit points  "}
        )

    assert scene.game_state_path_labels == {"player/health": "Hit points"}
    scene.attempt_auto_save.assert_awaited_once()
    emit_status.assert_called_once_with(scene)
    plugin.websocket_handler.queue_put.assert_called_once_with(
        {
            "type": "devtools",
            "action": "game_state_path_label_updated",
            "data": {"path": "player/health", "label": "Hit points"},
        }
    )

    await plugin.handle_set_game_state_path_label(
        {"path": "player/health", "label": ""}
    )
    assert scene.game_state_path_labels == {}


def test_knob_paths_and_labels_are_saved_and_reported_in_scene_status(scene):
    scene.game_state_knob_paths = ["player/health"]
    scene.game_state_path_labels = {"player/health": "Health"}

    assert scene.serialize["game_state_knob_paths"] == ["player/health"]
    assert scene.serialize["game_state_path_labels"] == {"player/health": "Health"}

    scene.active = True
    with patch("talemate.tale_mate.emit") as emit:
        scene._do_emit_status()

    (status,) = [call for call in emit.call_args_list if call.args[0] == "scene_status"]
    assert status.kwargs["data"]["game_state_knob_paths"] == ["player/health"]
    assert status.kwargs["data"]["game_state_path_labels"] == {
        "player/health": "Health"
    }


async def test_changelog_cleanup_keeps_knob_paths_as_a_list():
    result = await reconstruct_cleanup(
        {
            "game_state_knob_paths": {0: "player/health", 1: "quest/active"},
            "game_state_path_labels": {"player/health": "Health"},
        }
    )

    assert result["game_state_knob_paths"] == ["player/health", "quest/active"]
    assert result["game_state_path_labels"] == {"player/health": "Health"}


async def test_full_game_state_updates_are_persisted(scene):
    scene.load_active_pins = AsyncMock()
    plugin = _plugin(scene)

    with patch.object(type(scene), "emit_status", autospec=True) as emit_status:
        await plugin.handle_update_game_state({"variables": {"score": 2}})

    assert scene.game_state.variables == {"score": 2}
    scene.attempt_auto_save.assert_awaited_once()
    emit_status.assert_called_once_with(scene)
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
    assert emit_status.call_count == 2
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

        await plugin.handle_set_game_state_knob_paths({"paths": ["player/health"]})
        await asyncio.sleep(0.05)

    (status,) = [
        call for call in scene_emit.call_args_list if call.args[0] == "scene_status"
    ]
    assert status.kwargs["data"]["game_state_knob_paths"] == ["player/health"]
