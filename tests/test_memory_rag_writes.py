import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from talemate.agents.memory import MemoryAgent


@pytest.fixture
def memory():
    agent = object.__new__(MemoryAgent)
    agent.scene = SimpleNamespace(memory_revision=0)
    agent._ready_to_add = True
    agent.invalidate_audience_writes = Mock()
    agent.invalidate_audience_index = Mock()
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,args",
    [
        ("add", ("A new memory.",)),
        ("add_many", ([{"id": "lore", "text": "A new memory."}],)),
        ("delete", ({"ids": "lore"},)),
    ],
)
@pytest.mark.parametrize("fails", [False, True])
async def test_memory_write_invalidates_on_completion(memory, operation, args, fails):
    def persist(*args, **kwargs):
        assert memory.scene.memory_revision == 1
        if fails:
            raise RuntimeError("partial write")

    write = Mock(side_effect=persist)
    setattr(memory, f"_{operation}", write)
    call = getattr(MemoryAgent, operation).__wrapped__
    if fails:
        with pytest.raises(RuntimeError, match="partial write"):
            await call(memory, *args)
    else:
        await call(memory, *args)
    assert write.call_count == 1
    assert memory.scene.memory_revision == 2


@pytest.mark.asyncio
async def test_empty_writes_do_not_invalidate(memory):
    memory._add = Mock()
    memory._add_many = Mock()
    await MemoryAgent.add.__wrapped__(memory, "")
    await MemoryAgent.add_many.__wrapped__(memory, [])
    assert memory.scene.memory_revision == 0
    memory._add.assert_not_called()
    memory._add_many.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_cancelled_write_invalidates_original_scene_when_executor_finishes(
    memory, monkeypatch, fails
):
    original = memory.scene
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    completed = asyncio.Event()
    invalidated = asyncio.Event()
    warning = Mock()
    monkeypatch.setattr("talemate.agents.memory.log.warning", warning)
    memory.invalidate_audience_writes.side_effect = lambda *a, **kw: invalidated.set()

    def write(objects):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        if fails:
            raise RuntimeError("cancelled write failed")

    run_write = memory._write_memory

    def observed(*args):
        try:
            return run_write(*args)
        finally:
            loop.call_soon_threadsafe(completed.set)

    memory._add_many = write
    memory._write_memory = observed
    pending = asyncio.create_task(
        MemoryAgent.add_many.__wrapped__(memory, [{"id": "lore", "text": "new"}])
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert original.memory_revision == 1
        memory.scene = SimpleNamespace(memory_revision=0)
    finally:
        release.set()
        await asyncio.wait_for(completed.wait(), timeout=5)
    assert original.memory_revision == 2
    assert memory.scene.memory_revision == 0
    await asyncio.wait_for(invalidated.wait(), timeout=5)
    memory.invalidate_audience_writes.assert_called_once_with(
        [{"id": "lore", "text": "new"}], scene=original
    )
    if fails:
        warning.assert_called_once_with(
            "memory write failed after cancellation", error="cancelled write failed"
        )
    else:
        warning.assert_not_called()


@pytest.mark.asyncio
async def test_add_retry_keeps_original_revision_scene(memory, monkeypatch):
    original = memory.scene
    replacement = SimpleNamespace(memory_revision=0)

    async def rebind(_delay):
        memory.scene = replacement

    monkeypatch.setattr(asyncio, "sleep", rebind)
    memory._add = Mock(side_effect=[AttributeError("retry"), None])
    await MemoryAgent.add.__wrapped__(memory, "new")
    assert memory._add.call_count == 1
    assert original.memory_revision == 2
    assert replacement.memory_revision == 0
    memory.invalidate_audience_writes.assert_called_once_with(
        [{"id": None, "meta": {}}], scene=original
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_queued_write_refused_after_scene_rebind(memory, monkeypatch, cancel):
    original = memory.scene
    replacement = SimpleNamespace(memory_revision=0)
    loop = asyncio.get_running_loop()
    busy, queued, invalidated = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release = threading.Event()
    memory._add_many = Mock()
    memory.invalidate_audience_writes.side_effect = lambda *a, **kw: invalidated.set()
    run_in_executor = loop.run_in_executor

    def occupy_worker():
        loop.call_soon_threadsafe(busy.set)
        assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        blocker = executor.submit(occupy_worker)

        def enqueue(_executor, operation, *args):
            future = run_in_executor(executor, operation, *args)
            queued.set()
            return future

        monkeypatch.setattr(loop, "run_in_executor", enqueue)
        pending = None
        try:
            await asyncio.wait_for(busy.wait(), timeout=5)
            pending = asyncio.create_task(
                MemoryAgent.add_many.__wrapped__(
                    memory, [{"id": "lore", "text": "new"}]
                )
            )
            await asyncio.wait_for(queued.wait(), timeout=5)
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            memory.scene = replacement
        finally:
            release.set()
            if pending is not None and not pending.cancelled():
                await asyncio.wait_for(pending, timeout=5)
        await asyncio.wait_for(invalidated.wait(), timeout=5)
        blocker.result()
    memory._add_many.assert_not_called()
    assert original.memory_revision == replacement.memory_revision == 0
    memory.invalidate_audience_writes.assert_called_once_with(
        [{"id": "lore", "text": "new"}], scene=original
    )


def test_cancelled_write_completion_consumes_exception(memory, monkeypatch):
    operation = Mock()
    operation.exception.return_value = RuntimeError("cancelled write failed")
    warning = Mock()
    monkeypatch.setattr("talemate.agents.memory.log.warning", warning)
    objects = [{"id": "lore", "text": "new"}]
    memory._complete_cancelled_write(memory.scene, objects, operation)
    operation.exception.assert_called_once_with()
    warning.assert_called_once_with(
        "memory write failed after cancellation", error="cancelled write failed"
    )
    memory.invalidate_audience_writes.assert_called_once_with(
        objects, scene=memory.scene
    )
