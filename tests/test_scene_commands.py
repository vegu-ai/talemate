"""
Unit tests for the scene commands websocket plugin.

Covers the `scene_commands` router: dispatching a command module by name,
serving the command catalog on request and pushing it unprompted when the
scene loop registers its commands.

The plugin is driven with a minimal websocket handler stand-in and a scene
loop whose `_state` was populated by a real `register_commands` run, which
is how the loop state is reached in production (the node graph of the
scene's current environment).
"""

import pytest

from talemate.context import ActiveScene, active_scene
from talemate.exceptions import GenerationCancelled
from talemate.game.engine.nodes.core import GraphContext
from talemate.game.engine.nodes.scene import SceneLoop
from talemate.server.scene_commands import SceneCommandsPlugin

from conftest import MockScene, bootstrap_scene
from _command_test_helpers import make_command, wait_for


class _MockWebsocketHandler:
    """Minimal handler stand-in: exposes ``scene`` and a queue_put list."""

    def __init__(self, scene):
        self._scene = scene
        self.messages: list[dict] = []
        self.waiting_for_input = True

    @property
    def scene(self):
        return self._scene

    def queue_put(self, data):
        self.messages.append(data)

    def by_action(self, action):
        return [m for m in self.messages if m.get("action") == action]


@pytest.fixture
def scene():
    """Real Scene with bootstrapped agents and an empty node definition set."""
    s = MockScene()
    bootstrap_scene(s)
    s._NODE_DEFINITIONS = {}
    return s


@pytest.fixture
def plugin(scene):
    plugin = SceneCommandsPlugin(_MockWebsocketHandler(scene))
    yield plugin
    plugin.disconnect()


async def attach_scene_loop(scene, attribute: str = "node_graph") -> SceneLoop:
    """Register the scene's commands and hang the loop off the scene."""
    loop = SceneLoop()
    with ActiveScene(scene):
        with GraphContext() as state:
            await loop.register_commands(scene, state)
    loop._state = state
    setattr(scene, attribute, loop)
    return loop


async def run_command(plugin, data: dict):
    """`handle_run` returns the background task it scheduled, None if refused."""
    task = await plugin.handle_run(data)
    if task is not None:
        await task


async def dispatch(plugin, data: dict):
    """Drive the command through `Plugin.handle`, as the router does."""
    await plugin.handle({"action": "run", **data})
    await wait_for(lambda: bool(plugin.websocket_handler.by_action("operation_done")))


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_dispatches_command(plugin, scene):
    executed = []
    make_command(
        scene,
        "test/server_commands/Bow",
        name="bow",
        title="Bow",
        on_execute=executed.append,
    )
    await attach_scene_loop(scene)

    await run_command(
        plugin, {"name": "bow", "args": {"target": "guard"}, "request_id": "req-1"}
    )
    await wait_for(lambda: bool(executed))

    assert executed == [{"target": "guard"}]

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert done["request_id"] == "req-1"
    assert "error" not in done


@pytest.mark.asyncio
async def test_run_without_args(plugin, scene):
    executed = []
    make_command(
        scene,
        "test/server_commands/Rest",
        name="rest",
        title="Rest",
        on_execute=executed.append,
    )
    await attach_scene_loop(scene)

    await run_command(plugin, {"name": "rest"})
    await wait_for(lambda: bool(executed))

    assert executed == [{}]

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "request_id" not in done


@pytest.mark.asyncio
async def test_run_unknown_command_fails(plugin, scene):
    await attach_scene_loop(scene)

    await run_command(plugin, {"name": "nope", "request_id": "req-2"})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert done["error"]["message"] == "Unknown command: nope"
    assert done["failed_action"] == "run"
    assert done["request_id"] == "req-2"


@pytest.mark.asyncio
async def test_run_without_scene_loop_fails(plugin, scene):
    await run_command(plugin, {"name": "bow", "request_id": "req-3"})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert done["error"]["message"] == "No active scene loop"
    assert done["failed_action"] == "run"
    assert done["request_id"] == "req-3"


@pytest.mark.asyncio
async def test_run_while_not_waiting_for_input_fails(plugin, scene):
    executed = []
    make_command(
        scene,
        "test/server_commands/Flee",
        name="flee",
        title="Flee",
        on_execute=executed.append,
    )
    await attach_scene_loop(scene)
    plugin.websocket_handler.waiting_for_input = False

    await run_command(plugin, {"name": "flee", "request_id": "req-4"})
    await wait_for(lambda: bool(executed))

    assert executed == []

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert done["error"]["message"] == "Scene is not waiting for input"
    assert done["failed_action"] == "run"
    assert done["request_id"] == "req-4"


