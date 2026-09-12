import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from talemate.knowledge.processing import (
    track_evidence_task,
    wait_for_evidence_writers,
    evidence_writer,
)
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent


@pytest.fixture
def evidence_wait(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    agent = get_agent("world_state")
    statuses = []
    waiting = asyncio.Event()

    def emit(typ, **data):
        statuses.append(data)
        if data.get("message", "").startswith("Waiting for knowledge updates before"):
            waiting.set()

    monkeypatch.setattr("talemate.status.emit", emit)
    dispatch = AsyncMock()
    monkeypatch.setattr(agent, "dispatch_world_state_update", dispatch)
    agent._tracked_tasks = {}
    return SimpleNamespace(
        agent=agent, scene=scene, statuses=statuses, waiting=waiting, dispatch=dispatch
    )


@pytest.mark.asyncio
async def test_no_writer_does_not_start_work_or_show_a_wait(evidence_wait):
    t = evidence_wait
    await wait_for_evidence_writers(t.scene, agent=t.agent)
    t.dispatch.assert_not_awaited()
    assert t.statuses == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        "user",
        "consumed_user",
        "scene_switch",
        "writer_cancel",
        "waiter_cancel",
        "replacement",
    ],
)
async def test_wait_cancellation_and_replacement(evidence_wait, outcome):
    t = evidence_wait
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    track_evidence_task(t.scene, task)
    waiter = asyncio.create_task(wait_for_evidence_writers(t.scene, agent=t.agent))
    replacement = None
    try:
        await asyncio.wait_for(t.waiting.wait(), 2)
        if outcome in ("user", "consumed_user"):
            t.scene.interrupt()
            if outcome == "consumed_user":
                t.scene.cancel_requested = False
            with pytest.raises(GenerationCancelled) as raised:
                await asyncio.wait_for(waiter, 2)
            assert raised.value.by_user
            assert not task.done()
        elif outcome == "scene_switch":
            t.agent.scene = object()
            release.set()
            with pytest.raises(GenerationCancelled, match="Scene changed"):
                await asyncio.wait_for(waiter, 2)
        elif outcome == "waiter_cancel":
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not task.cancelled() and not task.done()
        elif outcome == "writer_cancel":
            task.cancel()
            await asyncio.wait_for(waiter, 2)
        else:
            replacement = asyncio.create_task(release.wait())
            track_evidence_task(t.scene, replacement)
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not waiter.done()
            release.set()
            await asyncio.wait_for(waiter, 2)
        t.dispatch.assert_not_awaited()
        assert t.statuses[-1]["status"] == "idle"
    finally:
        release.set()
        waiter.cancel()
        await asyncio.gather(
            task,
            waiter,
            *([replacement] if replacement else []),
            return_exceptions=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_writer_scope_finishes_before_owning_task(evidence_wait, failure):
    t = evidence_wait
    entered = asyncio.Event()
    release = asyncio.Event()
    keep_alive = asyncio.Event()

    @evidence_writer
    async def write(scene):
        # Nested consumers must not wait for their own enclosing writer.
        await wait_for_evidence_writers(scene, agent=t.agent)
        entered.set()
        await release.wait()
        if failure:
            raise ValueError("writer failed")

    async def long_lived_owner():
        try:
            await write(scene=t.scene)
        except ValueError:
            pass
        await keep_alive.wait()

    owner = asyncio.create_task(long_lived_owner())
    waiter = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        waiter = asyncio.create_task(wait_for_evidence_writers(t.scene, agent=t.agent))
        await asyncio.wait_for(t.waiting.wait(), 2)
        release.set()
        await asyncio.wait_for(waiter, 2)
        assert not owner.done()
    finally:
        release.set()
        keep_alive.set()
        await asyncio.gather(
            owner, *([waiter] if waiter else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_background_dispatch_registers_before_execution_and_drains_followups(
    evidence_wait,
):
    from talemate.status import background_task

    t = evidence_wait
    release = asyncio.Event()
    followup_started = asyncio.Event()
    followup_tasks = []

    @evidence_writer
    @background_task("Writing evidence")
    async def followup(scene):
        followup_started.set()
        await release.wait()

    @evidence_writer
    @background_task("Writing evidence")
    async def dispatch(scene):
        followup_tasks.append(await followup(scene))

    task = await dispatch(t.scene)
    # Neither dispatched coroutine has executed yet.
    waiter = asyncio.create_task(wait_for_evidence_writers(t.scene, agent=t.agent))
    try:
        await asyncio.wait_for(followup_started.wait(), 2)
        await asyncio.sleep(0)
        assert not waiter.done()
        release.set()
        await asyncio.wait_for(waiter, 2)
    finally:
        release.set()
        await asyncio.gather(task, waiter, *followup_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_standard_mode_does_not_wait_for_a_writer(evidence_wait):
    t = evidence_wait
    t.scene.knowledge_eligibility = "legacy"
    release = asyncio.Event()
    writer = asyncio.create_task(release.wait())
    track_evidence_task(t.scene, writer)
    try:
        await asyncio.wait_for(wait_for_evidence_writers(t.scene, agent=t.agent), 1)
        assert not writer.done()
        assert t.statuses == []
    finally:
        release.set()
        await writer


@pytest.mark.asyncio
async def test_wait_status_returns_when_one_background_writer_finishes(evidence_wait):
    from talemate.status import background_task

    t = evidence_wait
    first_release, last_release = asyncio.Event(), asyncio.Event()

    @evidence_writer
    @background_task("Updating character summaries")
    async def first(scene):
        await first_release.wait()

    first_writer = await first(t.scene)
    last_writer = asyncio.create_task(last_release.wait())
    track_evidence_task(t.scene, last_writer)
    waiter = asyncio.create_task(wait_for_evidence_writers(t.scene, agent=t.agent))
    try:
        await asyncio.wait_for(t.waiting.wait(), 2)
        first_release.set()
        await first_writer
        for _ in range(5):
            await asyncio.sleep(0)
        assert not waiter.done()
        assert any(status["status"] == "idle" for status in t.statuses)
        assert t.statuses[-1]["status"] == "busy"
        assert (
            t.statuses[-1]["message"]
            == "Waiting for knowledge updates before scene analysis"
        )
        last_release.set()
        await asyncio.wait_for(waiter, 2)
    finally:
        first_release.set()
        last_release.set()
        await asyncio.gather(first_writer, last_writer, waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_scene_release_cancels_wait_without_releasing_writer(evidence_wait):
    t = evidence_wait
    release = asyncio.Event()
    writer = asyncio.create_task(release.wait())
    track_evidence_task(t.scene, writer)
    waiter = asyncio.create_task(wait_for_evidence_writers(t.scene, agent=t.agent))
    try:
        await asyncio.wait_for(t.waiting.wait(), 2)
        t.scene.interrupt()
        t.scene.cancel_requested = False
        t.scene.active = False
        t.agent.scene = object()
        with pytest.raises(GenerationCancelled) as raised:
            await asyncio.wait_for(waiter, 1)
        assert raised.value.by_user
        assert not writer.done()
    finally:
        release.set()
        await asyncio.gather(writer, waiter, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["character", "world"])
async def test_reinforcement_dispatch_registers_entire_refresh(
    evidence_wait, monkeypatch, target
):
    from talemate.server.world_state_manager import WorldStateManagerPlugin

    t = evidence_wait
    release = asyncio.Event()
    finished = False

    async def refresh(*args, **kwargs):
        nonlocal finished
        await release.wait()
        finished = True

    manager = SimpleNamespace(
        run_detail_reinforcement=AsyncMock(side_effect=refresh),
        world_state=SimpleNamespace(
            find_reinforcement=AsyncMock(
                return_value=(None, SimpleNamespace(model_dump=lambda: {}))
            )
        ),
    )
    monkeypatch.setattr(
        "talemate.server.world_state_manager.WorldStateManager", lambda scene: manager
    )
    plugin = WorldStateManagerPlugin(
        SimpleNamespace(scene=t.scene, queue_put=lambda data: None)
    )
    monkeypatch.setattr(plugin, "handle_get_character_details", AsyncMock())
    monkeypatch.setattr(plugin, "handle_get_world", AsyncMock())
    monkeypatch.setattr(plugin, "signal_operation_done", AsyncMock())
    if target == "character":
        task = await plugin.handle_run_character_detail_reinforcement(
            {"name": "Alice", "question": "Location?"}
        )
    else:
        task = await plugin.handle_run_world_state_reinforcement(
            {"question": "Location?"}
        )
    waiter = asyncio.create_task(wait_for_evidence_writers(t.scene, agent=t.agent))
    try:
        await asyncio.wait_for(t.waiting.wait(), 2)
        assert not finished
        assert not waiter.done()
        release.set()
        await asyncio.wait_for(waiter, 2)
        assert finished
        manager.run_detail_reinforcement.assert_awaited_once()
        await task
        plugin.signal_operation_done.assert_awaited_once()
    finally:
        release.set()
        await asyncio.gather(task, waiter, return_exceptions=True)
