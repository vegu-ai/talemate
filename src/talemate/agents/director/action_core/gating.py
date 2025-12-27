"""
Gating utilities for DirectorChatSubAction nodes.

Provides static (non-executing) extraction of sub-action descriptors from
DirectorChatAction graphs and denylist-based gating checks.
"""

import pydantic
import structlog
from typing import Literal, TYPE_CHECKING

from talemate.game.engine.nodes.registry import get_nodes_by_base_type
from talemate.game.engine.nodes.core import Graph, UNRESOLVED, GraphState, Node

if TYPE_CHECKING:
    from talemate.agents.director import DirectorAgent

log = structlog.get_logger("talemate.agents.director.action_core.gating")

__all__ = [
    "CallbackDescriptor",
    "extract_callback_descriptors",
    "extract_all_callback_descriptors",
    "is_action_id_enabled",
    "get_disabled_action_ids",
    "ActionMode",
]

ActionMode = Literal["chat", "scene_direction"]

CALLBACK_NODE_REGISTRY = "agents/director/chat/DirectorChatSubAction"


class CallbackDescriptor(pydantic.BaseModel):
    """
    Lightweight representation of a DirectorChatSubAction node's properties,
    extracted without executing the graph.
    """

    action_id: str
    action_title: str = ""
    group: str = ""
    description_chat: str = ""
    description_scene_direction: str = ""
    instruction_examples: list[str] = pydantic.Field(default_factory=list)
    availability: Literal["both", "chat", "scene_direction"] = "both"
    force_enabled: bool = False

    # Parent action name (from the DirectorChatAction graph)
    parent_action_name: str = ""

    def get_description(self, mode: ActionMode) -> str:
        """Return mode-appropriate description, falling back to the other if not set."""
        if mode == "chat":
            return self.description_chat or self.description_scene_direction or ""
        return self.description_scene_direction or self.description_chat or ""


async def _evaluate_sub_action_condition(
    node: Node, state: GraphState, graph: Graph
) -> bool:
    try:
        condition_socket = node.get_input_socket("condition")
        if condition_socket and condition_socket.source:
            condition_fn = condition_socket.source.node
            condition_fn_wrapper = await condition_fn.get_function(graph, state)
            result = await condition_fn_wrapper()
            return result
        else:
            return True
    except Exception as e:
        log.error(
            "director.action_core.gating.evaluate_sub_action_condition.error",
            error=e,
            node=node,
        )
        return True


async def _extract_callbacks_from_graph(
    graph: Graph,
    parent_action_name: str,
    evaulate_conditions: bool = True,
) -> list[CallbackDescriptor]:
    """
    Extract CallbackDescriptor instances from a graph's direct nodes.

    Only looks at nodes directly inside the graph, not subgraphs.

    Args:
        graph: The graph to inspect
        parent_action_name: Name of the top-level DirectorChatAction

    Returns:
        List of CallbackDescriptor instances found in the graph
    """

    state = GraphState()
    graph = Graph(**graph.model_dump())
    graph.reset()
    state.graph = graph

    callback_nodes = [
        node for node in graph.nodes.values() if node.registry == CALLBACK_NODE_REGISTRY
    ]

    descriptors: list[CallbackDescriptor] = []
    for node in callback_nodes:
        action_id = node.get_property("action_id")
        if action_id and action_id != UNRESOLVED:
            availability = node.get_property("availability") or "both"
            if availability not in ["both", "chat", "scene_direction"]:
                availability = "both"
            force_enabled = node.get_property("force_enabled") or False

            if evaulate_conditions:
                condition_result = await _evaluate_sub_action_condition(
                    node, state, graph
                )
                if not condition_result:
                    continue

            descriptors.append(
                CallbackDescriptor(
                    action_id=action_id,
                    action_title=node.get_property("action_title") or "",
                    group=node.get_property("group") or "",
                    description_chat=node.get_property("description_chat") or "",
                    description_scene_direction=node.get_property(
                        "description_scene_direction"
                    )
                    or "",
                    instruction_examples=node.get_property("instruction_examples")
                    or [],
                    availability=availability,
                    force_enabled=force_enabled,
                    parent_action_name=parent_action_name,
                )
            )

    return descriptors


