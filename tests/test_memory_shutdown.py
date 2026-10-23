import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import threading
from unittest.mock import AsyncMock, Mock, PropertyMock

import pytest

from talemate.agents.memory import MemoryAgent
from talemate.agents.memory.exceptions import MemoryShutdownRefused
from talemate.prompts.base import Prompt
from talemate.load import load_scene_from_data
import talemate.instance as instance
from talemate.world_state import ContextPin


@pytest.fixture
def memory():
    return MemoryAgent()


async def test_shutdown_refuses_new_executor_work(memory, monkeypatch):
    submit = Mock()
    monkeypatch.setattr(asyncio.get_running_loop(), "run_in_executor", submit)
    memory.refuse_new_memory_work()

    with pytest.raises(MemoryShutdownRefused):
        memory._run_in_executor(Mock())
    with pytest.raises(MemoryShutdownRefused):
        await memory._to_thread(Mock())
    submit.assert_not_called()


async def test_shutdown_refuses_queued_memory_work(memory, monkeypatch):
    release = threading.Event()
    started = threading.Event()
    loop = asyncio.get_running_loop()
    submit = loop.run_in_executor
    work = Mock()

    def occupy_worker():
        started.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        blocker = executor.submit(occupy_worker)
        monkeypatch.setattr(
            loop, "run_in_executor", lambda _, fn, *args: submit(executor, fn, *args)
        )
        try:
            assert started.wait(1)
            queued = memory._run_in_executor(work)
            memory.refuse_new_memory_work()
            release.set()
            with pytest.raises(MemoryShutdownRefused):
                await asyncio.wait_for(queued, 2)
            assert not queued.cancelled()
            work.assert_not_called()
        finally:
            release.set()
            blocker.result(timeout=5)


async def test_thread_dispatch_preserves_context_and_arguments(memory):
    context = ContextVar("shutdown_test_context", default="unset")
    token = context.set("request")
    try:
        result = await memory._to_thread(
            lambda value, *, suffix: (context.get(), value + suffix), "a", suffix="b"
        )
        assert result == ("request", "ab")
    finally:
        context.reset(token)


async def test_shutdown_releases_memory_readiness_wait(memory):
    memory.scene = object()
    waiting = asyncio.create_task(memory._wait_until_ready())
    await asyncio.sleep(0)
    memory.refuse_new_memory_work()
    assert await asyncio.wait_for(waiting, 1) is False


@pytest.mark.parametrize("cancelled", [False, True])
async def test_refused_queued_write_does_not_invalidate_or_log(
    memory, monkeypatch, cancelled
):
    operation = asyncio.get_running_loop().create_future()
    invalidate = Mock()
    warning = Mock()
    monkeypatch.setattr("talemate.agents.memory.log.warning", warning)
    task = asyncio.create_task(memory._shielded_write(operation, invalidate))
    await asyncio.sleep(0)
    if cancelled:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    operation.set_exception(MemoryShutdownRefused())
    if not cancelled:
        assert await task is False
        assert task.cancelling() == 0
    await asyncio.sleep(0)
    invalidate.assert_not_called()
    warning.assert_not_called()


async def test_refused_database_setup_does_not_log_failure(memory, monkeypatch):
    invalidate = Mock()
    error = Mock()
    memory._set_db = Mock()
    monkeypatch.setattr(memory, "invalidate_audience_index", invalidate)
    monkeypatch.setattr("talemate.agents.memory.log.error", error)
    memory.refuse_new_memory_work()

    assert await memory.set_db() is False

    invalidate.assert_not_called()
    error.assert_not_called()
    memory._set_db.assert_not_called()


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize(
    "method,args",
    [
        ("get", ("lantern",)),
        ("get_document", (["lore"],)),
        ("get_documents_by_meta", ({"typ": "world_state"},)),
        ("multi_query", (["lantern"],)),
        ("rerank", (["lantern"], ["lore"])),
        ("embed_texts", (["lantern"],)),
    ],
)
async def test_refused_read_cancels_caller_without_error_or_result(
    memory, scene, monkeypatch, queued, method, args
):
    memory.scene = scene
    memory.db = Mock()
    monkeypatch.setattr(memory, "prepare_author_index", AsyncMock())
    monkeypatch.setattr(type(memory), "embedding_function", PropertyMock())
    monkeypatch.setattr(type(memory), "reranker", PropertyMock())
    operation = asyncio.get_running_loop().create_future()
    submitted = asyncio.Event()

    def submit(*args):
        submitted.set()
        return operation

    monkeypatch.setattr(asyncio.get_running_loop(), "run_in_executor", submit)
    log_error, ui_error, use_result, test_stop = Mock(), Mock(), Mock(), Mock()

    # This caller awaits the read in the same task; RunModule awaits a child task.
    async def caller():
        try:
            try:
                use_result(await getattr(memory, method)(*args))
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                test_stop()
        except Exception as error:
            log_error("game_loop", error=error, unhandled=True)
            ui_error(error)

    if not queued:
        memory.refuse_new_memory_work()
    task = asyncio.create_task(caller())
    if queued:
        await asyncio.wait_for(submitted.wait(), 2)
        memory.refuse_new_memory_work()
        operation.set_exception(MemoryShutdownRefused())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert task.cancelling() == 1
    log_error.assert_not_called()
    ui_error.assert_not_called()
    use_result.assert_not_called()
    test_stop.assert_not_called()
    assert not getattr(memory, "processing", 0)


@pytest.mark.parametrize("iterate", [None, 2])
async def test_prompt_memory_refusal_stays_quiet(memory, scene, monkeypatch, iterate):
    memory.scene = scene
    monkeypatch.setitem(instance.AGENTS, "memory", memory)
    error, completed = Mock(), Mock()
    prompt = Prompt(uid="memory-test", agent_type="memory", name="test")
    memory.refuse_new_memory_work()

    async def build_prompt():
        try:
            completed(prompt.query_memory("lantern", iterate=iterate))
        except Exception as exc:
            error(exc)

    task = asyncio.create_task(build_prompt())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    error.assert_not_called()
    completed.assert_not_called()


async def test_shutdown_does_not_prune_valid_pins_during_scene_load(
    memory, scene, monkeypatch
):
    memory.scene = scene
    monkeypatch.setitem(instance.AGENTS, "memory", memory)
    pin = ContextPin(entry_id="lore", active=True, condition="At dusk", decay=4)
    data = {
        "format_version": 1,
        "history": [],
        "archived_history": [{"id": "lore", "text": "The lantern glows.", "ts": 0}],
        "world_state": {
            "pins": {"lore": pin.model_dump(), "missing": {"entry_id": "missing"}}
        },
    }
    memory.refuse_new_memory_work()
    memory._set_db = Mock()

    await load_scene_from_data(scene, data)

    memory._set_db.assert_not_called()
    assert scene.world_state.pins == {"lore": pin}
