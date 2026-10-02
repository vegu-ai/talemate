"""
agent.summarization.perceptions.after / .failed, sent after the knowledge step.
"""

from _knowledge_step_helpers import push_and_step
from talemate.knowledge.step import knowledge_step
import asyncio
from contextlib import suppress

import pytest

import talemate.emit.async_signals as async_signals
from talemate.agents.summarize.perceptions import (
    PerceptionsAfterEmission,
    PerceptionsFailedEmission,
)
from talemate.exceptions import GenerationCancelled
from talemate.scene_message import NarratorMessage

import test_perception_audiences

audience_scene = test_perception_audiences.audience_scene


def step_lock(scene):
    from talemate.knowledge import step

    return step._locks[scene]


@pytest.fixture
def listen():
    connected = []

    def connect(name, handler):
        async_signals.get(name).connect(handler)
        connected.append((name, handler))

    yield connect
    for name, handler in connected:
        async_signals.get(name).disconnect(handler)


@pytest.mark.asyncio
async def test_after_carries_the_stored_views(audience_scene, listen):
    scene, summarizer, request = audience_scene
    events = []

    async def after(emission):
        events.append(emission)

    listen("agent.summarization.perceptions.after", after)
    message = NarratorMessage(message="The bell rings.")
    await push_and_step(scene, message)

    [event] = events
    assert isinstance(event, PerceptionsAfterEmission)
    assert event.agent is summarizer
    assert event.message_id == message.id
    assert event.analyzed == ["Alice"]
    assert event.verbatim == ["Bob"]
    assert {(view.character, view.status, view.text) for view in event.views} == {
        ("Alice", "ready", "The bell rings."),
        ("Bob", "ready", "The bell rings."),
    }


@pytest.mark.asyncio
async def test_listener_that_requests_perceptions_again_does_not_deadlock(
    audience_scene, listen
):
    scene, summarizer, request = audience_scene
    calls = []

    async def after(emission):
        calls.append(step_lock(scene).locked())
        await asyncio.wait_for(knowledge_step(scene), timeout=5)

    listen("agent.summarization.perceptions.after", after)
    await asyncio.wait_for(
        push_and_step(scene, NarratorMessage(message="Thunder.")), timeout=10
    )
    assert calls == [False]


@pytest.mark.asyncio
async def test_failed_is_sent_after_the_pass(audience_scene, listen):
    scene, summarizer, request = audience_scene
    events = []
    lock_held = []

    async def failed(emission):
        lock_held.append(step_lock(scene).locked())
        events.append(emission)

    async def broken(*args, **kwargs):
        raise ValueError("model broke")

    request.side_effect = broken
    listen("agent.summarization.perceptions.failed", failed)
    message = NarratorMessage(message="Smoke.")
    with suppress(GenerationCancelled):
        await push_and_step(scene, message)

    [event] = events
    assert isinstance(event, PerceptionsFailedEmission)
    assert event.message_id == message.id
    assert event.characters == ["Alice"]
    assert event.error == "model broke"
    assert lock_held == [False]


def edit_through_the_ui(scene, message, text):
    from types import SimpleNamespace

    from talemate.server.scene_message import SceneMessagePlugin

    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda d: None))
    return plugin.handle_edit({"id": message.id, "text": text})


def pending(scene):
    from talemate.knowledge.revision_refresh import revision_requires_refresh

    return [
        m.id
        for m in scene.history
        if m.revision_state is not None and revision_requires_refresh(scene, m)
    ]


@pytest.mark.asyncio
async def test_revision_refresh_listener_that_generates_does_not_deadlock(
    audience_scene, listen
):
    from structlog.testing import capture_logs

    from talemate.knowledge.revision_scope import in_revision_phase

    scene, summarizer, request = audience_scene
    message = NarratorMessage(message="The bell rings.")
    await push_and_step(scene, message)
    calls = []

    async def after(emission):
        calls.append(("start", in_revision_phase(scene), step_lock(scene).locked()))
        # a generation starts with its own knowledge step
        async with asyncio.timeout(5):
            await knowledge_step(scene)
        calls.append(("done", None, None))

    listen("agent.summarization.perceptions.after", after)
    await edit_through_the_ui(scene, message, "The bell stops.")
    with capture_logs() as logs:
        await asyncio.wait_for(knowledge_step(scene), timeout=10)
    assert calls == [("start", False, False), ("done", None, None)]
    assert not [log for log in logs if log["event"] == "Error in signal receiver"]
    assert message.knowledge.revision == 2


@pytest.mark.asyncio
async def test_step_sends_its_events_after_it_has_finished(audience_scene, listen):
    scene, summarizer, request = audience_scene
    first = NarratorMessage(message="The bell rings.")
    second = NarratorMessage(message="A door opens.")
    await push_and_step(scene, first)
    await push_and_step(scene, second)
    seen = []

    async def after(emission):
        seen.append((emission.message_id, pending(scene), step_lock(scene).locked()))

    listen("agent.summarization.perceptions.after", after)
    await edit_through_the_ui(scene, first, "The bell stops.")
    await edit_through_the_ui(scene, second, "A door slams.")
    assert pending(scene) == [first.id, second.id]
    # the generation that ran the step continues after the handlers
    await asyncio.wait_for(knowledge_step(scene), timeout=10)
    assert sorted(seen) == [(first.id, [], False), (second.id, [], False)]


@pytest.mark.asyncio
async def test_a_listener_task_started_in_a_step_sends_on_its_own(
    audience_scene, listen
):
    from talemate.knowledge.revision_scope import in_revision_phase, step_events

    scene, summarizer, request = audience_scene
    message = NarratorMessage(message="The bell rings.")
    await push_and_step(scene, message)
    await edit_through_the_ui(scene, message, "The bell stops.")
    probe = f"test.step_listener.{id(scene)}"
    async_signals.register(probe)
    step_ended = asyncio.Event()
    seen = {}
    answer = request.side_effect

    async def started_inside(*args, **kwargs):
        async_signals.send_soon(probe, None)
        return await answer(*args, **kwargs)

    async def late(emission):
        await step_ended.wait()
        seen["phase"] = in_revision_phase(scene)
        seen["step_list"] = step_events.get()
        summarizer._queue_perception_event(
            scene, "agent.summarization.perceptions.after", "late"
        )

    delivered = []

    async def after(emission):
        delivered.append(emission)

    request.side_effect = started_inside
    async_signals.get(probe).connect(late)
    listen("agent.summarization.perceptions.after", after)
    try:
        await asyncio.wait_for(knowledge_step(scene), timeout=10)
        step_ended.set()
        for _ in range(10):
            await asyncio.sleep(0)
    finally:
        async_signals.handlers.pop(probe, None)
    assert seen == {"phase": False, "step_list": None}
    assert "late" in delivered


def test_a_closed_step_list_holds_nothing():
    # a plain task the step started keeps the step's list after the step ends
    from talemate.knowledge.revision_scope import (
        StepEvents,
        hold_for_step,
        step_events,
    )

    events = StepEvents()
    events.closed = True
    token = step_events.set(events)
    try:
        assert not hold_for_step("agent.summarization.perceptions.after", "late")
    finally:
        step_events.reset(token)
    assert events == []
