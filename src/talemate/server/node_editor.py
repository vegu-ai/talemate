import pydantic
import structlog
import os
import json
import asyncio

from functools import wraps

from talemate.context import interaction


from talemate.game.engine.nodes.core import Graph, Loop, GraphState, Listen, graph_state, PASSTHROUGH_ERRORS, dynamic_node_import, load_extended_components
from talemate.game.engine.nodes.scene import SceneLoop
from talemate.game.engine.nodes.base_types import BASE_TYPES
from talemate.game.engine.nodes.registry import export_node_definitions, import_node_definition, normalize_registry_name, get_node
from talemate.game.engine.nodes.layout import normalize_node_filename, export_flat_graph, import_flat_graph, load_graph, list_node_files, PathInfo
from talemate.game.engine.nodes.run import BreakpointEvent
from talemate.save import save_node_module
import talemate.emit.async_signals as signals

from .websocket_plugin import Plugin
log = structlog.get_logger("talemate.server.node_editor")

TALEMATE_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..")

def requires_creative_environment(fn):
    @wraps(fn)
    async def wrapper(self, data):
        if self.scene.environment != "creative":
            return await self.signal_operation_failed("Cannot update scene nodes in non-creative environment")
        
        return await fn(self, data)
    
    return wrapper


class RequestNodeLibrary(pydantic.BaseModel):
    pass    

class RequestNodeModule(pydantic.BaseModel):
    path: str
    
class RequestCreateNodeModule(pydantic.BaseModel):
    name: str
    registry: str
    copy_from: str | None = None
    extend_from: str | None = None
    module_type: str = "graph"

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
        
    async def handle_breakpoint(self, breakpoint:BreakpointEvent):
        
        
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
                }
            }
        )
    
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
        
        filename = normalize_node_filename(request.name)
        
        
        if not request.copy_from and not request.extend_from:
            
            graph_cls = BASE_TYPES.get(request.module_type)

            if not graph_cls:
                return await self.signal_operation_failed("Invalid module type")
            
            registry = request.registry.replace("$N", normalize_registry_name(request.name))
            
            title = request.name.title()
            
            #new_graph_cls = dynamic_node_import(graph_cls(title=title).model_dump(), registry)
            
            graph_def = graph_cls(title=title).model_dump()
            graph_def["registry"] = registry
            
            new_graph_cls = import_node_definition(graph_def, self.scene._NODE_DEFINITIONS)
            new_graph_cls._module_path = await save_node_module(
                self.scene, new_graph_cls(), filename, set_as_main=False
            )
        
        elif request.extend_from:
            
            extend_from = request.extend_from
            
            # blank graph using the extend_from graph base type
            
            extend_graph, _ = load_graph(extend_from, search_paths=[self.scene.nodes_dir])
            
            if not extend_graph:
                return await self.signal_operation_failed("Cannot extend from non-existent node")
            
            base_type = extend_graph.base_type
            
            graph_cls = BASE_TYPES.get(base_type)
            
            if not graph_cls:
                return await self.signal_operation_failed("Invalid module type")
            
            registry = request.registry.replace("$N", normalize_registry_name(request.name))
            
            graph_def = graph_cls(title=request.name.title(), extends=extend_from).model_dump()
            graph_def["registry"] = registry
            
            new_graph_cls = import_node_definition(graph_def, self.scene._NODE_DEFINITIONS)
            
            new_graph_cls._module_path = await save_node_module(
                self.scene, new_graph_cls(), filename, set_as_main=False
            )
                
        elif request.copy_from:
            copy_from = request.copy_from
            
            graph, _ = load_graph(copy_from, search_paths=[self.scene.nodes_dir])
            graph.title = request.name.title()
            #new_graph_cls = dynamic_node_import(graph.model_dump(), registry)
            
            registry = request.registry.replace("$N", normalize_registry_name(request.name))
            
            graph_def = graph.model_dump()
            graph_def["registry"] = registry
            
            new_graph_cls = import_node_definition(graph_def, self.scene._NODE_DEFINITIONS)
            
            # if the scene NODE_DEFINITIONS does not currently have scene/SceneLoop base
            # type module in it and the incoming graph is a scene/SceneLoop, then set_as_main
            # to True
            set_as_main = False
            
            if isinstance(graph, SceneLoop):
                set_as_main = True
                for scene_node in self.scene._NODE_DEFINITIONS.values():
                    log.warning("checking base type", base_type=scene_node.base_type)
                    if scene_node.base_type == "scene/SceneLoop":
                        log.warning("found scene loop", scene_node=scene_node)
                        set_as_main = False
                        break
            
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
        # await self.handle_request_node_library({})
        
    
    async def handle_request_node_module(self, data: dict):
        
        request = RequestNodeModule(**data)
        
        graph, path_info = load_graph(request.path, search_paths=[self.scene.nodes_dir])
        
        export_nodes = ExportNodeModule(
            graph = export_flat_graph(graph),
            node_definitions = export_node_definitions(),
            path_info = path_info,
        )
        
        #with open("exported_nodes.json", "w") as file:
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
            node_cls = import_node_definition(graph.model_dump(), self.scene._NODE_DEFINITIONS, reimport=True)
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
            return await self.signal_operation_failed("Cannot delete node module outside of scene directory")
        
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
        
        scene = self.scene
        payload = RequestTestRun(**data)
        
        graph = import_flat_graph(payload.graph)
        
        active_graph_state:GraphState = scene.nodegraph_state
        
        async def on_error(state:GraphState, error:Exception):
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
            
        async def on_done(state:GraphState):
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
        
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "test_started",
                "data": payload.model_dump(),
            }
        )
        
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
        
    async def _stop_test(self):
        active_graph_state:GraphState = self.scene.nodegraph_state
        module = active_graph_state.shared.pop("__test_module", None)
        
        if not module:
            return
        
        task = active_graph_state.shared.pop(f"__run_{module.id}", None)
        if task:
            task.cancel()
        
    @requires_creative_environment
    async def handle_release_breakpoint(self, data: dict):
        active_graph_state:GraphState = self.scene.nodegraph_state
        active_graph_state.shared.pop("__breakpoint", None)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "breakpoint_released",
                "data": {},
            }
        )