"""Unit tests for optional time-passage titles (issue #235).

A `TimePassageMessage` carries an optional title that names the chapter it
opens; playthrough's chapter menu labels its entries with it. Covers the field
round-trip, the insert/update websocket paths, and the wire payload.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from conftest import MockScene, bootstrap_scene

from talemate.context import ActiveScene
from talemate.emit.base import Emission
from talemate.history import (
    collect_time_passages,
    insert_time_passage_after_message,
    update_time_passage_by_id,
)
from talemate.scene_message import NarratorMessage, TimePassageMessage
from talemate.server.time_passage import TimePassagePlugin
from talemate.server.world_state_manager import WorldStateManagerPlugin


@pytest.fixture
async def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    with ActiveScene(scene):
        yield scene


def _plugin(scene, cls=TimePassagePlugin):
    return cls(websocket_handler=SimpleNamespace(scene=scene, queue_put=Mock()))


def _archived(scene, start: int, end: int):
    scene.archived_history.append({"text": "summarized", "start": start, "end": end})


class TestField:
    def test_defaults_to_none(self):
        assert TimePassageMessage(ts=60, message="a minute later").title is None

    def test_round_trips_through_to_dict(self):
        message = TimePassageMessage(ts=60, message="a minute later", title="Dawn")

        assert message.to_dict()["title"] == "Dawn"
        assert TimePassageMessage(**message.to_dict()).title == "Dawn"

    def test_a_scene_saved_before_titles_existed_still_loads(self):
        legacy = {"message": "a minute later", "id": 1, "typ": "time", "ts": 60}

        assert TimePassageMessage(**legacy).title is None


class TestInsert:
    def test_title_is_stored(self, scene):
        scene.history.append(NarratorMessage("opening"))

        message = insert_time_passage_after_message(
            scene, scene.history[0].id, 1, "days", title="The Reckoning"
        )

        assert message.title == "The Reckoning"
        assert scene.history[1] is message

    def test_title_is_optional(self, scene):
        scene.history.append(NarratorMessage("opening"))

        message = insert_time_passage_after_message(
            scene, scene.history[0].id, 1, "days"
        )

        assert message.title is None

    async def test_handler_passes_the_title_through(self, scene):
        scene.history.append(NarratorMessage("opening"))
        plugin = _plugin(scene)

        with patch.object(type(scene), "emit_history", autospec=True):
            await plugin.handle_insert_after(
                {
                    "message_id": scene.history[0].id,
                    "amount": 1,
                    "unit": "days",
                    "title": "The Reckoning",
                }
            )

        assert scene.history[1].title == "The Reckoning"


class TestUpdate:
    def test_title_is_editable(self, scene):
        time_message = TimePassageMessage(ts=60, message="a minute later")
        scene.history.append(time_message)

        update_time_passage_by_id(scene, time_message.id, 2, "hours", title="Nightfall")

        assert time_message.title == "Nightfall"
        assert time_message.ts == 7200

    def test_title_can_be_cleared(self, scene):
        time_message = TimePassageMessage(ts=60, message="later", title="Nightfall")
        scene.history.append(time_message)

        update_time_passage_by_id(scene, time_message.id, 2, "hours")

        assert time_message.title is None

    async def test_handler_passes_the_title_through(self, scene):
        time_message = TimePassageMessage(ts=60, message="a minute later")
        scene.history.append(time_message)
        plugin = _plugin(scene)

        with patch.object(type(scene), "emit_history", autospec=True):
            await plugin.handle_update(
                {
                    "message_id": time_message.id,
                    "amount": 2,
                    "unit": "hours",
                    "title": "Nightfall",
                }
            )

        assert time_message.title == "Nightfall"


class TestWirePayload:
    def test_title_reaches_the_frontend(self):
        from talemate.server.websocket_server import WebsocketHandler

        message = TimePassageMessage(ts=60, message="a minute later", title="Dawn")
        handler = WebsocketHandler.__new__(WebsocketHandler)
        handler.queue_put = Mock()

        WebsocketHandler.handle_time(
            handler,
            Emission(
                typ="time",
                message=message.message,
                message_object=message,
                id=message.id,
            ),
        )

        assert handler.queue_put.call_args.args[0]["title"] == "Dawn"


class TestWorldEditorSurfaces:
    """The world editor's History tab is the only surface that reaches a
    passage inserted before a summarized entry: it lands deep in past history,
    outside the tail the scene view loads, so it has to be titled here.
    """

    async def test_insert_carries_the_title(self, scene):
        scene.history.append(NarratorMessage("opening"))
        _archived(scene, 0, 0)
        plugin = _plugin(scene, WorldStateManagerPlugin)

        with (
            patch.object(type(scene), "emit_history", autospec=True),
            patch.object(
                WorldStateManagerPlugin, "handle_request_scene_history", autospec=True
            ),
        ):
            await plugin.handle_insert_time_passage(
                {
                    "archive_index": 0,
                    "amount": 1,
                    "unit": "days",
                    "title": "The Reckoning",
                }
            )

        assert scene.history[0].title == "The Reckoning"

    async def test_update_carries_the_title(self, scene):
        time_message = TimePassageMessage(ts=60, message="a minute later")
        scene.history.append(time_message)
        plugin = _plugin(scene, WorldStateManagerPlugin)

        with (
            patch.object(type(scene), "emit_history", autospec=True),
            patch.object(
                WorldStateManagerPlugin, "handle_request_scene_history", autospec=True
            ),
        ):
            await plugin.handle_update_time_passage(
                {
                    "history_index": 0,
                    "amount": 2,
                    "unit": "hours",
                    "title": "Nightfall",
                }
            )

        assert time_message.title == "Nightfall"
        assert time_message.ts == 7200

    def test_the_tab_can_display_a_title(self, scene):
        scene.history.append(TimePassageMessage(ts=60, message="later", title="Dawn"))

        (passage,) = collect_time_passages(scene)

        assert passage["title"] == "Dawn"


class TestAdvanceTime:
    async def test_the_agent_carries_the_title(self, scene):
        from talemate.agents.world_state import WorldStateAgent

        agent = WorldStateAgent.__new__(WorldStateAgent)
        agent.scene = scene

        with (
            patch.object(type(scene), "push_history", autospec=True),
            patch.object(type(scene), "emit_status", autospec=True),
            patch("talemate.agents.world_state.emit"),
        ):
            message = await WorldStateAgent.advance_time(
                agent, 3600, title="The Reckoning"
            )

        assert message.title == "The Reckoning"

    def test_the_node_exposes_a_chapter_title(self):
        # `title` is reserved on a node (it names the node), so the socket is
        # `chapter_title`
        from talemate.agents.world_state.nodes import AdvanceTime

        node = AdvanceTime()

        assert "chapter_title" in node.properties
        assert "chapter_title" in [socket.name for socket in node.inputs]
