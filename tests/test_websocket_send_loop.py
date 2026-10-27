import asyncio
import json

import pytest

from talemate.server.api import send_queued_frames


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
async def test_send_loop_sends_in_order_and_returns_the_closing_error():
    queue = asyncio.Queue()
    socket = RecordingSocket(fail_on="character")
    queue.put_nowait({"type": "status"})
    queue.put_nowait({"type": "character"})

    error = await asyncio.wait_for(send_queued_frames(socket, queue), 1)

    assert isinstance(error, RuntimeError)
    assert [frame["type"] for frame in socket.sent] == ["status"]
