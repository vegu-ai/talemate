"""A cancelled node-editor test run must not report completion (issue #270).

The module runs through the real `RunModule` node, which is what registers the
task the stop path cancels.
"""

from __future__ import annotations

import asyncio

import pytest

from talemate.game.engine.nodes.core import (
    Entry,
    Graph,
    GraphState,
    Loop,
    Node,
)
from talemate.game.engine.nodes.run import RunModule
from talemate.server.node_editor import NodeEditorPlugin


class _Scene:
    environment = "creative"

    def __init__(self):
        self.nodegraph_state = GraphState()


class _WebsocketHandler:
    """Only `scene` and `queue_put` are reached from the code under test."""

    def __init__(self, scene: _Scene):
        self.scene = scene
        self.queued = []

    def queue_put(self, data):
        self.queued.append(data)


@pytest.fixture
def plugin():
    handler = NodeEditorPlugin(_WebsocketHandler(_Scene()))
    yield handler
    handler.disconnect()


def actions(plugin: NodeEditorPlugin) -> list[str]:
    return [message["action"] for message in plugin.websocket_handler.queued]


class _ModuleNode(Node):
    """Emit the module to run on the `module` output."""

    def __init__(self, module: Graph, title: str = "Module", **kwargs):
        super().__init__(title=title, **kwargs)
        self._module = module

    def setup(self):
        self.add_output("module")

    async def run(self, state: GraphState):
        self.set_output_values({"module": self._module})


class _SleepNode(Node):
    def setup(self):
        self.add_input("trigger")

    async def run(self, state: GraphState):
        await asyncio.sleep(0.05)


class _RaisingNode(Node):
    def setup(self):
        self.add_input("trigger")

    async def run(self, state: GraphState):
        raise RuntimeError("module blew up")


def _looping_module(body: Node) -> Loop:
    entry = Entry()
    module = Loop()
    module.add_node(entry)
    module.add_node(body)
    module.connect(entry.outputs[0], body.inputs[0])
    return module


def _runner(module: Graph) -> Graph:
    source = _ModuleNode(module)
    run_module = RunModule()
    graph = Graph()
    graph.add_node(source)
    graph.add_node(run_module)
    graph.connect(source.outputs[0], run_module.inputs[0])
    return graph


@pytest.mark.asyncio
async def test_stopping_a_test_run_reports_stopped_but_not_done(plugin):
    module = _looping_module(_SleepNode(title="sleeper"))

    await plugin._start_test_with_graph(module)

    runner = asyncio.create_task(_runner(module).execute(plugin.scene.nodegraph_state))
    await asyncio.sleep(0.2)

    await plugin.handle_test_stop({})
    # the module loops forever - a stop path that stops resolving the task must
    # fail this test, not hang it
    await asyncio.wait_for(runner, timeout=5)

    assert actions(plugin) == ["test_stopped"]


@pytest.mark.asyncio
async def test_a_failing_test_run_reports_the_error_but_not_done(plugin):
    """The error path stops the run by cancelling it, so it used to report the
    failure and then completion."""

    module = _looping_module(_RaisingNode(title="boom"))

    await plugin._start_test_with_graph(module)

    await _runner(module).execute(plugin.scene.nodegraph_state)

    assert actions(plugin) == ["test_error", "test_stopped"]


@pytest.mark.asyncio
async def test_a_test_run_that_finishes_reports_done(plugin):
    entry = Entry()
    module = Graph()
    module.add_node(entry)

    await plugin._start_test_with_graph(module)

    await _runner(module).execute(plugin.scene.nodegraph_state)

    assert actions(plugin) == ["test_done", "test_stopped"]