async def extract_callback_descriptors(action_name: str) -> list[CallbackDescriptor]:
    """
    Extract all CallbackDescriptor instances from a specific DirectorChatAction
    by its registered name.

    Args:
        action_name: The name property of the DirectorChatAction

    Returns:
        List of CallbackDescriptor instances found in the action's graph
    """
    for node_cls in get_nodes_by_base_type("agents/director/DirectorChatAction"):
        node = node_cls()
        if node.get_property("name") == action_name:
            if isinstance(node, Graph):
                return await _extract_callbacks_from_graph(node, action_name)
    return []


async def extract_all_callback_descriptors(
    evaulate_conditions: bool = True,
) -> dict[str, list[CallbackDescriptor]]:
    """
    Extract CallbackDescriptor instances from all registered DirectorChatAction graphs.

    Returns:
        Dict mapping action names to their list of CallbackDescriptor instances
    """
    result: dict[str, list[CallbackDescriptor]] = {}

    for node_cls in get_nodes_by_base_type("agents/director/DirectorChatAction"):
        node = node_cls()
        action_name = node.get_property("name")
        if action_name and isinstance(node, Graph):
            descriptors = await _extract_callbacks_from_graph(
                node, action_name, evaulate_conditions
            )
            if descriptors:
                result[action_name] = descriptors

    return result


def get_disabled_action_ids(mode: ActionMode, director: "DirectorAgent") -> list[str]:
    """
    Get the list of disabled action_ids for a given mode from scene state.

    Args:
        mode: "chat" or "scene_direction"
        director: The director agent instance

    Returns:
        List of disabled action_id strings (denylist)
    """
    # Read from scene state instead of agent config
    disabled_sub_actions = director.get_scene_state("disabled_sub_actions", default={})

    if not isinstance(disabled_sub_actions, dict):
        return []

    # Get the list for the specific mode
    mode_disabled = disabled_sub_actions.get(mode, [])

    if isinstance(mode_disabled, list):
        return mode_disabled
    return []


def is_action_id_enabled(
    mode: ActionMode,
    action_id: str,
    director: "DirectorAgent",
    descriptor: CallbackDescriptor,
) -> bool:
    """
    Check if a specific action_id is enabled for the given mode.

    Applies availability and force_enabled overrides from the descriptor,
    then checks the denylist if needed.

    Args:
        mode: "chat" or "scene_direction"
        action_id: The action_id to check
        director: The director agent instance
        descriptor: CallbackDescriptor with availability/force_enabled info

    Returns:
        True if enabled, False if disabled
    """
    # Check availability first (hard override)
    if descriptor.availability != "both" and descriptor.availability != mode:
        return False

    # If force_enabled is true, skip denylist check
    if descriptor.force_enabled:
        return True

    # Check denylist
    disabled = get_disabled_action_ids(mode, director)
    return action_id not in disabled


async def get_all_callback_choices(
    mode: ActionMode | None = None,
    director: "DirectorAgent | None" = None,
    evaulate_conditions: bool = True,
) -> list[dict[str, str | bool]]:
    """
    Get all callback action_ids as choices for the flags config.

    Args:
        mode: Optional mode to filter by availability. If provided, only returns
              choices available in that mode.
        director: Optional director agent instance. Required if mode is provided
                  to check force_enabled status.

    Returns:
        List of dicts with 'label', 'value', and optionally 'locked' keys
    """
    all_descriptors = await extract_all_callback_descriptors(evaulate_conditions)
    choices: list[dict[str, str | bool]] = []
    seen_ids: set[str] = set()

    for action_name, descriptors in all_descriptors.items():
        for desc in descriptors:
            if desc.action_id and desc.action_id not in seen_ids:
                # Filter by availability if mode is provided
                if mode is not None:
                    if desc.availability != "both" and desc.availability != mode:
                        continue

                seen_ids.add(desc.action_id)
                # Use action_title if available, otherwise use action_id
                label = desc.action_title or desc.action_id
                if desc.group:
                    label = f"[{desc.group}] {label}"

                choice: dict[str, str | bool] = {
                    "label": label,
                    "value": desc.action_id,
                }

                # Add locked status if director is provided
                if director is not None and desc.force_enabled:
                    choice["locked"] = True

                choices.append(choice)

    # Sort by label for better UX
    choices.sort(key=lambda x: str(x["label"]))
    return choices
