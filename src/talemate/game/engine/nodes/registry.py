import os
import json
import re
import structlog
import traceback
from typing import TYPE_CHECKING
from pathlib import Path
from talemate.context import active_scene
from talemate.util.data import JSONEncoder

from talemate.game.engine.nodes.base_types import base_node_type
from talemate.game.engine.nodes import SEARCH_PATHS

if TYPE_CHECKING:
    from .core import NodeBase
    from talemate.tale_mate import Scene

__all__ = [
    'register', 
    'get_node', 
    'NODES', 
    'export_node_definitions',
    'import_node_definitions',
    'import_node_definition',
    'import_scene_node_definitions',
    'import_talemate_node_definitions',
    'normalize_registry_name',
    'get_nodes_by_base_type',
    'validate_registry_path',
]

log = structlog.get_logger("talemate.game.engine.nodes.registry")

NODES = {}

INITIAL_IMPORT_DONE = False

def normalize_registry_name(name:str) -> str:
    """
    Will normalize a registry name to a consistent format of
    camel case with no spaces or special characters.
    
    Arguments:
        name (str): Name to normalize
    
    Examples:
    
    - "My Node" -> "myNode"
    - "My-Node" -> "myNode"
    - "My Other Node" -> "myOtherNode"    
    """
    
    name = name.title()
    
    # first letter lowercase
    name = name[0].lower() + name[1:]

    # remove spaces and special characters
    name = re.sub(r"[^a-zA-Z0-9]", "", name)

    return name

def get_node(name):
    if not name:
        return None
    
    scene:"Scene" = active_scene.get()
    
    SCENE_NODES = getattr(scene, "_NODE_DEFINITIONS", {})
    
    if name in SCENE_NODES:
        return SCENE_NODES[name]
    
    cls = NODES.get(name)
    if not cls:
        raise ValueError(f"Node type '{name}' not found")
    return cls

def get_nodes_by_base_type(base_type:str) -> list["NodeBase"]:
    """
    Returns a list of all nodes that have the given base type.
    
    Will check both the scene and the talemate node definitions.
    
    Scene nodes take priority if both register the same node.
    """
    
    scene:"Scene" = active_scene.get()
    
    SCENE_NODES = getattr(scene, "_NODE_DEFINITIONS", {})
    
    nodes = {}
    
    
    for node_name, node_cls in NODES.items():
        if node_cls._base_type == base_type:
            nodes[node_name] = node_cls
    
    for node_name, node_cls in SCENE_NODES.items():
        if node_cls._base_type == base_type:
            nodes[node_name] = node_cls
            
    return list(nodes.values())

class register:
    def __init__(self, name, as_base_type:bool=False, container:dict|None=None):
        self.name = name
        self.as_base_type = as_base_type
        self.container = container or NODES

    def __call__(self, cls):
        self.container[self.name] = cls
        cls._registry = self.name
        
        if self.as_base_type:
            base_node_type(self.name)(cls)
        return cls

def validate_registry_path(path:str, node_definitions:dict | None = None):
    """
    Validates a registry path to ensure it is a valid path.
    
    Arguments:
    
    - path (str): The registry path to validate
    - node_definitions (dict): The node definitions to validate against
    
    Raises:
    
    - ValueError: if the path is invalid
    """
    
    if not node_definitions:
        node_definitions = export_node_definitions()
    
    if not path:
        raise ValueError("Empty registry path")
    
    # path needs to have at least one / with two parts
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError("Registry path must contain at least two parts (e.g., 'my/node')")
    
    # the path can not be the prefix of an existing path
    # e.g., can't put a node where a path is already registered
    for existing_path in node_definitions["nodes"].keys():
        if existing_path.startswith(path + "/"):
            raise ValueError(f"Registry path {path} is colliding with {existing_path}")
        
        
def export_node_definitions() -> dict:
    export = {
        "nodes": []
    }
    
    scene:"Scene" = active_scene.get()
    
    libraries = {
        **NODES
    }
    
    if hasattr(scene, "_NODE_DEFINITIONS"):
       libraries.update(scene._NODE_DEFINITIONS)
       
    for name, node_cls in libraries.items():
        
        try:
            node:"NodeBase" = node_cls()
        except ValueError as exc:
            log.warning("export_node_definitions: failed to instantiate node class", name=name)
            continue
        
        if not node._export_definition:
            continue
        
        field_defs = {}
        
        for prop_name in node.properties.keys():
            field_defs[prop_name] = node.get_property_field(prop_name).model_dump()
            
        if hasattr(node, "module_properties"):
            for prop_name, prop_data in node.module_properties.items():
                field_defs[prop_name] = prop_data.model_dump()
        
        exported_node = {
            "fields": field_defs,
            **node.model_dump()
        }
        
        exported_node.pop("nodes", None)
        exported_node.pop("edges", None)
        
        export["nodes"].append(exported_node)
        
    # sort
    export["nodes"] = {
        n["registry"]: n for n in sorted(export["nodes"], key=lambda x: x["registry"])
    }
    
    #with open("exported_nodes.json", "w") as file:
    #    json.dump(export, file, indent=2, cls=JSONEncoder)
        
    return export

