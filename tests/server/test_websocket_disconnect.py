"""Unit tests for `WebsocketHandler.release_scene` and the disconnect wiring.

Agents are process-global singletons that stay bound to whatever scene the
last connection loaded. Without a release on disconnect the next connection
reports — and generates with — the closed session's per-scene overrides.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
import structlog

import talemate.emit.async_signals as async_signals
import talemate.instance as instance
from _agent_override_test_helpers import override_agent_class, scene_overlay
from talemate.agents.base import Agent
from talemate.agents.tts.websocket_handler import TTSWebsocketHandler
from talemate.emit.base import Receiver
from talemate.game.engine.nodes.core import Entry, Graph, GraphContext, GraphState, Node
from talemate.game.engine.nodes.run import RunModule
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

    It borrows the methods under test unbound and records `queue_put`
    messages instead of feeding a socket.
    """

    init_scene = WebsocketHandler.init_scene
    release_scene = WebsocketHandler.release_scene
    load_scene = WebsocketHandler.load_scene
    _stop_scene_test_module = WebsocketHandler._stop_scene_test_module

    def __init__(self, scene):
        self.scene = scene
        self.queued = []

    def queue_put(self, data):
        self.queued.append(data)


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


class _FakeTask:
    def __init__(self, done=False):
        self.cancelled = False
        self._done = done

    def done(self):
        return self._done

    def cancel(self):
        self.cancelled = True


def _running_test_module(scene, task=None):
    """Track a node-editor test module on the scene the way handle_test_run
    and RunModule do."""
    scene.nodegraph_state = GraphState()
    module = Graph()
    task = task or _FakeTask()
    scene.nodegraph_state.shared["__test_module"] = module
    scene.nodegraph_state.shared[f"__run_{module.id}"] = task
    return module, task


def test_release_cancels_a_running_test_module(wired):
    handler, scene, agent, memory = wired
    module, task = _running_test_module(scene)

    handler.release_scene()

    assert task.cancelled is True
    assert scene.nodegraph_state.shared == {}
    assert handler.queued == [
        {"type": "node_editor", "action": "test_stopped", "data": {}}
    ]


def test_release_stops_an_unstarted_test_module(wired):
    """A module the creative loop has not picked up yet has no task - it must
    still be dropped and the frontend told."""
    handler, scene, agent, memory = wired
    module, _ = _running_test_module(scene)
    scene.nodegraph_state.shared.pop(f"__run_{module.id}")

    handler.release_scene()

    assert scene.nodegraph_state.shared == {}
    assert handler.queued == [
        {"type": "node_editor", "action": "test_stopped", "data": {}}
    ]


def test_release_without_a_test_module_sends_nothing(wired):
    """No loop state at all: the scene never ran a loop."""
    handler, scene, agent, memory = wired

    handler.release_scene()

    assert handler.queued == []


def test_release_with_loop_state_but_no_test_module_sends_nothing(wired):
    """The ordinary case: the scene ran a loop, so nodegraph_state exists,
    but no test module was ever tracked on it."""
    handler, scene, agent, memory = wired
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared["unrelated"] = 1

    handler.release_scene()

    assert handler.queued == []
    assert scene.nodegraph_state.shared == {"unrelated": 1}


def test_release_with_a_finished_test_task_sends_stopped_without_cancelling(wired):
    handler, scene, agent, memory = wired
    module, task = _running_test_module(scene, task=_FakeTask(done=True))

    handler.release_scene()

    assert task.cancelled is False
    assert scene.nodegraph_state.shared == {}
    assert handler.queued == [
        {"type": "node_editor", "action": "test_stopped", "data": {}}
    ]


async def test_cancelled_load_with_parked_test_module_keeps_new_scene_active(
    wired, monkeypatch
):
    """The join of this change: a scene task parked inside RunModule is
    cancelled while its replacement load rebinds the handler. The old frame's
    `finally` must not deactivate the incoming scene."""
    handler, scene, agent, memory = wired

    module_started = asyncio.Event()
    scenes_started = []

    class _Block(Node):
        def __init__(self, **kw):
            super().__init__(title="Block", **kw)

        def setup(self):
            self.add_input("state")

        async def run(self, state):
            module_started.set()
            await asyncio.Event().wait()

    async def fake_start(self):
        scenes_started.append(self)
        if len(scenes_started) == 1:
            # first scene: park inside RunModule the way the creative loop
            # does while running a test module
            self.nodegraph_state = GraphState()
            module = Graph()
            entry = Entry(title="entry")
            block = _Block()
            module.add_node(entry)
            module.add_node(block)
            module.connect(entry.outputs[0], block.get_input_socket("state"))
            self.nodegraph_state.shared["__test_module"] = module
            node = RunModule()
            node.set_property("module", module)
            with GraphContext(outer_state=self.nodegraph_state) as state:
                await node.run(state)
        else:
            await asyncio.Event().wait()

    async def fake_load(scene, *args, **kwargs):
        return scene

    monkeypatch.setattr(Scene, "start", fake_start)
    monkeypatch.setattr(websocket_server, "load_scene", fake_load)

    task_a = asyncio.create_task(handler.load_scene("a.json"))
    await asyncio.wait_for(module_started.wait(), timeout=5)
    scene_a = scenes_started[0]

    # what process_message does on load_scene: cancel, then immediately
    # create the replacement load task
    task_a.cancel()
    task_b = asyncio.create_task(handler.load_scene("b.json"))

    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task_a, timeout=5)
    await asyncio.sleep(0.1)

    assert task_a.cancelled()
    assert len(scenes_started) == 2
    scene_b = scenes_started[1]
    assert handler.scene is scene_b
    assert scene_a.active is False
    assert scene_b.active is True
    assert {m["action"] for m in handler.queued} == {"test_stopped"}

    task_b.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task_b, timeout=5)


async def test_load_frame_exit_deactivates_its_scene(wired, monkeypatch):
    """No replacement load: when the frame ends, the scene it loaded must end
    inactive."""
    handler, scene, agent, memory = wired

    async def fake_start(self):
        return

    async def fake_load(scene, *args, **kwargs):
        return scene

    monkeypatch.setattr(Scene, "start", fake_start)
    monkeypatch.setattr(websocket_server, "load_scene", fake_load)

    await handler.load_scene("a.json")

    assert handler.scene.active is False
