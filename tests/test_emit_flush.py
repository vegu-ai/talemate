"""A player line reaches the websocket before the save of the input starts."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import talemate.server.websocket_server as websocket_server
import talemate.tale_mate as tale_mate
from talemate.emit import Receiver, flush_emissions
from talemate.scene_message import CharacterMessage
from talemate.server.api import send_queued_frames
from talemate.server.websocket_server import WebsocketHandler


class RecordingReceiver(Receiver):
    def __init__(self, calls):
        self.calls = calls

    def handle(self, emission):
        return True

    async def flush(self):
        self.calls.append(self)


@pytest.mark.asyncio
async def test_flush_emissions_reaches_connected_receivers_only():
    calls = []
    connected, disconnected = RecordingReceiver(calls), RecordingReceiver(calls)
    connected.connect()
    disconnected.connect()
    disconnected.disconnect()
    try:
        await flush_emissions()
    finally:
        connected.disconnect()

    assert calls == [connected]


class RecordingSocket:
    def __init__(self, fail_on: str | None = None):
        self.sent = []
        self.fail_on = fail_on

    async def send(self, payload):
        await asyncio.sleep(0.01)
        frame = json.loads(payload)
        if frame["type"] == self.fail_on:
            raise RuntimeError("socket closed")
        self.sent.append(frame)


@pytest.mark.asyncio
async def test_websocket_flush_waits_for_the_real_send_loop(monkeypatch):
    # a flush that has to wait for the timeout fails this test
    monkeypatch.setattr(websocket_server, "FLUSH_TIMEOUT", 5)
    queue = asyncio.Queue()
    socket = RecordingSocket()
    sender = asyncio.create_task(send_queued_frames(socket, queue))
    try:
        # queue_put schedules the put; flush must still see it
        loop = asyncio.get_running_loop()
        loop.call_soon(queue.put_nowait, {"type": "status"})
        loop.call_soon(queue.put_nowait, {"type": "character"})
        started = loop.time()
        await WebsocketHandler.flush(SimpleNamespace(out_queue=queue))
        assert loop.time() - started < 1
        assert [frame["type"] for frame in socket.sent] == ["status", "character"]
    finally:
        sender.cancel()


@pytest.mark.asyncio
async def test_send_loop_marks_a_failed_frame_done_and_returns_the_error():
    queue = asyncio.Queue()
    socket = RecordingSocket(fail_on="character")
    queue.put_nowait({"type": "status"})
    queue.put_nowait({"type": "character"})

    error = await asyncio.wait_for(send_queued_frames(socket, queue), 1)

    assert isinstance(error, RuntimeError)
    assert [frame["type"] for frame in socket.sent] == ["status"]
    await asyncio.wait_for(queue.join(), 1)


@pytest.mark.asyncio
async def test_websocket_flush_gives_up_when_nothing_sends(monkeypatch):
    monkeypatch.setattr(websocket_server, "FLUSH_TIMEOUT", 0.05)
    queue = asyncio.Queue()
    queue.put_nowait({"type": "character"})

    await WebsocketHandler.flush(SimpleNamespace(out_queue=queue))

    assert queue.qsize() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("emit_message", [True, False])
async def test_player_line_is_flushed_before_the_save(scene, monkeypatch, emit_message):
    order = []

    async def flush():
        order.append("flush")

    async def save():
        order.append("save")

    monkeypatch.setattr(tale_mate, "flush_emissions", flush)
    monkeypatch.setattr(
        scene, "emit_history_message", lambda message: order.append("emit")
    )
    monkeypatch.setattr(scene, "attempt_auto_save", save)
    message = CharacterMessage(message="Alice: I take the key.", source="player")

    await scene._append_for_dispatch([message], emit_message=emit_message)

    assert order == (["emit", "flush", "save"] if emit_message else ["save"])
    assert message.history_dispatch_pending
