import asyncio
from collections.abc import Callable, Coroutine
from time import monotonic

from talemate.context import active_scene
from talemate.exceptions import GenerationCancelled


CURRENTNESS_POLL_SECONDS = 0.01


def consume_task(task):
    if not task.cancelled():
        task.exception()


class Ownership:
    def __init__(self, is_current: Callable[[], bool] = lambda: True):
        self.owner = asyncio.current_task()
        self.is_current = is_current
        self.scene = active_scene.get()
        self.cancel_sequence = getattr(self.scene, "cancel_sequence", None)
        self.cancellation: BaseException | None = None

    def check(self):
        if self.cancellation is not None:
            raise self.cancellation
        if self.owner and self.owner.cancelling():
            self.cancellation = asyncio.CancelledError()
            raise self.cancellation
        scene = self.scene
        if not self.is_current() or (
            scene is not None
            and (
                active_scene.get() is not scene
                or not scene.active
                or scene.cancel_requested
                or scene.cancel_sequence != self.cancel_sequence
            )
        ):
            self.cancellation = GenerationCancelled(
                "Decision policy input is no longer current"
            )
            raise self.cancellation

    async def _watch(self):
        while True:
            self.check()
            await asyncio.sleep(CURRENTNESS_POLL_SECONDS)

    async def wait(self, operation: Coroutine, timeout: float | None = None):
        task = asyncio.create_task(operation)
        watcher = asyncio.create_task(self._watch())
        deadline = monotonic() + timeout if timeout is not None else None
        try:
            self.check()
            done, _ = await asyncio.wait(
                (task, watcher), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            self.check()
            if watcher in done:
                watcher.result()
            if task not in done or (deadline is not None and monotonic() >= deadline):
                raise TimeoutError
            return task.result()
        finally:
            # A provider may suppress cancellation. Never await it beyond the deadline
            # or let its late value re-enter policy routing.
            for owned in (task, watcher):
                if not owned.done():
                    owned.cancel()
                owned.add_done_callback(consume_task)

    def bridge(self, operation: Coroutine):
        return asyncio.get_event_loop().run_until_complete(self.wait(operation))
