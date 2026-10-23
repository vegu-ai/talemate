import asyncio
import structlog
from functools import wraps
from typing import Awaitable, Callable, Coroutine, Iterable, Optional

from talemate.exceptions import ControlFlowException

__all__ = [
    "bounded_gather",
    "bounded_gather_apply",
    "cleanup_pending_tasks",
    "debounce",
    "shared_debounce",
]

log = structlog.get_logger("talemate.util.async_tools")

TASKS = {}


def throttle(delay: float):
    """
    Ensures the decorated function is only called once every `delay` seconds.

    Unlike debounce which will delay the function until the last call, throttle will
    ensure the function is called at most once every `delay` seconds.
    """

    def decorator(fn):
        last_called = 0

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            nonlocal last_called

            now = asyncio.get_event_loop().time()
            if now - last_called > delay:
                last_called = now
                return await fn(*args, **kwargs)

        return wrapper

    return decorator


def debounce(delay: float):
    """
    Decorator to debounce a coroutine function.
    """

    def decorator(fn):
        task: Optional[asyncio.Task] = None

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            nonlocal task

            # Cancel any existing task
            if task and not task.done():
                task.cancel()

            # Create new delayed task
            async def delayed():
                await asyncio.sleep(delay)
                return await fn(*args, **kwargs)

            task = asyncio.create_task(delayed())

        return wrapper

    return decorator


def shared_debounce(
    delay: float, task_key: str = "default", tasks: dict = None, immediate: bool = True
):
    """
    Decorator to debounce a coroutine function, but share the task across multiple calls.

    This allows you to debounce a function across multiple calls, so that only one task is running at a time.
    """

    if tasks is None:
        tasks = TASKS

    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            loop = asyncio.get_running_loop()

            is_first = True

            if task_key not in tasks:
                tasks[task_key] = None

            if tasks[task_key] and not tasks[task_key].done():
                try:
                    tasks[task_key].cancel()
                except RuntimeError as exc:
                    log.error("shared_debounce: Error cancelling task", exc=exc)
                is_first = False

            if is_first and immediate:
                await fn(*args, **kwargs)

            async def delayed():
                try:
                    await asyncio.sleep(delay)
                    if not is_first or not immediate:
                        await fn(*args, **kwargs)
                except asyncio.CancelledError:
                    pass

            # Create and store the task, but attach it to the loop
            task = loop.create_task(delayed())
            tasks[task_key] = task

            return task  # Return the task but don't await it

        return wrapper

    return decorator


async def bounded_gather(
    coros: Iterable[Coroutine],
    max_concurrent: int = 3,
    return_exceptions: bool = False,
) -> list:
    """
    Gather coroutines with at most `max_concurrent` running at a time.

    `max_concurrent=1` degenerates to sequential execution - callers that
    fan out LLM calls use this to respect `supports_concurrent_inference`.

    Unlike plain gather, a batch-fatal failure keeps queued coroutines from
    launching: with `return_exceptions=False` any failure is batch-fatal,
    with `return_exceptions=True` only interrupts (ControlFlowException,
    cancellation) are - other failures are collected as results while the
    rest of the batch runs.
    """
    semaphore = asyncio.Semaphore(max(1, max_concurrent))
    failed = False

    async def bounded(coro: Coroutine):
        nonlocal failed
        try:
            async with semaphore:
                # a flag, not sibling-task cancellation: the semaphore hands
                # off to a queued task before the gather sees the failure
                if failed:
                    raise asyncio.CancelledError()
                try:
                    return await coro
                except (ControlFlowException, asyncio.CancelledError):
                    failed = True
                    raise
                except BaseException:
                    if not return_exceptions:
                        failed = True
                    raise
        finally:
            coro.close()

    tasks = [asyncio.ensure_future(bounded(coro)) for coro in coros]
    try:
        return await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def bounded_gather_apply(
    items: list,
    generate: Callable[[object], Coroutine],
    apply: Callable[[object, object], Awaitable],
    max_concurrent: int = 3,
    on_error: Callable[[object, BaseException], None] | None = None,
):
    """
    Fan `generate(item)` out via bounded_gather, then run `apply(item, result)`
    sequentially in item order, so all side effects stay ordered.

    An interrupt (ControlFlowException or cancellation) among the results
    aborts before anything applies. Other failures are reported via
    `on_error`, the successful results still apply, and the first failure
    re-raises afterwards - mirroring a sequential loop where items before a
    failure survive it.
    """
    results = await bounded_gather(
        [generate(item) for item in items],
        max_concurrent=max_concurrent,
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, (ControlFlowException, asyncio.CancelledError)):
            raise result

    first_error = None
    for item, result in zip(items, results):
        if isinstance(result, BaseException):
            if on_error:
                on_error(item, result)
            if first_error is None:
                first_error = result
            continue
        await apply(item, result)

    if first_error is not None:
        raise first_error


async def cleanup_pending_tasks():
    # Get all tasks from the current loop
    pending = [
        task
        for task in asyncio.all_tasks()
        if not task.done() and task is not asyncio.current_task()
    ]

    # Cancel them
    for task in pending:
        task.cancel()

    # Wait for them to finish
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
