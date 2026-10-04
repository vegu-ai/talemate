"""Unit tests for playthrough mode (issue #235).

Covers the `playthrough` router, the uncapped history emit it triggers and the
progress it records in the scene file. The frontend drives the mode itself
(issue #329), so there is no backend state for these to inspect.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from conftest import MockScene, bootstrap_scene

from talemate.context import ActiveScene
from talemate.exceptions import TalemateError
from talemate.scene_message import NarratorMessage
from talemate.server.playthrough import PlaythroughPlugin
from talemate.server.websocket_plugin import Plugin


@pytest.fixture
async def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.name = "Playthrough Test"
    scene.filename = "playthrough-test.json"
    with ActiveScene(scene):
        yield scene


def _ws(scene):
    return SimpleNamespace(scene=scene, queue_put=Mock())


def _plugin(cls, scene):
    return cls(websocket_handler=_ws(scene))


class TestStart:
    async def test_start_emits_the_full_history(self, scene):
        for i in range(5):
            scene.history.append(NarratorMessage(f"message {i}"))

        plugin = _plugin(PlaythroughPlugin, scene)

        with patch.object(
            type(scene), "emit_history", autospec=True
        ) as mock_emit_history:
            await plugin.handle_start({})

        mock_emit_history.assert_called_once()
        assert mock_emit_history.call_args.kwargs == {"uncapped": True}

    async def test_start_reports_when_the_replay_is_all_there(self, scene):
        # the history arrives message by message and the status is debounced,
        # so a client resuming a saved position needs an explicit end
        plugin = _plugin(PlaythroughPlugin, scene)

        with patch.object(type(scene), "emit_history", autospec=True):
            await plugin.handle_start({})

        actions = [
            call.args[0]["action"]
            for call in plugin.websocket_handler.queue_put.call_args_list
        ]
        assert "replay_complete" in actions
        assert actions.index("replay_complete") < actions.index("operation_done")

    async def test_start_does_not_dirty_the_scene(self, scene):
        scene.saved = True
        plugin = _plugin(PlaythroughPlugin, scene)

        with patch.object(type(scene), "emit_history", autospec=True):
            await plugin.handle_start({})

        assert scene.saved is True


class TestUncappedHistory:
    async def test_capped_by_default(self, scene):
        for i in range(10):
            scene.history.append(NarratorMessage(f"message {i}"))

        with (
            patch.object(type(scene), "max_backscroll", 3),
            patch("talemate.tale_mate.emit") as mock_emit,
        ):
            await scene.emit_history()

        emitted = [c for c in mock_emit.call_args_list if c.args[0] == "narrator"]
        assert [str(c.args[1]) for c in emitted] == [
            "message 7",
            "message 8",
            "message 9",
        ]

    async def test_uncapped_emits_everything(self, scene):
        for i in range(10):
            scene.history.append(NarratorMessage(f"message {i}"))

        with (
            patch.object(type(scene), "max_backscroll", 3),
            patch("talemate.tale_mate.emit") as mock_emit,
        ):
            await scene.emit_history(uncapped=True)

        emitted = [c for c in mock_emit.call_args_list if c.args[0] == "narrator"]
        assert [str(c.args[1]) for c in emitted] == [f"message {i}" for i in range(10)]


class TestProgress:
    """Covers Scene.write_playthrough_progress - see its docstring."""

    @pytest.fixture
    def scene_file(self, scene, tmp_path):
        import json

        path = tmp_path / "scene.json"
        path.write_text(json.dumps({"name": "Playthrough Test", "history": []}))
        with (
            patch.object(type(scene), "full_path", str(path)),
            patch.object(type(scene), "save_dir", str(tmp_path)),
        ):
            yield path

    def _written(self, scene_file):
        import json

        return json.loads(scene_file.read_text())

    def test_progress_is_written_to_the_scene_file(self, scene, scene_file):
        scene.write_playthrough_progress(42)

        assert self._written(scene_file)["playthrough_progress"] == 42
        assert scene.playthrough_progress == 42

    def test_the_rest_of_the_file_is_left_alone(self, scene, scene_file):
        scene.name = "renamed in memory only"
        scene.history.append(NarratorMessage("only in memory"))

        scene.write_playthrough_progress(42)

        written = self._written(scene_file)
        assert written["name"] == "Playthrough Test"
        assert written["history"] == []

    def test_recording_progress_is_not_a_change_to_the_scene(self, scene, scene_file):
        scene.saved = True

        scene.write_playthrough_progress(42)

        assert self._written(scene_file)["playthrough_progress"] == 42
        assert scene.saved is True

    def test_the_intro_sentinel_round_trips(self, scene, scene_file):
        scene.write_playthrough_progress("intro")

        assert self._written(scene_file)["playthrough_progress"] == "intro"

    def test_a_read_only_scene_is_not_written_to(self, scene, scene_file):
        # bundled scenes load with immutable_save set; recording progress into
        # one would edit a file the user does not own
        scene.immutable_save = True
        before = scene_file.read_bytes()

        with pytest.raises(TalemateError):
            scene.write_playthrough_progress(42)

        assert scene_file.read_bytes() == before
        # and nothing was changed in memory on the way out either
        assert scene.playthrough_progress is None

    async def test_the_handler_reports_a_read_only_scene(self, scene, scene_file):
        scene.immutable_save = True
        plugin = _plugin(PlaythroughPlugin, scene)

        await plugin.handle_save_progress({"message_id": 42})

        (payload,) = [
            call.args[0] for call in plugin.websocket_handler.queue_put.call_args_list
        ]
        assert "read-only" in payload["error"]["message"]

    def test_an_unsaved_scene_has_nowhere_to_record_it(self, scene):
        with patch.object(type(scene), "full_path", None):
            with pytest.raises(TalemateError):
                scene.write_playthrough_progress(42)

    def test_progress_is_reported_in_the_status(self, scene):
        scene.active = True
        scene.playthrough_progress = 42

        with patch("talemate.tale_mate.emit") as mock_emit:
            scene._do_emit_status()

        (call,) = [c for c in mock_emit.call_args_list if c.args[0] == "scene_status"]
        assert call.kwargs["data"]["playthrough_progress"] == 42

    def test_progress_survives_a_save(self, scene):
        scene.playthrough_progress = 42

        assert scene.serialize["playthrough_progress"] == 42

    async def test_the_handler_records_and_reports(self, scene, scene_file):
        plugin = _plugin(PlaythroughPlugin, scene)

        await plugin.handle_save_progress({"message_id": 42})

        assert self._written(scene_file)["playthrough_progress"] == 42

    async def test_the_handler_reports_a_scene_it_cannot_write(self, scene):
        plugin = _plugin(PlaythroughPlugin, scene)

        with patch.object(type(scene), "full_path", None):
            await plugin.handle_save_progress({"message_id": 42})

        (payload,) = [
            call.args[0] for call in plugin.websocket_handler.queue_put.call_args_list
        ]
        assert "Could not record replay progress" in payload["error"]["message"]


class TestAudioStopIsNotASceneChange:
    """The frontend sends `tts/stop_and_clear` on every step of a playthrough
    (`cancelPlaythroughPacing`), whether or not narration is on. Stopping
    playback is not a scene change, so it must leave `saved` alone - otherwise
    replaying a scene marks it unsaved without anything having changed."""

    @pytest.mark.parametrize("auto_save", [True, False])
    async def test_stopping_playback_leaves_the_scene_alone(self, scene, auto_save):
        from unittest.mock import AsyncMock

        from talemate.agents.tts.websocket_handler import TTSWebsocketHandler

        scene.saved = True
        tts_agent = SimpleNamespace(stop_and_clear_queue=AsyncMock())
        plugin = _plugin(TTSWebsocketHandler, scene)

        with (
            patch.object(type(scene), "auto_save", auto_save),
            patch.object(type(scene), "save", autospec=True) as mock_save,
            patch(
                "talemate.agents.tts.websocket_handler.get_agent",
                return_value=tts_agent,
            ),
        ):
            await plugin.handle_stop_and_clear({})

        tts_agent.stop_and_clear_queue.assert_awaited()
        mock_save.assert_not_called()
        assert scene.saved is True
        plugin.disconnect()


class TestNoGuardMachinery:
    """The frontend is the arbiter (#329): it does not offer the actions that
    progress a scene, and that is the whole enforcement story. The backend has
    no mode to guard, which nothing else can assert - a playthrough is not
    visible to it at all - so these pin the deletion itself.
    """

    def test_the_scene_carries_no_playthrough_state(self, scene):
        assert not hasattr(scene, "playthrough")

    def test_routers_have_no_way_to_refuse_a_playthrough(self):
        assert not hasattr(Plugin, "playthrough_blocked_actions")
        assert not hasattr(Plugin, "playthrough_blocks")

    def test_the_router_has_nothing_to_leave(self):
        assert not hasattr(PlaythroughPlugin, "handle_stop")
