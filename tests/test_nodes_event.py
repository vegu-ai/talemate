"""Coverage-focused unit tests for talemate.game.engine.nodes.event.

Listen-node connect/disconnect helpers are tested by registering a real
Listen node into a Graph and verifying the underlying async-signals
registry. Emit nodes (EmitStatus, EmitSystemMessage, EmitSceneStatus,
EmitWorldEditorSync, EmitAgentMessage, EmitStatusConditional) are run
through `Node.run` with a real blinker subscriber capturing the outgoing
event payload.

No internals are mocked — the blinker `signal(...)` registry and the
`async_signals` registry are real process-global objects used as-is.
"""

from __future__ import annotations

import pytest
from blinker import signal as blinker_signal

import talemate.emit.async_signals as async_signals
from _node_test_helpers import run_node
from talemate.game.engine.nodes.core import (
    Graph,
    GraphContext,
    GraphState,
    Listen,
)
from talemate.game.engine.nodes.event import (
    EmitAgentMessage,
    EmitSceneStatus,
    EmitStatus,
    EmitStatusConditional,
    EmitSystemMessage,
    EmitWorldEditorSync,
    State as EventState,
    collect_auto_register_listeners,
    collect_listeners,
    connect_auto_register_listeners,
    connect_listeners,
    disconnect_auto_register_listeners,
    disconnect_listeners,
)
from talemate.game.engine.nodes.registry import NODES, register
from talemate.tale_mate import Scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def scene():
    """Plain real Scene — no agents are needed for these emit nodes."""
    s = Scene()
    return s


def _capture_blinker(typ: str):
    """Subscribe to a blinker signal and return (sig, recv, captured_list).

    The receiver MUST be retained — `weak=False` ensures the closure
    keeps it alive for the life of the test.

    NOTE: the talemate `emit()` helper uses `signal.send(Emission(...))`,
    so the blinker sender argument IS the Emission dataclass. We capture
    that directly.
    """
    sig = blinker_signal(typ)
    captured = []

    def _on(sender, *args, **kwargs):
        captured.append(sender)

    sig.connect(_on, weak=False)
    return sig, _on, captured


# ---------------------------------------------------------------------------
# collect_listeners / connect_listeners / disconnect_listeners
# ---------------------------------------------------------------------------


class TestListenerCollection:
    def test_collects_listen_nodes_at_top_level(self):
        # Register two Listen nodes for distinct events; collect_listeners
        # returns them grouped by event_name.
        g = Graph()
        l1 = Listen()
        l1.set_property("event_name", "evt.alpha")
        l2 = Listen()
        l2.set_property("event_name", "evt.beta")
        g.add_node(l1)
        g.add_node(l2)

        result = collect_listeners(g)
        assert set(result.keys()) == {"evt.alpha", "evt.beta"}
        assert result["evt.alpha"] == [l1]
        assert result["evt.beta"] == [l2]

    def test_skips_listen_with_empty_event_name(self, caplog):
        g = Graph()
        bad = Listen()
        bad.set_property("event_name", "")
        g.add_node(bad)

        result = collect_listeners(g)
        assert result == {}

    def test_skips_listen_with_auto_register_true(self):
        # Listen nodes with auto_register=True are owned by the
        # collect_auto_register_listeners path — collect_listeners must
        # ignore them even when they are embedded in the graph.
        g = Graph()
        embedded = Listen()
        embedded.set_property("event_name", "evt.auto")
        embedded.set_property("auto_register", True)
        regular = Listen()
        regular.set_property("event_name", "evt.regular")
        g.add_node(embedded)
        g.add_node(regular)

        result = collect_listeners(g)
        assert "evt.auto" not in result
        assert result == {"evt.regular": [regular]}

    def test_recurses_into_nested_graphs(self):
        # Listen nodes inside a nested Graph are also discovered.
        outer = Graph()
        nested = Graph()
        outer.add_node(nested)
        listener = Listen()
        listener.set_property("event_name", "evt.nested")
        nested.add_node(listener)
        result = collect_listeners(outer)
        assert "evt.nested" in result


