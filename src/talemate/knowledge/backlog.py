"""The Cancel answers given to knowledge error dialogs, counted per scene."""

from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

_cancels: WeakKeyDictionary = WeakKeyDictionary()


def record_cancel(scene: "Scene") -> None:
    _cancels[scene] = _cancels.get(scene, 0) + 1


def cancel_count(scene: "Scene") -> int:
    return _cancels.get(scene, 0)


def cancelled_since(scene: "Scene", count: int) -> bool:
    return _cancels.get(scene, 0) != count
