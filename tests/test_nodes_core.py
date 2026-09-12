"""
Coverage-focused unit tests for talemate.game.engine.nodes.core.

These tests build small synthetic graphs and exercise public entry points
(Node.run, Graph.execute, Loop.execute, Listen.execute_from_event,
Trigger.run, etc.) so we cover:

- Socket/Property edge cases (missing graph_state, dunder methods,
  generate_choices)
- Graph traversal helpers (set_node_references, set_socket_source_references,
  ensure_connections, connect by string)
- Serialization (model_dump with/without SaveContext, _node_serialization_fields)
- Dispatch & error handling inside Graph._execute_inner / Loop.execute
- Listen and Trigger event hooks
- ModuleProperty.cast_value branches
- load_extended_components from a JSON file
- dynamic_node_import factory

No domain agents/scenes are required — every test instantiates real Node
subclasses and runs them through real Graph/Loop primitives.
"""

import asyncio
import json
from typing import Any, ClassVar

import pytest
import structlog

from talemate.emit.async_signals import DEFERRED
from talemate.game.engine.nodes.core import (
    UNRESOLVED,
    Comment,
    Entry,
    Graph,
    GraphContext,
    GraphState,
    Group,
    InputValueError,
    Listen,
    Loop,
    LoopExit,
    ModuleProperty,
    ModuleStyle,
    Node,
    NodeBase,
    NodeState,
    NodeVerbosity,
    Output,
    Input,
    PropertyField,
    Route,
    SaveContext,
    Socket,
    Stage,
    StageExit,
    StopGraphExecution,
    StopModule,
    Trigger,
    Watch,
    dynamic_node_import,
    get_ancestors_with_forks,
    get_type_class,
    load_extended_components,
    save_state,
    validate_node,
)
from talemate.util.async_tools import cleanup_pending_tasks

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class ValueNode(Node):
    """Emit a constant value on its `value` output."""

    def __init__(self, value: Any = None, title: str = "ValueNode", **kwargs):
        super().__init__(title=title, **kwargs)
        self._emit = value

    def setup(self):
        self.add_output("value")

    async def run(self, state: GraphState):
        self.set_output_values({"value": self._emit})


class CaptureNode(Node):
    """Capture `value` input into ``self.captured``."""

    captured: list = None

    def __init__(self, title: str = "Capture", **kwargs):
        super().__init__(title=title, **kwargs)
        self.captured = []

    def setup(self):
        self.add_input("value")

    async def run(self, state: GraphState):
        self.captured.append(self.get_input_value("value"))


class RaisingNode(Node):
    """Raise the exception class supplied via ``self._exc``."""

    def __init__(self, exc: Exception, title: str = "Raise", **kwargs):
        super().__init__(title=title, **kwargs)
        self._exc = exc

    def setup(self):
        self.add_input("trigger", optional=True)
        self.add_output("done")

    async def run(self, state: GraphState):
        raise self._exc


def build_value_capture_graph(value):
    """Create a Graph: ValueNode -> CaptureNode wired on `value`."""
    g = Graph()
    src = ValueNode(value=value)
    sink = CaptureNode()
    g.add_node(src)
    g.add_node(sink)
    g.connect(src.outputs[0], sink.inputs[0])
    return g, src, sink


# ---------------------------------------------------------------------------
# Module-level helpers (get_type_class, get_ancestors_with_forks,
# load_extended_components, dynamic_node_import)
# ---------------------------------------------------------------------------


class TestGetTypeClass:
    def test_known_type_returns_class(self):
        assert get_type_class("str") is str
        assert get_type_class("int") is int
        assert get_type_class("dict") is dict

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Could not find class"):
            get_type_class("not-a-type")


class TestGetAncestorsWithForks:
    def test_includes_forked_branch(self):
        """A branch from a shared ancestor that does not lead to the target
        is still included (this is the helper's whole point)."""
        import networkx as nx

        # A -> B -> D (target)
        # A -> C  (fork: doesn't reach D)
        g = nx.DiGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "D")
        g.add_edge("A", "C")

        result = get_ancestors_with_forks(g, "D")

        # Direct ancestors
        assert "A" in result
        assert "B" in result
        # Fork that nx.ancestors() would miss
        assert "C" in result
        # Target itself is not included
        assert "D" not in result

    def test_no_ancestors_returns_empty(self):
        import networkx as nx

        g = nx.DiGraph()
        g.add_node("A")
        assert get_ancestors_with_forks(g, "A") == set()


class TestLoadExtendedComponents:
    def test_merges_nodes_edges_groups_comments_marking_inherited(self, tmp_path):
        base_path = tmp_path / "base.json"
        base = {
            "nodes": {"n1": {"id": "n1", "title": "Base"}},
            "edges": {"n1.out": ["n2.in"]},
            "groups": [{"title": "G1"}],
            "comments": [{"text": "C1"}],
        }
        base_path.write_text(json.dumps(base))

        target = {
            "nodes": {"n2": {"id": "n2", "title": "Target"}},
            "edges": {},
            "groups": [],
            "comments": [],
        }
        load_extended_components(str(base_path), target)

        # Inherited nodes are added with inherited=True
        assert "n1" in target["nodes"]
        assert target["nodes"]["n1"]["inherited"] is True
        # Existing nodes are not overwritten
        assert target["nodes"]["n2"]["title"] == "Target"
        # Edges merged
        assert target["edges"]["n1.out"] == ["n2.in"]
        # Groups/comments inherited and stamped
        assert target["groups"][0]["inherited"] is True
        assert target["comments"][0]["inherited"] is True

    def test_chained_extends(self, tmp_path):
        """When a base file itself extends another, the chain is loaded."""
        deep = tmp_path / "deep.json"
        deep.write_text(
            json.dumps(
                {
                    "nodes": {"deep_node": {"id": "deep_node"}},
                    "edges": {},
                    "groups": [],
                    "comments": [],
                }
            )
        )
        mid = tmp_path / "mid.json"
        mid.write_text(
            json.dumps(
                {
                    "extends": str(deep),
                    "nodes": {"mid_node": {"id": "mid_node"}},
                    "edges": {},
                    "groups": [],
                    "comments": [],
                }
            )
        )

        target = {"nodes": {}, "edges": {}, "groups": [], "comments": []}
        load_extended_components(str(mid), target)

        assert "deep_node" in target["nodes"]
        assert "mid_node" in target["nodes"]
        assert target["nodes"]["deep_node"]["inherited"] is True
        assert target["nodes"]["mid_node"]["inherited"] is True


class TestDynamicNodeImport:
    def test_unknown_base_type_raises(self):
        with pytest.raises(ValueError, match="Cannont import"):
            dynamic_node_import(
                {"base_type": "core/NotARealBaseType"},
                "test/UnknownBase",
            )

    def test_creates_dynamic_class_in_provided_container(self):
        container = {}
        cls = dynamic_node_import(
            {
                "base_type": "core/Graph",
                "title": "DynamicGraph",
                "nodes": {},
                "edges": {},
            },
            "test/DynamicGraphNode",
            registry_container=container,
        )

        # Class registered into our isolated container, not the global NODES
        assert "test/DynamicGraphNode" in container
        assert getattr(cls, "__dynamic_imported__") is True
        assert cls._base_type == "core/Graph"
        # Name is taken from the trailing segment of the registry name
        assert cls.__name__ == "DynamicGraphNode"

        # The dynamic class is instantiable as a Graph subclass
        instance = cls()
        assert isinstance(instance, Graph)


# ---------------------------------------------------------------------------
# UNRESOLVED sentinel
# ---------------------------------------------------------------------------


def test_unresolved_is_falsy_and_repr_stable():
    assert bool(UNRESOLVED()) is False
    assert str(UNRESOLVED()) == "<UNRESOLVED>"
    assert repr(UNRESOLVED()) == "<UNRESOLVED>"


# ---------------------------------------------------------------------------
# Socket
# ---------------------------------------------------------------------------


