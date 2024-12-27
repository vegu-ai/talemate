import structlog

from talemate.emit import emit
from talemate.exceptions import GenerationCancelled

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
        cancellable: bool = False
    ):
        self.message = message
        self.set_busy = set_busy
        self.set_success = set_success
        self.set_error = set_error
        self.cancellable = cancellable

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
            except GenerationCancelled:
                if self.set_error:
                    emit("status", message=f"{self.message}: Cancelled", status="idle")
            except Exception as e:
                if self.set_error:
                    emit("status", message=f"{self.message}: Failed", status="error")
                raise e

        return wrapper


class LoadingStatus:
    def __init__(self, max_steps: int):
        self.max_steps = max_steps
        self.current_step = 0

    def __call__(self, message: str):
        self.current_step += 1
        emit(
            "status",
            message=f"{message} [{self.current_step}/{self.max_steps}]",
            status="busy",
        )
