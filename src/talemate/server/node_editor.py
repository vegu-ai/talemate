import pydantic
import structlog
import os
import asyncio

from functools import wraps
from talemate.context import Interaction
from talemate.game.engine.nodes.core import (
    GraphState,
    PASSTHROUGH_ERRORS,
)
from talemate.game.engine.nodes.scene import SceneLoop
from talemate.game.engine.nodes.base_types import BASE_TYPES
from talemate.game.engine.nodes.registry import (
    export_node_definitions,
    import_node_definition,
    normalize_registry_name,
    validate_registry_path,
)
from talemate.game.engine.nodes.layout import (
    normalize_node_filename,
    export_flat_graph,
    import_flat_graph,
    load_graph,
    list_node_files,
    PathInfo,
)
from talemate.game.engine.nodes.run import BreakpointEvent
from talemate.save import save_node_module, combine_paths
import talemate.emit.async_signals as signals

from .websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.node_editor")

TALEMATE_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..")


def requires_creative_environment(fn):
    @wraps(fn)
    async def wrapper(self, data):
        if self.scene.environment != "creative":
            return await self.signal_operation_failed(
                "Cannot update scene nodes in non-creative environment"
            )

        return await fn(self, data)

    return wrapper


class RequestNodeLibrary(pydantic.BaseModel):
    pass


class RequestNodeModule(pydantic.BaseModel):
    path: str


class RequestCreateNodeModule(pydantic.BaseModel):
    name: str
    registry: str
    filename: str | None = None
    copy_from: str | None = None
    extend_from: str | None = None
    module_type: str = "graph"
    nodes: dict | None = None


class ExportNodeModule(pydantic.BaseModel):
    node_definitions: dict
    graph: dict
    path_info: PathInfo


class RequestUpdateNodeModule(pydantic.BaseModel):
    path: str
    graph: dict
    set_as_main: bool = False


class RequestDeleteNodeModule(pydantic.BaseModel):
    path: str


class RequestTestRun(pydantic.BaseModel):
    graph: dict


