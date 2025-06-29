import asyncio
import structlog

from talemate.emit import emit
from talemate.exceptions import GenerationCancelled
from talemate.context import handle_generation_cancelled

__all__ = [
    "set_loading",
    "LoadingStatus",
]

log = structlog.get_logger("talemate.status")


class set_loading:
    def __init__(
        self,
        message,
        set_busy: bool = True,
        set_success: bool = False,
        set_error: bool = False,
        cancellable: bool = False,
        as_async: bool = False,
    ):
        self.message = message
        self.set_busy = set_busy
        self.set_success = set_success
        self.set_error = set_error
        self.cancellable = cancellable
        self.as_async = as_async

    def __call__(self, fn):
        async def wrapper(*args, **kwargs):
            if self.set_busy:
                status_data = {}
                if self.cancellable:
                    status_data["cancellable"] = True
                emit("status", message=self.message, status="busy", data=status_data)
            try:
                result = await fn(*args, **kwargs)
                if self.set_success:
                    emit("status", message=self.message, status="success")
                else:
                    emit("status", message="", status="idle")
                return result
            except GenerationCancelled as e:
                log.warning("Generation cancelled", args=args, kwargs=kwargs)
                if self.set_error:
                    emit("status", message=f"{self.message}: Cancelled", status="idle")
                handle_generation_cancelled(e)
            except Exception as e:
                log.error("Error in set_loading wrapper", error=e)
                if self.set_error:
                    emit("status", message=f"{self.message}: Failed", status="error")
                raise e

        # if as_async we want to wrap the function in a coroutine
        # that adds a task to the event loop and returns the task

        if self.as_async:

            async def async_wrapper(*args, **kwargs):
                return asyncio.create_task(wrapper(*args, **kwargs))

            return async_wrapper

        return wrapper


class LoadingStatus:
    def __init__(self, max_steps: int | None = None, cancellable: bool = False):
        self.max_steps = max_steps
        self.current_step = 0
        self.cancellable = cancellable

    def __call__(self, message: str):
        self.current_step += 1

        if self.max_steps is None:
            counter = ""
        else:
            counter = f" [{self.current_step}/{self.max_steps}]"

        emit(
            "status",
            message=f"{message}{counter}",
            status="busy",
            data={
                "cancellable": self.cancellable,
            },
        )

    def done(self, message: str = "", status: str = "idle"):
        if self.current_step == 0:
            return

        emit(
            "status",
            message=message,
            status=status,
        )