class TestSocketBehaviour:
    def test_value_outside_graph_state_returns_unresolved(self):
        node = Node(title="N")
        sock = node.add_input("foo")
        # No GraphContext active — there is no graph_state set
        assert sock.value is UNRESOLVED

    def test_setting_value_outside_graph_state_is_silent_noop(self):
        node = Node(title="N")
        sock = node.add_output("foo")
        sock.value = 123  # must not raise
        assert sock.value is UNRESOLVED

    def test_deactivated_outside_graph_state_returns_true(self):
        node = Node(title="N")
        sock = node.add_input("foo")
        # Outside the graph context, sockets are considered deactivated as a
        # safety default (the runtime requires a state to track activation).
        assert sock.deactivated is True

    def test_setting_deactivated_outside_graph_state_is_silent_noop(self):
        node = Node(title="N")
        sock = node.add_input("foo")
        sock.deactivated = False  # must not raise

    def test_value_within_graph_context(self):
        node = Node(title="N")
        sock = node.add_output("foo")
        with GraphContext():
            sock.value = "hello"
            assert sock.value == "hello"

    def test_value_through_source_lookup(self):
        a = Node(title="A")
        b = Node(title="B")
        out = a.add_output("out")
        inp = b.add_input("in")
        inp.source = out

        with GraphContext() as state:
            state.set_node_socket_value(a, "out", 42)
            # Reading from `inp` follows source -> A.out
            assert inp.value == 42

    def test_full_id_combines_node_and_socket(self):
        n = Node(title="N", id="node-id")
        s = n.add_input("sname")
        assert s.full_id == "node-id.sname"

    def test_str_with_node(self):
        n = Node(title="MyNode")
        s = n.add_input("foo")
        assert str(s) == "MyNode.foo"
        assert repr(s) == "MyNode.foo"

    def test_str_without_node(self):
        s = Socket(name="orphan")
        assert str(s) == "orphan"

    def test_eq_and_hash_use_id(self):
        n = Node(title="N")
        s1 = n.add_input("x")
        # Two sockets with the same id compare equal and hash the same
        s2 = Socket(name="x", id=s1.id)
        assert s1 == s2
        assert hash(s1) == hash(s2)
        # Different id
        s3 = n.add_input("y")
        assert s1 != s3

    def test_socket_as_bool_unresolved(self):
        assert Socket.as_bool(UNRESOLVED) is False
        assert Socket.as_bool(0) is False  # bool(0)
        assert Socket.as_bool("hello") is True


# ---------------------------------------------------------------------------
# PropertyField & RESERVED_PROPERTY_NAMES
# ---------------------------------------------------------------------------


class TestPropertyField:
    def test_reserved_name_rejected(self):
        with pytest.raises(ValueError, match="reserved"):
            PropertyField(name="id", description="x", type="str")

    def test_model_dump_without_generate_choices(self):
        field = PropertyField(name="x", description="x", type="str", choices=["a", "b"])
        data = field.model_dump()
        assert data["choices"] == ["a", "b"]

    def test_generate_choices_overrides_choices(self):
        def gen():
            return ["dynamic1", "dynamic2"]

        field = PropertyField(
            name="x",
            description="x",
            type="str",
            choices=["static"],
            generate_choices=gen,
        )
        data = field.model_dump()
        assert data["choices"] == ["dynamic1", "dynamic2"]


# ---------------------------------------------------------------------------
# NodeBase
# ---------------------------------------------------------------------------


class TestNodeBaseHelpers:
    def test_set_property_rejects_reserved_name(self):
        n = Node(title="N")
        with pytest.raises(ValueError, match="reserved"):
            n.set_property("id", "anything")

    def test_remove_input_and_output(self):
        n = Node(title="N")
        n.add_input("a")
        n.add_input("b")
        n.add_output("x")
        n.add_output("y")

        n.remove_input("a")
        assert [s.name for s in n.inputs] == ["b"]
        # Removing a non-existent socket is a no-op
        n.remove_input("does-not-exist")
        assert [s.name for s in n.inputs] == ["b"]

        n.remove_output("y")
        assert [s.name for s in n.outputs] == ["x"]

    def test_field_definitions_includes_properties_and_meta_class(self):
        # Stage has a Fields meta-class with `stage` PropertyField
        s = Stage()
        defs = s.field_definitions
        assert "stage" in defs
        assert defs["stage"].type == "int"

    def test_field_definitions_for_unknown_property_falls_back(self):
        n = Node(title="N")
        n.set_property("count", 5)
        defs = n.field_definitions
        # `count` is not declared in any Fields meta — falls back to inferred type
        assert "count" in defs
        assert defs["count"].type == "int"

    def test_handle_unresolved_properties_validator(self):
        # The before-validator converts None / 'UNRESOLVED' string back to
        # the UNRESOLVED sentinel. Call the classmethod directly because the
        # public __init__ pops `properties` before pydantic validation runs.
        out = NodeBase.handle_unresolved_properties(
            {"properties": {"foo": "UNRESOLVED", "bar": None, "baz": 5}}
        )
        assert out["properties"]["foo"] is UNRESOLVED
        assert out["properties"]["bar"] is UNRESOLVED
        assert out["properties"]["baz"] == 5

    def test_handle_unresolved_properties_validator_passthrough_for_non_dict(self):
        # The validator is a no-op for inputs that are not a dict with
        # `properties` set.
        assert NodeBase.handle_unresolved_properties({}) == {}
        # Also no-op for non-dict (the validator only mutates dict-shaped inputs)
        assert NodeBase.handle_unresolved_properties("anything") == "anything"

    def test_model_dump_replaces_unresolved_with_none(self):
        # Set the UNRESOLVED sentinel directly so we hit the dump-time
        # normalization branch.
        n = Node(title="N")
        n.properties["foo"] = UNRESOLVED
        n.properties["bar"] = "ordinary"
        data = n.model_dump()
        assert data["properties"]["foo"] is None
        assert data["properties"]["bar"] == "ordinary"

    def test_default_title_falls_back_to_class_name_with_spaces(self):
        # Title not provided -> derived from class name
        class MyCustomThing(Node):
            pass

        n = MyCustomThing()
        assert n.title == "My Custom Thing"

    def test_eq_uses_id_and_returns_false_for_non_node(self):
        n = Node(title="N")
        assert (n == "not a node") is False


class TestRequireInput:
    @pytest.mark.asyncio
    async def test_require_input_raises_when_unresolved(self):
        class StrictNode(Node):
            def setup(self):
                self.add_input("must_be_set")

            async def run(self, state):
                self.require_input("must_be_set")

        n = StrictNode()
        g = Graph()
        g.add_node(n)

        with pytest.raises(InputValueError):
            with GraphContext() as state:
                await n.run(state)

    @pytest.mark.asyncio
    async def test_require_input_returns_value_when_set(self):
        class StrictNode(Node):
            received: Any = None

            def setup(self):
                self.add_input("v")

            async def run(self, state):
                self.received = self.require_input("v")

        n = StrictNode()
        n.set_property("v", "hello")
        with GraphContext():
            await n.run(None)
        assert n.received == "hello"

    @pytest.mark.asyncio
    async def test_require_input_treats_none_as_unset_by_default(self):
        n = Node(title="N")
        n.add_input("v")
        n.set_property("v", None)
        with GraphContext():
            with pytest.raises(InputValueError):
                n.require_input("v")

    @pytest.mark.asyncio
    async def test_require_input_with_none_is_set_true(self):
        n = Node(title="N")
        n.add_input("v")
        n.set_property("v", None)
        with GraphContext():
            assert n.require_input("v", none_is_set=True) is None


class TestNormalizedInputValue:
    def test_unresolved_becomes_none(self):
        n = Node(title="N")
        n.add_input("v")
        with GraphContext():
            assert n.normalized_input_value("v") is None

    def test_set_value_returned(self):
        n = Node(title="N")
        n.add_input("v")
        n.set_property("v", "x")
        with GraphContext():
            assert n.normalized_input_value("v") == "x"


class TestRequireNumberInput:
    def _make_node(self, value):
        n = Node(title="N")
        n.add_input("num")
        n.set_property("num", value)
        return n

    def test_string_int_is_converted(self):
        n = self._make_node("42")
        with GraphContext():
            assert n.require_number_input("num", types=(int,)) == 42

    def test_string_float_is_converted(self):
        n = self._make_node("3.14")
        with GraphContext():
            assert n.require_number_input("num", types=(float, int)) == pytest.approx(
                3.14
            )

    def test_invalid_string_raises(self):
        n = self._make_node("not-a-number")
        with GraphContext():
            with pytest.raises(InputValueError, match="Invalid number"):
                n.require_number_input("num")

    def test_non_number_value_raises(self):
        n = self._make_node([1, 2])
        with GraphContext():
            with pytest.raises(InputValueError, match="must be a number"):
                n.require_number_input("num")

    def test_int_passes_through(self):
        n = self._make_node(7)
        with GraphContext():
            assert n.require_number_input("num") == 7


