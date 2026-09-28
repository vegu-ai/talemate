"""
agent.summarization.perceptions.before / .after / .failed.
"""

import asyncio
from contextlib import suppress

import pytest

import talemate.emit.async_signals as async_signals
from talemate.agents.base import DynamicInstruction
from talemate.agents.summarize.perceptions import (
    PerceptionsAfterEmission,
    PerceptionsBeforeEmission,
    PerceptionsFailedEmission,
)
from talemate.exceptions import GenerationCancelled
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage

import test_perception_audiences

audience_scene = test_perception_audiences.audience_scene


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
    await scene.push_history(message)

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
async def test_before_instructions_reach_the_request(audience_scene, listen):
    scene, summarizer, request = audience_scene
    seen = []

    async def before(emission):
        seen.append(emission)
        emission.dynamic_instructions.append(
            DynamicInstruction(title="Secret", content="Nobody sees the mask.")
        )

    listen("agent.summarization.perceptions.before", before)
    message = NarratorMessage(message="A masked figure passes.")
    await scene.push_history(message)

    [emission] = seen
    assert isinstance(emission, PerceptionsBeforeEmission)
    assert emission.message_id == message.id
    assert emission.characters == ["Alice"]
    assert emission.attempt == 1
    variables = request.await_args.kwargs["vars"]
    assert [str(i) for i in variables["dynamic_instructions"]] == [
        "<|SECTION:Secret|>\nNobody sees the mask.\n<|CLOSE_SECTION|>"
    ]
    rendered = Prompt.get("summarizer.perceptions", vars=variables).render()
    assert "Nobody sees the mask." in rendered


@pytest.mark.asyncio
async def test_prompt_without_instructions_is_unchanged(audience_scene):
    scene, summarizer, request = audience_scene
    await scene.push_history(NarratorMessage(message="Rain."))
    variables = request.await_args.kwargs["vars"]
    assert variables["dynamic_instructions"] == []
    with_list = Prompt.get("summarizer.perceptions", vars=variables).render()
    without = Prompt.get(
        "summarizer.perceptions",
        vars={k: v for k, v in variables.items() if k != "dynamic_instructions"},
    ).render()
    assert with_list == without


@pytest.mark.asyncio
async def test_listener_that_requests_perceptions_again_does_not_deadlock(
    audience_scene, listen
):
    scene, summarizer, request = audience_scene
    calls = []

    async def after(emission):
        calls.append(summarizer._perception_locks[scene].locked())
        await asyncio.wait_for(summarizer.ensure_perceptions(scene), timeout=5)

    listen("agent.summarization.perceptions.after", after)
    await asyncio.wait_for(
        scene.push_history(NarratorMessage(message="Thunder.")), timeout=10
    )
    assert calls == [False]


@pytest.mark.asyncio
async def test_failed_is_sent_after_the_pass(audience_scene, listen):
    scene, summarizer, request = audience_scene
    events = []
    lock_held = []

    async def failed(emission):
        lock_held.append(summarizer._perception_locks[scene].locked())
        events.append(emission)

    async def broken(*args, **kwargs):
        raise ValueError("model broke")

    request.side_effect = broken
    listen("agent.summarization.perceptions.failed", failed)
    message = NarratorMessage(message="Smoke.")
    with suppress(GenerationCancelled):
        await scene.push_history(message)

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

    from talemate.knowledge.revision_refresh import catch_up_revisions
    from talemate.knowledge.revision_scope import in_revision_phase

    scene, summarizer, request = audience_scene
    message = NarratorMessage(message="The bell rings.")
    await scene.push_history(message)
    calls = []

    async def after(emission):
        calls.append(("start", in_revision_phase(scene)))
        # a generation starts by catching up on pending revisions
        async with asyncio.timeout(5):
            await catch_up_revisions(scene)
        calls.append(("done", None))

    listen("agent.summarization.perceptions.after", after)
    await edit_through_the_ui(scene, message, "The bell stops.")
    with capture_logs() as logs:
        await asyncio.wait_for(catch_up_revisions(scene), timeout=10)
    assert calls == [("start", False), ("done", None)]
    assert not [log for log in logs if log["event"] == "Error in signal receiver"]
    assert message.knowledge.revision == 2


@pytest.mark.asyncio
async def test_listener_runs_after_every_pending_revision(audience_scene, listen):
    from talemate.knowledge.revision_refresh import catch_up_revisions

    scene, summarizer, request = audience_scene
    first = NarratorMessage(message="The bell rings.")
    second = NarratorMessage(message="A door opens.")
    await scene.push_history(first)
    await scene.push_history(second)
    seen = []

    async def after(emission):
        seen.append((emission.message_id, pending(scene)))

    listen("agent.summarization.perceptions.after", after)
    await edit_through_the_ui(scene, first, "The bell stops.")
    await edit_through_the_ui(scene, second, "A door slams.")
    assert pending(scene) == [first.id, second.id]
    await asyncio.wait_for(catch_up_revisions(scene), timeout=10)
    assert sorted(message_id for message_id, _ in seen) == [first.id, second.id]
    assert all(still_pending == [] for _, still_pending in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["before_queued", "after_queued"])
