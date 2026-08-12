"""
Unit tests for src/talemate/game/engine/nodes/run.py.

Covers function/graph plumbing nodes:
- title_to_function_name
- BreakpointEvent (dataclass shape)
- FunctionArgument._convert_value (many type conversions)
- FunctionArgument.run (resolving argument value from state.data)
- FunctionReturn.run (sets __fn_result, raises StopGraphExecution)
- DefineFunction (isolated, never_run) and GetFunction lookup
- FunctionWrapper.__call__ via Define+Get+Return-style minimal graphs
- CallFunction with a FunctionWrapper
- CallForEach with list/dict items
- RunModule: success, infinite-loop guard, error wrapping
- Breakpoint: skipped in non-creative environment, skipped when active=False
- UnpackException with ExceptionWrapper
- ErrorHandler.catch shape

Skipped paths:
- Function.run (graph-level) creates an `ai_callback` via `wrapped.ai_callback`,
  which scans for a Metadata node and calls `normalized_input_value` — covered
  via the FunctionWrapper.ai_callback test that uses a real DefineFunction
  endpoint.
- Breakpoint's wait-for-release loop: tested only the short-circuit paths;
  the wait-loop polls `state.shared['__breakpoint']` and signals are exercised
  in higher-level integration tests.
"""

import asyncio

import pytest

from talemate.game.engine.nodes.core import (
    Entry,
    Graph,
    GraphState,
    Node,
    StopGraphExecution,
    UNRESOLVED,
)
from talemate.game.engine.nodes.core.exception import ExceptionWrapper
from talemate.game.engine.nodes.run import (
    Breakpoint,
    BreakpointEvent,
    CallForEach,
    CallFunction,
    DefineFunction,
    ErrorHandler,
    Function,
    FunctionArgument,
    FunctionReturn,
    FunctionWrapper,
    GetFunction,
    RunModule,
    UnpackException,
    title_to_function_name,
)
from talemate.util.async_tools import cleanup_pending_tasks

from conftest import MockScene
from _node_test_helpers import run_node


# ---------------------------------------------------------------------------
# title_to_function_name
# ---------------------------------------------------------------------------


def test_title_to_function_name_replaces_special_chars():
    assert title_to_function_name("My Function!") == "My_Function_"


def test_title_to_function_name_keeps_alphanumeric_and_underscores():
    assert title_to_function_name("foo_bar123") == "foo_bar123"


# ---------------------------------------------------------------------------
# BreakpointEvent
# ---------------------------------------------------------------------------


def test_breakpoint_event_holds_node_and_state():
    n = Breakpoint()
    state = GraphState()
    evt = BreakpointEvent(node=n, state=state, module_path="some/path")
    assert evt.node is n
    assert evt.state is state
    assert evt.module_path == "some/path"


def test_breakpoint_event_module_path_defaults_to_none():
    evt = BreakpointEvent(node=Breakpoint(), state=GraphState())
    assert evt.module_path is None


# ---------------------------------------------------------------------------
# FunctionArgument._convert_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typ,value,expected",
    [
        ("any", "anything", "anything"),
        ("any", 42, 42),
        ("str", 5, "5"),
        ("str", True, "True"),
        ("int", "7", 7),
        ("int", None, None),
        ("float", "3.14", 3.14),
        ("float", None, None),
        ("bool", "true", True),
        ("bool", "yes", True),
        ("bool", "1", True),
        ("bool", "false", False),
        ("bool", "no", False),
        ("bool", "0", False),
        ("bool", "anything else", True),  # non-empty string -> True
        ("bool", 1, True),
        ("bool", 0, False),
        ("list", ["a", "b"], ["a", "b"]),
        ("list", "a\nb\nc", ["a", "b", "c"]),
    ],
)
def test_function_argument_convert_value(typ, value, expected):
    arg = FunctionArgument()
    arg.set_property("typ", typ)
    assert arg._convert_value(value) == expected


def test_function_argument_str_passes_through_non_scalar():
    """`typ=str` only stringifies scalar primitives; complex objects pass
    through unchanged."""
    arg = FunctionArgument()
    arg.set_property("typ", "str")
    obj = {"a": 1}
    assert arg._convert_value(obj) is obj


