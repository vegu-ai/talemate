"""
Which revision work runs now, for modules that `revision_refresh` imports and
that therefore cannot import it back.
"""

from contextvars import ContextVar
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

# (scene, message, phase) of the revision refresh phase running in this task
active_revision_phase = ContextVar("revision_refresh_transaction", default=None)


class JobEvents(list):
    # set when the job has sent or held its events; a task the job started
    # keeps this list in its context and must then queue elsewhere
    closed: bool = False


# the perception events of the revision refresh job running in this task
job_perception_events: ContextVar[JobEvents | None] = ContextVar(
    "job_perception_events", default=None
)
# a listener task runs apart from the job: no revision journal, own events
async_signals.detach_in_listener_tasks(active_revision_phase)
async_signals.detach_in_listener_tasks(job_perception_events)
# the task that runs catch_up_revisions for a scene
catch_up_owners: WeakKeyDictionary = WeakKeyDictionary()
# perception events that wait until the scene's catch-up has released its lock
after_catch_up_events: WeakKeyDictionary = WeakKeyDictionary()


def in_revision_phase(scene: "Scene") -> bool:
    active = active_revision_phase.get()
    return active is not None and active[0] is scene


def catch_up_running(scene: "Scene") -> bool:
    return scene in catch_up_owners


def hold_until_catch_up_ends(scene: "Scene", events: list) -> None:
    after_catch_up_events.setdefault(scene, []).extend(events)
