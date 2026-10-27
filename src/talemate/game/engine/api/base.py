"""
Base classes and helpers of the legacy game-scripting API.

DEPRECATED: the legacy game-scripting API (the scoped ``TM`` API a scene's
``game.py`` calls) is unmaintained and being phased out in favour of node
graph modules. No fixes or new features are accepted for it; build scene logic
with node modules instead.
"""

import asyncio
from typing import Coroutine

__all__ = [
    "run_async",
    "ScopedAPI",
]


def run_async(coro: Coroutine):
    """
    runs a coroutine
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


class ScopedAPI:
    """
    Base class for scoped API classes
    """

    def __getattribute__(self, name: str):
        """
        If `assert_scene_active` exists in the class, it will be called before any other method
        """

        if name != "assert_scene_active" and hasattr(self, "assert_scene_active"):
            self.assert_scene_active()

        return super().__getattribute__(name)