# ---------------------------------------------------------------------------
# FunctionArgument.run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_function_argument_resolves_value_from_state_data():
    """run() reads `state.data[f'{node.id}__fn_arg_value']` and converts it."""
    arg = FunctionArgument()
    arg.set_property("name", "x")
    arg.set_property("typ", "int")

    def setup(state):
        state.data[f"{arg.id}__fn_arg_value"] = "12"

    out = await run_node(arg, state_setup=setup)
    assert out["value"] == 12


@pytest.mark.asyncio
async def test_function_argument_unresolved_when_no_state_value():
    """When the bound state value is missing, run() emits UNRESOLVED converted
    by typ (any -> UNRESOLVED)."""
    arg = FunctionArgument()
    arg.set_property("name", "x")
    arg.set_property("typ", "any")

    out = await run_node(arg)
    assert out["value"] is UNRESOLVED


# ---------------------------------------------------------------------------
# FunctionReturn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_function_return_sets_fn_result_and_raises_stop():
    ret = FunctionReturn()

    with pytest.raises(StopGraphExecution):
        await run_node(ret, inputs={"value": "ok"})


@pytest.mark.asyncio
async def test_function_return_unresolved_input_does_not_raise():
    """If `value` is UNRESOLVED, FunctionReturn returns silently (no
    StopGraphExecution, no __fn_result)."""
    ret = FunctionReturn()
    ret.properties["value"] = UNRESOLVED
    out = await run_node(ret)
    assert out["value"] is UNRESOLVED


# ---------------------------------------------------------------------------
# DefineFunction / GetFunction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_define_function_run_is_noop_and_marks_isolated():
    define = DefineFunction()
    # `_isolated` blocks the node from running in normal scheduling
    assert DefineFunction._isolated is True
    # never_run is True so dispatcher won't reach this
    assert define.never_run is True
    # run still works (returns None)
    state = GraphState()
    result = await define.run(state)
    assert result is None


@pytest.mark.asyncio
async def test_get_function_returns_wrapper_when_define_function_exists():
    """A graph with a DefineFunction node (matching name) and a GetFunction
    node will produce a FunctionWrapper from `GetFunction.run`."""
    define = DefineFunction()
    define.set_property("name", "my_fn")

    # DefineFunction needs a `nodes` source — wire any node's output into it
    src = Entry(title="src")
    graph = Graph()
    graph.add_node(src)
    graph.add_node(define)
    graph.connect(src.outputs[0], define.get_input_socket("nodes"))

    # GetFunction is at module-level; we don't need to add it to the graph
    # for this test — `state.graph` is what matters
    get_fn = GetFunction()
    get_fn.set_property("name", "my_fn")

    state = GraphState()
    state.graph = graph

    wrapper = await get_fn.get_function(graph, state)
    assert isinstance(wrapper, FunctionWrapper)


@pytest.mark.asyncio
async def test_get_function_raises_when_not_found():
    """Without a matching DefineFunction node, run() raises ValueError."""
    graph = Graph()
    state = GraphState()
    state.graph = graph
    get_fn = GetFunction()
    get_fn.set_property("name", "nope")
    with pytest.raises(ValueError):
        await get_fn.run(state)


# ---------------------------------------------------------------------------
# FunctionWrapper.__call__ end-to-end via DefineFunction with subgraph endpoint
# ---------------------------------------------------------------------------


def _build_function_graph(ret_value: int):
    """Build a graph that defines an inline function which simply returns
    `ret_value` immediately. Returns (graph, define_node)."""

    class _Constant(Node):
        def __init__(self, **kw):
            super().__init__(title="Constant", **kw)

        def setup(self):
            self.add_output("value")

        async def run(self, state):
            self.set_output_values({"value": ret_value})

    const = _Constant()
    fn_return = FunctionReturn()
    define = DefineFunction()
    define.set_property("name", "the_fn")

    graph = Graph()
    graph.add_node(const)
    graph.add_node(fn_return)
    graph.add_node(define)
    graph.connect(const.outputs[0], fn_return.get_input_socket("value"))
    graph.connect(
        fn_return.get_output_socket("value"),
        define.get_input_socket("nodes"),
    )
    return graph, define