class TestConnectAndDisconnectListeners:
    @pytest.fixture
    def isolated_signal(self):
        # Register a fresh signal name we can safely connect/disconnect to
        # without affecting the rest of the system.
        name = "test_event_evt_12345"
        # Already registered? Tear it down before re-registering.
        if name in async_signals.handlers:
            async_signals.handlers.pop(name)
        async_signals.register(name)
        yield name
        async_signals.handlers.pop(name, None)

    def test_connect_subscribes_listen_node_to_signal(self, isolated_signal):
        g = Graph()
        listener = Listen()
        listener.set_property("event_name", isolated_signal)
        g.add_node(listener)

        sig = async_signals.get(isolated_signal)
        connect_listeners(g, GraphState())
        assert listener.execute_from_event in sig.receivers

    def test_connect_to_unknown_signal_logs_and_skips(self, caplog):
        g = Graph()
        listener = Listen()
        listener.set_property("event_name", "test_completely_unknown_signal_zzz")
        g.add_node(listener)
        # Should not raise — warning is logged.
        connect_listeners(g, GraphState())

    def test_disconnect_removes_listener(self, isolated_signal):
        g = Graph()
        listener = Listen()
        listener.set_property("event_name", isolated_signal)
        g.add_node(listener)
        sig = async_signals.get(isolated_signal)

        connect_listeners(g, GraphState())
        assert listener.execute_from_event in sig.receivers
        disconnect_listeners(g, GraphState())
        assert listener.execute_from_event not in sig.receivers

    def test_connect_with_disconnect_flag_replaces(self, isolated_signal):
        # Calling connect_listeners with disconnect=True first removes the
        # existing listener, then re-adds it (idempotent).
        g = Graph()
        listener = Listen()
        listener.set_property("event_name", isolated_signal)
        g.add_node(listener)
        sig = async_signals.get(isolated_signal)

        connect_listeners(g, GraphState())
        connect_listeners(g, GraphState(), disconnect=True)
        # Listener still present after the disconnect/connect cycle
        assert listener.execute_from_event in sig.receivers


# ---------------------------------------------------------------------------
# Auto-register listeners (self-registering Listen subclasses)
# ---------------------------------------------------------------------------


