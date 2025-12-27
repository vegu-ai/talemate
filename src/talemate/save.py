from typing import TYPE_CHECKING
import json
import os
import structlog
from talemate.scene_message import SceneMessage
from talemate.game.engine.nodes.core import Graph, UNRESOLVED
from talemate.game.engine.nodes.scene import SceneLoop

from talemate.game.engine.nodes.layout import save_graph

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.save")


def combine_paths(absolute, relative):
    # Split paths into components
    rel_parts = os.path.normpath(relative).split(os.sep)

    # Get just the filename/last component from relative path
    rel_end = rel_parts[-1]

    # Join absolute path with just the final component
    return os.path.join(absolute, rel_end)


class SceneEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, SceneMessage):
            return obj.__dict__()
        if obj is UNRESOLVED:
            return None
        return super().default(obj)


async def save_node_module(
    scene: "Scene", graph: "Graph", filename: str = None, set_as_main: bool = False
) -> str:
    if not os.path.exists(scene.nodes_dir):
        os.makedirs(scene.nodes_dir)

    if isinstance(graph, SceneLoop) and set_as_main:
        scene.nodes_filename = filename or "scene-loop.json"
        log.debug("saving scene nodes", filename=scene.nodes_filepath)
        await save_graph(graph, scene.nodes_filepath)
        return scene.nodes_filepath
    else:
        if not filename:
            raise ValueError("filename is required for non SceneLoop nodes")

        # filename make contain relative path
        # scenes.node_dir is the base path (absolute)

        save_to_path = combine_paths(scene.nodes_dir, filename)

        log.debug("saving nodes", filename=save_to_path)
        await save_graph(graph, save_to_path)
        return save_to_path
