import asyncio
from functools import wraps

from talemate.agents.memory.exceptions import MemoryShutdownRefused


def cancel_on_memory_shutdown(fn):
    @wraps(fn)
    async def wrapped(self, *args, **kwargs):
        try:
            if self._refuse_memory_work:
                raise MemoryShutdownRefused("Memory work refused during shutdown")
            return await fn(self, *args, **kwargs)
        except MemoryShutdownRefused:
            # Cancel the task that runs the read, so the caller sees a cancellation
            # and not an empty result. Parent cancellation counts stay unchanged;
            # RunModule may continue until shutdown cancels the scene task.
            asyncio.current_task().cancel()
            await asyncio.sleep(0)

    return wrapped
