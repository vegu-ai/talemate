"""Unit tests for the node editor's automatic node module sync."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import talemate.game.engine.nodes.registry as registry
import talemate.server.node_editor as node_editor
from talemate.agents.base import AGENT_WEBSOCKET_HANDLER_BASE_TYPE
from talemate.agents.director.action_core.gating import DIRECTOR_CHAT_ACTION_BASE_TYPE
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphContext, GraphState
from talemate.game.engine.nodes.layout import export_flat_graph
from talemate.game.engine.nodes.registry import (
    register_module_sync_base_type,
    requires_module_sync,
)
from talemate.game.engine.nodes.scene import COMMAND_BASE_TYPE, SceneLoop
from talemate.save import save_node_module
from talemate.server.node_editor import NodeEditorPlugin

from conftest import MockScene
from _command_test_helpers import make_command

THROWAWAY_BASE_TYPE = "test/autosync/ThrowawayBaseType"


async def write_command_module(scene, registry_name: str, filename: str, name: str):
    """Register a command module on the scene and write it to its nodes dir."""
    command_cls = make_command(scene, registry_name, name=name, title=name.title())
    with ActiveScene(scene):
        module_path = await save_node_module(scene, command_cls(), filename)
    command_cls._module_path = module_path
    return command_cls, module_path


def queued_actions(plugin) -> list[str]:
    """Actions the handler has sent to the frontend, in order."""
    return [message["action"] for message in plugin.websocket_handler.messages]


class _Scene:
    """Minimal stand-in for the bits the node editor handlers touch."""

    def __init__(self, save_dir: Path):
        self.save_dir = str(save_dir)
        self.environment = "creative"
        self.nodes_filename = ""
        self.saved = True
        self.auto_save = False
        self.cancel_requested = False
        self._NODE_DEFINITIONS = {}

    @property
    def nodes_dir(self) -> str:
        return os.path.join(self.save_dir, "nodes")


class _WebsocketHandler:
    def __init__(self, scene):
        self.scene = scene
        self.messages = []

    def queue_put(self, message):
        self.messages.append(message)


@pytest.fixture
def scene(tmp_path: Path) -> _Scene:
    scene_dir = tmp_path / "scene"
    (scene_dir / "nodes").mkdir(parents=True)
    return _Scene(scene_dir)


@pytest.fixture
def plugin(scene):
    handler = _WebsocketHandler(scene)
    plugin = NodeEditorPlugin(handler)
    try:
        yield plugin
    finally:
        plugin.disconnect()


@pytest.fixture
def scene_loop(scene):
    """A creative scene loop that has already been through `on_loop_start`."""
    loop = SceneLoop()
    loop._state = GraphState()
    scene.creative_node_graph = loop
    return loop


@pytest.fixture
def emitted(monkeypatch) -> list:
    calls = []
    monkeypatch.setattr(
        node_editor, "emit", lambda typ, **kwargs: calls.append((typ, kwargs))
    )
    return calls


@pytest.fixture
def synced(monkeypatch, plugin) -> list:
    calls = []

    async def _sync():
        calls.append(True)

    monkeypatch.setattr(plugin, "_sync_node_modules", _sync)
    return calls


@pytest.fixture
def auto_synced(monkeypatch, plugin) -> list:
    calls = []

    async def _auto_sync(base_type):
        calls.append(base_type)

    monkeypatch.setattr(plugin, "_auto_sync_node_modules", _auto_sync)
    return calls


@pytest.fixture
def failing_sync(monkeypatch, plugin):
    async def _sync():
        raise RuntimeError("sync failed")

    monkeypatch.setattr(plugin, "_sync_node_modules", _sync)


@pytest.fixture
def command_scene() -> MockScene:
    """Real Scene - `register_commands` sends an event that validates its type."""
    scene = MockScene()
    scene._NODE_DEFINITIONS = {}
    return scene


@pytest.fixture
def talemate_root(monkeypatch, tmp_path: Path) -> Path:
    """Promotion target root - the real one is the repo's templates dir."""
    root = tmp_path / "talemate-root"
    root.mkdir()
    monkeypatch.setattr(node_editor, "TALEMATE_ROOT", str(root))
    return root


@pytest.fixture
def restore_global_nodes():
    """Undo global registrations - promotion registers into `registry.NODES`."""
    known = set(registry.NODES)
    yield
    for name in set(registry.NODES) - known:
        registry.NODES.pop(name, None)


@pytest.fixture
def throwaway_base_type():
    yield THROWAWAY_BASE_TYPE
    registry.MODULE_SYNC_BASE_TYPES.discard(THROWAWAY_BASE_TYPE)


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def test_requires_module_sync_rejects_unregistered_base_types(throwaway_base_type):
    assert requires_module_sync(None) is False
    assert requires_module_sync("") is False
    assert requires_module_sync(throwaway_base_type) is False


