"""Unit tests for `WebsocketHandler.release_scene` and the disconnect wiring.

Agents are process-global singletons that stay bound to whatever scene the
last connection loaded. Without a release on disconnect the next connection
reports — and generates with — the closed session's per-scene overrides.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import structlog

import talemate.emit.async_signals as async_signals
import talemate.instance as instance
from _agent_override_test_helpers import override_agent_class, scene_overlay
from talemate.agents.base import Agent
from talemate.agents.tts.websocket_handler import TTSWebsocketHandler
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


@pytest.fixture
def config_signals():
    """Restores the module-global signals a leaking connection would grow."""
    signals = [
        async_signals.get("config.changed"),
        async_signals.get("config.changed.follow"),
    ]
    before = [list(signal.receivers) for signal in signals]
    try:
        yield signals
    finally:
        for signal, receivers in zip(signals, before):
            signal.receivers[:] = receivers


def _bare_handler(scene, routes, monkeypatch):
    """The real handler, minus everything __init__ needs a live socket for."""
    handler = object.__new__(WebsocketHandler)
    handler.scene = scene
    handler.routes = routes
    handler._cleanup_scene_assets_batching = lambda: None
    monkeypatch.setattr(websocket_server, "abort_wait_for_input", lambda: None)
    return handler


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


def test_a_failing_plugin_teardown_cannot_strand_the_agents(
    wired, monkeypatch, config_signals
):
    handler, scene, agent, memory = wired
    _, follow = config_signals

    later_plugin = object.__new__(TTSWebsocketHandler)
    later_plugin.websocket_handler = None
    later_plugin.connect()

    routes = {"plugin": _RaisingPlugin(), TTSWebsocketHandler.router: later_plugin}
    real_handler = _bare_handler(scene, routes, monkeypatch)
    monkeypatch.setattr(Receiver, "disconnect", lambda self: None)

    with structlog.testing.capture_logs() as logs:
        real_handler.disconnect()

    errors = [entry for entry in logs if entry["log_level"] == "error"]
    assert len(errors) == 1
    assert errors[0]["plugin"] == "plugin"
    assert "RuntimeError: plugin teardown failed" in errors[0]["error"]

    assert later_plugin.on_app_config_change_followup not in follow.receivers
    assert scene.active is False
    assert agent.scene is not scene
    assert agent.scene is real_handler.scene
    assert agent.scene_overrides() is None


def test_a_failing_batching_cleanup_cannot_strand_the_plugin_receivers(
    wired, monkeypatch, config_signals
):
    handler, scene, agent, memory = wired
    _, follow = config_signals

    plugin = object.__new__(TTSWebsocketHandler)
    plugin.websocket_handler = None
    plugin.connect()

    routes = {TTSWebsocketHandler.router: plugin}
    real_handler = _bare_handler(scene, routes, monkeypatch)

    def _failing_cleanup():
        raise RuntimeError("batching cleanup failed")

    real_handler._cleanup_scene_assets_batching = _failing_cleanup

    with pytest.raises(RuntimeError, match="batching cleanup failed"):
        real_handler.disconnect()

    assert plugin.on_app_config_change_followup not in follow.receivers
    assert agent.scene is real_handler.scene


def test_disconnect_removes_the_config_changed_receiver(
    wired, monkeypatch, config_signals
):
    handler, scene, agent, memory = wired
    changed, _ = config_signals
    baseline = len(changed.receivers)

    for _ in range(2):
        real_handler = _bare_handler(scene, {}, monkeypatch)
        real_handler.connect()

        assert real_handler.on_config_changed in changed.receivers

        real_handler.disconnect()

        assert real_handler.on_config_changed not in changed.receivers
        assert len(changed.receivers) == baseline


def test_disconnect_removes_the_tts_config_follow_receiver(
    wired, monkeypatch, config_signals
):
    handler, scene, agent, memory = wired
    _, follow = config_signals
    baseline = len(follow.receivers)

    for _ in range(2):
        plugin = object.__new__(TTSWebsocketHandler)
        plugin.websocket_handler = None
        plugin.connect()

        assert plugin.on_app_config_change_followup in follow.receivers

        routes = {TTSWebsocketHandler.router: plugin}
        _bare_handler(scene, routes, monkeypatch).disconnect()

        assert plugin.on_app_config_change_followup not in follow.receivers
        assert len(follow.receivers) == baseline