class TestAutoRegisterListeners:
    """Auto-register listeners discover Listen subclasses that have
    auto_register=True baked into their persisted properties — these come
    from user-authored scene-module graphs (loaded via
    ``import_node_definition``) rather than being placed in the scene
    loop graph manually.

    For tests we register a minimal Listen subclass into ``NODES`` with a
    matching ``_base_type``, since ``get_nodes_by_base_type`` checks the
    underscored attribute (which scene modules set explicitly via
    ``dynamic_node_import``). This is the realistic shape.
    """

    @pytest.fixture
    def auto_signal(self):
        name = "test_auto_register_signal_xyz"
        if name in async_signals.handlers:
            async_signals.handlers.pop(name)
        async_signals.register(name)
        yield name
        async_signals.handlers.pop(name, None)

    @pytest.fixture
    def registered_auto_listen(self, auto_signal):
        # Build a Listen subclass that, when instantiated, has the
        # persisted auto_register=True and event_name set — mirroring the
        # shape produced by dynamic_node_import for scene modules.
        signal_name = auto_signal
        registry_name = "test/AutoListenForTest"

        @register(registry_name)
        class _TestAutoListen(Listen):
            _base_type = "core/Event"

            def setup(self):
                super().setup()
                self.set_property("event_name", signal_name)
                self.set_property("auto_register", True)

        yield _TestAutoListen, signal_name, registry_name
        NODES.pop(registry_name, None)

    @pytest.fixture
    def registered_auto_listen_no_event(self):
        registry_name = "test/AutoListenNoEvent"

        @register(registry_name)
        class _TestAutoListenNoEvent(Listen):
            _base_type = "core/Event"

            def setup(self):
                super().setup()
                self.set_property("event_name", "")
                self.set_property("auto_register", True)

        yield registry_name
        NODES.pop(registry_name, None)

    @pytest.fixture
    def registered_non_auto_listen(self):
        registry_name = "test/NonAutoListen"

        @register(registry_name)
        class _TestNonAutoListen(Listen):
            _base_type = "core/Event"

            def setup(self):
                super().setup()
                self.set_property("event_name", "test.non_auto")
                self.set_property("auto_register", False)

        yield registry_name
        NODES.pop(registry_name, None)

    def test_collects_auto_register_listen_subclass(self, registered_auto_listen):
        _cls, signal_name, _registry = registered_auto_listen
        instances = collect_auto_register_listeners()
        # Find our instance among any other registered core/Event nodes
        ours = [i for i in instances if i.get_property("event_name") == signal_name]
        assert len(ours) == 1
        assert ours[0].get_property("auto_register") is True

    def test_skips_listen_subclass_without_auto_register(
        self, registered_non_auto_listen
    ):
        instances = collect_auto_register_listeners()
        event_names = [i.get_property("event_name") for i in instances]
        assert "test.non_auto" not in event_names

    def test_skips_auto_register_with_empty_event_name(
        self, registered_auto_listen_no_event
    ):
        # collect_auto_register_listeners warns and skips when event_name
        # is empty — it should not crash and should not return that one.
        instances = collect_auto_register_listeners()
        # Empty event_name means no instance can be returned for it
        for inst in instances:
            assert inst.get_property("event_name") != ""

    def test_connect_subscribes_auto_register_listener(self, registered_auto_listen):
        _cls, signal_name, _registry = registered_auto_listen
        instances = collect_auto_register_listeners()
        ours = [i for i in instances if i.get_property("event_name") == signal_name]
        assert len(ours) == 1
        instance = ours[0]

        sig = async_signals.get(signal_name)
        connect_auto_register_listeners([instance], GraphState())
        assert instance.execute_from_event in sig.receivers

    def test_disconnect_removes_auto_register_listener(self, registered_auto_listen):
        _cls, signal_name, _registry = registered_auto_listen
        instances = collect_auto_register_listeners()
        ours = [i for i in instances if i.get_property("event_name") == signal_name]
        instance = ours[0]
        sig = async_signals.get(signal_name)

        connect_auto_register_listeners([instance], GraphState())
        assert instance.execute_from_event in sig.receivers
        disconnect_auto_register_listeners([instance], GraphState())
        assert instance.execute_from_event not in sig.receivers

    def test_connect_with_disconnect_flag_is_idempotent(self, registered_auto_listen):
        # Reconnecting with disconnect=True should NOT double up the
        # listener in the receiver list (same instance, same bound method).
        _cls, signal_name, _registry = registered_auto_listen
        instances = collect_auto_register_listeners()
        ours = [i for i in instances if i.get_property("event_name") == signal_name]
        instance = ours[0]
        sig = async_signals.get(signal_name)

        connect_auto_register_listeners([instance], GraphState())
        connect_auto_register_listeners([instance], GraphState(), disconnect=True)
        # Listener present exactly once
        matching = [r for r in sig.receivers if r == instance.execute_from_event]
        assert len(matching) == 1

    def test_connect_to_unknown_signal_logs_and_skips(self):
        # An auto-register Listen pointing at an unknown signal must not
        # raise — the function logs a warning and moves on.
        registry_name = "test/AutoListenUnknownSignal"

        @register(registry_name)
        class _TestAutoListenUnknown(Listen):
            _base_type = "core/Event"

            def setup(self):
                super().setup()
                self.set_property("event_name", "completely_unregistered_signal_xx")
                self.set_property("auto_register", True)

        try:
            instances = collect_auto_register_listeners()
            ours = [
                i
                for i in instances
                if i.get_property("event_name") == "completely_unregistered_signal_xx"
            ]
            assert len(ours) == 1
            # Must not raise
            connect_auto_register_listeners(ours, GraphState())
        finally:
            NODES.pop(registry_name, None)

    def test_embedded_and_auto_registered_fires_once(self, registered_auto_listen):
        # If a Listen subclass with auto_register=True is also dropped as
        # an instance into the scene loop graph, the receiver list must
        # contain exactly ONE bound method after both wiring paths run.
        # collect_listeners must skip the embedded copy and only the
        # auto-register path subscribes.
        _cls, signal_name, _registry = registered_auto_listen

        # Embedded copy of the same Listen class in a graph
        embedded_graph = Graph()
        embedded = _cls()
        embedded_graph.add_node(embedded)

        # Auto-register path collects the registry instance
        registry_instances = collect_auto_register_listeners()
        from_registry = [
            i for i in registry_instances if i.get_property("event_name") == signal_name
        ]
        assert len(from_registry) == 1

        # Run both wiring paths
        sig = async_signals.get(signal_name)
        connect_listeners(embedded_graph, GraphState(), disconnect=True)
        connect_auto_register_listeners(from_registry, GraphState(), disconnect=True)

        # The embedded instance must NOT be in the receiver list
        assert embedded.execute_from_event not in sig.receivers
        # The registry instance IS in the receiver list, exactly once
        assert sig.receivers.count(from_registry[0].execute_from_event) == 1


