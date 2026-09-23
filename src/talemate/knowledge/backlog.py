"""Perception backlog state that outlives one call: Cancel answers and pushed passages."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

_cancels: WeakKeyDictionary = WeakKeyDictionary()
# (scene, Cancel count) when the current action started
_action: ContextVar = ContextVar("perception_backlog_action", default=None)
# (scene, passages) that the running push appends after its catch-up
_pushing: ContextVar = ContextVar("perception_backlog_pushing", default=None)


def record_cancel(scene: "Scene") -> None:
    _cancels[scene] = _cancels.get(scene, 0) + 1


def cancels_at_start(scene: "Scene") -> int:
    """The Cancel count when the current action started, or now outside an action."""
    action = _action.get()
    if action is not None and action[0] is scene:
        return action[1]
    return _cancels.get(scene, 0)


def cancelled_since(scene: "Scene", count: int) -> bool:
    return _cancels.get(scene, 0) != count


@contextmanager
def cancel_stops_other_questions(scene: "Scene"):
    """
    One user action: a Cancel answered during it stops its other calls
    without a second question, parallel calls included.
    """
    token = _action.set((scene, _cancels.get(scene, 0)))
    try:
        yield
    finally:
        _action.reset(token)


@contextmanager
def counting_pushed(scene: "Scene", count: int):
    """Count the passages a push appends in the questions of its catch-up."""
    token = _pushing.set((scene, count))
    try:
        yield
    finally:
        _pushing.reset(token)


def pushed_count(scene: "Scene") -> int:
    pushing = _pushing.get()
    return pushing[1] if pushing is not None and pushing[0] is scene else 0
