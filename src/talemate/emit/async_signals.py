import structlog
import traceback

from talemate.exceptions import ControlFlowException, GenerationCancelled

__all__ = [
    "register",
    "get",
    "handlers",
    "DEFERRED",
]

log = structlog.get_logger("talemate.emit.async_signals")

handlers = {}
DEFERRED = object()


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

    async def send(
        self, emission, *, completed: list[str] | None = None
    ) -> list[tuple]:
        """Optionally checkpoint receivers, propagating failures and deferred work."""
        failures = []
        for receiver in self.receivers:
            if completed is not None:
                function = (
                    receiver
                    if hasattr(receiver, "__qualname__")
                    else type(receiver).__call__
                )
                key = f"{self.name}:{function.__module__}.{function.__qualname__}"
                owner = getattr(receiver, "__self__", receiver)
                owner_key = getattr(owner, "signal_receiver_key", None)
                if owner_key is not None:
                    key = f"{key}:{owner_key}"
                if key in completed:
                    continue
            try:
                result = await receiver(emission)
                if completed is not None and result is DEFERRED:
                    raise GenerationCancelled(
                        "A scene action has not finished yet. Retry to continue."
                    )
            except ControlFlowException:
                raise
            except Exception as exc:
                log.error(
                    "Error in signal receiver",
                    signal=self.name,
                    receiver=repr(receiver),
                    error=traceback.format_exc(),
                )
                if completed is not None:
                    raise
                failures.append((receiver, exc))
            else:
                if completed is not None:
                    completed.append(key)
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