# ---------------------------------------------------------------------------
# EventState (event/Event) — returns state.data["event"]
# ---------------------------------------------------------------------------


class TestEventState:
    @pytest.mark.asyncio
    async def test_returns_event_from_state_data(self):
        node = EventState()

        with GraphContext() as state:
            state.data["event"] = {"kind": "external"}
            await node.run(state)
            assert node.get_output_socket("event").value == {"kind": "external"}

    @pytest.mark.asyncio
    async def test_returns_none_when_no_event_in_state(self):
        node = EventState()
        with GraphContext() as state:
            await node.run(state)
            assert node.get_output_socket("event").value is None


# ---------------------------------------------------------------------------
# EmitStatus
# ---------------------------------------------------------------------------


class TestEmitStatus:
    @pytest.mark.asyncio
    async def test_emits_status_message(self, scene):
        sig, recv, captured = _capture_blinker("status")
        try:
            out = await run_node(
                EmitStatus(),
                scene=scene,
                inputs={"message": "Working...", "status": "info"},
            )
            assert out["emitted"] is True
            assert len(captured) == 1
            emission = captured[0]
            assert emission.message == "Working..."
            assert emission.status == "info"
            assert emission.scene is scene
        finally:
            sig.disconnect(recv)

    @pytest.mark.asyncio
    async def test_as_scene_message_flag_passed_through(self, scene):
        sig, recv, captured = _capture_blinker("status")
        try:
            await run_node(
                EmitStatus(),
                scene=scene,
                inputs={
                    "message": "hi",
                    "status": "info",
                    "as_scene_message": True,
                },
            )
            assert captured[0].data == {"as_scene_message": True}
        finally:
            sig.disconnect(recv)


# ---------------------------------------------------------------------------
# EmitSystemMessage
# ---------------------------------------------------------------------------


class TestEmitSystemMessage:
    @pytest.mark.asyncio
    async def test_emits_with_meta_block(self, scene):
        sig, recv, captured = _capture_blinker("system")
        try:
            out = await run_node(
                EmitSystemMessage(),
                scene=scene,
                inputs={
                    "state": "passthrough",
                    "message": "system note",
                    "message_title": "Note",
                    "font_color": "white",
                    "icon": "mdi-x",
                    "display": "tonal",
                    "as_markdown": True,
                },
            )
            # `state` socket carries the original state input through
            assert out["state"] == "passthrough"
            assert len(captured) == 1
            emission = captured[0]
            assert emission.message == "system note"
            assert emission.meta["title"] == "Note"
            assert emission.meta["color"] == "white"
            assert emission.meta["icon"] == "mdi-x"
            assert emission.meta["display"] == "tonal"
            assert emission.meta["as_markdown"] is True
        finally:
            sig.disconnect(recv)


# ---------------------------------------------------------------------------
# EmitStatusConditional
# ---------------------------------------------------------------------------