def import_initial_node_definitions():
    global INITIAL_IMPORT_DONE
    if INITIAL_IMPORT_DONE:
        return
    
    import_talemate_node_definitions()
    INITIAL_IMPORT_DONE = True

def import_talemate_node_definitions():
    
    retry = []
    files = []

    for base_path in SEARCH_PATHS:
        base_path = Path(base_path)
        for path in base_path.rglob("*.json"):
            if path.is_file():
                files.append(str(path))
                #log.debug("import_talemate_node_definitions: found node definition", path=path)
                
    for filepath in files:
        with open(filepath, "r") as file:
            data = json.load(file)
            try:
                node_cls = import_node_definition(data)
                node_cls._module_path = filepath
            except Exception as exc:
                retry.append( (data, filepath) )

    attempt_retry = True
    while retry and attempt_retry:
        attempt_retry = False
        for data, filepath in retry:
            try:
                node_cls = import_node_definition(data)
                node_cls._module_path = filepath
                retry.remove( (data, filepath) )
                attempt_retry = True
            except Exception as exc:
                log.error("import_talemate_node_definitions: failed to import node definition", data=data["registry"], exc=traceback.format_exc())
                pass

def import_scene_node_definitions(scene:"Scene"):
    scene._NODE_DEFINITIONS = {}
        
    # loop files in scene.nodes_dir
    # and register the ones that have 'registry' specified
    # at the root level of the json file
    
    if not os.path.exists(scene.nodes_dir):
        return
    
    retries = []
    
    for filename in os.listdir(scene.nodes_dir):
        
        if not filename.endswith(".json"):
            continue
        
        #log.debug("import_scene_node_definitions: importing node definition", filename=filename)
        
        if filename == scene.nodes_filename:
            log.warning("import_scene_node_definitions: skipping scene nodes file", filename=filename)
            continue
        
        filepath = os.path.join(scene.nodes_dir, filename)
        
        with open(filepath, "r") as file:
            data = json.load(file)
        
        if not data.get("registry"):
            log.warning("import_scene_node_definitions: node definition missing registry, skipping", filename=filename)
            continue
        try:
            node_cls = import_node_definition(data, scene._NODE_DEFINITIONS)
            node_cls._module_path = filepath
        except Exception as exc:
            retries.append( (data, filepath) )
            
    attempt_retry = True
    while retries and attempt_retry:
        attempt_retry = False
        for data, filepath in retries:
            try:
                node_cls = import_node_definition(data, scene._NODE_DEFINITIONS)
                node_cls._module_path = filepath
                retries.remove( (data, filepath) )
                attempt_retry = True
            except Exception as exc:
                log.error("import_scene_node_definitions: failed to import node definition", data=data["registry"], exc=traceback.format_exc())
                pass
    
    
    
def import_node_definitions(data:dict):
    for node_data in data["nodes"]:
        import_node_definition(node_data)

def import_node_definition(node_data:dict, registry=None, reimport:bool=False) -> "NodeBase":
    
    """
    Imports a node definition from a dictionary and registers it in the NODES registry as
    a class.
    
    Arguments:
    
    - node_data (dict): The node definition data
    - registry (dict): The registry to register the node class in - defaults to NODES
    - reimport (bool): If True, will reimport the node class if it already exists in the registry, removing the old one first.
    """

    from .core import dynamic_node_import

    if registry is None:
        registry = NODES
        
    if reimport:
        registry.pop(node_data["registry"], None)
    
    try:
        node_cls = registry[node_data["registry"]]
    except KeyError:
        node_cls = dynamic_node_import(node_data, node_data["registry"], registry)
    
    node = node_cls()
    
    if "fields" in node_data:
        for prop_name, prop_data in node_data["fields"].items():
            field = node.get_property_field(prop_name)
            field.model_validate(prop_data)
        
    node.model_validate(node_data)
    
    registry[node_data["registry"]] = node_cls
    
    return node_cls
