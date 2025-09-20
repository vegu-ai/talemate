import contextvars
import pydantic
import structlog
import asyncio

from talemate.game.engine.context_id.scanner import OpenContextIDScanCollector


__all__ = [
    "DirectorChatContext",
    "director_chat_context",
    "create_task_with_chat_context",
]

log = structlog.get_logger("talemate.agents.director.chat.context")

director_chat_context = contextvars.ContextVar("director_chat_context", default=None)


class DirectorChatContext(pydantic.BaseModel):
    chat_id: str
    confirm_write_actions: bool = True
    token: str | None = None
    _context_id_collector: OpenContextIDScanCollector | None = None

    def __enter__(self):
        self.token = director_chat_context.set(self)
        self._context_id_collector = OpenContextIDScanCollector()
        self._context_id_collector.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._context_id_collector:
            self._context_id_collector.__exit__(exc_type, exc_value, traceback)
        director_chat_context.reset(self.token)


def create_task_with_chat_context(fn, chat_id: str, *args, **kwargs):
    async def wrapper(*args, **kwargs):
        with DirectorChatContext(chat_id=chat_id):
            return await fn(*args, **kwargs)

    return asyncio.create_task(wrapper(*args, **kwargs))