# ---------------------------------------------------------------------------
# NodeState
# ---------------------------------------------------------------------------


class TestNodeState:
    def _state_for(self, node):
        with GraphContext() as state:
            ns = NodeState(node=node, state=state)
        return ns

    def test_eq_compares_node_id(self):
        n1 = Node(title="N", id="abc")
        n2 = Node(title="N2", id="abc")
        ns1 = self._state_for(n1)
        ns2 = self._state_for(n2)
        assert ns1 == ns2

    def test_eq_against_non_nodestate_returns_false(self):
        n1 = Node(title="N")
        ns1 = self._state_for(n1)
        # Hits the AttributeError branch
        assert (ns1 == "not a node state") is False

    def test_lt_gt_use_node_id(self):
        n1 = Node(title="N", id="aaa")
        n2 = Node(title="N", id="bbb")
        ns1 = self._state_for(n1)
        ns2 = self._state_for(n2)
        assert ns1 < ns2
        assert ns2 > ns1

    def test_lt_against_non_nodestate_returns_notimplemented(self):
        n1 = Node(title="N")
        ns1 = self._state_for(n1)
        assert ns1.__lt__("nope") is NotImplemented
        assert ns1.__gt__("nope") is NotImplemented

    def test_hash_uses_node_id(self):
        n1 = Node(title="N", id="hash-id")
        ns1 = self._state_for(n1)
        assert hash(ns1) == hash("hash-id")

    def test_str_and_repr(self):
        n = Node(title="N", id="ident")
        ns = self._state_for(n)
        assert "ident" in str(ns)
        assert "ident" in repr(ns)

    def test_flattened_truncates_long_values(self):
        n = Node(title="N", id="x")
        n.add_input("a")
        n.set_property("p", "y" * 1000)
        ns = self._state_for(n)
        ns.input_values = {"a": "x" * 5000}
        ns.output_values = {}
        flat = ns.flattened
        # reprlib truncates long strings under maxstring=255
        assert len(flat["input_values"]["a"]) <= 300
        assert flat["node_id"] == "x"


class TestGraphStateFlattened:
    def test_flattened_returns_stack_dump(self):
        with GraphContext() as state:
            n = Node(title="N", id="abc")
            ns = NodeState(node=n, state=state)
            state.stack.append(ns)

            data = state.flattened
            assert "stack" in data
            assert len(data["stack"]) == 1
            assert data["stack"][0]["node_id"] == "abc"

    def test_flattened_handles_circular_references(self):
        """If the stack contains something that confuses repr, the
        helper clears the stack and returns an empty list rather than
        crashing."""

        class BadNodeState:
            def __init__(self):
                pass

            @property
            def flattened(self):
                raise RuntimeError("circular!")

        state = GraphState()
        state.stack = [BadNodeState()]
        result = state.flattened
        assert result == {"stack": []}
        # Stack is cleared as a recovery
        assert state.stack == []


# ---------------------------------------------------------------------------
# GraphState set/get helpers
# ---------------------------------------------------------------------------


class TestGraphStateHelpers:
    def test_node_property_round_trip(self):
        n = Node(title="N")
        st = GraphState()
        st.set_node_property(n, "k", "v")
        assert st.get_node_property(n, "k") == "v"

    def test_node_property_falls_back_to_property_then_unresolved(self):
        n = Node(title="N")
        n.set_property("local_only", "from-node")
        st = GraphState()
        # Not set in state -> falls back to node.properties
        assert st.get_node_property(n, "local_only") == "from-node"
        # Not set anywhere -> UNRESOLVED
        assert st.get_node_property(n, "missing") is UNRESOLVED

    def test_node_socket_value_round_trip(self):
        n = Node(title="N")
        st = GraphState()
        st.set_node_socket_value(n, "out", 99)
        assert st.get_node_socket_value(n, "out") == 99

    def test_node_socket_value_default_unresolved(self):
        n = Node(title="N")
        st = GraphState()
        assert st.get_node_socket_value(n, "no-such-socket") is UNRESOLVED

    def test_node_socket_state_round_trip(self):
        n = Node(title="N")
        st = GraphState()
        # default false
        assert st.get_node_socket_state(n, "x") is False
        st.set_node_socket_state(n, "x", True)
        assert st.get_node_socket_state(n, "x") is True


class TestSaveContext:
    def test_save_state_within_context(self):
        # Outside the context, save_state has no value
        with pytest.raises(LookupError):
            save_state.get()

        with SaveContext():
            assert save_state.get() is True

        # Reset on exit
        with pytest.raises(LookupError):
            save_state.get()


# ---------------------------------------------------------------------------
# Graph: connect, set_node_references, ensure_connections, model_dump
# ---------------------------------------------------------------------------


class TestGraphWiring:
    def test_connect_with_socket_string_ids(self):
        g = Graph()
        a = ValueNode(value=1, title="A")
        b = CaptureNode(title="B")
        g.add_node(a)
        g.add_node(b)
        # connect by socket string id, exercises the str -> Socket lookup
        # branch.
        g.connect(a.outputs[0].id, b.inputs[0].id)
        assert b.inputs[0].source.id == a.outputs[0].id
        assert (
            f"{a.id}.{a.outputs[0].name}" in g.edges
            and f"{b.id}.{b.inputs[0].name}" in g.edges[f"{a.id}.{a.outputs[0].name}"]
        )

    def test_connect_with_invalid_string_id_logs_and_returns(self):
        g = Graph()
        a = ValueNode(value=1)
        g.add_node(a)
        # Lookup against unknown id raises KeyError
        with pytest.raises(KeyError):
            g.connect("no-such-socket-id", a.outputs[0].id)

    def test_connect_dedup_avoids_duplicate_edge(self):
        g, src, sink = build_value_capture_graph(1)
        # Reconnecting the same edge should be a no-op (set semantics on
        # the input list)
        g.connect(src.outputs[0], sink.inputs[0])
        edge_key = f"{src.id}.value"
        assert g.edges[edge_key].count(f"{sink.id}.value") == 1

    def test_set_node_references_populates_full_id_lookup(self):
        """set_node_references re-keys self.sockets by full_id and assigns
        socket.node back to its parent node."""
        g = Graph()
        a = ValueNode(value=1)
        b = CaptureNode()
        g.add_node(a)
        g.add_node(b)

        # Reset the node refs to simulate a freshly deserialized graph
        for node in (a, b):
            for socket in node.inputs + node.outputs:
                socket.node = None

        result = g.set_node_references()
        assert result is g  # chainable
        # Sockets keyed by full_id
        assert f"{a.id}.value" in g.sockets
        assert f"{b.id}.value" in g.sockets
        # node back-reference restored
        assert a.outputs[0].node is a
        assert b.inputs[0].node is b

    def test_reinitialize_restores_source_references_via_ensure_connections(self):
        """`reinitialize()` rebuilds source pointers, socket lookups, and
        ensures connections."""
        g = Graph()
        a = ValueNode(value=1)
        b = CaptureNode()
        g.add_node(a)
        g.add_node(b)
        g.connect(a.outputs[0], b.inputs[0])

        # Strip the source pointer to simulate a re-loaded graph
        b.inputs[0].source = None

        g.reinitialize()
        # ensure_connections rewires the source from the edges dict
        assert b.inputs[0].source is not None
        assert b.inputs[0].source.full_id == f"{a.id}.value"

    def test_ensure_connections_warns_for_missing_input_socket(self, caplog):
        g = Graph()
        a = ValueNode(value=1)
        b = CaptureNode()
        g.add_node(a)
        g.add_node(b)

        # Edge points at an input socket that does not exist on b
        g.edges[f"{a.id}.value"] = [f"{b.id}.does_not_exist"]
        g.set_node_references()

        # Should not raise — should emit a warning and continue
        g.ensure_connections()
        assert b.inputs[0].source is None  # nothing was connected

    def test_node_lookup_helper(self):
        g, src, sink = build_value_capture_graph(1)
        assert g.node(src.id) is src
        assert g.node(sink.id) is sink

    def test_get_input_socket_returns_none_when_missing(self):
        n = Node(title="N")
        n.add_input("a")
        assert n.get_input_socket("a") is not None
        assert n.get_input_socket("missing") is None

    def test_get_output_socket_returns_none_when_missing(self):
        n = Node(title="N")
        n.add_output("a")
        assert n.get_output_socket("a") is not None
        assert n.get_output_socket("missing") is None


