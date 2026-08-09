"""Unit tests for `WebsocketHandler.release_scene` and the disconnect wiring.

Agents are process-global singletons that stay bound to whatever scene the
last connection loaded. Without a release on disconnect the next connection
reports — and generates with — the closed session's per-scene overrides.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import talemate.instance as instance
from _agent_override_test_helpers import override_agent_class, scene_overlay
from talemate.agents.base import Agent
from talemate.emit.base import Receiver
from talemate.server import websocket_server
from talemate.server.websocket_server import WebsocketHandler
from talemate.tale_mate import Scene

AGENT_TYPE = "release-test"

_ReleaseAgent = override_agent_class(AGENT_TYPE)


class _MemoryAgent:
    """Only `close_db` is reached from the code under test."""

    def __init__(self):
        self.error: Exception | None = None
        self.closed = []
        self.agent_scenes = []

    def close_db(self, scene):
        self.closed.append(scene)
        # `close_db` purges the scene's unsaved memory through the agent's own
        # `scene`, so the rebind must not have happened yet
        self.agent_scenes.append(instance.AGENTS[AGENT_TYPE].scene)
        if self.error:
            raise self.error


class _ReleaseHandler:
    """Stand-in for the real handler, which is too heavy to construct.

    It borrows the methods under test unbound — neither reads anything on
    `self` but `scene`.
    """

    init_scene = WebsocketHandler.init_scene
    release_scene = WebsocketHandler.release_scene

    def __init__(self, scene):
        self.scene = scene


class _RaisingPlugin:
    def disconnect(self):
        raise RuntimeError("plugin teardown failed")


@pytest.fixture
def wired(monkeypatch, tmp_path: Path):
    scene = Scene()
    scene.active = True
    scene.agent_overrides = scene_overlay(tmp_path / "agent-settings.json", AGENT_TYPE)

    agent = _ReleaseAgent(scene)
    memory = _MemoryAgent()
    handler = _ReleaseHandler(scene)

    instance.AGENTS[AGENT_TYPE] = agent
    instance.AGENTS["memory"] = memory
    # the real agent types have no instances in a test process
    monkeypatch.setattr(instance, "agent_types", lambda: [AGENT_TYPE])
    try:
        yield handler, scene, agent, memory
    finally:
        instance.AGENTS.pop(AGENT_TYPE, None)
        instance.AGENTS.pop("memory", None)


def test_release_drops_the_closed_sessions_overrides(wired):
    handler, scene, agent, memory = wired

    assert Agent.config_options(agent)["scene_overrides"]
    assert agent.resolve_config("container", "fmt") == "scene-fmt"
    assert agent.resolve_enabled("container") is False

    handler.release_scene()

    assert scene.active is False
    assert agent.scene is not scene
    assert agent.scene is handler.scene
    assert Agent.config_options(agent)["scene_overrides"] == {}
    assert agent.resolve_config("container", "fmt") == "global-fmt"
    assert agent.resolve_enabled("container") is True


def test_released_agents_are_scene_free_ready(wired):
    handler, scene, agent, memory = wired

    handler.release_scene()

    # what scene-free generation expects: a placeholder scene, no overlay
    assert agent.scene_overrides() is None
    assert agent.scene.active is False
    assert agent.resolve_config("container", "fmt") == "global-fmt"
    assert agent.resolve_enabled("container") is True


def test_release_closes_the_memory_db_before_rebinding(wired):
    handler, scene, agent, memory = wired

    handler.release_scene()

    assert memory.closed == [scene]
    assert memory.agent_scenes == [scene]


def test_release_survives_a_failing_teardown(wired):
    handler, scene, agent, memory = wired
    memory.error = RuntimeError("close_db failed")

    handler.release_scene()

    assert scene.active is False
    assert agent.scene is not scene
    assert agent.scene is handler.scene
    assert agent.scene_overrides() is None


def test_release_without_a_scene_still_rebinds(wired):
    handler, scene, agent, memory = wired
    handler.scene = None

    handler.release_scene()

    assert isinstance(handler.scene, Scene)
    assert agent.scene is handler.scene
    assert agent.scene_overrides() is None


def test_a_failing_plugin_teardown_cannot_strand_the_agents(wired, monkeypatch):
    handler, scene, agent, memory = wired

    # the real handler, minus everything __init__ needs a live socket for
    real_handler = object.__new__(WebsocketHandler)
    real_handler.scene = scene
    real_handler.routes = {"plugin": _RaisingPlugin()}
    real_handler._cleanup_scene_assets_batching = lambda: None
    monkeypatch.setattr(websocket_server, "abort_wait_for_input", lambda: None)
    monkeypatch.setattr(Receiver, "disconnect", lambda self: None)

    with pytest.raises(RuntimeError):
        real_handler.disconnect()

    assert scene.active is False
    assert agent.scene is not scene
    assert agent.scene is real_handler.scene
    assert agent.scene_overrides() is None
