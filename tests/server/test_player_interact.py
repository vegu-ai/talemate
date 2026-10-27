import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.context import interaction
from talemate.server import api


@pytest.mark.asyncio
async def test_interact_hands_input_to_scene_without_waiting_for_refresh(
    scene, monkeypatch
):
    incoming = asyncio.Queue()
    accepted = asyncio.Event()
    received = []

    def send_input(text):
        received.append((text, interaction.get().act_as))
        accepted.set()

    handler = SimpleNamespace(
        scene=scene,
        waiting_for_input=True,
        send_input=send_input,
        disconnect=Mock(),
    )
    socket = SimpleNamespace(recv=incoming.get, send=AsyncMock())
    refresh = AsyncMock(side_effect=AssertionError("interact must not refresh"))
    monkeypatch.setattr(api, "WebsocketHandler", lambda *args: handler)
    monkeypatch.setattr(api, "import_initial_node_definitions", lambda: None)

    async def client_status_loop():
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "client_status_loop", client_status_loop)
    monkeypatch.setattr(api, "_active_frontend_websocket", None)
    monkeypatch.setattr(api, "_active_frontend_websocket_handler", None)
    monkeypatch.setattr(
        "talemate.knowledge.revision_refresh.catch_up_revisions", refresh
    )
    task = asyncio.create_task(api.websocket_endpoint(socket))
    try:
        await incoming.put(
            json.dumps({"type": "interact", "text": "Hello.", "act_as": "Alice"})
        )
        await asyncio.wait_for(accepted.wait(), 5)
        assert received == [("Hello.", "Alice")]
        refresh.assert_not_awaited()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    handler.disconnect.assert_called_once_with()
