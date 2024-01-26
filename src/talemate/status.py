import structlog

from talemate.emit import emit

__all__ = [
    "set_loading",
    "LoadingStatus",
]

log = structlog.get_logger("talemate.status")


class set_loading:
    def __init__(self, message, set_busy: bool = True):
        self.message = message
        self.set_busy = set_busy

    def __call__(self, fn):
        async def wrapper(*args, **kwargs):
            if self.set_busy:
                emit("status", message=self.message, status="busy")
            try:
                return await fn(*args, **kwargs)
            finally:
                emit("status", message="", status="idle")

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