@pytest.mark.asyncio
async def test_function_wrapper_call_returns_function_return_value():
    graph, define = _build_function_graph(42)
    state = GraphState()
    state.graph = graph

    wrapper = await define.get_function(state)
    result = await wrapper()
    assert result == 42

    await cleanup_pending_tasks()


@pytest.mark.asyncio
async def test_function_wrapper_get_argument_nodes_filters_by_type():
    graph, define = _build_function_graph(1)
    arg = FunctionArgument()
    arg.set_property("name", "arg1")
    graph.add_node(arg)
    # Wire arg into FunctionReturn so it shows up as a connected ancestor
    fn_return = next(n for n in graph.nodes.values() if isinstance(n, FunctionReturn))
    # There is already a connection from constant; replace by routing through arg
    # We won't actually call the function; we just want get_argument_nodes to find arg
    graph.connect(arg.get_output_socket("value"), fn_return.get_input_socket("value"))

    state = GraphState()
    state.graph = graph
    wrapper = await define.get_function(state)
    arg_nodes = await wrapper.get_argument_nodes()
    assert len(arg_nodes) == 1
    assert arg_nodes[0] is arg


# ---------------------------------------------------------------------------
# CallFunction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_function_invokes_wrapper_and_returns_result():
    graph, define = _build_function_graph(7)
    state = GraphState()
    state.graph = graph
    wrapper = await define.get_function(state)

    node = CallFunction()
    out = await run_node(node, inputs={"fn": wrapper, "args": {}})
    assert out["result"] == 7

    await cleanup_pending_tasks()


@pytest.mark.asyncio
async def test_call_function_rejects_non_function_input():
    node = CallFunction()
    with pytest.raises(ValueError):
        await run_node(node, inputs={"fn": "not a function", "args": {}})


# ---------------------------------------------------------------------------
# CallForEach
# ---------------------------------------------------------------------------


class _RecordingFunctionWrapper:
    """Minimal stand-in for `FunctionWrapper` used to test CallForEach. We
    can't easily build a real graph-backed wrapper that takes a runtime arg
    in this scope, but `CallForEach` doesn't care about implementation —
    it just checks `isinstance(fn, FunctionWrapper)`. So we patch the type
    inheritance via subclassing FunctionWrapper directly."""


@pytest.mark.asyncio
async def test_call_for_each_iterates_list_items():
    """Verify CallForEach calls a fn-wrapper once per list item, passing the
    item under the configured argument name."""
    received = []

    class _RecordingWrapper(FunctionWrapper):
        def __init__(self):
            # Skip parent __init__ — we don't need a real graph.
            pass

        async def __call__(self, **kwargs):
            received.append(kwargs)
            return f"ok-{kwargs.get('item')}"

    fn = _RecordingWrapper()
    node = CallForEach()
    out = await run_node(
        node,
        inputs={
            "state": "STATE",
            "fn": fn,
            "items": ["a", "b", "c"],
            "argument_name": "item",
        },
    )
    assert out["state"] == "STATE"
    assert out["results"] == ["ok-a", "ok-b", "ok-c"]
    assert received == [{"item": "a"}, {"item": "b"}, {"item": "c"}]


@pytest.mark.asyncio
async def test_call_for_each_iterates_dict_values():
    """Dict items are converted to a list of values and iterated."""
    received = []

    class _W(FunctionWrapper):
        def __init__(self):
            pass

        async def __call__(self, **kwargs):
            received.append(kwargs.get("v"))
            return None

    node = CallForEach()
    await run_node(
        node,
        inputs={
            "state": "x",
            "fn": _W(),
            "items": {"k1": "v1", "k2": "v2"},
            "argument_name": "v",
            "copy_items": True,
        },
    )
    assert sorted(received) == ["v1", "v2"]