class NodeEditorPlugin(Plugin):
    router = "node_editor"

    def connect(self):
        signals.get("nodes_node_state").connect(self.handle_node_state)
        signals.get("nodes_breakpoint").connect(self.handle_breakpoint)

    def disconnect(self):
        signals.get("nodes_node_state").disconnect(self.handle_node_state)
        signals.get("nodes_breakpoint").disconnect(self.handle_breakpoint)

    async def handle_node_state(self, state: GraphState):
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "node_state",
                "data": state.flattened,
            }
        )

    async def handle_breakpoint(self, breakpoint: BreakpointEvent):
        absolute_module_path = breakpoint.module_path
        base_dir_path = os.path.abspath(TALEMATE_BASE_DIR)

        relative_module_path = os.path.relpath(absolute_module_path, base_dir_path)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "breakpoint",
                "data": {
                    "node": breakpoint.node.model_dump(),
                    "module_path": relative_module_path,
                },
            }
        )

    async def handle_restart_scene_loop(self, data: dict):
        with Interaction(reset_requested=True):
            return

    async def handle_sync_node_modules(self, data: dict):
        scene_loop: SceneLoop = self.scene.creative_node_graph
        await scene_loop.register_commands(self.scene, scene_loop._state)
        await scene_loop.init_agent_nodes(self.scene, scene_loop._state)

        await self.signal_operation_done(emit_status_message="Node modules synced")

    async def handle_request_node_library(self, data: dict):
        files = list_node_files(search_paths=[self.scene.nodes_dir])
        scene = self.scene

        # Define scene loop path
        scene_dir = scene.save_dir

        # Add separator to scene_dir for proper directory matching
        if not scene_dir.endswith(os.path.sep):
            scene_dir_prefix = scene_dir + os.path.sep
        else:
            scene_dir_prefix = scene_dir

        # Define sorting key function
        def sort_key(file_path):
            filename = os.path.basename(file_path)

            if file_path == scene_dir or file_path.startswith(scene_dir_prefix):
                return (1, filename.lower())
            else:
                return (2, filename.lower())

        # Apply sorting
        files = sorted(files, key=sort_key)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "node_library",
                "data": files,
            }
        )

    async def handle_create_mode_module(self, data: dict):
        request = RequestCreateNodeModule(**data)

        log.debug("creating node", request=request)

        filename = request.filename or normalize_node_filename(request.name)

        # Check if file already exists - prevent overwriting existing modules
        file_path = combine_paths(self.scene.nodes_dir, filename)
        if os.path.exists(file_path):
            return await self.signal_operation_failed(
                f"A module with the name '{request.name}' already exists at '{filename}'. "
                "Please choose a different name or delete the existing module first."
            )

        registry = request.registry.replace("$N", normalize_registry_name(request.name))
        node_definitions = export_node_definitions()
        try:
            validate_registry_path(registry, node_definitions)
        except ValueError as e:
            return await self.signal_operation_failed(str(e))

        if request.nodes and not request.copy_from and not request.extend_from:
            # Create a module from selected nodes

            if registry in node_definitions["nodes"]:
                return await self.signal_operation_failed(
                    f"Cannot create blank module at existing path: {registry}. If you intend to override it, create it as a copy."
                )

            title = request.name.title()

            new_graph_cls = await self._create_module_from_nodes(
                self.scene,
                request.nodes,
                title,
                registry,
                request.module_type,
                filename,
            )

            if not new_graph_cls:
                return await self.signal_operation_failed("Invalid module type")

        elif not request.copy_from and not request.extend_from:
            # create a new module from scratch

            if registry in node_definitions["nodes"]:
                return await self.signal_operation_failed(
                    f"Cannot create new module at existing path: {registry}. If you intend to override it, create it as a copy."
                )

            graph_cls = BASE_TYPES.get(request.module_type)

            if not graph_cls:
                return await self.signal_operation_failed("Invalid module type")

            title = request.name.title()

            graph_def = graph_cls(title=title).model_dump()
            graph_def["registry"] = registry

            new_graph_cls = import_node_definition(
                graph_def, self.scene._NODE_DEFINITIONS
            )
            new_graph_cls._module_path = await save_node_module(
                self.scene, new_graph_cls(), filename, set_as_main=False
            )

        elif request.extend_from:
            # extend from a node module (inheritance)

            extend_from = request.extend_from
            extend_graph, _ = load_graph(
                extend_from, search_paths=[self.scene.nodes_dir]
            )

            if not extend_graph:
                return await self.signal_operation_failed(
                    "Cannot extend from non-existent node"
                )

            base_type = extend_graph.base_type

            graph_cls = BASE_TYPES.get(base_type)

            if not graph_cls:
                return await self.signal_operation_failed("Invalid module type")

            graph_def = graph_cls(
                title=request.name.title(), extends=extend_from
            ).model_dump()
            graph_def["registry"] = registry

            new_graph_cls = import_node_definition(
                graph_def, self.scene._NODE_DEFINITIONS
            )

            new_graph_cls._module_path = await save_node_module(
                self.scene, new_graph_cls(), filename, set_as_main=False
            )

        elif request.copy_from:
            # copy from a node module

            copy_from = request.copy_from

            graph, _ = load_graph(copy_from, search_paths=[self.scene.nodes_dir])
            graph.title = request.name.title()

            graph_def = graph.model_dump()
            graph_def["registry"] = registry

            new_graph_cls = import_node_definition(
                graph_def, self.scene._NODE_DEFINITIONS
            )

            # if the scene NODE_DEFINITIONS does not currently have scene/SceneLoop base
            # type module in it and the incoming graph is a scene/SceneLoop, then set_as_main
            # to True
            set_as_main = False

            if isinstance(graph, SceneLoop):
                set_as_main = True
                for scene_node in self.scene._NODE_DEFINITIONS.values():
                    if scene_node.base_type == "scene/SceneLoop":
                        set_as_main = False
                        break

            new_graph_cls._registry = registry
            graph.registry = registry

            new_graph_cls._module_path = await save_node_module(
                self.scene, graph, filename, set_as_main=set_as_main
            )

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "created_node_module",
                "data": filename,
            }
        )

        await self.handle_request_node_module({"path": filename})

    async def _create_module_from_nodes(
        self, scene, nodes_data, title, registry, module_type, filename
    ):
        """
        Create a new module using selected nodes from the editor.

        Args:
            scene: The current scene context
            nodes_data: JSON data from convertSelectedGraphToJSON including nodes and connections
            title: Title for the new module
            registry: Registry path for the new module
            module_type: Type of module to create (e.g., "graph", "command/Command")
            filename: Filename for the new module

        Returns:
            The created module class
        """
        graph_cls = BASE_TYPES.get(module_type)
        if not graph_cls:
            return None

        # Create basic graph definition
        graph_def = graph_cls(title=title).model_dump()
        graph_def["registry"] = registry

        # Import the node definition to create the class
        new_graph_cls = import_node_definition(graph_def, scene._NODE_DEFINITIONS)

        # Create an instance of the graph
        new_graph = new_graph_cls()

        # Create a flat data structure compatible with import_flat_graph
        flat_data = {
            "nodes": nodes_data.get("nodes", []),
            "connections": nodes_data.get("connections", []),
            "comments": nodes_data.get("comments", []),
            "groups": nodes_data.get("groups", []),
            "properties": {},
            "registry": registry,
            "base_type": module_type,
            "title": title,
            "extends": None,
        }

        # Use import_flat_graph to properly create the graph
        populated_graph = import_flat_graph(flat_data, new_graph)

        # Save the module
        new_graph_cls._module_path = await save_node_module(
            scene, populated_graph, filename, set_as_main=False
        )

        return new_graph_cls

    async def handle_request_node_module(self, data: dict):
        request = RequestNodeModule(**data)

        graph, path_info = load_graph(request.path, search_paths=[self.scene.nodes_dir])

        export_nodes = ExportNodeModule(
            graph=export_flat_graph(graph),
            node_definitions=export_node_definitions(),
            path_info=path_info,
        )

        # with open("exported_nodes.json", "w") as file:
        #    import json
        #    json.dump(export_nodes, file, indent=2)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "node_module",
                "data": export_nodes.model_dump(),
            }
        )

        try:
            await self.handle_node_state(self.scene.nodegraph_state)
        except AttributeError:
            pass

    @requires_creative_environment
    async def handle_update_node_module(self, data: dict):
        import_nodes = RequestUpdateNodeModule(**data)
        graph = import_flat_graph(import_nodes.graph)

        # ensure absolute path
        base_dir = os.path.abspath(TALEMATE_BASE_DIR)
        if not import_nodes.path.startswith(base_dir):
            import_nodes.path = os.path.join(base_dir, import_nodes.path)

        log.debug("updating nodes", path=import_nodes.path)

        if graph.registry:
            node_cls = import_node_definition(
                graph.model_dump(), self.scene._NODE_DEFINITIONS, reimport=True
            )
            node_cls._module_path = import_nodes.path

        await save_node_module(self.scene, graph, import_nodes.path)

        if graph.base_type == "scene/SceneLoop":
            if import_nodes.set_as_main:
                self.scene.nodes_filename = import_nodes.path
                self.scene.saved = False

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "node_module_updated",
                "data": {},
            }
        )

    @requires_creative_environment
    async def handle_delete_node_module(self, data: dict):
        request = RequestDeleteNodeModule(**data)

        # only scene nodes can be deleted
        # check by checking against the scene's save_dir property
        path = os.path.join(TALEMATE_BASE_DIR, request.path)

        path = os.path.abspath(path)

        log.debug("deleting", path=path, reqest=request)

        if not path.startswith(self.scene.save_dir):
            return await self.signal_operation_failed(
                "Cannot delete node module outside of scene directory"
            )

        try:
            os.remove(path)
        except FileNotFoundError:
            pass

        for scene_node in list(self.scene._NODE_DEFINITIONS.values()):
            if scene_node._module_path == path:
                self.scene._NODE_DEFINITIONS.pop(scene_node._registry, None)
                break

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "deleted_node_module",
                "path": request.path,
            }
        )

        await self.handle_request_node_library({})

    @requires_creative_environment
    async def handle_test_run(self, data: dict):
        """
        Loads a graph from json and runs it.
        """

        payload = RequestTestRun(**data)

        graph = import_flat_graph(payload.graph)

        await self._start_test_with_graph(graph)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "test_started",
                "data": payload.model_dump(),
            }
        )

    @requires_creative_environment
    async def handle_test_run_scene_loop(self, data: dict):
        """
        Loads the scene's main loop and runs it.
        """
        scene = self.scene

        # Load the scene's main loop
        graph, _ = load_graph(scene.nodes_filename, search_paths=[scene.nodes_dir])

        await self._start_test_with_graph(graph)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "test_started",
                "data": {},
            }
        )

    async def _start_test_with_graph(self, graph):
        """
        Common logic for starting a test with a loaded graph
        """
        active_graph_state: GraphState = self.scene.nodegraph_state

        async def on_error(state: GraphState, error: Exception):
            if isinstance(error, PASSTHROUGH_ERRORS):
                return
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "test_error",
                    "data": {
                        "error": str(error),
                    },
                }
            )

            await self.handle_test_stop({})

        async def on_done(state: GraphState):
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "test_done",
                    "data": {},
                }
            )

            await self.handle_test_stop({})

        graph.callbacks.append(on_done)
        graph.error_handlers.append(on_error)

        if isinstance(graph, SceneLoop):
            graph.properties["trigger_game_loop"] = True

        active_graph_state.shared["__test_module"] = graph

    @requires_creative_environment
    async def handle_test_restart(self, data: dict):
        await self._stop_test()
        await asyncio.sleep(1)
        await self.handle_test_run(data)

    @requires_creative_environment
    async def handle_test_stop(self, data: dict):
        await self._stop_test()

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "test_stopped",
                "data": {},
            }
        )

    @requires_creative_environment
    async def handle_release_breakpoint(self, data: dict):
        active_graph_state: GraphState = self.scene.nodegraph_state
        active_graph_state.shared.pop("__breakpoint", None)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "breakpoint_released",
                "data": {},
            }
        )

    async def _stop_test(self):
        active_graph_state: GraphState = self.scene.nodegraph_state
        module = active_graph_state.shared.pop("__test_module", None)

        if not module:
            return

        task = active_graph_state.shared.pop(f"__run_{module.id}", None)
        if task:
            task.cancel()
