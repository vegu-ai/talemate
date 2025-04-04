import json
import os
import aiofiles
import pydantic
import structlog
from pathlib import Path
from .core import Graph, UNRESOLVED, NodeBase, Group, Comment, load_extended_components, SaveContext
from .registry import get_node
from .base_types import get_base_type
from talemate.game.engine.nodes import SEARCH_PATHS, TALEMATE_ROOT

__all__ = [
    'load_graph',
    'save_graph',
    'export_flat_graph',
    'import_flat_graph',
    'list_node_files',
    'PathInfo',
    'JSONEncoder',
    'normalize_node_filename',
    'load_graph_from_file',
]

log = structlog.get_logger("talemate.game.engine.nodes.layout")

class PathInfo(pydantic.BaseModel):
    full_path: str
    relative_path: str
    search_paths: list[str] = pydantic.Field(default_factory=list)

class JSONEncoder(json.JSONEncoder):
    """
    Will serialize unknowns to strings
    """
    
    def default(self, obj):
        
        if isinstance(obj, UNRESOLVED):
            return None
        
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def list_node_files(search_paths: list[str] = None, dedupe:bool=True) -> list[str]:
    if search_paths is None:
        search_paths = SEARCH_PATHS.copy()
    else:
        search_paths = search_paths.copy() + SEARCH_PATHS.copy()
        
    files = []
    
    for base_path in search_paths:
        base_path = Path(base_path)
        for path in base_path.rglob("*.json"):
            if path.is_file():
                files.append(str(path))
                
    # we want semi relative paths, based of the talemate root dir
    files = [os.path.relpath(file, TALEMATE_ROOT) for file in files]
    
    # if dedupe is true we want to dedupe from the back (E.g., the first file found is the one we want)
    # this is for the filename, NOT the relative path
    if dedupe:
        deduped = []
        _files = []
        for relative_path in files:
            filename = os.path.basename(relative_path)
            if filename not in deduped:
                deduped.append(filename)
                _files.append(relative_path)
                
        files = _files
                
    return files

def export_flat_graph(graph:"Graph") -> dict:
    flat = {
        "nodes": [],
        "connections": [],
        "groups": [group.model_dump() for group in graph.groups],
        "comments": [comment.model_dump() for comment in graph.comments],
        "properties": graph.model_dump().get("properties", {}),
        "fields": {
            name: field.model_dump() for name, field in graph.field_definitions.items()
        },
        "registry": graph.registry,
        "base_type": graph.base_type,
        "title": graph.title,
        "extends": graph.extends,
    }
    
    graph.set_node_references()
    graph.set_socket_source_references()
    graph.ensure_connections()
    
    for node in graph.nodes.values():
        flat_node:dict = {
            "id": node.id,
            "registry": node.registry,
            "properties": node.properties,
            "x": node.x,
            "y": node.y,
            "width": node.width,
            "height": node.height,
            "parent": graph.id,
            "title": node.title,
            "collapsed": node.collapsed,
            "inherited": node.inherited,
        }
        flat["nodes"].append(flat_node)
        
        for input in node.inputs:
            
            if not input.source:
                continue
            
            flat["connections"].append({
                "from": input.source.full_id,
                "to": input.full_id,
            })
            
    return flat

