import asyncio
import structlog
from functools import wraps
from typing import Optional

__all__ = [
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

            asyncio.create_task(delayed())

        return wrapper

    return decorator


def shared_debounce(
    delay: float, task_key: str = "default", tasks: dict = None, immediate: bool = True
):
    """
    Decorator to debounce a coroutine function, but share the task across multiple calls.

    This allows you to debounce a function across multiple calls, so that only one task is running at a time.
    """

    if not tasks:
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