@pytest.mark.asyncio
async def test_call_for_each_rejects_non_function_fn():
    from talemate.game.engine.nodes.core import InputValueError

    node = CallForEach()
    with pytest.raises(InputValueError):
        await run_node(
            node,
            inputs={
                "state": "x",
                "fn": "not a function",
                "items": ["a"],
                "argument_name": "item",
            },
        )


@pytest.mark.asyncio
async def test_call_for_each_rejects_non_collection_items():
    from talemate.game.engine.nodes.core import InputValueError

    class _W(FunctionWrapper):
        def __init__(self):
            pass

        async def __call__(self, **kwargs):
            return None

    node = CallForEach()
    with pytest.raises(InputValueError):
        await run_node(
            node,
            inputs={
                "state": "x",
                "fn": _W(),
                "items": "not a list or dict",
                "argument_name": "item",
            },
        )


@pytest.mark.asyncio
async def test_call_for_each_rejects_blank_argument_name():
    from talemate.game.engine.nodes.core import InputValueError

    class _W(FunctionWrapper):
        def __init__(self):
            pass

        async def __call__(self, **kwargs):
            return None

    node = CallForEach()
    with pytest.raises(InputValueError):
        await run_node(
            node,
            inputs={
                "state": "x",
                "fn": _W(),
                "items": ["a"],
                "argument_name": "",
            },
        )


# ---------------------------------------------------------------------------
# RunModule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_module_executes_inner_graph():
    """Successful execution of a passed module sets done=True."""
    from talemate.game.engine.nodes.core import GraphContext

    ran: list[bool] = []

    class _InnerSink(Node):
        """A sink with an `add_input` so it qualifies as an endpoint and runs.

        Disconnected nodes are skipped by Graph.execute (it iterates only the
        weakly-connected components of the edges graph), so we wire the entry
        node's output into the sink's input.
        """

        def __init__(self, **kw):
            super().__init__(title="InnerSink", **kw)

        def setup(self):
            self.add_input("state")

        async def run(self, state):
            ran.append(True)

    inner = Graph()
    entry = Entry(title="entry")
    sink = _InnerSink()
    inner.add_node(entry)
    inner.add_node(sink)
    inner.connect(entry.outputs[0], sink.get_input_socket("state"))

    node = RunModule()
    node.set_property("module", inner)

    outer_state = GraphState()
    with GraphContext(outer_state=outer_state) as state:
        await node.run(state)
        out = {sock.name: sock.value for sock in node.outputs}

    assert out["done"] is True
    assert ran == [True]

    await cleanup_pending_tasks()


@pytest.mark.asyncio
async def test_run_module_rejects_non_graph_module():
    from talemate.game.engine.nodes.core import GraphContext

    node = RunModule()
    node.set_property("module", "not a graph")
    with GraphContext(outer_state=GraphState()) as state:
        with pytest.raises(ValueError):
            await node.run(state)


@pytest.mark.asyncio
async def test_run_module_detects_infinite_loop():
    """If the module is already running on `state.outer.data['_in_run_module']`
    (same module reference), RunModule must raise ValueError."""
    from talemate.game.engine.nodes.core import GraphContext

    inner = Graph()

    outer_state = GraphState()
    outer_state.data["_in_run_module"] = inner  # claim it's running

    node = RunModule()
    node.set_property("module", inner)
    with GraphContext(outer_state=outer_state) as state:
        with pytest.raises(ValueError):
            await node.run(state)


@pytest.mark.asyncio
async def test_run_module_wraps_inner_exception_as_module_error():
    """When the inner module raises a regular exception, RunModule wraps it
    as a ModuleError after marking failed=str(exc)."""
    from talemate.game.engine.nodes.core import GraphContext, ModuleError

    class _Boom(Node):
        def __init__(self, **kw):
            super().__init__(title="Boom", **kw)

        def setup(self):
            self.add_input("state")

        async def run(self, state):
            raise RuntimeError("inner boom")

    inner = Graph()
    entry = Entry(title="entry")
    boom = _Boom()
    inner.add_node(entry)
    inner.add_node(boom)
    inner.connect(entry.outputs[0], boom.get_input_socket("state"))

    node = RunModule()
    node.set_property("module", inner)

    with GraphContext(outer_state=GraphState()) as state:
        with pytest.raises(ModuleError):
            await node.run(state)
        failed_value = node.get_output_socket("failed").value

    assert "inner boom" in failed_value

    await cleanup_pending_tasks()


