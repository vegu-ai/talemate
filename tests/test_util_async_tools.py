"""Tests for talemate.util.async_tools.

Covers bounded_gather, throttle, debounce, shared_debounce, and
cleanup_pending_tasks.
"""

import asyncio

import pytest

from talemate.exceptions import GenerationCancelled
from talemate.util.async_tools import (
    bounded_gather,
    bounded_gather_apply,
    cleanup_pending_tasks,
    debounce,
    shared_debounce,
    throttle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CallCounter:
    """Tracks invocations of a wrapped coroutine."""

    def __init__(self):
        self.calls = []

    async def coro(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return ("ok", args, kwargs)


# ---------------------------------------------------------------------------
# bounded_gather
# ---------------------------------------------------------------------------


class InFlightTracker:
    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0

    async def coro(self, value):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return value


async def test_bounded_gather_respects_bound_and_preserves_order():
    tracker = InFlightTracker()
    results = await bounded_gather(
        [tracker.coro(i) for i in range(6)], max_concurrent=3
    )
    assert results == [0, 1, 2, 3, 4, 5]
    assert tracker.max_in_flight == 3


async def test_bounded_gather_max_concurrent_one_is_sequential():
    tracker = InFlightTracker()
    results = await bounded_gather(
        [tracker.coro(i) for i in range(4)], max_concurrent=1
    )
    assert results == [0, 1, 2, 3]
    assert tracker.max_in_flight == 1


async def test_bounded_gather_propagates_exceptions_by_default():
    async def boom():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await bounded_gather([boom()], max_concurrent=2)


async def test_bounded_gather_return_exceptions_collects_failures():
    async def boom():
        raise RuntimeError("boom")

    async def ok():
        return "ok"

    results = await bounded_gather(
        [boom(), ok()], max_concurrent=2, return_exceptions=True
    )
    assert isinstance(results[0], RuntimeError)
    assert results[1] == "ok"


async def test_bounded_gather_empty_is_noop():
    assert await bounded_gather([], max_concurrent=3) == []


async def test_bounded_gather_failure_cancels_queued_work():
    started = []

    async def boom():
        started.append("boom")
        raise RuntimeError("boom")

    async def queued():
        started.append("queued")

    with pytest.raises(RuntimeError, match="boom"):
        await bounded_gather([boom(), queued()], max_concurrent=1)

    await asyncio.sleep(0)
    assert started == ["boom"]


async def test_bounded_gather_interrupt_stops_queued_work_with_return_exceptions():
    # interrupts are batch-fatal even in return_exceptions mode, where
    # ordinary failures are collected while the rest of the batch runs
    started = []

    async def interrupt():
        started.append("interrupt")
        raise GenerationCancelled("cancelled")

    async def queued():
        started.append("queued")

    results = await bounded_gather(
        [interrupt(), queued()], max_concurrent=1, return_exceptions=True
    )

    assert started == ["interrupt"]
    assert isinstance(results[0], GenerationCancelled)
    assert isinstance(results[1], asyncio.CancelledError)


async def test_bounded_gather_ordinary_failure_collected_with_return_exceptions():
    async def boom():
        raise RuntimeError("boom")

    async def sibling():
        return "ran"

    results = await bounded_gather(
        [boom(), sibling()], max_concurrent=1, return_exceptions=True
    )
    assert isinstance(results[0], RuntimeError)
    assert results[1] == "ran"


async def test_bounded_gather_outer_cancel_settles_and_closes_coroutines():
    async def work(i):
        await asyncio.sleep(1)
        return i

    coros = [work(i) for i in range(5)]
    task = asyncio.create_task(bounded_gather(coros, max_concurrent=2))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # every wrapped coroutine is finished or closed - none left un-awaited
    assert all(coro.cr_frame is None for coro in coros)


# ---------------------------------------------------------------------------
# bounded_gather_apply
# ---------------------------------------------------------------------------


class ApplyTracker:
    def __init__(self, fail_on=None, interrupt_on=None):
        self.fail_on = fail_on
        self.interrupt_on = interrupt_on
        self.generated = []
        self.applied = []
        self.errors = []

    async def generate(self, item):
        await asyncio.sleep(0.01)
        if item == self.interrupt_on:
            raise GenerationCancelled(f"cancelled at {item}")
        if item == self.fail_on:
            raise RuntimeError(f"failed at {item}")
        self.generated.append(item)
        return f"result-{item}"

    async def apply(self, item, result):
        assert result == f"result-{item}"
        self.applied.append(item)

    def on_error(self, item, error):
        self.errors.append((item, str(error)))


async def test_bounded_gather_apply_generates_then_applies_in_order():
    tracker = ApplyTracker()
    await bounded_gather_apply(
        ["a", "b", "c", "d"], tracker.generate, tracker.apply, max_concurrent=2
    )
    assert sorted(tracker.generated) == ["a", "b", "c", "d"]
    assert tracker.applied == ["a", "b", "c", "d"]


async def test_bounded_gather_apply_failure_applies_successes_then_raises():
    tracker = ApplyTracker(fail_on="b")
    with pytest.raises(RuntimeError, match="failed at b"):
        await bounded_gather_apply(
            ["a", "b", "c"],
            tracker.generate,
            tracker.apply,
            max_concurrent=1,
            on_error=tracker.on_error,
        )
    assert tracker.applied == ["a", "c"]
    assert tracker.errors == [("b", "failed at b")]


async def test_bounded_gather_apply_failure_without_on_error():
    tracker = ApplyTracker(fail_on="a")
    with pytest.raises(RuntimeError, match="failed at a"):
        await bounded_gather_apply(
            ["a", "b"], tracker.generate, tracker.apply, max_concurrent=1
        )
    assert tracker.applied == ["b"]


async def test_bounded_gather_apply_interrupt_aborts_batch_and_applies():
    tracker = ApplyTracker(interrupt_on="a")
    with pytest.raises(GenerationCancelled):
        await bounded_gather_apply(
            ["a", "b", "c"],
            tracker.generate,
            tracker.apply,
            max_concurrent=1,
            on_error=tracker.on_error,
        )
    # queued generations never launched, nothing applied, nothing reported
    assert tracker.generated == []
    assert tracker.applied == []
    assert tracker.errors == []


# ---------------------------------------------------------------------------
# throttle
# ---------------------------------------------------------------------------


async def test_throttle_first_call_executes_and_returns_value():
    counter = CallCounter()

    @throttle(0.05)
    async def wrapped(x):
        return await counter.coro(x)

    result = await wrapped(42)
    assert result == ("ok", (42,), {})
    assert counter.calls == [((42,), {})]


async def test_throttle_blocks_repeat_calls_within_window():
    counter = CallCounter()

    @throttle(0.5)
    async def wrapped(x):
        return await counter.coro(x)

    first = await wrapped("a")
    second = await wrapped("b")
    third = await wrapped("c")

    assert first == ("ok", ("a",), {})
    # Subsequent calls within window are dropped (return None)
    assert second is None
    assert third is None
    # Only the first call ran
    assert counter.calls == [(("a",), {})]


async def test_throttle_allows_call_after_window_expires():
    counter = CallCounter()

    @throttle(0.01)
    async def wrapped(x):
        return await counter.coro(x)

    await wrapped("first")
    # Sleep longer than the window
    await asyncio.sleep(0.05)
    second = await wrapped("second")

    assert second == ("ok", ("second",), {})
    assert counter.calls == [(("first",), {}), (("second",), {})]


# ---------------------------------------------------------------------------
# debounce
# ---------------------------------------------------------------------------


async def test_debounce_executes_after_delay():
    """A single debounced call should fire after the configured delay."""
    counter = CallCounter()

    @debounce(0.02)
    async def wrapped(x):
        return await counter.coro(x)

    await wrapped("hello")
    # Has not run yet
    assert counter.calls == []
    # Wait long enough for delay + scheduling
    await asyncio.sleep(0.1)
    assert counter.calls == [(("hello",), {})]


async def test_debounce_returns_none_immediately():
    """The wrapper schedules the work and returns None synchronously."""

    @debounce(0.05)
    async def wrapped(x):
        return x * 2

    rv = await wrapped(7)
    assert rv is None


async def test_debounce_multiple_calls_only_last_fires():
    """Each call cancels the previous one. Only the last call's delayed
    execution survives — the earlier ones are cancelled before their
    asyncio.sleep returns."""
    counter = CallCounter()

    @debounce(0.05)
    async def wrapped(x):
        return await counter.coro(x)

    await wrapped(1)
    await wrapped(2)
    await wrapped(3)
    # Wait for the surviving delayed task to fire.
    await asyncio.sleep(0.15)
    # Only the last call ran.
    args_seen = [call[0][0] for call in counter.calls]
    assert args_seen == [3]


# ---------------------------------------------------------------------------
# shared_debounce
# ---------------------------------------------------------------------------


async def test_shared_debounce_immediate_runs_first_call_synchronously():
    """With immediate=True, the first call runs the body before returning."""
    counter = CallCounter()
    tasks: dict = {}

    @shared_debounce(0.05, task_key="t1", tasks=tasks, immediate=True)
    async def wrapped(x):
        return await counter.coro(x)

    task = await wrapped("first")
    # First call ran immediately
    assert counter.calls == [(("first",), {})]
    # A pending task is returned
    assert isinstance(task, asyncio.Task)
    # Wait for the deferred follow-up to finish (no-op since is_first and immediate)
    await asyncio.sleep(0.1)
    # Still only one call executed
    assert counter.calls == [(("first",), {})]


async def test_shared_debounce_cancels_pending_when_called_again():
    """A second call within the window cancels the prior pending task."""
    counter = CallCounter()
    tasks: dict = {}

    @shared_debounce(0.1, task_key="t2", tasks=tasks, immediate=False)
    async def wrapped(x):
        return await counter.coro(x)

    # First call: schedules a delayed run (immediate=False so body NOT yet run)
    first_task = await wrapped("a")
    assert counter.calls == []
    # Second call within window: should cancel the first
    second_task = await wrapped("b")
    # Yield so the cancellation actually finishes propagating
    await asyncio.sleep(0)
    assert first_task.cancelled() or first_task.done()
    # Wait for the second call's delay to elapse
    await asyncio.sleep(0.2)
    # Only the last queued call ran
    assert counter.calls == [(("b",), {})]
    assert second_task.done()


async def test_shared_debounce_immediate_false_runs_after_delay():
    """When immediate=False, the body runs only after the delay elapses."""
    counter = CallCounter()
    tasks: dict = {}

    @shared_debounce(0.05, task_key="t3", tasks=tasks, immediate=False)
    async def wrapped(x):
        return await counter.coro(x)

    await wrapped("delayed")
    # Body has not run yet
    assert counter.calls == []
    await asyncio.sleep(0.15)
    assert counter.calls == [(("delayed",), {})]


async def test_shared_debounce_separate_keys_dont_interfere():
    """Different task_keys should be tracked independently."""
    counter = CallCounter()
    tasks: dict = {}

    @shared_debounce(0.05, task_key="key_a", tasks=tasks, immediate=True)
    async def wrapped_a(x):
        return await counter.coro(("a", x))

    @shared_debounce(0.05, task_key="key_b", tasks=tasks, immediate=True)
    async def wrapped_b(x):
        return await counter.coro(("b", x))

    await wrapped_a(1)
    await wrapped_b(2)
    # Both immediate calls fired
    args_seen = sorted(call[0][0] for call in counter.calls)
    assert args_seen == [("a", 1), ("b", 2)]
    # Both keys were stored independently
    assert "key_a" in tasks
    assert "key_b" in tasks
    assert tasks["key_a"] is not tasks["key_b"]
    # Let the deferred follow-ups finish
    await asyncio.sleep(0.15)


async def test_shared_debounce_uses_default_tasks_when_no_dict_provided():
    """Verify the decorator works with the global default TASKS registry."""
    from talemate.util.async_tools import TASKS

    counter = CallCounter()

    @shared_debounce(0.02, task_key="default_test_unique_key", immediate=True)
    async def wrapped(x):
        return await counter.coro(x)

    try:
        await wrapped("hi")
        assert counter.calls == [(("hi",), {})]
        assert "default_test_unique_key" in TASKS
        # Drain pending background task
        await asyncio.sleep(0.1)
    finally:
        # Cleanup so we don't leak into other tests
        TASKS.pop("default_test_unique_key", None)


# ---------------------------------------------------------------------------
# cleanup_pending_tasks
# ---------------------------------------------------------------------------


async def test_cleanup_pending_tasks_cancels_other_tasks():
    """All non-current pending tasks should be cancelled."""

    async def long_running():
        await asyncio.sleep(10)

    t1 = asyncio.create_task(long_running())
    t2 = asyncio.create_task(long_running())
    # Yield so they are actually scheduled
    await asyncio.sleep(0)
    assert not t1.done()
    assert not t2.done()

    await cleanup_pending_tasks()

    assert t1.done()
    assert t2.done()
    assert t1.cancelled()
    assert t2.cancelled()


async def test_cleanup_pending_tasks_does_not_cancel_self():
    """The task running cleanup_pending_tasks should not cancel itself."""
    current = asyncio.current_task()

    # Should not raise CancelledError on the calling task
    await cleanup_pending_tasks()

    assert current is asyncio.current_task()
    assert not current.cancelled()


async def test_cleanup_pending_tasks_no_pending_is_noop():
    """When there are no other pending tasks, nothing happens."""
    # Should complete cleanly
    await cleanup_pending_tasks()
