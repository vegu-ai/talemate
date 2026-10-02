import asyncio
import contextvars
import structlog
import traceback

from talemate.exceptions import ControlFlowException

__all__ = [
    "register",
    "get",
    "handlers",
    "send_soon",
]

log = structlog.get_logger("talemate.emit.async_signals")

handlers = {}
# the event loop keeps only a weak reference to a task
_pending_sends: set[asyncio.Task] = set()
# context vars a send_soon listener must not inherit from its sender
_detached_vars: list[contextvars.ContextVar] = []


def detach_in_listener_tasks(var: contextvars.ContextVar) -> None:
    """
    A send_soon listener runs while its sender goes on; it starts with `var`
    unset instead of sharing the sender's value.
    """
    if var not in _detached_vars:
        _detached_vars.append(var)


class AsyncSignal:
    def __init__(self, name):
        self.receivers = []
        self.name = name

    def connect(self, handler):
        if handler in self.receivers:
            return
        self.receivers.append(handler)

    def disconnect(self, handler):
        try:
            self.receivers.remove(handler)
        except ValueError:
            pass

    async def send(self, emission) -> list[tuple]:
        failures = []
        for receiver in self.receivers:
            try:
                await receiver(emission)
            except ControlFlowException:
                raise
            except Exception as exc:
                log.error(
                    "Error in signal receiver",
                    signal=self.name,
                    receiver=repr(receiver),
                    error=traceback.format_exc(),
                )
                failures.append((receiver, exc))
        return failures


def _register(name: str):
    """
    Registers a signal handler

    Arguments:
        name (str): The name of the signal
        handler (signal): The signal handler
    """

    if name in handlers:
        raise ValueError(f"Signal {name} already registered")

    handlers[name] = AsyncSignal(name)
    return handlers[name]


def register(*names):
    """
    Registers many signal handlers

    Arguments:
        *names (str): The names of the signals
    """
    for name in names:
        _register(name)


def get(name: str):
    """
    Gets a signal handler

    Arguments:
        name (str): The name of the signal handler
    """
    return handlers.get(name)


def _sent(task: asyncio.Task) -> None:
    _pending_sends.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning(
            "Signal task ended with an exception",
            task=task.get_name(),
            error_type=type(exc).__name__,
            error=str(exc),
        )


def send_soon(name: str, emission) -> asyncio.Task:
    """
    Send a signal from synchronous code: receivers run in a task on the running
    loop, after the caller returns.
    """
    context = contextvars.copy_context()
    for var in _detached_vars:
        context.run(var.set, None)
    task = asyncio.get_running_loop().create_task(
        get(name).send(emission), name=f"signal:{name}", context=context
    )
    _pending_sends.add(task)
    task.add_done_callback(_sent)
    return task