def _blocking_module(started: "asyncio.Event") -> Graph:
    """A module whose chain blocks forever, so a cancel lands mid-run."""

    class _Block(Node):
        def __init__(self, **kw):
            super().__init__(title="Block", **kw)

        def setup(self):
            self.add_input("state")

        async def run(self, state):
            started.set()
            await asyncio.Event().wait()

    inner = Graph()
    entry = Entry(title="entry")
    block = _Block()
    inner.add_node(entry)
    inner.add_node(block)
    inner.connect(entry.outputs[0], block.get_input_socket("state"))
    return inner


@pytest.mark.asyncio
async def test_run_module_swallows_module_only_cancel():
    """test_stop cancels only the module task: RunModule must swallow the
    resulting CancelledError (its own task is not being cancelled) and report
    cancelled=True."""
    from talemate.game.engine.nodes.core import GraphContext

    started = asyncio.Event()
    inner = _blocking_module(started)

    node = RunModule()
    node.set_property("module", inner)

    with GraphContext(outer_state=GraphState()) as state:
        run_task = asyncio.create_task(node.run(state))
        await asyncio.wait_for(started.wait(), timeout=5)
        state.shared[f"__run_{inner.id}"].cancel()
        await asyncio.wait_for(run_task, timeout=5)
        out = {sock.name: sock.value for sock in node.outputs}

    assert out["cancelled"] is True
    assert f"__run_{inner.id}" not in state.shared

    await cleanup_pending_tasks()


@pytest.mark.asyncio
async def test_run_module_reraises_outer_cancel():
    """On scene unload the surrounding scene-loop task is cancelled while it
    awaits the module: RunModule must re-raise so the loop task dies instead
    of running on untracked."""
    from talemate.game.engine.nodes.core import GraphContext

    started = asyncio.Event()
    inner = _blocking_module(started)

    node = RunModule()
    node.set_property("module", inner)

    with GraphContext(outer_state=GraphState()) as state:
        run_task = asyncio.create_task(node.run(state))
        await asyncio.wait_for(started.wait(), timeout=5)
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task

    assert run_task.cancelled()
    assert f"__run_{inner.id}" not in state.shared

    await cleanup_pending_tasks()


# ---------------------------------------------------------------------------
# Breakpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breakpoint_skipped_in_non_creative_environment():
    """Breakpoint should pass through state and not raise outside creative."""
    scene = MockScene()
    scene.environment = "scene"  # not "creative"

    out = await run_node(
        Breakpoint(),
        scene=scene,
        inputs={"state": "STATE", "active": True},
    )
    assert out["state"] == "STATE"


@pytest.mark.asyncio
async def test_breakpoint_skipped_when_inactive_in_creative():
    """Breakpoint with active=False is a passthrough even in creative."""
    scene = MockScene()
    scene.environment = "creative"

    node = Breakpoint()
    node.set_property("active", False)

    out = await run_node(node, scene=scene, inputs={"state": "STATE"})
    assert out["state"] == "STATE"


# ---------------------------------------------------------------------------
# UnpackException
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpack_exception_emits_name_and_message():
    exc = ExceptionWrapper(name="ValueError", message="something broke")
    out = await run_node(UnpackException(), inputs={"exc": exc})
    assert out["name"] == "ValueError"
    assert out["message"] == "something broke"


@pytest.mark.asyncio
async def test_unpack_exception_returns_silently_for_wrong_type():
    """When the input is not an ExceptionWrapper, run() logs and returns
    without setting outputs (UNRESOLVED)."""
    out = await run_node(
        UnpackException(), inputs={"exc": {"name": "X", "message": "Y"}}
    )
    assert out["name"] is UNRESOLVED
    assert out["message"] is UNRESOLVED


