"""
Which knowledge work runs now, for modules that `revision_refresh` and the
knowledge step import and that therefore cannot import them back.
"""

from contextvars import ContextVar
from typing import TYPE_CHECKING

import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

# (scene, message, phase) of the revision refresh phase running in this task
active_revision_phase = ContextVar("revision_refresh_transaction", default=None)


class StepEvents(list):
    # set when the step has sent its events; a task the step started
    # keeps this list in its context and must then send on its own
    closed: bool = False


# the events of the knowledge step running in this task, sent after it
step_events: ContextVar[StepEvents | None] = ContextVar("step_events", default=None)
# a listener task runs apart from the step: no revision journal, own events
async_signals.detach_in_listener_tasks(active_revision_phase)
async_signals.detach_in_listener_tasks(step_events)


def hold_for_step(name: str, emission) -> bool:
    """Keep an event of a running knowledge step until the step has finished."""
    events = step_events.get()
    if events is None or events.closed:
        return False
    events.append((name, emission))
    return True


def in_revision_phase(scene: "Scene") -> bool:
    active = active_revision_phase.get()
    return active is not None and active[0] is scene