def test_register_module_sync_base_type_registers_and_returns_the_name(
    throwaway_base_type,
):
    assert register_module_sync_base_type(throwaway_base_type) == throwaway_base_type
    assert throwaway_base_type in registry.MODULE_SYNC_BASE_TYPES
    assert requires_module_sync(throwaway_base_type) is True


def test_sync_consumers_declare_their_base_types():
    assert COMMAND_BASE_TYPE == "command/Command"
    assert AGENT_WEBSOCKET_HANDLER_BASE_TYPE == "agents/AgentWebsocketHandler"
    assert DIRECTOR_CHAT_ACTION_BASE_TYPE == "agents/director/DirectorChatAction"
    assert registry.MODULE_SYNC_BASE_TYPES >= {
        COMMAND_BASE_TYPE,
        AGENT_WEBSOCKET_HANDLER_BASE_TYPE,
        DIRECTOR_CHAT_ACTION_BASE_TYPE,
    }


# ---------------------------------------------------------------------------
# _auto_sync_node_modules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_sync_syncs_and_emits_for_sync_base_type(
    plugin, scene_loop, synced, emitted
):
    await plugin._auto_sync_node_modules(COMMAND_BASE_TYPE)

    assert synced == [True]
    assert emitted == [
        ("status", {"message": "Node modules synced", "status": "success"})
    ]
    assert plugin.websocket_handler.messages == []