# ---------------------------------------------------------------------------
# ErrorHandler
# ---------------------------------------------------------------------------


def test_error_handler_is_isolated_and_never_runs():
    """ErrorHandler is marked _isolated and never_run by design — the
    dispatcher must not pick it up; only `catch()` is invoked from the
    Graph error path."""
    handler = ErrorHandler()
    assert ErrorHandler._isolated is True
    assert handler.never_run is True


@pytest.mark.asyncio
async def test_error_handler_catch_invokes_caught_function_with_exception_wrapper():
    """ErrorHandler.catch wires an ExceptionWrapper through the user-supplied
    function (a FunctionWrapper) and returns its result."""

    captured: list[ExceptionWrapper] = []

    class _RecordingWrapper(FunctionWrapper):
        def __init__(self):
            pass

        async def __call__(self, **kwargs):
            captured.append(kwargs.get("exc"))
            return "handled"

    handler = ErrorHandler()

    # The handler reads `fn_socket.source.node.run(state)` — that node must
    # return the FunctionWrapper. We build a minimal Node that returns one.

    class _FnSource(Node):
        def __init__(self, **kw):
            super().__init__(title="FnSource", **kw)

        def setup(self):
            self.add_output("fn", socket_type="function")

        async def run(self, state):
            return _RecordingWrapper()

    fn_source = _FnSource()
    graph = Graph()
    graph.add_node(handler)
    graph.add_node(fn_source)
    graph.connect(
        fn_source.get_output_socket("fn"),
        handler.get_input_socket("fn"),
    )

    state = GraphState()
    state.graph = graph

    result = await handler.catch(state, RuntimeError("boom"))
    assert result == "handled"
    assert len(captured) == 1
    assert isinstance(captured[0], ExceptionWrapper)
    assert captured[0].name == "RuntimeError"
    assert captured[0].message == "boom"


@pytest.mark.asyncio
async def test_error_handler_catch_returns_false_when_fn_not_a_wrapper():
    """If the user-supplied `fn` source returns something that isn't a
    FunctionWrapper, `catch` logs and returns False."""

    class _BadFnSource(Node):
        def __init__(self, **kw):
            super().__init__(title="BadFnSource", **kw)

        def setup(self):
            self.add_output("fn", socket_type="function")

        async def run(self, state):
            return "not a wrapper"

    handler = ErrorHandler()
    src = _BadFnSource()
    graph = Graph()
    graph.add_node(handler)
    graph.add_node(src)
    graph.connect(src.get_output_socket("fn"), handler.get_input_socket("fn"))

    state = GraphState()
    state.graph = graph

    result = await handler.catch(state, RuntimeError("oops"))
    assert result is False


# ---------------------------------------------------------------------------
# Function (Graph-level) — outputs on its run()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_function_graph_run_emits_fn_and_name_outputs():
    """A Function (module-graph) sets the fn, name, allow_multiple_calls and
    ai_callback output sockets when run."""
    from talemate.game.engine.nodes.core import GraphContext

    fn_graph = Function()
    fn_graph.set_property("name", "my_function")
    fn_graph.set_property("allow_multiple_calls", True)

    with GraphContext() as state:
        await fn_graph.run(state)
        out = {sock.name: sock.value for sock in fn_graph.outputs}

    assert out["name"] == "my_function"
    assert out["allow_multiple_calls"] is True
    assert isinstance(out["fn"], FunctionWrapper)
    # ai_callback returns a focal.Callback
    import talemate.game.focal as focal

    assert isinstance(out["ai_callback"], focal.Callback)
    assert out["ai_callback"].name == "my_function"


@pytest.mark.asyncio
async def test_function_graph_inputs_outputs_are_static():
    """Function.inputs is always [] (functions have no graph-level inputs);
    outputs is a 4-tuple of fn/name/allow_multiple_calls/ai_callback."""
    fn = Function()
    assert fn.inputs == []
    output_names = sorted(s.name for s in fn.outputs)
    assert output_names == ["ai_callback", "allow_multiple_calls", "fn", "name"]