def import_flat_graph(flat_data: dict, main_graph:"Graph" = None) -> Graph:
    """
    Import a flat graph representation and return a Graph object, handling nested graphs.
    
    Args:
        flat_data (dict): Dictionary containing flattened graph data with 'nodes' and 'connections' lists
        
    Returns:
        Graph: Reconstructed Graph object with all nodes and connections
        
    The flat_data format should be:
    {
        "nodes": [
            {
                "id": str,
                "registry": str,
                "properties": dict,
                "x": int,
                "y": int,
                "width": int, 
                "height": int,
                "parent": str | None  # ID of parent node if nested, None if top-level
            },
            ...
        ],
        "connections": [
            {
                "from": "node_id.socket_name",
                "to": "node_id.socket_name"
            },
            ...
        ],
        "groups": [
            {
                "title": str,
                "x": int,
                "y": int,
                "width": int,
                "height": int,
                "color": str,
                "font_size": int,
            },
            ...
        ],
        "registry": str  # Registry value for the main graph
        
    }
    """
    
    # if main_graph is not set get it from the root registry value
    if main_graph is None:
        main_graph_cls = get_node(flat_data["registry"])
        if not main_graph_cls:
            main_graph_cls = Graph
            
        if getattr(main_graph_cls, "__dynamic_imported__", False):
            main_graph = main_graph_cls(nodes={}, edges={}, groups=[], comments=[])
        else:
            main_graph = main_graph_cls()
    
    main_graph.properties = flat_data.get("properties", {})
    main_graph.extends = flat_data.get("extends", None)
    
    def create_mode_module(node_data: dict) -> NodeBase:
        """Helper function to create a node instance from node data"""
        node_cls = get_node(node_data["registry"])
        if not node_cls:
            raise ValueError(f"Unknown node type: {node_data['registry']}")
            
        node = node_cls(
            id=node_data["id"],
            x=node_data["x"],
            y=node_data["y"],
            width=node_data["width"],
            height=node_data["height"],
            title=node_data["title"],
            collapsed=node_data.get("collapsed", False),
        )
        
        
        # this needs to happen after the node is created
        # so that inputs and outputs are created
        node.properties = node_data["properties"]
        
        return node

    def add_connections(graph: Graph, connections: list, node_map: dict):
        """Helper function to add connections to a graph"""
        graph.edges = {}
        
        for connection in connections:
            if connection["from"] not in graph.edges:
                graph.edges[connection["from"]] = []
            
            if connection["to"] not in graph.edges[connection["from"]]:
                graph.edges[connection["from"]].append(connection["to"])

    node_map = {}  # Maps node IDs to node instances
    
    # First pass: Create all nodes and build hierarchy
    for node_data in flat_data["nodes"]:
        node = create_mode_module(node_data)
        node_map[node.id] = node
        
        # Add to parent if nested, otherwise to main graph
        parent_id = node_data.get("parent")
        if parent_id:
            if parent_id not in node_map:
                raise ValueError(f"Parent node {parent_id} not found for node {node.id}")
            parent_node = node_map[parent_id]
            if not hasattr(parent_node, "nodes"):
                raise ValueError(f"Parent node {parent_id} cannot contain other nodes")
            parent_node.add_node(node)
        else:
            main_graph.add_node(node)
    
    # Second pass: Create all connections
    add_connections(main_graph, flat_data["connections"], node_map)
    
    # Third pass: Rebuild groups
    for group_data in flat_data["groups"]:
        group = Group(**group_data)
        main_graph.groups.append(group)
        
    # Fourth pass: Rebuild comments
    for comment_data in flat_data["comments"]:
        comment = Comment(**comment_data)
        main_graph.comments.append(comment)       
        
    if main_graph.extends:
        graph_data = main_graph.model_dump()
        load_extended_components(main_graph.extends, graph_data)
        main_graph = main_graph.__class__(**graph_data)
        
    # Initialize the graph
    return main_graph.reinitialize()

def load_graph(file_name: str, search_paths: list[str] = None, graph_cls = None) -> tuple[Graph, PathInfo]:
    
    
    if search_paths is None:
        search_paths = SEARCH_PATHS.copy()
    else:
        search_paths = search_paths.copy() + SEARCH_PATHS.copy()

    # file_name may have path components, so we need to join it with the search paths
    # and then strip the path components to get the actual file name
    file_dir, file_name = os.path.split(file_name)
    if file_dir:
        for path in search_paths:
            path = Path(path) / file_dir
            if path.exists():
                search_paths = [path]
                break


    # Convert all search paths to Path objects
    search_paths = [Path(path) for path in search_paths]
    
    for base_path in search_paths:
        # Look for the file in current directory
        file_path = base_path / file_name
        if file_path.exists():
            return load_graph_from_file(file_path, graph_cls, search_paths)
                
        # Search recursively through subdirectories
        for path in base_path.rglob(file_name):
            if path.is_file():
                return load_graph_from_file(path, graph_cls, search_paths)

    raise FileNotFoundError(f"Could not find {file_name} in any of the search paths: {search_paths}")

def load_graph_from_file(file_path: str, graph_cls = None, search_paths: list[str] = None) -> tuple[Graph, PathInfo]:
    
    with open(file_path, 'r') as file:
        data = json.load(file)
        
        if data.get("extends"):
            load_extended_components(data["extends"], data)
        
        if not graph_cls:
            try:
                graph_cls = get_node(data["registry"])
            except ValueError:
                pass
        if not graph_cls:
            graph_cls = get_base_type(data["base_type"])
        if not graph_cls:
            graph_cls = Graph
        return graph_cls(**data).reinitialize(), PathInfo(
            full_path=str(file_path),
            relative_path=os.path.relpath(file_path, TALEMATE_ROOT),
            search_paths=[str(path) for path in search_paths] if search_paths else []
        )


async def save_graph(graph: Graph, file_path: str):
    with SaveContext():
        async with aiofiles.open(file_path, 'w') as file:
            await file.write(json.dumps(graph.model_dump(), indent=2, cls=JSONEncoder))
        
    
def normalize_node_filename(node_name:str) -> str:
    return node_name.lower().replace(" ", "-") + ".json"