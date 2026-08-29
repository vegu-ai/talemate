"""
Tests for the episode management websocket handlers.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from conftest import MockScene, bootstrap_scene

from talemate.server.world_state_manager.episodes import EpisodesMixin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scene():
    """Real bootstrapped `MockScene` with the emit plumbing stubbed.

    `emit_status` / `emit_history` fan out to signals and agents that aren't
    the unit under test here, so they are stubbed and asserted against.
    """
    scene = MockScene()
    bootstrap_scene(scene)
    scene.emit_status = MagicMock()
    scene.emit_history = AsyncMock()
    return scene


@pytest.fixture
def mixin_instance():
    """Create an instance of EpisodesMixin with stubbed websocket plumbing."""

    class TestMixin(EpisodesMixin):
        def __init__(self, scene):
            self._scene = scene
            self.websocket_handler = MagicMock()
            self._signal_done_called = False

        @property
        def scene(self):
            return self._scene

        async def signal_operation_done(self):
            self._signal_done_called = True

    def _factory(scene):
        return TestMixin(scene)

    return _factory


# ---------------------------------------------------------------------------
# Tests: Set Intro
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_intro_writes_intro_and_notifies_client(scene, mixin_instance):
    mixin = mixin_instance(scene)

    await mixin.handle_set_intro({"intro": "The episode begins."})

    assert scene.intro == "The episode begins."
    mixin.websocket_handler.queue_put.assert_called_once_with(
        {
            "type": "world_state_manager",
            "action": "intro_set",
            "data": {"intro": "The episode begins."},
        }
    )
    assert mixin._signal_done_called


@pytest.mark.asyncio
async def test_set_intro_emits_status_and_history(scene, mixin_instance):
    """The main view only renders the intro from an emit_history pass."""
    mixin = mixin_instance(scene)

    await mixin.handle_set_intro({"intro": "The episode begins."})

    scene.emit_status.assert_called_once()
    scene.emit_history.assert_awaited_once()
