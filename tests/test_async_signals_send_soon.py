"""
send_soon listener tasks, and signals held while a template renders.
"""

import asyncio
import uuid

import pytest
from structlog.testing import capture_logs

import talemate.emit.async_signals as async_signals
from talemate.agents.context import ActiveAgent, active_agent
from talemate.exceptions import GenerationCancelled
from talemate.prompts.base import send_outside_render, signals_after_render


class _Agent:
    verbose_name = "agent"


@pytest.fixture
def signal():
    name = f"test.send_soon.{uuid.uuid4().hex}"
    async_signals.register(name)
    yield async_signals.get(name)
    async_signals.handlers.pop(name, None)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_listener_does_not_share_the_sender_agent_state(signal):
    started, parent_done = asyncio.Event(), asyncio.Event()
    seen = {}

    async def listener(emission):
        seen["inherited"] = active_agent.get()
        with ActiveAgent(_Agent(), listener) as context:
            context.state["listener"] = True
            started.set()
            await parent_done.wait()
            seen["state"] = dict(context.state)

    signal.connect(listener)

    async def parent():
        with ActiveAgent(_Agent(), parent) as context:
            async_signals.send_soon(signal.name, "emission")
            await started.wait()
            context.state["parent"] = True
        parent_done.set()

    await asyncio.wait_for(parent(), timeout=5)
    await settle()
    assert seen["inherited"] is None
    assert seen["state"] == {"listener": True}


async def test_a_listener_error_in_the_task_is_logged(signal):
    async def listener(emission):
        raise GenerationCancelled("stopped")

    signal.connect(listener)
    with capture_logs() as logs:
        task = async_signals.send_soon(signal.name, "emission")
        await asyncio.gather(task, return_exceptions=True)
        await settle()
    [entry] = [e for e in logs if e["event"] == "Signal task ended with an exception"]
    assert entry["error_type"] == "GenerationCancelled"
    assert entry["task"] == f"signal:{signal.name}"


async def test_a_task_that_outlives_its_render_still_sends(signal):
    received = []

    async def listener(emission):
        received.append(emission)

    signal.connect(listener)
    release = asyncio.Event()

    async def late():
        await release.wait()
        await send_outside_render(signal.name, "late")

    with signals_after_render():
        task = asyncio.create_task(late())
        await send_outside_render(signal.name, "held")
        assert received == []
    await settle()
    assert received == ["held"]
    release.set()
    await asyncio.wait_for(task, timeout=5)
    assert received == ["held", "late"]
