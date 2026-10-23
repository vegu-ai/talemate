from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from talemate.server.assistant import AssistantPlugin


class _MockWebsocketHandler:
    def __init__(self, scene):
        self.scene = scene
        self.messages = []

    def queue_put(self, data):
        self.messages.append(data)


@pytest.fixture
def scene(tmp_path):
    return SimpleNamespace(save_dir=str(tmp_path))


@pytest.fixture
def plugin(scene):
    return AssistantPlugin(_MockWebsocketHandler(scene))


async def test_fork_refusal_answers_the_matching_request(plugin, scene, tmp_path):
    (tmp_path / "taken.json").write_text("original")
    creator = SimpleNamespace(fork_scene=AsyncMock())

    with (
        patch("talemate.server.assistant.get_agent", return_value=creator),
        patch("talemate.server.websocket_plugin.emit") as emit,
    ):
        await plugin.handle_fork_new_scene(
            {
                "message_id": 7,
                "save_name": "taken",
                "request_id": "fork-request-1",
            }
        )

    creator.fork_scene.assert_not_awaited()
    emit.assert_not_called()
    assert plugin.websocket_handler.messages == [
        {
            "type": "assistant",
            "action": "operation_done",
            "error": {
                "message": "A save named 'taken' already exists — pick a different name"
            },
            "request_id": "fork-request-1",
            "failed_action": "fork_new_scene",
        }
    ]


async def test_accepted_fork_answers_then_requests_the_scene_load(plugin, tmp_path):
    fork_path = str(tmp_path / "available.json")
    creator = SimpleNamespace(fork_scene=AsyncMock(return_value=fork_path))

    with patch("talemate.server.assistant.get_agent", return_value=creator):
        await plugin.handle_fork_new_scene(
            {
                "message_id": 7,
                "save_name": "  available  ",
                "request_id": "fork-request-2",
            }
        )

    creator.fork_scene.assert_awaited_once_with(7, "available")
    assert plugin.websocket_handler.messages == [
        {
            "type": "assistant",
            "action": "operation_done",
            "data": {},
            "request_id": "fork-request-2",
        },
        {
            "type": "system",
            "id": "load_scene_request",
            "data": {"path": fork_path},
        },
    ]


async def test_failed_fork_still_answers_the_matching_request(plugin):
    creator = SimpleNamespace(fork_scene=AsyncMock(return_value=None))

    with patch("talemate.server.assistant.get_agent", return_value=creator):
        await plugin.handle_fork_new_scene(
            {
                "message_id": 7,
                "save_name": "available",
                "request_id": "fork-request-3",
            }
        )

    assert plugin.websocket_handler.messages == [
        {
            "type": "assistant",
            "action": "operation_done",
            "error": {"message": "Scene fork failed"},
            "request_id": "fork-request-3",
            "failed_action": "fork_new_scene",
        }
    ]
