"""Perception backlog state that outlives one call: Cancel answers and the step's new lines."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

_cancels: WeakKeyDictionary = WeakKeyDictionary()
# (scene, Cancel count) when the current action started
_action: ContextVar = ContextVar("perception_backlog_action", default=None)
# (scene, {id: requests}) of the new lines the running knowledge step registers
# after its catch-up
_new_lines: ContextVar = ContextVar("perception_backlog_new_lines", default=None)


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
def counting_new_lines(scene: "Scene", requests: dict[int, int]):
    """Count the step's new lines in a question asked before they are registered."""
    token = _new_lines.set((scene, requests))
    try:
        yield
    finally:
        _new_lines.reset(token)


def counted_new_lines(scene: "Scene") -> dict[int, int]:
    new_lines = _new_lines.get()
    if new_lines is None or new_lines[0] is not scene:
        return {}
    return new_lines[1]