@pytest.mark.asyncio
async def test_run_uses_the_graph_of_the_current_environment(plugin, scene):
    """A stale game loop lingers after a switch to creative - the plugin has
    to resolve the loop by environment, not by `active_node_graph`."""

    executed = []
    make_command(
        scene,
        "test/server_commands/Sculpt",
        name="sculpt",
        title="Sculpt",
        on_execute=executed.append,
    )
    await attach_scene_loop(scene, attribute="creative_node_graph")

    make_command(
        scene,
        "test/server_commands/Swing",
        name="swing",
        title="Swing",
        on_execute=executed.append,
    )
    await attach_scene_loop(scene, attribute="node_graph")

    scene.environment = "creative"
    plugin.websocket_handler.messages.clear()

    await plugin.handle_request_catalog({})
    (catalog,) = plugin.websocket_handler.by_action("catalog")
    assert [entry["name"] for entry in catalog["data"]["commands"]] == ["sculpt"]

    await run_command(plugin, {"name": "swing", "request_id": "req-5"})
    await run_command(plugin, {"name": "sculpt", "request_id": "req-6"})
    await wait_for(lambda: bool(executed))

    assert executed == [{}]

    refused, done = plugin.websocket_handler.by_action("operation_done")
    assert refused["error"]["message"] == "Unknown command: swing"
    assert refused["request_id"] == "req-5"
    assert "error" not in done
    assert done["request_id"] == "req-6"


# ---------------------------------------------------------------------------
# run through Plugin.handle (production dispatch path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_run_provides_its_own_scene_context(plugin, scene):
    """No ambient `ActiveScene` here - the plugin has to set it itself."""

    seen = []
    make_command(
        scene,
        "test/server_commands/Kneel",
        name="kneel",
        title="Kneel",
        on_execute=lambda kwargs: seen.append(active_scene.get()),
    )
    await attach_scene_loop(scene)
    plugin.websocket_handler.messages.clear()

    await dispatch(plugin, {"name": "kneel", "request_id": "req-7"})

    assert seen == [scene]

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert done["request_id"] == "req-7"
    assert "error" not in done


@pytest.mark.asyncio
async def test_handle_run_failure_posts_error_envelope(plugin, scene):
    def boom(kwargs):
        raise ValueError("command exploded")

    make_command(
        scene,
        "test/server_commands/Detonate",
        name="detonate",
        title="Detonate",
        on_execute=boom,
    )
    await attach_scene_loop(scene)
    plugin.websocket_handler.messages.clear()

    await dispatch(plugin, {"name": "detonate", "request_id": "req-8"})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert done["error"]["message"] == "command exploded"
    # posted by the done-callback, which has no request to answer
    assert "request_id" not in done


@pytest.mark.asyncio
async def test_handle_run_cancelled_posts_bare_envelope(plugin, scene):
    def cancel(kwargs):
        raise GenerationCancelled("cancelled")

    make_command(
        scene,
        "test/server_commands/Halt",
        name="halt",
        title="Halt",
        on_execute=cancel,
    )
    await attach_scene_loop(scene)
    plugin.websocket_handler.messages.clear()

    await dispatch(plugin, {"name": "halt", "request_id": "req-9"})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert done["data"] == {}
    assert "error" not in done
    assert "request_id" not in done


# ---------------------------------------------------------------------------
# request_catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_catalog_returns_catalog(plugin, scene):
    make_command(
        scene,
        "test/server_commands/Wave",
        name="wave",
        title="Wave",
        icon="mdi-hand-wave",
        menu="social",
    )
    await attach_scene_loop(scene)
    plugin.websocket_handler.messages.clear()

    await plugin.handle_request_catalog({})

    (response,) = plugin.websocket_handler.by_action("catalog")
    assert response["type"] == "scene_commands"
    assert response["data"]["commands"] == [
        {
            "name": "wave",
            "label": "Wave",
            "icon": "mdi-hand-wave",
            "menu": "social",
            "args": [],
        }
    ]


@pytest.mark.asyncio
async def test_request_catalog_without_scene_loop_is_empty(plugin):
    await plugin.handle_request_catalog({})

    (response,) = plugin.websocket_handler.by_action("catalog")
    assert response["data"]["commands"] == []


# ---------------------------------------------------------------------------
# catalog signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_commands_pushes_catalog(plugin, scene):
    make_command(
        scene,
        "test/server_commands/Ponder",
        name="ponder",
        title="Ponder",
    )

    await attach_scene_loop(scene)

    (pushed,) = plugin.websocket_handler.by_action("catalog")
    assert [entry["name"] for entry in pushed["data"]["commands"]] == ["ponder"]