async def test_cancelled_waiter_leaves_the_events_to_the_job(
    audience_scene, listen, monkeypatch, cancel
):
    from talemate.knowledge.revision_refresh import _jobs, refresh_revision

    scene, summarizer, request = audience_scene
    message = NarratorMessage(message="The bell rings.")
    await scene.push_history(message)
    await edit_through_the_ui(scene, message, "The bell stops.")

    answer_now = asyncio.Event()
    queued = asyncio.Event()
    finish_now = asyncio.Event()
    original = request.side_effect
    repair = summarizer.repair_summary_views

    async def gated(*args, **kwargs):
        await answer_now.wait()
        return await original(*args, **kwargs)

    async def gated_repair(*args, **kwargs):
        # runs after the analysis has stored the views and queued the event
        queued.set()
        await finish_now.wait()
        return await repair(*args, **kwargs)

    request.side_effect = gated
    monkeypatch.setattr(summarizer, "repair_summary_views", gated_repair)
    job = None
    deliveries = []

    async def after(emission):
        deliveries.append(job.done())

    listen("agent.summarization.perceptions.after", after)
    waiter = asyncio.create_task(refresh_revision(scene, message))
    await asyncio.sleep(0.05)
    job = _jobs[scene][message.id]
    if cancel == "after_queued":
        answer_now.set()
        await asyncio.wait_for(queued.wait(), timeout=5)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    for _ in range(5):
        await asyncio.sleep(0)
    assert deliveries == []
    answer_now.set()
    finish_now.set()
    await asyncio.wait_for(asyncio.shield(job), timeout=10)
    for _ in range(5):
        await asyncio.sleep(0)
    assert deliveries == [True]


@pytest.mark.asyncio
async def test_a_listener_task_started_in_a_job_queues_outside_it(
    audience_scene, listen
):
    from talemate.knowledge.revision_refresh import refresh_revision
    from talemate.knowledge.revision_scope import (
        in_revision_phase,
        job_perception_events,
    )

    scene, summarizer, request = audience_scene
    message = NarratorMessage(message="The bell rings.")
    await scene.push_history(message)
    await edit_through_the_ui(scene, message, "The bell stops.")
    probe = f"test.job_listener.{id(scene)}"
    async_signals.register(probe)
    job_ended = asyncio.Event()
    seen = {}

    async def late(emission):
        await job_ended.wait()
        seen["phase"] = in_revision_phase(scene)
        seen["job_list"] = job_perception_events.get()
        summarizer._queue_perception_event(
            scene, "agent.summarization.perceptions.after", "late"
        )
        await summarizer.ensure_perceptions(scene)

    async def before(emission):
        async_signals.send_soon(probe, emission)

    delivered = []

    async def after(emission):
        delivered.append(emission)

    async_signals.get(probe).connect(late)
    listen("agent.summarization.perceptions.before", before)
    listen("agent.summarization.perceptions.after", after)
    try:
        await asyncio.wait_for(refresh_revision(scene, message), timeout=10)
        job_ended.set()
        for _ in range(10):
            await asyncio.sleep(0)
    finally:
        async_signals.handlers.pop(probe, None)
    assert seen == {"phase": False, "job_list": None}
    assert "late" in delivered


@pytest.fixture
def held_signal():
    name = "test.after_catch_up"
    async_signals.register(name)
    received = []

    async def receiver(emission):
        received.append(emission)
        if emission == "raise":
            raise GenerationCancelled("stopped")

    async_signals.get(name).connect(receiver)
    yield name, received
    async_signals.handlers.pop(name, None)


@pytest.mark.asyncio
async def test_a_cancelled_waiter_does_not_take_the_owner_events(
    audience_scene, held_signal, monkeypatch
):
    from talemate.knowledge import revision_refresh
    from talemate.knowledge.revision_scope import (
        catch_up_owners,
        hold_until_catch_up_ends,
    )

    scene, summarizer, request = audience_scene
    name, received = held_signal
    release = asyncio.Event()

    async def pending(scene):
        hold_until_catch_up_ends(scene, [(name, "held")])
        await release.wait()

    monkeypatch.setattr(revision_refresh, "_catch_up_pending", pending)
    owner = asyncio.create_task(revision_refresh.catch_up_revisions(scene))
    async with asyncio.timeout(5):
        while scene not in catch_up_owners:
            await asyncio.sleep(0)
    waiter = asyncio.create_task(revision_refresh.catch_up_revisions(scene))
    await asyncio.sleep(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await asyncio.sleep(0.01)
    assert received == []
    release.set()
    await asyncio.wait_for(owner, timeout=5)
    assert received == ["held"]


@pytest.mark.asyncio
async def test_a_raising_listener_leaves_the_rest_to_tasks(
    audience_scene, held_signal, monkeypatch
):
    from talemate.knowledge import revision_refresh
    from talemate.knowledge.revision_scope import hold_until_catch_up_ends

    scene, summarizer, request = audience_scene
    name, received = held_signal

    async def pending(scene):
        hold_until_catch_up_ends(scene, [(name, "raise"), (name, "rest")])

    monkeypatch.setattr(revision_refresh, "_catch_up_pending", pending)
    with pytest.raises(GenerationCancelled):
        await revision_refresh.catch_up_revisions(scene)
    for _ in range(5):
        await asyncio.sleep(0)
    assert received == ["raise", "rest"]


@pytest.mark.asyncio
async def test_a_closed_job_list_queues_on_the_scene(audience_scene):
    # a plain task the job started keeps the job's list after the job ends
    from talemate.knowledge.revision_scope import JobEvents, job_perception_events

    scene, summarizer, request = audience_scene
    events = JobEvents()
    events.closed = True
    token = job_perception_events.set(events)
    try:
        summarizer._queue_perception_event(
            scene, "agent.summarization.perceptions.after", "late"
        )
    finally:
        job_perception_events.reset(token)
    assert events == []
    assert summarizer._perception_events[scene] == [
        ("agent.summarization.perceptions.after", "late")
    ]
