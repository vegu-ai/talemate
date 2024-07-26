"""
Functions for scene direction and manipulation
"""

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine

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
