import structlog
import traceback

from talemate.exceptions import ControlFlowException

__all__ = [
    "register",
    "get",
    "handlers",
]

log = structlog.get_logger("talemate.emit.async_signals")

handlers = {}


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