@pytest.mark.asyncio
async def test_auto_sync_runs_the_scene_loop_registrations(
    monkeypatch, plugin, scene, scene_loop, emitted
):
    registered = []

    async def register_commands(self, scene, state):
        registered.append(("commands", scene, state))

    async def init_agent_nodes(self, scene, state):
        registered.append(("agent_nodes", scene, state))

    monkeypatch.setattr(SceneLoop, "register_commands", register_commands)
    monkeypatch.setattr(SceneLoop, "init_agent_nodes", init_agent_nodes)

    await plugin._auto_sync_node_modules(COMMAND_BASE_TYPE)

    assert registered == [
        ("commands", scene, scene_loop._state),
        ("agent_nodes", scene, scene_loop._state),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("base_type", ["graph", "", None])
async def test_auto_sync_skips_base_types_that_need_no_sync(
    plugin, scene_loop, synced, emitted, base_type
):
    await plugin._auto_sync_node_modules(base_type)

    assert synced == []
    assert emitted == []


@pytest.mark.asyncio
async def test_auto_sync_skips_without_creative_node_graph(
    plugin, scene, synced, emitted
):
    assert not hasattr(scene, "creative_node_graph")

    await plugin._auto_sync_node_modules(COMMAND_BASE_TYPE)

    assert synced == []
    assert emitted == []


@pytest.mark.asyncio
async def test_auto_sync_skips_when_the_scene_loop_never_ran(
    plugin, scene, synced, emitted
):
    scene.creative_node_graph = SceneLoop()

    await plugin._auto_sync_node_modules(COMMAND_BASE_TYPE)

    assert synced == []
    assert emitted == []


# ---------------------------------------------------------------------------
# Handler wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_node_module_auto_syncs_with_the_module_base_type(
    plugin, scene, auto_synced
):
    command_cls = make_command(
        scene, "test/autosync/UpdateCommand", name="update", title="Update"
    )
    flat = export_flat_graph(command_cls())

    with ActiveScene(scene):
        await plugin.handle_update_node_module(
            {"path": "auto-sync-command.json", "graph": flat}
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert os.path.exists(os.path.join(scene.nodes_dir, "auto-sync-command.json"))


@pytest.mark.asyncio
async def test_update_node_module_refused_outside_creative_environment(
    plugin, scene, auto_synced
):
    scene.environment = "scene"

    with ActiveScene(scene):
        await plugin.handle_update_node_module({"path": "nope.json", "graph": {}})

    assert auto_synced == []


@pytest.mark.asyncio
async def test_delete_node_module_auto_syncs_with_the_removed_base_type(
    plugin, scene, auto_synced
):
    command_cls = make_command(
        scene, "test/autosync/DeleteCommand", name="delete", title="Delete"
    )
    module_path = os.path.join(scene.nodes_dir, "delete-command.json")
    Path(module_path).write_text("{}")
    command_cls._module_path = module_path

    with ActiveScene(scene):
        await plugin.handle_delete_node_module({"path": module_path})

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert "test/autosync/DeleteCommand" not in scene._NODE_DEFINITIONS
    assert not os.path.exists(module_path)


@pytest.mark.asyncio
async def test_delete_node_module_without_a_definition_syncs_nothing(
    plugin, scene, auto_synced
):
    with ActiveScene(scene):
        await plugin.handle_delete_node_module(
            {"path": os.path.join(scene.nodes_dir, "never-existed.json")}
        )

    assert auto_synced == [None]
    assert requires_module_sync(None) is False


@pytest.mark.asyncio
async def test_create_node_module_auto_syncs_with_the_new_base_type(
    plugin, scene, auto_synced
):
    with ActiveScene(scene):
        await plugin.handle_create_mode_module(
            {
                "name": "Auto Sync Command",
                "registry": "test/autosync/MyCommand",
                "module_type": COMMAND_BASE_TYPE,
            }
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert "test/autosync/MyCommand" in scene._NODE_DEFINITIONS
    assert os.path.exists(os.path.join(scene.nodes_dir, "auto-sync-command.json"))


@pytest.mark.asyncio
async def test_create_node_module_from_a_copy_auto_syncs_with_the_source_base_type(
    plugin, scene, auto_synced
):
    await write_command_module(
        scene, "test/autosync/CopySource", "copy-source.json", "copysource"
    )

    with ActiveScene(scene):
        await plugin.handle_create_mode_module(
            {
                "name": "Copied Command",
                "registry": "test/autosync/CopiedCommand",
                "copy_from": "copy-source.json",
            }
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert "test/autosync/CopiedCommand" in scene._NODE_DEFINITIONS
    assert os.path.exists(os.path.join(scene.nodes_dir, "copied-command.json"))


@pytest.mark.asyncio
async def test_create_node_module_extending_another_auto_syncs_with_the_base_type(
    monkeypatch, plugin, scene, auto_synced, tmp_path
):
    _, module_path = await write_command_module(
        scene, "test/autosync/ExtendSource", "extend-source.json", "extendsource"
    )
    # the product sends a path relative to the backend cwd (the talemate root);
    # `extends` is stored verbatim and open()d against that cwd
    monkeypatch.chdir(tmp_path)

    with ActiveScene(scene):
        await plugin.handle_create_mode_module(
            {
                "name": "Extended Command",
                "registry": "test/autosync/ExtendedCommand",
                "extend_from": os.path.relpath(module_path, tmp_path),
            }
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert "test/autosync/ExtendedCommand" in scene._NODE_DEFINITIONS
    assert os.path.exists(os.path.join(scene.nodes_dir, "extended-command.json"))


@pytest.mark.asyncio
async def test_create_node_module_from_selected_nodes_auto_syncs_with_the_base_type(
    plugin, scene, auto_synced
):
    with ActiveScene(scene):
        await plugin.handle_create_mode_module(
            {
                "name": "Selection Command",
                "registry": "test/autosync/SelectionCommand",
                "module_type": COMMAND_BASE_TYPE,
                "nodes": {
                    "nodes": [],
                    "connections": [],
                    "comments": [],
                    "groups": [],
                },
            }
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert "test/autosync/SelectionCommand" in scene._NODE_DEFINITIONS
    assert os.path.exists(os.path.join(scene.nodes_dir, "selection-command.json"))


@pytest.mark.asyncio
async def test_create_node_module_refused_outside_creative_environment(
    plugin, scene, auto_synced
):
    scene.environment = "scene"

    with ActiveScene(scene):
        await plugin.handle_create_mode_module(
            {
                "name": "Refused Command",
                "registry": "test/autosync/RefusedCommand",
                "module_type": COMMAND_BASE_TYPE,
            }
        )

    assert auto_synced == []
    assert [
        message["error"]["message"]
        for message in plugin.websocket_handler.messages
        if "error" in message
    ] == ["Cannot update scene nodes in non-creative environment"]
    assert not os.path.exists(os.path.join(scene.nodes_dir, "refused-command.json"))


@pytest.mark.asyncio
async def test_promote_node_module_copy_auto_syncs_with_the_module_base_type(
    plugin, scene, auto_synced, talemate_root, restore_global_nodes
):
    _, module_path = await write_command_module(
        scene, "test/autosync/PromoteCopy", "promote-copy.json", "promotecopy"
    )

    with ActiveScene(scene):
        await plugin.handle_promote_node_module(
            {
                "path": module_path,
                "project": "autosync",
                "registry": "test/autosync/PromoteCopy",
                "filename": "promote-copy.json",
                "mode": "copy",
            }
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert (
        talemate_root / "templates" / "modules" / "autosync" / "promote-copy.json"
    ).exists()
    assert "test/autosync/PromoteCopy" in scene._NODE_DEFINITIONS
    assert os.path.exists(module_path)
    assert "test/autosync/PromoteCopy" in registry.NODES


@pytest.mark.asyncio
async def test_promote_node_module_move_auto_syncs_and_unregisters_the_source(
    plugin, scene, auto_synced, talemate_root, restore_global_nodes
):
    _, module_path = await write_command_module(
        scene, "test/autosync/PromoteMove", "promote-move.json", "promotemove"
    )

    with ActiveScene(scene):
        await plugin.handle_promote_node_module(
            {
                "path": module_path,
                "project": "autosync",
                "registry": "test/autosync/PromoteMove",
                "filename": "promote-move.json",
                "mode": "move",
            }
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert (
        talemate_root / "templates" / "modules" / "autosync" / "promote-move.json"
    ).exists()
    assert "test/autosync/PromoteMove" not in scene._NODE_DEFINITIONS
    assert not os.path.exists(module_path)
    assert "test/autosync/PromoteMove" in registry.NODES


@pytest.mark.asyncio
async def test_promote_node_module_with_a_new_registry_auto_syncs_and_registers_it(
    plugin, scene, auto_synced, talemate_root, restore_global_nodes
):
    _, module_path = await write_command_module(
        scene, "test/autosync/PromoteRename", "promote-rename.json", "promoterename"
    )

    with ActiveScene(scene):
        await plugin.handle_promote_node_module(
            {
                "path": module_path,
                "project": "autosync",
                "registry": "test/autosync/PromotedRenamed",
                "filename": "promote-rename.json",
                "mode": "copy",
            }
        )

    assert auto_synced == [COMMAND_BASE_TYPE]
    assert (
        talemate_root / "templates" / "modules" / "autosync" / "promote-rename.json"
    ).exists()
    assert "test/autosync/PromotedRenamed" in registry.NODES
    assert "test/autosync/PromoteRename" not in registry.NODES


# ---------------------------------------------------------------------------
# Sync runs after the handler's own response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_node_module_sends_the_module_before_syncing(
    plugin, scene, scene_loop, failing_sync
):
    with ActiveScene(scene):
        with pytest.raises(RuntimeError, match="sync failed"):
            await plugin.handle_create_mode_module(
                {
                    "name": "Ordered Command",
                    "registry": "test/autosync/OrderedCommand",
                    "module_type": COMMAND_BASE_TYPE,
                }
            )

    assert "node_module" in queued_actions(plugin)


@pytest.mark.asyncio
async def test_delete_node_module_sends_the_library_before_syncing(
    plugin, scene, scene_loop, failing_sync
):
    _, module_path = await write_command_module(
        scene, "test/autosync/OrderedDelete", "ordered-delete.json", "ordereddelete"
    )

    with ActiveScene(scene):
        with pytest.raises(RuntimeError, match="sync failed"):
            await plugin.handle_delete_node_module({"path": module_path})

    assert "node_library" in queued_actions(plugin)


@pytest.mark.asyncio
async def test_promote_node_module_sends_the_library_before_syncing(
    plugin, scene, scene_loop, failing_sync, talemate_root, restore_global_nodes
):
    _, module_path = await write_command_module(
        scene, "test/autosync/OrderedPromote", "ordered-promote.json", "orderedpromote"
    )

    with ActiveScene(scene):
        with pytest.raises(RuntimeError, match="sync failed"):
            await plugin.handle_promote_node_module(
                {
                    "path": module_path,
                    "project": "autosync",
                    "registry": "test/autosync/OrderedPromote",
                    "filename": "ordered-promote.json",
                    "mode": "copy",
                }
            )

    assert "node_library" in queued_actions(plugin)


# ---------------------------------------------------------------------------
# register_commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_commands_keeps_the_previous_map_when_it_fails(
    monkeypatch, command_scene
):
    make_command(
        command_scene, "test/autosync/FirstCommand", name="first", title="First"
    )
    make_command(
        command_scene, "test/autosync/SecondCommand", name="second", title="Second"
    )

    loop = SceneLoop()

    with ActiveScene(command_scene):
        with GraphContext() as state:
            await loop.register_commands(command_scene, state)
            snapshot = dict(state.data["_commands"])
            assert snapshot["first"] == "test/autosync/FirstCommand"
            assert snapshot["second"] == "test/autosync/SecondCommand"

            async def collect_command_args(self, command_node):
                raise RuntimeError("collect failed")

            monkeypatch.setattr(SceneLoop, "collect_command_args", collect_command_args)

            with pytest.raises(RuntimeError, match="collect failed"):
                await loop.register_commands(command_scene, state)

            assert state.data["_commands"] == snapshot


# ---------------------------------------------------------------------------
# Manual sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_sync_reports_the_operation_as_done(monkeypatch, plugin, synced):
    done = []

    async def signal_operation_done(**kwargs):
        done.append(kwargs)

    monkeypatch.setattr(plugin, "signal_operation_done", signal_operation_done)

    await plugin.handle_sync_node_modules({})

    assert synced == [True]
    assert done == [{"emit_status_message": "Node modules synced"}]