class TestEmitStatusConditional:
    @pytest.mark.asyncio
    async def test_emits_and_passes_state(self, scene):
        sig, recv, captured = _capture_blinker("status")
        try:
            out = await run_node(
                EmitStatusConditional(),
                scene=scene,
                inputs={
                    "state": "ok",
                    "message": "Hello",
                    "status": "info",
                },
            )
            # Conditional flavor passes state through and still emits.
            assert out["state"] == "ok"
            assert len(captured) == 1
            assert captured[0].message == "Hello"
        finally:
            sig.disconnect(recv)


# ---------------------------------------------------------------------------
# EmitSceneStatus
# ---------------------------------------------------------------------------


class TestEmitSceneStatus:
    @pytest.mark.asyncio
    async def test_calls_scene_emit_status(self, scene):
        # Replace scene.emit_status with a tracking lambda — the real one is
        # debounced/async and not what we're testing here.
        called = []
        scene.emit_status = lambda *a, **kw: called.append(True)

        out = await run_node(
            EmitSceneStatus(), scene=scene, inputs={"state": "passthrough"}
        )
        assert out["state"] == "passthrough"
        assert called == [True]


# ---------------------------------------------------------------------------
# EmitWorldEditorSync
# ---------------------------------------------------------------------------


class TestEmitWorldEditorSync:
    @pytest.mark.asyncio
    async def test_emits_world_state_manager_sync(self, scene):
        sig, recv, captured = _capture_blinker("world_state_manager")
        try:
            out = await run_node(
                EmitWorldEditorSync(),
                scene=scene,
                inputs={"state": "passthrough"},
            )
            assert out["state"] == "passthrough"
            assert len(captured) == 1
            emission = captured[0]
            assert emission.kwargs == {"action": "sync"}
            assert emission.websocket_passthrough is True
        finally:
            sig.disconnect(recv)


# ---------------------------------------------------------------------------
# EmitAgentMessage
# ---------------------------------------------------------------------------


class TestEmitAgentMessage:
    @pytest.mark.asyncio
    async def test_emits_with_agent_string(self, scene):
        # NOTE: typ "agent_message" is mapped to signal name "agent" in
        # talemate/emit/signals.py — subscribe to the underlying blinker
        # signal name, not the typ string.
        sig, recv, captured = _capture_blinker("agent")
        try:
            out = await run_node(
                EmitAgentMessage(),
                scene=scene,
                inputs={
                    "state": "ok",
                    "message": "Done",
                    "agent": "editor",
                    "header": "Removed",
                    "message_color": "highlight4",
                    "meta": {"action": "x"},
                },
            )
            assert out["emitted"] is True
            assert len(captured) == 1
            emission = captured[0]
            assert emission.message == "Done"
            assert emission.data["agent"] == "editor"
            assert emission.data["header"] == "Removed"
            assert emission.data["color"] == "highlight4"
            # Auto-generated UUID present
            assert emission.data["uuid"]
            assert emission.meta == {"action": "x"}
            assert emission.websocket_passthrough is True
        finally:
            sig.disconnect(recv)

    @pytest.mark.asyncio
    async def test_emits_with_agent_object_uses_name(self, scene):
        # When the `agent` input is an Agent instance, we use its .name —
        # rather than instantiating a real Agent (which would require
        # bootstrap), use a minimal stand-in object that satisfies isinstance.
        from talemate.agents.base import Agent

        class FakeAgent(Agent):
            agent_type = "fake"

            def __init__(self, name):
                self.name = name

            @property
            def enabled(self):
                return False

        agent = FakeAgent("named_agent")

        sig, recv, captured = _capture_blinker("agent")
        try:
            await run_node(
                EmitAgentMessage(),
                scene=scene,
                inputs={
                    "state": "ok",
                    "message": "X",
                    "agent": agent,
                    "header": "H",
                    "message_color": "white",
                    "meta": {},
                },
            )
            assert captured[0].data["agent"] == "named_agent"
        finally:
            sig.disconnect(recv)
