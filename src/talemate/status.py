import asyncio
import contextvars
import structlog
from functools import wraps
from typing import Callable

from talemate.emit import emit
from talemate.exceptions import GenerationCancelled
from talemate.context import handle_generation_cancelled

__all__ = [
    "set_loading",
    "set_loading_label",
    "background_task",
    "LoadingLabel",
    "LoadingStatus",
]

log = structlog.get_logger("talemate.status")

PLACEHOLDER = "{}"
FALLBACK_LABEL = "Working on it"


class LoadingLabel:
    """
    A loading message with the names in it kept apart from the words around
    them, so the interface can paint the names: `LoadingLabel("Looking at {}",
    "Mara")`. A name is passed rather than substituted because a name can
    repeat the letters of the words around it - "Analyzing Ana's development".
    """

    def __init__(self, template: str, *names: str):
        self.chunks = template.split(PLACEHOLDER)
        if len(self.chunks) != len(names) + 1:
            raise ValueError(
                f"{template!r} takes {len(self.chunks) - 1} names, got {len(names)}"
            )
        self.names = [str(name) for name in names]

    @classmethod
    def plain(cls, text: str) -> "LoadingLabel":
        """A message with nothing to paint: any braces in it are characters."""
        label = cls("")
        label.chunks = [text]
        return label

    def followed_by(self, suffix: str) -> "LoadingLabel":
        label = LoadingLabel.plain("")
        label.chunks = self.chunks[:-1] + [self.chunks[-1] + suffix]
        label.names = list(self.names)
        return label

    @property
    def parts(self) -> list[dict]:
        """The label as alternating chunks, each one a name or not."""
        parts = []
        for index, chunk in enumerate(self.chunks):
            if chunk:
                parts.append({"text": chunk, "name": False})
            if index < len(self.names):
                parts.append({"text": self.names[index], "name": True})
        return parts

    @property
    def text(self) -> str:
        return "".join(part["text"] for part in self.parts)


LabelSource = str | LoadingLabel | Callable[..., "str | LoadingLabel"]


def _as_label(label: str | LoadingLabel) -> LoadingLabel:
    return label if isinstance(label, LoadingLabel) else LoadingLabel.plain(label)


class _Loading:
    """The status one `set_loading` call is showing, while it runs."""

    def __init__(self, label: LoadingLabel, cancellable: bool, set_busy: bool):
        self.label = label
        self.cancellable = cancellable
        self.set_busy = set_busy
        self.finished = False

    def emit(self, status: str, suffix: str = "", cancellable: bool = False):
        label = self.label.followed_by(suffix) if suffix else self.label
        data = {}
        if cancellable:
            data["cancellable"] = True
        if label.names:
            data["label"] = label.parts
        emit("status", message=label.text, status=status, data=data)

    def emit_busy(self):
        self.emit("busy", cancellable=self.cancellable)


_active_loading: contextvars.ContextVar[_Loading | None] = contextvars.ContextVar(
    "active_loading", default=None
)


def set_loading_label(label: str | LoadingLabel) -> bool:
    """
    Rename the loading status that is showing, for a handler that only knows
    what it works on once it has started. Returns False outside `set_loading`,
    and for a task that outlived the call it was started in.
    """
    loading = _active_loading.get()
    if loading is None or loading.finished:
        return False
    loading.label = _as_label(label)
    if loading.set_busy:
        loading.emit_busy()
    return True


class set_loading:
    def __init__(
        self,
        message: LabelSource,
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

    def _label(self, *args, **kwargs) -> LoadingLabel:
        """The label of one call: a callable is given the call's own arguments."""
        if isinstance(self.message, (str, LoadingLabel)):
            return _as_label(self.message)
        try:
            return _as_label(self.message(*args, **kwargs))
        except Exception as e:
            # the call is what matters; it reports a bad payload itself
            log.warning("Could not build the loading label", error=e)
            return LoadingLabel(FALLBACK_LABEL)

    def __call__(self, fn):
        async def wrapper(*args, **kwargs):
            loading = _Loading(
                self._label(*args, **kwargs), self.cancellable, self.set_busy
            )
            token = _active_loading.set(loading)
            try:
                if self.set_busy:
                    loading.emit_busy()
                result = await fn(*args, **kwargs)
                if self.set_success:
                    loading.emit("success")
                else:
                    emit("status", message="", status="idle")
                return result
            except GenerationCancelled as e:
                log.warning("Generation cancelled", args=args, kwargs=kwargs)
                if self.set_error:
                    loading.emit("idle", suffix=": Cancelled")
                else:
                    # Always clear the busy status on cancel. Without this the
                    # frontend's notificatioonBusy lock (driven by status=='busy')
                    # never resolves and the scene input stays disabled.
                    emit("status", message="", status="idle")
                handle_generation_cancelled(e)
                # Re-raise so callers (notably the @background_task decorator's
                # done-callback in Plugin.handle) can post a router-level
                # operation_done envelope and clear per-component busy state.
                raise
            except Exception as e:
                log.error("Error in set_loading wrapper", error=e)
                if self.set_error:
                    loading.emit("error", suffix=": Failed")
                raise e
            finally:
                loading.finished = True
                _active_loading.reset(token)

        # if as_async we want to wrap the function in a coroutine
        # that adds a task to the event loop and returns the task

        if self.as_async:

            async def async_wrapper(*args, **kwargs):
                task = asyncio.create_task(wrapper(*args, **kwargs))
                # Mark exceptions as retrieved so cancellations / errors that
                # propagate out of the wrapper don't surface as
                # "Task exception was never retrieved" warnings.
                task.add_done_callback(_consume_task_exception)
                return task

            return async_wrapper

        return wrapper


def _consume_task_exception(task: asyncio.Task) -> None:
    """
    Mark a background task's exception as retrieved to suppress the
    "Task exception was never retrieved" warning at GC time. The
    exception itself is already logged by the set_loading wrapper.
    """
    if task.cancelled():
        return
    # Calling exception() is enough to mark it retrieved; the return value
    # is intentionally discarded.
    task.exception()


def background_task(
    message: LabelSource,
    *,
    cancellable: bool = True,
    set_success: bool = False,
    set_error: bool = True,
):
    """
    Decorator: schedule the wrapped coroutine as a background asyncio task
    with set_loading status emissions and exception cleanup.

    The wrapped function returns immediately with the task object — calling
    code can ignore it. This is what frees the websocket receive loop so
    follow-up messages (e.g. the cancel/retry/ignore dialog response from
    the LLM client) can be dispatched while the work is still running.

    The frontend still observes a busy snackbar (with a cancel button when
    cancellable=True) for the duration of the task; "background" here refers
    to the backend handler returning before the work completes, not to the
    UX being free to continue.
    """

    def decorator(fn):
        wrapped = set_loading(
            message,
            cancellable=cancellable,
            set_success=set_success,
            set_error=set_error,
        )(fn)

        @wraps(fn)
        async def outer(*args, **kwargs):
            task = asyncio.create_task(wrapped(*args, **kwargs))
            task.add_done_callback(_consume_task_exception)
            return task

        return outer

    return decorator


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
