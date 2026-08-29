"""
Shared helpers for node-graph unit tests.

These tests instantiate node classes directly and invoke their `run` method
inside a `GraphContext` so that socket value setters can write to state.
Inputs that have no upstream producer are pre-loaded as properties on the
node — `Node.get_input_value` falls back to the matching property when the
input socket has no `source` connection.

Mirrors the pattern in `tests/test_nodes_scene.py::_run_node` to avoid code
duplication across the per-module node-test files.
"""

from __future__ import annotations

from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import (
    Graph,
    GraphContext,
    Node,
    NodeVerbosity,
)


# Reserved property names cannot be set via Node.set_property — they are
# pydantic model fields on Node, not entries in the `properties` dict. Tests
# that need to override these mutate `node.properties[name]` directly.
_RESERVED_PROPERTY_NAMES = {"title", "id"}


def apply_inputs(node, inputs: dict | None):
    """Pre-load `inputs` onto the node as properties. See module docstring."""
    if not inputs:
        return
    for k, v in inputs.items():
        if k in _RESERVED_PROPERTY_NAMES:
            node.properties[k] = v
        else:
            node.set_property(k, v)


def capture_outputs(node) -> dict:
    """Capture outputs (and a `__deactivated` companion key per output) into a
    plain dict. MUST be called BEFORE the surrounding `GraphContext` is
    exited — socket `.value` and `.deactivated` reads are scoped to the
    active context."""
    outputs = {sock.name: sock.value for sock in node.outputs}
    outputs.update(
        {f"{sock.name}__deactivated": sock.deactivated for sock in node.outputs}
    )
    return outputs


async def run_node(
    node,
    *,
    scene=None,
    inputs: dict | None = None,
    verbosity: NodeVerbosity = NodeVerbosity.NORMAL,
    state_setup=None,
):
    """Run a node inside a GraphContext.

    Parameters
    ----------
    node:
        Node instance to run.
    scene:
        Optional Scene to bind via `ActiveScene` for the duration of the run.
        Many nodes call `talemate.context.active_scene.get()` and need this.
    inputs:
        Dict of {name: value} pre-loaded as properties on `node`. The node's
        `get_input_value(name)` falls back to the property value when the
        input socket has no source connected.
    verbosity:
        GraphState.verbosity to use for the run.
    state_setup:
        Optional `state_setup(state)` callback invoked AFTER the GraphContext
        is created and BEFORE `node.run(state)`. Use to seed `state.data` /
        `state.shared` etc.

    Returns a dict of {output_name: value} plus {f"{name}__deactivated": bool}
    for each output socket.
    """
    apply_inputs(node, inputs)

    async def _run():
        with GraphContext() as state:
            state.verbosity = verbosity
            if state_setup:
                state_setup(state)
            await node.run(state)
            return capture_outputs(node)

    if scene is not None:
        with ActiveScene(scene):
            return await _run()
    return await _run()


def make_constant(**values):
    """Node emitting fixed values on identically named outputs."""

    class _Constant(Node):
        def __init__(self, **kw):
            super().__init__(title="Constant", **kw)

        def setup(self):
            for name in values:
                self.add_output(name)

        async def run(self, state):
            self.set_output_values(dict(values))

    return _Constant()


def make_capture(captured: dict, *keys):
    """Node mirroring its inputs into the `captured` dict."""

    class _Capture(Node):
        def __init__(self, **kw):
            super().__init__(title="Capture", **kw)

        def setup(self):
            for name in keys:
                self.add_input(name, optional=True)

        async def run(self, state):
            for name in keys:
                captured[name] = self.get_input_value(name)

    return _Capture()


def build_graph(*nodes) -> Graph:
    graph = Graph()
    for node in nodes:
        graph.add_node(node)
    return graph


async def execute_graph(scene, graph: Graph):
    """Execute `graph` with `scene` active, re-raising any node error."""

    def error_handler(state, error: Exception):
        raise error

    graph.error_handlers.append(error_handler)
    with ActiveScene(scene):
        await graph.execute()
