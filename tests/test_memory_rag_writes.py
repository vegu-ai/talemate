import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from talemate.agents.memory import MemoryAgent
from talemate.agents.memory.exceptions import MemoryShutdownRefused


@pytest.fixture
def memory():
    agent = object.__new__(MemoryAgent)
    agent.scene = SimpleNamespace(
        memory_revision=0, memory_writes_in_flight=0, rag_cache={"old": {}}
    )
    agent._db_lock = threading.Lock()
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
async def test_memory_write_keeps_entries_but_advances_revision(
    memory, operation, args, fails
):
    def persist(*args, **kwargs):
        assert memory.scene.memory_revision == 1
        assert memory.scene.memory_writes_in_flight == 1
        assert memory.scene.rag_cache == {"old": {}}
        memory.scene.rag_cache["during-write"] = {"memory_revision": 1}
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
    assert memory.scene.memory_writes_in_flight == 0
    assert memory.scene.rag_cache == {
        "old": {},
        "during-write": {"memory_revision": 1},
    }


@pytest.mark.asyncio
async def test_empty_writes_preserve_store_revision_and_rag_cache(memory):
    memory._add = Mock()
    memory._add_many = Mock()
    await MemoryAgent.add.__wrapped__(memory, "")
    await MemoryAgent.add_many.__wrapped__(memory, [])
    assert memory.scene.memory_revision == 0
    assert memory.scene.rag_cache == {"old": {}}
    memory._add.assert_not_called()
    memory._add_many.assert_not_called()
    memory.invalidate_audience_writes.assert_called_once_with([], scene=memory.scene)


@pytest.mark.parametrize(
    "operation,args",
    [
        ("add", ("New memory",)),
        ("add_many", ([{"id": "new", "text": "New memory"}],)),
        ("delete", ({"ids": "new"},)),
    ],
)
@pytest.mark.parametrize("queued", [False, True])
async def test_refused_write_is_not_written(
    memory, monkeypatch, operation, args, queued
):
    def refuse(*args):
        if queued:
            future = asyncio.get_running_loop().create_future()
            future.set_exception(MemoryShutdownRefused())
            return future
        raise MemoryShutdownRefused()

    monkeypatch.setattr(memory, "_run_in_executor", refuse)
    error = Mock()
    monkeypatch.setattr("talemate.agents.memory.log.error", error)
    call = getattr(MemoryAgent, operation).__wrapped__

    assert await call(memory, *args) is False

    assert memory.scene.memory_revision == 0
    memory.invalidate_audience_index.assert_not_called()
    memory.invalidate_audience_writes.assert_not_called()
    error.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("operation", ["add_many", "delete"])
async def test_cancelled_write_invalidates_original_scene_when_executor_finishes(
    memory, monkeypatch, fails, operation
):
    original = memory.scene
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    completed = asyncio.Event()
    invalidated = asyncio.Event()
    warning = Mock()
    monkeypatch.setattr("talemate.agents.memory.log.warning", warning)
    invalidation = (
        memory.invalidate_audience_writes
        if operation == "add_many"
        else memory.invalidate_audience_index
    )
    invalidation.side_effect = lambda *a, **kw: invalidated.set()

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

    setattr(memory, f"_{operation}", write)
    memory._write_memory = observed
    payload = (
        [{"id": "lore", "text": "new"}]
        if operation == "add_many"
        else {"ids": ["lore"]}
    )
    pending = asyncio.create_task(
        getattr(MemoryAgent, operation).__wrapped__(memory, payload)
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
    if operation == "add_many":
        invalidation.assert_called_once_with(payload, scene=original)
    else:
        invalidation.assert_called_once_with(scene=original, reconcile=True)
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
@pytest.mark.parametrize("operation", ["add_many", "delete"])
async def test_queued_write_refused_without_invalidation_after_scene_rebind(
    memory, monkeypatch, cancel, operation
):
    original = memory.scene
    replacement = SimpleNamespace(memory_revision=0)
    loop = asyncio.get_running_loop()
    busy, queued, invalidated = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release = threading.Event()
    write = Mock()
    setattr(memory, f"_{operation}", write)
    payload = (
        [{"id": "lore", "text": "new"}]
        if operation == "add_many"
        else {"ids": ["lore"]}
    )
    invalidation = (
        memory.invalidate_audience_writes
        if operation == "add_many"
        else memory.invalidate_audience_index
    )
    invalidation.side_effect = lambda *a, **kw: invalidated.set()
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
                getattr(MemoryAgent, operation).__wrapped__(memory, payload)
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
                assert await asyncio.wait_for(pending, timeout=5) is False
        blocker.result()
        await asyncio.sleep(0)
    write.assert_not_called()
    assert original.memory_revision == replacement.memory_revision == 0
    assert not invalidated.is_set()
    invalidation.assert_not_called()


def test_cancelled_write_completion_consumes_exception(memory, monkeypatch):
    operation = Mock()
    operation.exception.return_value = RuntimeError("cancelled write failed")
    warning = Mock()
    monkeypatch.setattr("talemate.agents.memory.log.warning", warning)
    objects = [{"id": "lore", "text": "new"}]
    from functools import partial

    memory._complete_cancelled_write(
        partial(memory.invalidate_audience_writes, objects, scene=memory.scene),
        operation,
    )
    operation.exception.assert_called_once_with()
    warning.assert_called_once_with(
        "memory write failed after cancellation", error="cancelled write failed"
    )
    memory.invalidate_audience_writes.assert_called_once_with(
        objects, scene=memory.scene
    )