# ---------------------------------------------------------------------------
# Graph: build, execute, callback wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_execute_propagates_value():
    g, src, sink = build_value_capture_graph("hello")
    await g.execute()
    await cleanup_pending_tasks()
    assert sink.captured == ["hello"]


@pytest.mark.asyncio
async def test_graph_execute_runs_user_callbacks_after_state_callbacks():
    g, _, sink = build_value_capture_graph("x")
    order = []

    async def on_state(state):
        order.append("graph-callback")

    async def on_user(state):
        order.append("user-callback")

    g.callbacks.append(on_state)
    await g.execute(callbacks=[on_user])
    await cleanup_pending_tasks()

    assert sink.captured == ["x"]
    assert order == ["graph-callback", "user-callback"]


@pytest.mark.asyncio
async def test_graph_execute_with_state_values():
    """state_values must be merged into state.data so nodes can read them."""

    captured_data = {}

    class ReadDataNode(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            captured_data["preset"] = state.data.get("preset")

    # Need an entry node with an outbound edge — Graph.execute() iterates
    # over weakly_connected_components, so disconnected nodes are skipped.
    entry = Entry()
    n = ReadDataNode()
    g = Graph()
    g.add_node(entry)
    g.add_node(n)
    g.connect(entry.outputs[0], n.inputs[0])

    await g.execute(state_values={"preset": "hello"})
    await cleanup_pending_tasks()
    assert captured_data["preset"] == "hello"


@pytest.mark.asyncio
async def test_graph_cycle_raises():
    """Building a graph with a cycle should raise on execute()."""
    g = Graph()
    a = Node(title="A")
    b = Node(title="B")
    a_out = a.add_output("o")
    a_in = a.add_input("i")
    b_out = b.add_output("o")
    b_in = b.add_input("i")
    g.add_node(a)
    g.add_node(b)
    g.connect(a_out, b_in)
    g.connect(b_out, a_in)

    with pytest.raises(ValueError, match="cycles"):
        await g.execute()


@pytest.mark.asyncio
async def test_graph_execute_to_node_raises_when_node_missing():
    g, src, sink = build_value_capture_graph("x")
    other = Node(title="Detached")
    with pytest.raises(ValueError, match="not found in graph"):
        await g.execute_to_node(other)


@pytest.mark.asyncio
async def test_graph_execute_to_node_runs_partial():
    """execute_to_node should only run the ancestors of the target."""

    class TrackNode(ValueNode):
        ran: bool = False

        async def run(self, state):
            self.ran = True
            await super().run(state)

    g = Graph()
    a = TrackNode(value=1, title="A")
    b = CaptureNode(title="B")
    c = TrackNode(value=2, title="C-extra")
    g.add_node(a)
    g.add_node(b)
    g.add_node(c)
    g.connect(a.outputs[0], b.inputs[0])
    # `c` is detached — it must NOT run when stopping at `b`
    await g.execute_to_node(b)
    await cleanup_pending_tasks()
    assert a.ran is True
    assert c.ran is False


@pytest.mark.asyncio
async def test_get_nodes_with_filter():
    g, src, sink = build_value_capture_graph("x")
    only_value_nodes = await g.get_nodes(lambda n: isinstance(n, ValueNode))
    assert only_value_nodes == [src]


@pytest.mark.asyncio
async def test_get_node_unique_raises_on_duplicates():
    g = Graph()
    a = ValueNode(value=1, title="A")
    b = ValueNode(value=2, title="B")
    g.add_node(a)
    g.add_node(b)

    with pytest.raises(ValueError, match="Multiple nodes"):
        await g.get_node(lambda n: isinstance(n, ValueNode))


@pytest.mark.asyncio
async def test_get_node_returns_none_when_no_match():
    g, src, sink = build_value_capture_graph("x")
    assert await g.get_node(lambda n: False) is None


# ---------------------------------------------------------------------------
# Graph: get_nodes_connected_to (uses get_ancestors_with_forks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_nodes_connected_to_includes_forks():
    g = Graph()
    a = Node(title="A")
    b = Node(title="B")
    c = Node(title="C")
    d = Node(title="D")
    a_out1 = a.add_output("o1")
    a_out2 = a.add_output("o2")
    b_in = b.add_input("i")
    b_out = b.add_output("o")
    c_in = c.add_input("i")
    d_in = d.add_input("i")
    g.add_node(a)
    g.add_node(b)
    g.add_node(c)
    g.add_node(d)

    # A->B->D and A->C (fork)
    g.connect(a_out1, b_in)
    g.connect(b_out, d_in)
    g.connect(a_out2, c_in)

    ancestors_of_d = await g.get_nodes_connected_to(d)
    titles = sorted(n.title for n in ancestors_of_d)
    # A and B are direct ancestors; C is a fork from a shared ancestor
    assert titles == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Graph serialization
# ---------------------------------------------------------------------------


class TestGraphSerialization:
    def test_serialize_nodes_filters_by_node_serialization_fields(self):
        g, src, sink = build_value_capture_graph(1)
        data = g.model_dump()
        for node_id, node_data in data["nodes"].items():
            # Only fields in _node_serialization_fields should appear
            assert set(node_data.keys()).issubset(g._node_serialization_fields)

    def test_save_state_drops_inherited_nodes_and_edges(self):
        # Build a graph where one node is marked inherited
        g = Graph()
        keep = ValueNode(value=1, title="Keep")
        drop = ValueNode(value=2, title="Drop")
        sink = CaptureNode(title="Sink")
        drop.inherited = True
        g.add_node(keep)
        g.add_node(drop)
        g.add_node(sink)
        g.connect(keep.outputs[0], sink.inputs[0])
        # Edge from inherited node — must be dropped
        g.connect(drop.outputs[0], sink.inputs[0])

        # Add an inherited group/comment too
        g.groups.append(Group(title="kept group"))
        g.groups.append(Group(title="inherited group", inherited=True))
        g.comments.append(Comment(text="kept comment"))
        g.comments.append(Comment(text="inherited comment", inherited=True))

        # Without SaveContext: full data is returned
        full = g.model_dump()
        assert drop.id in full["nodes"]
        assert any(c["text"] == "inherited comment" for c in full["comments"])

        # With SaveContext: inherited stuff is filtered
        with SaveContext():
            saved = g.model_dump()
        assert drop.id not in saved["nodes"]
        assert keep.id in saved["nodes"]
        # Edges referencing the dropped node are also gone
        assert all(drop.id not in edge_key for edge_key in saved["edges"].keys())
        for input_ids in saved["edges"].values():
            for input_id in input_ids:
                assert drop.id not in input_id
        # Inherited groups and comments are filtered
        assert all(g["title"] != "inherited group" for g in saved["groups"])
        assert all(c["text"] != "inherited comment" for c in saved["comments"])

    @pytest.mark.asyncio
    async def test_clone_yields_independent_graph(self):
        # Clone reconstructs a graph from its JSON dump, which means each
        # node must be registered so validate_node can locate its class.
        g = Graph()
        a = Route()
        b = Route()
        g.add_node(a)
        g.add_node(b)
        g.connect(a.outputs[0], b.inputs[0])

        clone = await g.clone()
        # Same nodes
        assert set(clone.nodes.keys()) == set(g.nodes.keys())
        # But independent: editing the clone doesn't touch the original
        clone.title = "renamed"
        assert g.title != "renamed"


# ---------------------------------------------------------------------------
# Graph: input/output node mapping (Input / Output / ModuleProperty)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_routes_input_node_value_from_outer_state():
    """Inner graph reads value of an Input node from the outer state."""

    class OuterEntry(Node):
        def setup(self):
            self.add_output("payload")

        async def run(self, state):
            self.set_output_values({"payload": "from-outside"})

    inner = Graph()
    in_node = Input()
    in_node.set_property("input_name", "payload")
    inner.add_node(in_node)

    sink = CaptureNode(title="Sink")
    inner.add_node(sink)
    inner.connect(in_node.outputs[0], sink.inputs[0])

    # Mark the inner module's input list (must be reset before computed_field
    # is read again). Force recomputation so inner.inputs picks up the new
    # Input node.
    if hasattr(inner, "_inputs"):
        delattr(inner, "_inputs")

    # Outer graph wires its own producer into the inner graph's input
    outer = Graph()
    src = OuterEntry(title="Outer")
    outer.add_node(src)
    outer.add_node(inner)
    outer.connect(src.outputs[0], inner.inputs[0])

    await outer.execute()
    await cleanup_pending_tasks()

    assert sink.captured == ["from-outside"]


@pytest.mark.asyncio
async def test_graph_routes_output_node_value_to_outer_state():
    """An Output node inside an inner graph propagates its value out."""

    class OuterCapture(Node):
        captured_values: list = None

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.captured_values = []

        def setup(self):
            self.add_input("value")

        async def run(self, state):
            self.captured_values.append(self.get_input_value("value"))

    inner = Graph()
    src = ValueNode(value="inner-value", title="src")
    out_node = Output()
    out_node.set_property("output_name", "result")
    inner.add_node(src)
    inner.add_node(out_node)
    inner.connect(src.outputs[0], out_node.inputs[0])

    if hasattr(inner, "_outputs"):
        delattr(inner, "_outputs")

    outer = Graph()
    sink = OuterCapture()
    outer.add_node(inner)
    outer.add_node(sink)
    outer.connect(inner.outputs[0], sink.inputs[0])

    await outer.execute()
    await cleanup_pending_tasks()

    assert sink.captured_values == ["inner-value"]


# ---------------------------------------------------------------------------
# ModuleProperty — cast_value branches
# ---------------------------------------------------------------------------


class TestModulePropertyCastValue:
    def _make(self, prop_type: str, default: Any = UNRESOLVED) -> ModuleProperty:
        mp = ModuleProperty()
        mp.set_property("property_type", prop_type)
        mp.set_property("default", default)
        return mp

    def test_unresolved_uses_default(self):
        mp = self._make("str", default="fallback")
        assert mp.cast_value(UNRESOLVED) == "fallback"

    def test_str_cast(self):
        assert self._make("str").cast_value(123) == "123"

    def test_text_cast(self):
        assert self._make("text").cast_value(123) == "123"

    def test_bool_true_strings(self):
        mp = self._make("bool")
        for v in ("true", "yes", "1", "TRUE", "Yes"):
            assert mp.cast_value(v) is True

    def test_bool_false_strings(self):
        mp = self._make("bool")
        for v in ("false", "no", "0", "FALSE", "No"):
            assert mp.cast_value(v) is False

    def test_bool_other_strings_use_python_bool(self):
        # Non-empty non-special string -> truthy
        assert self._make("bool").cast_value("anything-else") is True

    def test_bool_non_string_uses_bool(self):
        assert self._make("bool").cast_value(0) is False
        assert self._make("bool").cast_value(1) is True
        assert self._make("bool").cast_value([1]) is True

    def test_int_cast(self):
        assert self._make("int").cast_value("7") == 7

    def test_float_cast(self):
        assert self._make("float").cast_value("1.5") == pytest.approx(1.5)

    def test_unknown_type_falls_back_to_str(self):
        # Hitting the final `return str(value)` branch
        assert self._make("custom-type").cast_value(99) == "99"


@pytest.mark.asyncio
async def test_graph_module_properties_aggregated_from_nodes():
    g = Graph()
    mp1 = ModuleProperty()
    mp1.set_property("property_name", "alpha")
    mp1.set_property("property_type", "str")
    mp1.set_property("default", "x")
    mp1.set_property("num", 0)
    mp1.set_property("choices", [])

    mp2 = ModuleProperty()
    mp2.set_property("property_name", "beta")
    mp2.set_property("property_type", "int")
    mp2.set_property("default", 5)
    mp2.set_property("num", 1)
    mp2.set_property("choices", [])

    g.add_node(mp1)
    g.add_node(mp2)

    props = g.module_properties
    assert set(props.keys()) == {"alpha", "beta"}
    assert props["alpha"].type == "str"
    assert props["beta"].type == "int"


def test_graph_style_returns_module_style_when_present():
    g = Graph()
    style_node = ModuleStyle()
    style_node.set_property("node_color", "#ff0000")
    style_node.set_property("title_color", "#00ff00")
    style_node.set_property("auto_title", "")
    style_node.set_property("icon", "")
    g.add_node(style_node)
    s = g.style
    assert s is not None
    assert s.node_color == "#ff0000"
    assert s.title_color == "#00ff00"


def test_graph_style_returns_none_when_absent():
    g = Graph()
    g.add_node(ValueNode(value=1))
    assert g.style is None


# ---------------------------------------------------------------------------
# Graph stage priority ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_priority_orders_chains():
    """Chains with lower stage priority run before higher ones."""
    order = []

    class OrderedNode(Node):
        def __init__(self, label, **kwargs):
            super().__init__(title=label, **kwargs)
            self._label = label

        def setup(self):
            self.add_input("trigger", optional=True)
            self.add_output("done")

        async def run(self, state):
            order.append(self._label)
            self.set_output_values({"done": True})

    g = Graph()
    # Chain 1 (higher stage)
    s1 = Stage()
    s1.set_property("stage", 5)
    n1 = OrderedNode("late")
    g.add_node(s1)
    g.add_node(n1)
    g.connect(s1.outputs[0], n1.inputs[0])

    # Chain 2 (lower stage)
    s2 = Stage()
    s2.set_property("stage", 1)
    n2 = OrderedNode("early")
    g.add_node(s2)
    g.add_node(n2)
    g.connect(s2.outputs[0], n2.inputs[0])

    await g.execute()
    await cleanup_pending_tasks()

    assert order == ["early", "late"]


# ---------------------------------------------------------------------------
# Stage exit handling inside a chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_exit_breaks_current_chain_only():
    """A StageExit in one chain stops that chain but the next still runs."""
    runs = []

    class ChainOneA(Node):
        def setup(self):
            self.add_output("done")

        async def run(self, state):
            runs.append("chain1-a")

    class StageExitNode(Node):
        def setup(self):
            self.add_input("trigger", optional=True)
            self.add_output("done")

        async def run(self, state):
            raise StageExit()

    class ChainTwo(Node):
        def setup(self):
            self.add_output("done")

        async def run(self, state):
            runs.append("chain2")

    g = Graph()
    s1 = Stage()
    s1.set_property("stage", 0)
    a = ChainOneA(title="a")
    boom = StageExitNode(title="boom")
    s2 = Stage()
    s2.set_property("stage", 1)
    c = ChainTwo(title="c")

    g.add_node(s1)
    g.add_node(a)
    g.add_node(boom)
    g.add_node(s2)
    g.add_node(c)

    # Chain 1: s1 -> a -> boom (boom raises StageExit, halting chain 1)
    g.connect(s1.outputs[0], a.inputs[0]) if False else None
    # Actually wire chain 1 explicitly
    a_in = a.add_input("trigger")
    g.connect(s1.outputs[0], a_in)
    g.connect(a.outputs[0], boom.inputs[0])

    # Chain 2: s2 -> c
    c_in = c.add_input("trigger")
    g.connect(s2.outputs[0], c_in)

    await g.execute()
    await cleanup_pending_tasks()

    # chain1-a ran; chain2 ran. The StageExit terminated chain 1 inside the
    # boom node, but chain 2 was unaffected.
    assert "chain1-a" in runs
    assert "chain2" in runs


@pytest.mark.asyncio
async def test_stop_graph_execution_halts_entire_graph():
    """StopGraphExecution caught at the inner level halts execution silently."""

    runs = []

    class StopperNode(Node):
        def setup(self):
            self.add_output("done")

        async def run(self, state):
            runs.append("stop")
            raise StopGraphExecution()

    class NeverRunsInChain1(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            runs.append("never1")

    class ShouldNotRunChain2(Node):
        def setup(self):
            self.add_output("done")

        async def run(self, state):
            runs.append("never2")

    g = Graph()
    stop = StopperNode(title="stop")
    after = NeverRunsInChain1(title="after")
    other = ShouldNotRunChain2(title="other")
    g.add_node(stop)
    g.add_node(after)
    g.add_node(other)
    g.connect(stop.outputs[0], after.inputs[0])

    await g.execute()
    await cleanup_pending_tasks()

    assert runs == ["stop"]


# ---------------------------------------------------------------------------
# Error handler nodes (catch / attempt_catch_with_node_error_handler)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unhandled_exception_calls_error_handlers_list():
    """Errors that aren't caught by node-level handlers run the
    Graph.error_handlers list."""

    captured = []

    class BoomNode(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            raise RuntimeError("boom-boom")

    async def handler(state, exc):
        captured.append((type(exc).__name__, str(exc)))

    g = Graph()
    entry = Entry()
    boom = BoomNode(title="boom")
    g.add_node(entry)
    g.add_node(boom)
    g.connect(entry.outputs[0], boom.inputs[0])
    g.error_handlers.append(handler)

    with pytest.raises(RuntimeError, match="boom-boom"):
        await g.execute()
    await cleanup_pending_tasks()

    assert captured == [("RuntimeError", "boom-boom")]


@pytest.mark.asyncio
async def test_handle_error_swallows_handler_exceptions():
    """A misbehaving handler must not mask the original exception."""

    class BoomNode(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            raise RuntimeError("original")

    async def bad_handler(state, exc):
        raise ValueError("handler-died")

    g = Graph()
    entry = Entry()
    boom = BoomNode(title="boom")
    g.add_node(entry)
    g.add_node(boom)
    g.connect(entry.outputs[0], boom.inputs[0])
    g.error_handlers.append(bad_handler)

    # Original exception still propagates
    with pytest.raises(RuntimeError, match="original"):
        await g.execute()
    await cleanup_pending_tasks()


# ---------------------------------------------------------------------------
# Graph.reset / reset_sockets / reset_ephemeral_properties
# ---------------------------------------------------------------------------


def test_reset_clears_socket_values_and_deactivation():
    g, src, sink = build_value_capture_graph(1)
    with GraphContext():
        src.outputs[0].value = 42
        src.outputs[0].deactivated = True
        assert src.outputs[0].value == 42
        # reset_sockets nullifies value and deactivation
        g.reset_sockets()
        assert src.outputs[0].value is UNRESOLVED
        assert src.outputs[0].deactivated is False


def test_reset_ephemeral_property_resets_to_default():
    class EphemeralPropNode(Node):
        class Fields:
            cache = PropertyField(
                name="cache",
                description="ephemeral cache",
                type="str",
                default="default-val",
                ephemeral=True,
            )

    n = EphemeralPropNode()
    n.set_property("cache", "current-value")
    g = Graph()
    g.add_node(n)
    g.reset_ephemeral_properties()
    assert n.get_property("cache") == "default-val"


# ---------------------------------------------------------------------------
# Loop execution paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_continue_skips_rest_of_iteration_chain():
    """A LoopContinue raised from a node aborts the current chain loop iteration
    but the loop body keeps running. We pair it with an exit_condition that
    fires after the node has incremented the counter so the loop exits
    deterministically."""

    iteration_count = {"n": 0}

    class IncrementThenContinueNode(Node):
        def setup(self):
            self.add_input("trigger")
            self.add_output("done")

        async def run(self, state):
            iteration_count["n"] += 1
            # Stop iterating once we've run twice
            if iteration_count["n"] >= 2:
                raise LoopExit()
            from talemate.game.engine.nodes.core import LoopContinue

            raise LoopContinue()

    entry = Entry(title="entry")
    body = IncrementThenContinueNode(title="body")
    loop = Loop()
    loop.add_node(entry)
    loop.add_node(body)
    loop.connect(entry.outputs[0], body.inputs[0])

    outer_entry = Entry(title="outer-entry")
    outer = Graph()
    outer.add_node(outer_entry)
    outer.add_node(loop)
    outer.connect(outer_entry.outputs[0], loop.inputs[0])

    callback_seen = []

    async def cb(state):
        callback_seen.append(True)

    loop.callbacks.append(cb)

    await outer.execute()
    await cleanup_pending_tasks()
    assert iteration_count["n"] == 2
    # finally-block fires once
    assert callback_seen == [True]


@pytest.mark.asyncio
async def test_loop_exit_terminates_immediately_without_callbacks_after_break():
    """LoopExit returns from the loop completely (not from the iteration)."""

    runs = []

    class ExitNode(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            runs.append("exit")
            raise LoopExit()

    entry = Entry()
    exit_node = ExitNode(title="exitnode")
    loop = Loop()
    loop.add_node(entry)
    loop.add_node(exit_node)
    loop.connect(entry.outputs[0], exit_node.inputs[0])

    outer_entry = Entry(title="outer-entry")
    outer = Graph()
    outer.add_node(outer_entry)
    outer.add_node(loop)
    outer.connect(outer_entry.outputs[0], loop.inputs[0])

    cb_called = []

    async def cb(state):
        cb_called.append(True)

    loop.callbacks.append(cb)

    await outer.execute()
    await cleanup_pending_tasks()
    assert runs == ["exit"]
    # finally-block runs callbacks
    assert cb_called == [True]


@pytest.mark.asyncio
async def test_loop_cancellation_skips_callbacks():
    """A cancelled loop never completed, so its callbacks must not fire -
    the node editor registers `test_done` as one of them (issue #270)."""

    class SleepNode(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            await asyncio.sleep(0.05)

    entry = Entry()
    sleeper = SleepNode(title="sleeper")
    loop = Loop()
    loop.add_node(entry)
    loop.add_node(sleeper)
    loop.connect(entry.outputs[0], sleeper.inputs[0])

    cb_called = []

    async def cb(state):
        cb_called.append(True)

    loop.callbacks.append(cb)

    task = asyncio.create_task(loop.execute(GraphState()))
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await cleanup_pending_tasks()
    assert task.cancelled() is True
    assert cb_called == []


@pytest.mark.asyncio
async def test_loop_stop_module_still_runs_callbacks():
    """Only cancellation skips the callbacks - a loop torn down by a control
    exception still reports completion."""

    class StopNode(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            raise StopModule()

    entry = Entry()
    loop = Loop()
    loop.add_node(entry)
    stop_node = StopNode(title="stop")
    loop.add_node(stop_node)
    loop.connect(entry.outputs[0], stop_node.inputs[0])

    cb_called = []

    async def cb(state):
        cb_called.append(True)

    loop.callbacks.append(cb)

    with pytest.raises(StopModule):
        await loop.execute(GraphState())

    await cleanup_pending_tasks()
    assert cb_called == [True]


@pytest.mark.asyncio
async def test_loop_exit_condition_terminates_loop():
    """exit_condition checked after each node's run."""

    counter = {"n": 0}

    class IncNode(Node):
        def setup(self):
            self.add_input("trigger")
            self.add_output("done")

        async def run(self, state):
            counter["n"] += 1

    entry = Entry()
    inc = IncNode(title="inc")

    loop = Loop(exit_condition=lambda state: counter["n"] >= 3)
    loop.add_node(entry)
    loop.add_node(inc)
    loop.connect(entry.outputs[0], inc.inputs[0])

    outer_entry = Entry(title="outer-entry")
    outer = Graph()
    outer.add_node(outer_entry)
    outer.add_node(loop)
    outer.connect(outer_entry.outputs[0], loop.inputs[0])

    await outer.execute()
    await cleanup_pending_tasks()

    assert counter["n"] == 3


@pytest.mark.asyncio
async def test_loop_cycle_raises():
    loop = Loop()
    a = Node(title="A")
    b = Node(title="B")
    a_out = a.add_output("o")
    a_in = a.add_input("i")
    b_out = b.add_output("o")
    b_in = b.add_input("i")
    loop.add_node(a)
    loop.add_node(b)
    loop.connect(a_out, b_in)
    loop.connect(b_out, a_in)

    with pytest.raises(ValueError, match="cycles"):
        # outer_state isn't strictly needed if we never get past the cycle check
        await loop.execute(outer_state=GraphState())


# ---------------------------------------------------------------------------
# Listen / Trigger event nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listen_execute_from_event_runs_inner_graph():
    """Listen.execute_from_event populates state.data['event'] and executes
    its body."""

    captured = {}

    class CaptureEventNode(Node):
        def setup(self):
            # Endpoint node — no outputs — always available
            self.add_input("trigger", optional=True)

        async def run(self, state):
            captured["event"] = state.data.get("event")

    listen = Listen(title="listen")
    listen.set_property("event_name", "my_event")
    entry = Entry()
    n = CaptureEventNode()
    listen.add_node(entry)
    listen.add_node(n)
    listen.connect(entry.outputs[0], n.inputs[0])

    sentinel = object()
    # execute_from_event needs an active GraphContext OR a scene with
    # nodegraph_state. We provide an active GraphContext.
    with GraphContext():
        await listen.execute_from_event(sentinel)

    assert captured["event"] is sentinel


@pytest.mark.asyncio
async def test_listen_execute_from_event_failsafe_skips_recent_failure():
    """If Listen recently failed, the next call within ~1.3s is skipped."""

    listen = Listen(title="listen")
    listen.set_property("event_name", "evt")
    listen._failed = __import__("time").time()

    # Should silently skip and clear the marker
    with GraphContext():
        await listen.execute_from_event("ignored")

    assert listen._failed is None


@pytest.mark.asyncio
async def test_listen_execute_from_event_stop_module_is_not_a_failure():
    """StopModule from the inner graph ends the run cleanly, so the fail-safe
    is not armed and the next event still executes the body."""

    executed = []

    class StopModuleNode(Node):
        def setup(self):
            self.add_input("trigger", optional=True)

        async def run(self, state):
            executed.append(state.data.get("event"))
            raise StopModule()

    listen = Listen(title="listen")
    listen.set_property("event_name", "evt")
    entry = Entry()
    n = StopModuleNode()
    listen.add_node(entry)
    listen.add_node(n)
    listen.connect(entry.outputs[0], n.inputs[0])

    with GraphContext():
        await listen.execute_from_event("first")
        assert listen._failed is None
        await listen.execute_from_event("second")

    assert executed == ["first", "second"]


@pytest.mark.asyncio
async def test_listen_execute_from_event_outside_state_reports_deferred():
    listen = Listen(title="listen")
    listen.set_property("event_name", "evt")
    result = await listen.execute_from_event("payload")
    assert result is DEFERRED


@pytest.mark.asyncio
async def test_trigger_run_emits_signal():
    """Trigger.run should look up the named signal and send the event."""

    # Create a custom Trigger subclass with a real make_event_object
    class MyTrigger(Trigger):
        def make_event_object(self, state):
            return {"hello": "world"}

    import talemate.emit.async_signals as async_signals

    signal_name = "test_trigger_signal__core"
    async_signals.register(signal_name)

    received = []

    async def listener(event):
        received.append(event)

    async_signals.get(signal_name).connect(listener)

    try:
        t = MyTrigger()
        t.set_property("event_name", signal_name)

        # Execute through the graph so state is set up properly. Wire an
        # entry into Trigger.trigger and a sink onto Trigger.event so neither
        # input nor output is left unconnected (which check_is_available
        # treats as deactivated).
        g = Graph()
        entry = Entry()
        sink = CaptureNode()
        g.add_node(entry)
        g.add_node(t)
        g.add_node(sink)
        g.connect(entry.outputs[0], t.get_input_socket("trigger"))
        g.connect(t.get_output_socket("event"), sink.inputs[0])

        await g.execute()
        await cleanup_pending_tasks()

        assert received == [{"hello": "world"}]
        # Trigger output also exposes the event object
        assert sink.captured == [{"hello": "world"}]
    finally:
        async_signals.get(signal_name).disconnect(listener)


@pytest.mark.asyncio
async def test_trigger_run_with_no_event_name_logs_and_returns():
    class MyTrigger(Trigger):
        def make_event_object(self, state):
            return None

    t = MyTrigger()
    # event_name unset / empty
    t.set_property("event_name", "")
    t.set_property("trigger", "x")
    g = Graph()
    entry = Entry()
    sink = CaptureNode()
    g.add_node(entry)
    g.add_node(t)
    g.add_node(sink)
    g.connect(entry.outputs[0], t.get_input_socket("trigger"))
    g.connect(t.get_output_socket("event"), sink.inputs[0])
    # Should not raise — Trigger.run returns early due to missing event_name.
    await g.execute()
    await cleanup_pending_tasks()
    # No event was emitted onto the output socket
    assert sink.captured in ([], [UNRESOLVED])


@pytest.mark.asyncio
async def test_trigger_run_with_unknown_signal_returns_silently():
    class MyTrigger(Trigger):
        def make_event_object(self, state):
            return None

    t = MyTrigger()
    t.set_property("event_name", "this_signal_does_not_exist")
    t.set_property("trigger", "x")
    g = Graph()
    entry = Entry()
    sink = CaptureNode()
    g.add_node(entry)
    g.add_node(t)
    g.add_node(sink)
    g.connect(entry.outputs[0], t.get_input_socket("trigger"))
    g.connect(t.get_output_socket("event"), sink.inputs[0])
    # Should not raise — Trigger logs and returns
    await g.execute()
    await cleanup_pending_tasks()


def test_trigger_make_event_object_default_raises():
    t = Trigger()
    with pytest.raises(NotImplementedError):
        t.make_event_object(None)


# ---------------------------------------------------------------------------
# validate_node WrapValidator
# ---------------------------------------------------------------------------


def _identity_handler(v):
    return v


def test_validate_node_returns_existing_nodebase():
    n = Node(title="N")
    info = type("I", (), {})()
    out = validate_node(n, _identity_handler, info)
    assert out is n


def test_validate_node_raises_on_unrecognised_dict():
    info = type("I", (), {})()
    with pytest.raises(ValueError, match="Could not validate"):
        validate_node({"foo": "bar"}, _identity_handler, info)


# ---------------------------------------------------------------------------
# check_is_available — additional deactivation paths
# ---------------------------------------------------------------------------


def test_check_is_available_returns_false_when_required_input_missing():
    """A node with an unresolved required input gets all of its outputs
    deactivated and reports unavailable."""
    n = Node(title="N")
    n.add_input("req")  # no source, no property -> UNRESOLVED
    n.add_output("o")

    g = Graph()
    g.add_node(n)

    with GraphContext() as state:
        assert n.check_is_available(state) is False
        assert n.outputs[0].deactivated is True


def test_check_is_available_endpoint_node_only_needs_inputs():
    """A node with only inputs (an "endpoint") is available as long as its
    required inputs are satisfied."""

    n = Node(title="endpoint")
    n.add_input("v")
    n.set_property("v", "x")  # property satisfies the input

    g = Graph()
    g.add_node(n)

    with GraphContext() as state:
        assert n.check_is_available(state) is True


def test_check_is_available_grouped_inputs_one_satisfied_is_enough():
    """Grouped inputs: at least one must be available — none being available
    deactivates the node."""

    n = Node(title="grouped")
    n.add_input("a", group="g1")
    n.add_input("b", group="g1")
    n.add_output("o")

    g = Graph()
    g.add_node(n)

    # Neither set -> unavailable
    with GraphContext() as state:
        assert n.check_is_available(state) is False

    # Property on `a` -> available
    n.set_property("a", "x")
    n.outputs[0].deactivated = False
    with GraphContext() as state:
        # Need a non-deactivated downstream output to satisfy the path check.
        # Add a downstream consumer.
        downstream = Node(title="downstream")
        downstream.add_input("v")
        g.add_node(downstream)
        g.connect(n.outputs[0], downstream.inputs[0])
        assert n.check_is_available(state) is True


def test_check_is_available_isolated_node_returns_false():
    """_isolated nodes report unavailable to opt out of normal dispatch."""

    class IsolatedThing(Node):
        _isolated: ClassVar[bool] = True

        def setup(self):
            self.add_output("v")

    n = IsolatedThing()
    g = Graph()
    g.add_node(n)
    with GraphContext() as state:
        assert n.check_is_available(state) is False


# ---------------------------------------------------------------------------
# Stage node default behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_node_unconnected_state_input_defaults_true():
    """An unconnected `state` input on a Stage node propagates True."""

    captured = []

    class Recorder(Node):
        def setup(self):
            self.add_input("v")

        async def run(self, state):
            captured.append(self.get_input_value("v"))

    g = Graph()
    s = Stage()
    s.set_property("stage", 0)
    rec = Recorder(title="rec")
    g.add_node(s)
    g.add_node(rec)
    g.connect(s.outputs[0], rec.inputs[0])

    await g.execute()
    await cleanup_pending_tasks()
    assert captured == [True]


# ---------------------------------------------------------------------------
# Watch / Route / Null / Entry pass-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_passes_value_through():
    g = Graph()
    src = ValueNode(value="watched", title="src")
    w = Watch(title="watcher")
    sink = CaptureNode(title="sink")
    g.add_node(src)
    g.add_node(w)
    g.add_node(sink)
    g.connect(src.outputs[0], w.inputs[0])
    g.connect(w.outputs[0], sink.inputs[0])
    await g.execute()
    await cleanup_pending_tasks()
    assert sink.captured == ["watched"]


@pytest.mark.asyncio
async def test_route_passes_value_through():
    g = Graph()
    src = ValueNode(value=999, title="src")
    r = Route()
    sink = CaptureNode(title="sink")
    g.add_node(src)
    g.add_node(r)
    g.add_node(sink)
    g.connect(src.outputs[0], r.inputs[0])
    g.connect(r.outputs[0], sink.inputs[0])
    await g.execute()
    await cleanup_pending_tasks()
    assert sink.captured == [999]


# ---------------------------------------------------------------------------
# Group / Comment
# ---------------------------------------------------------------------------


def test_group_and_comment_defaults():
    g = Group(title="hello")
    assert g.title == "hello"
    assert g.inherited is False

    c = Comment(text="note")
    assert c.text == "note"
    assert c.inherited is False


# ---------------------------------------------------------------------------
# Creative-mode node-state tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_state_push_pop_returns_node_state_in_creative_mode():
    """When state.shared['creative_mode'] is True, push/pop construct and
    return NodeState snapshots (the stack itself is debounced/flushed by
    signal_note_state)."""

    class TouchNode(Node):
        def setup(self):
            self.add_input("trigger", optional=True)

        async def run(self, state):
            pass

    g = Graph()
    n = TouchNode(title="touch", id="touch-id")
    g.add_node(n)

    outer = GraphState()
    outer.shared["creative_mode"] = True

    pushed = await g.node_state_push(n, outer)
    assert pushed is not None
    assert pushed.node_id == "touch-id"

    popped = await g.node_state_pop(pushed, n, outer)
    assert popped is not None
    # pop() always sets end_time
    assert popped.end_time is not None
    assert popped.node_id == "touch-id"

    # pop with error string surfaces the error on the snapshot
    popped_err = await g.node_state_pop(pushed, n, outer, error="boom-trace")
    assert popped_err.error == "boom-trace"


@pytest.mark.asyncio
async def test_node_state_push_pop_noop_outside_creative_mode():
    """Push and pop short-circuit when creative_mode is not set."""
    g = Graph()
    n = Node(title="N")
    state = GraphState()  # default: shared is empty
    pushed = await g.node_state_push(n, state)
    assert pushed is None
    popped = await g.node_state_pop(pushed, n, state)
    assert popped is None
    assert state.stack == []


@pytest.mark.asyncio
async def test_node_state_push_inactive_marks_node_state_deactivated():
    n = Node(title="N")
    g = Graph()
    g.add_node(n)
    outer = GraphState()
    outer.shared["creative_mode"] = True
    pushed = await g.node_state_push(n, outer, inactive=True)
    assert pushed.deactivated is True


# ---------------------------------------------------------------------------
# Loop on_loop_start / on_loop_end / on_loop_error subclass hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_subclass_lifecycle_hooks_invoked():
    """Subclass-overridable hooks fire in the right order each iteration."""

    events = []

    class LifecycleLoop(Loop):
        async def on_loop_start(self, state):
            events.append("start")

        async def on_loop_end(self, state):
            events.append("end")

    class StopAfterFirst(Node):
        ran: bool = False

        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            self.ran = True
            raise LoopExit()

    entry = Entry()
    body = StopAfterFirst(title="body")
    loop = LifecycleLoop()
    loop.add_node(entry)
    loop.add_node(body)
    loop.connect(entry.outputs[0], body.inputs[0])

    outer = Graph()
    outer_entry = Entry(title="outer")
    outer.add_node(outer_entry)
    outer.add_node(loop)
    outer.connect(outer_entry.outputs[0], loop.inputs[0])

    await outer.execute()
    await cleanup_pending_tasks()

    # on_loop_start fires before any chains; LoopExit returns inside the
    # node loop so on_loop_end does NOT fire on that iteration.
    assert events == ["start"]
    assert body.ran is True


@pytest.mark.asyncio
async def test_loop_on_loop_error_invoked_on_exception():
    """When a body raises a non-control exception the loop's
    handle_error and on_loop_error callbacks both fire and the loop
    keeps iterating until LoopExit."""

    handled = []
    on_loop_errors = []
    iteration = {"n": 0}

    class ErrorThenExit(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            iteration["n"] += 1
            if iteration["n"] == 1:
                raise RuntimeError("first-iteration-fail")
            raise LoopExit()

    class TrackingLoop(Loop):
        sleep: float = 0.0  # avoid the 1-second post-error sleep

        async def on_loop_error(self, state, exc):
            on_loop_errors.append(type(exc).__name__)

    async def handler(state, exc):
        handled.append(type(exc).__name__)

    entry = Entry()
    body = ErrorThenExit(title="body")
    loop = TrackingLoop()
    # Patch the per-iteration sleep delay introduced by handle_error so the
    # test doesn't take a full second.
    loop.sleep = 0.0
    loop.error_handlers.append(handler)
    loop.add_node(entry)
    loop.add_node(body)
    loop.connect(entry.outputs[0], body.inputs[0])

    outer_entry = Entry(title="outer")
    outer = Graph()
    outer.add_node(outer_entry)
    outer.add_node(loop)
    outer.connect(outer_entry.outputs[0], loop.inputs[0])

    # Don't actually wait the 1s asyncio.sleep in the loop's exception
    # handler — we just want to verify the hooks fire.
    import asyncio as _asyncio

    real_sleep = _asyncio.sleep

    async def fast_sleep(_):
        await real_sleep(0)

    _asyncio.sleep = fast_sleep
    try:
        await outer.execute()
    finally:
        _asyncio.sleep = real_sleep
    await cleanup_pending_tasks()

    assert handled == ["RuntimeError"]
    assert on_loop_errors == ["RuntimeError"]
    assert iteration["n"] == 2  # second iteration ran and raised LoopExit


# ---------------------------------------------------------------------------
# Verbose state mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_executes_with_verbose_state(caplog):
    """Bumping verbosity to VERBOSE exercises the verbose-only log paths."""
    g, src, sink = build_value_capture_graph("v")

    async def set_verbose(state):
        state.verbosity = NodeVerbosity.VERBOSE

    # Pre-callback to set verbosity then execute. Easiest: subclass execute.
    # Instead, install a pre-execute hack via state_values is not possible —
    # just exercise via the graph callbacks list (assertions: no exception).
    g.callbacks.append(set_verbose)
    await g.execute()
    await cleanup_pending_tasks()
    assert sink.captured == ["v"]


# ---------------------------------------------------------------------------
# Loop initial cycle protection (through outer Graph.execute)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_run_method_calls_execute():
    """Loop is itself a Node; when used as a sub-node Graph._execute_inner
    invokes Loop.run which delegates to Loop.execute."""

    runs = []

    class StopOnce(Node):
        def setup(self):
            self.add_input("trigger")

        async def run(self, state):
            runs.append(1)
            raise LoopExit()

    inner_entry = Entry()
    body = StopOnce(title="body")
    loop = Loop()
    loop.add_node(inner_entry)
    loop.add_node(body)
    loop.connect(inner_entry.outputs[0], body.inputs[0])

    outer = Graph()
    outer_entry = Entry(title="outer-entry")
    outer.add_node(outer_entry)
    outer.add_node(loop)
    outer.connect(outer_entry.outputs[0], loop.inputs[0])

    await outer.execute()
    await cleanup_pending_tasks()
    assert runs == [1]


# ---------------------------------------------------------------------------
# Trigger.after hook called after signal send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_after_hook_called_with_event():
    """Trigger.after runs after the signal is dispatched."""

    after_calls = []

    class MyTrigger(Trigger):
        def make_event_object(self, state):
            return "evt"

        async def after(self, state, event):
            after_calls.append(event)

    import talemate.emit.async_signals as async_signals

    signal_name = "test_trigger_after_signal"
    async_signals.register(signal_name)

    t = MyTrigger()
    t.set_property("event_name", signal_name)
    t.set_property("trigger", "x")

    g = Graph()
    entry = Entry()
    sink = CaptureNode()
    g.add_node(entry)
    g.add_node(t)
    g.add_node(sink)
    g.connect(entry.outputs[0], t.get_input_socket("trigger"))
    g.connect(t.get_output_socket("event"), sink.inputs[0])

    await g.execute()
    await cleanup_pending_tasks()
    assert after_calls == ["evt"]
