"""
Utility functions for director action features.

These are standalone functions with explicit parameters to avoid
MRO issues when used in diamond inheritance scenarios.
"""

import json
import structlog
import traceback
from typing import Any, TYPE_CHECKING, Callable, Awaitable, Literal

from talemate.prompts.base import Prompt
from talemate.game.engine.nodes.registry import get_nodes_by_base_type, get_node
from talemate.game.engine.nodes.core import GraphState, UNRESOLVED
import talemate.game.focal as focal
from talemate.game.engine.nodes.run import FunctionWrapper
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.context_id import get_meta_groups
from talemate.util.data import extract_data_with_ai_fallback
import talemate.util as util
from talemate.util.prompt import (
    parse_response_section,
    parse_decision_section,
    extract_actions_block,
    clean_visible_response,
    auto_close_tags,
)
from talemate.instance import get_agent

from .schema import (
    ActionCoreFunctionAvailable,
    ActionCoreBudgets,
    ActionCoreCallbackGroup,
)
from .exceptions import ActionRejected, UnknownAction
from .gating import (
    ActionMode,
    CallbackDescriptor,
    is_action_id_enabled,
    extract_all_callback_descriptors,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.client import ClientBase
    from talemate.agents.director import DirectorAgent

log = structlog.get_logger("talemate.agent.director.action_core.utils")

__all__ = [
    "init_action_nodes",
    "get_available_actions",
    "parse_response",
    "extract_actions",
    "clean_response",
    "reverse_trim_history",
    "compact_if_needed",
    "build_prompt_vars",
    "request_and_parse",
    "execute_actions",
    "serialize_history",
]


async def init_action_nodes(scene: "Scene", state: GraphState) -> None:
    """Initialize action nodes from the registry into shared state."""
    log.debug("action_core.init_nodes")

    director_chat_actions = {}

    for node_cls in get_nodes_by_base_type("agents/director/DirectorChatAction"):
        _node = node_cls()
        action_name = _node.get_property("name")
        director_chat_actions[action_name] = _node.registry
        log.debug("action_core.init_nodes.action", action_name=action_name)

    state.shared["_director_chat_actions"] = director_chat_actions

    # Update callback choices now that actions are loaded
    director = get_agent("director")
    if director and hasattr(director, "update_callback_choices"):
        director.update_callback_choices()


def _build_callback_groups(
    descriptors: list[CallbackDescriptor],
    mode: ActionMode,
    director: "DirectorAgent",
) -> list[ActionCoreCallbackGroup]:
    """
    Build structured callback groups from callback descriptors, filtering by gating.

    Args:
        descriptors: List of CallbackDescriptor for this action
        mode: "chat" or "scene_direction"
        director: The director agent instance

    Returns:
        List of ActionCoreCallbackGroup with enabled sub-actions, or empty list
    """
    enabled_descs: list[CallbackDescriptor] = []

    for desc in descriptors:
        if is_action_id_enabled(mode, desc.action_id, director, descriptor=desc):
            enabled_descs.append(desc)

    if not enabled_descs:
        return []

    # Group by group name
    groups: dict[str, list[CallbackDescriptor]] = {}
    for desc in enabled_descs:
        group_name = desc.group or "General"
        if group_name not in groups:
            groups[group_name] = []
        groups[group_name].append(desc)

    callback_groups: list[ActionCoreCallbackGroup] = []

    for group_name in sorted(groups.keys()):
        group_descs = groups[group_name]
        callbacks: list[dict[str, Any]] = []

        for desc in group_descs:
            title = desc.action_title or desc.action_id
            mode_desc = desc.get_description(mode)

            callback_data: dict[str, Any] = {
                "title": title,
                "description": mode_desc or "",
            }

            # Add instruction examples if available
            if desc.instruction_examples:
                callback_data["examples"] = desc.instruction_examples

            callbacks.append(callback_data)

        callback_groups.append(
            ActionCoreCallbackGroup(group_name=group_name, callbacks=callbacks)
        )

    return callback_groups


async def get_available_actions(
    scene: "Scene",
    mode: ActionMode = "chat",
) -> list[ActionCoreFunctionAvailable]:
    """
    Get available actions from the shared registry with mode-aware descriptions.

    Args:
        scene: The current scene
        mode: "chat" or "scene_direction" - affects which descriptions are shown
              and which callbacks are considered enabled

    Returns:
        List of ActionCoreFunctionAvailable with mode-appropriate descriptions
    """
    state: GraphState = scene.nodegraph_state
    director: "DirectorAgent" = get_agent("director")

    actions: list[ActionCoreFunctionAvailable] = []

    director_chat_actions = state.shared.get("_director_chat_actions", {})
    log.debug(
        "action_core.available_actions",
        director_chat_actions=list(director_chat_actions.keys()),
        mode=mode,
    )

    # Get all callback descriptors upfront
    all_callbacks = await extract_all_callback_descriptors()

    for name, node_registry in director_chat_actions.items():
        node = get_node(node_registry)()
        description = node.get_property("description")

        if description is UNRESOLVED or not description:
            description = ""

        # Get callback descriptors for this action
        action_callbacks = all_callbacks.get(name, [])

        # Skip actions with no sub-actions (no DirectorChatSubAction nodes)
        if not action_callbacks:
            log.debug(
                "action_core.available_actions.skipped",
                action=name,
                reason="no_sub_actions",
                mode=mode,
            )
            continue

        # Check if there are any enabled callbacks for this mode
        enabled_count = sum(
            1
            for desc in action_callbacks
            if is_action_id_enabled(mode, desc.action_id, director, descriptor=desc)
        )

        # If all callbacks are disabled, skip this action entirely
        if enabled_count == 0:
            log.debug(
                "action_core.available_actions.skipped",
                action=name,
                reason="all_callbacks_disabled",
                mode=mode,
            )
            continue

        # Get structured callback groups
        callback_groups = _build_callback_groups(action_callbacks, mode, director)

        actions.append(
            ActionCoreFunctionAvailable(
                name=name, description=description, callback_groups=callback_groups
            )
        )

    actions.sort(key=lambda x: x.name)
    return actions


def parse_response(
    response: str, section: Literal["message", "decision"] = "message"
) -> str | None:
    """
    Extract the primary response section from a response.

    Args:
        response: The response text to parse
        section: Which section to extract ("message" or "decision")

    Returns:
        The extracted content, or None if not found
    """
    if section == "decision":
        return parse_decision_section(response)
    return parse_response_section(response)


async def extract_actions(client: "ClientBase", response: str) -> list[dict] | None:
    """
    Extract and parse an <ACTIONS> section containing a typed JSON or YAML code block.
    Returns a list of {name, instructions} dicts or None if not found/parsable.
    """
    try:
        content = extract_actions_block(response)

        if not content:
            return None

        schema_format = (client.data_format or "json").lower()

        data_items = await extract_data_with_ai_fallback(
            client, content, Prompt, schema_format
        )

        if isinstance(data_items, dict):
            data_items = [data_items]
        if not isinstance(data_items, list):
            return None

        normalized = []
        for item in data_items:
            if isinstance(item, list):
                for sub in item:
                    if isinstance(sub, dict):
                        name = sub.get("name") or sub.get("function")
                        instructions = sub.get("instructions") or ""
                        if name:
                            normalized.append(
                                {
                                    "name": str(name),
                                    "instructions": str(instructions),
                                }
                            )
                continue
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("function")
            instructions = item.get("instructions") or ""
            if name:
                normalized.append(
                    {"name": str(name), "instructions": str(instructions)}
                )
        return normalized or None
    except Exception:
        return None


def clean_response(
    text: str, section: Literal["message", "decision"] = "message"
) -> str:
    """
    Remove action selection blocks and optionally decision blocks from user-visible text.

    Args:
        text: The text to clean
        section: Which section is the primary output ("message" or "decision")

    Returns:
        Cleaned text with special blocks removed
    """
    return clean_visible_response(text, section=section)


def reverse_trim_history(
    history: list[Any],
    budget_tokens: int,
) -> list[Any]:
    """
    Reverse-trim history to fit within a token budget.
    Walk from the end, include items until token count exceeds budget.
    Returns items in chronological order.
    """
    try:
        if not history or budget_tokens <= 0:
            return []

        def _count_item_tokens(message: Any) -> int:
            if message.type == "action_result":
                name_text = message.name or ""
                instr_text = message.instructions or ""
                try:
                    result_text = json.dumps(message.result, default=str)
                except Exception:
                    result_text = str(message.result)
                return util.count_tokens(
                    "\n".join([name_text, instr_text, result_text])
                )
            elif message.type == "user_interaction":
                return util.count_tokens(message.user_input or "")
            return util.count_tokens(message.message or "")

        selected_indices: list[int] = []
        total_tokens = 0

        for i in range(len(history) - 1, -1, -1):
            t = _count_item_tokens(history[i])
            if total_tokens + t <= budget_tokens:
                selected_indices.append(i)
                total_tokens += t
            else:
                break

        if not selected_indices:
            return []
        return [history[i] for i in reversed(selected_indices)]
    except Exception as e:
        log.error("action_core.reverse_trim_history.error", error=e)
        return [history[-1]] if history else []


async def compact_if_needed(
    messages: list[Any],
    budgets: ActionCoreBudgets,
    staleness_threshold: float,
    create_message: Callable[[str, str], Any],
    set_messages: Callable[[list[Any]], None],
    on_compacted: Callable[[list[Any]], Awaitable[None]] | None = None,
    on_compacting: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    """
    If history token size exceeds thresholds, summarize the stale part
    into a single message. Returns True when compaction occurred.

    Args:
        messages: Current message history
        budgets: Budget snapshot to use for thresholds
        staleness_threshold: Fraction of history budget to treat as stale
        create_message: Factory function(message, source) to create a message
        set_messages: Callback to persist new messages
        on_compacted: Optional callback after compaction
        on_compacting: Optional callback before compaction starts
    """
    if not messages:
        return False

    token_lengths: list[int] = [util.count_tokens(str(m)) for m in messages]
    total_tokens = sum(token_lengths)

    available = budgets.available
    ratio = budgets.scene_context_ratio
    history_budget = int((1 - ratio) * available)

    stale_threshold = int(staleness_threshold * history_budget)
    active_threshold = max(1, history_budget - stale_threshold)

    log.debug(
        "action_core.compact.check",
        total_tokens=total_tokens,
        stale_threshold=stale_threshold,
        active_threshold=active_threshold,
    )

    if total_tokens <= stale_threshold + active_threshold:
        return False

    if on_compacting:
        try:
            await on_compacting()
        except Exception:
            pass

    # Determine split index so that tail tokens <= active_threshold
    running = 0
    split_idx = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        running += token_lengths[i]
        if running > active_threshold:
            split_idx = i + 1
            break

    split_idx = min(max(1, split_idx), len(messages))
    stale_messages = messages[:split_idx]

    summary_text: str = ""
    try:
        summarizer = get_agent("summarizer")
        summary_text = await summarizer.summarize_director_chat(history=stale_messages)
    except Exception as e:
        log.error("action_core.compact.summarize.error", error=e)
        return False

    summary_message = create_message(
        f"Summary of earlier conversation: {summary_text}",
        "director",
    )
    new_messages = [summary_message] + messages[split_idx:]

    set_messages(new_messages)

    if on_compacted:
        try:
            await on_compacted(new_messages)
        except Exception as e:
            log.error("action_core.compact.on_compacted.error", error=e)

    log.info(
        "action_core.compacted",
        total_tokens=total_tokens,
        split_index=split_idx,
    )

    return True


async def build_prompt_vars(
    scene: "Scene",
    client: "ClientBase",
    history_for_prompt: list[Any],
    scene_snapshot: str,
    budgets: ActionCoreBudgets,
    enable_analysis: bool,
    scene_context_ratio: float,
    history_trim_fn: Callable[[list[Any], int], list[Any]],
    extra_vars: dict | None = None,
    mode: ActionMode = "chat",
) -> dict:
    """
    Construct prompt variables for action requests.

    Args:
        scene: The current scene
        client: The LLM client
        history_for_prompt: Chat/direction history
        scene_snapshot: Recent scene text
        budgets: Token budget configuration
        enable_analysis: Whether analysis step is enabled
        scene_context_ratio: Ratio for scene context allocation
        history_trim_fn: Function to trim history
        extra_vars: Additional template variables
        mode: "chat" or "scene_direction" - affects available_functions

    Returns:
        Dict of prompt template variables
    """
    vars = {
        "scene": scene,
        "max_tokens": client.max_token_length,
        "history": history_for_prompt,
        "scene_snapshot": scene_snapshot,
        "available_functions": await get_available_actions(scene, mode=mode),
        "enable_analysis": enable_analysis,
        "scene_context_ratio": scene_context_ratio,
        "useful_context_ids": await get_meta_groups(
            scene,
            filter_fn=lambda meta: meta.permanent,
        ),
        "budgets": budgets,
        "history_trim": history_trim_fn,
        "gamestate": scene.game_state.variables,
    }
    if extra_vars:
        vars.update(extra_vars)
    return vars


async def request_and_parse(
    client: "ClientBase",
    prompt_template: str,
    kind: str,
    prompt_vars: dict,
    max_retries: int = 0,
    response_section: Literal["message", "decision"] = "message",
) -> tuple[str | None, list[dict] | None, str]:
    """
    Make a Prompt.request for the given kind, with optional retries.
    Returns (parsed_response|None, actions_selected|None, raw_response).

    Args:
        client: The LLM client
        prompt_template: Template name for the prompt
        kind: The request kind/type
        prompt_vars: Variables for the prompt template
        max_retries: Maximum number of retries on missing response
        response_section: Which section to extract as the response ("message" or "decision")

    Returns:
        Tuple of (parsed_response, actions_selected, raw_response)
    """
    attempt = 0
    raw_response = ""
    parsed_response: str | None = None
    actions_selected: list[dict] | None = None

    while True:
        try:
            raw_response = await Prompt.request(
                prompt_template,
                client,
                kind=kind,
                vars=prompt_vars,
                dedupe_enabled=False,
            )
            log.debug("action_core.request.complete", template=prompt_template)
        except Exception as e:
            log.error("action_core.request.error", error=e, kind=kind)
            raw_response = ""

        # Auto-close unclosed XML-like tags before parsing
        # LLMs sometimes forget to close tags like <ANALYSIS> before starting <MESSAGE>
        repaired_response = auto_close_tags(raw_response) if raw_response else ""

        actions_selected = (
            await extract_actions(client, repaired_response)
            if repaired_response
            else None
        )
        parsed_response = parse_response(repaired_response, section=response_section)

        has_actions = bool(actions_selected)

        is_valid = bool((parsed_response and parsed_response.strip()) or has_actions)
        if is_valid or attempt >= max_retries:
            break
        attempt += 1
        log.warn(
            "action_core.retry_missing_response",
            attempt=attempt,
            max_retries=max_retries,
            kind=kind,
        )

    if parsed_response:
        parsed_response = clean_response(parsed_response, section=response_section)
    return parsed_response, actions_selected, raw_response


async def execute_actions(
    client: "ClientBase",
    scene: "Scene",
    actions_selected: list[dict],
    history_for_prompt: list[Any],
    create_result: Callable[..., Any],
    on_action_complete: Callable[[Any], Awaitable[None]] | None = None,
) -> list[Any]:
    """
    Execute selected actions via FOCAL and return result messages.

    Args:
        client: The LLM client
        scene: The current scene
        actions_selected: List of {name, instructions} dicts
        history_for_prompt: Current history for prompt context
        create_result: Factory function to create result messages
        on_action_complete: Optional callback after each action completes

    Returns:
        List of action result messages
    """
    # Import here to avoid circular imports
    from talemate.agents.director.chat.nodes import DirectorChatActionArgument

    state: GraphState = scene.nodegraph_state
    director_chat_actions = state.shared.get("_director_chat_actions", {})

    callbacks: list[focal.Callback] = []
    ordered_callbacks: list[focal.Callback] = []
    ordered_instructions: dict[str, str] = {}
    ordered_examples: dict[str, list] = {}
    selection_instructions: dict[str, str] = {}
    ordered_argument_usage: dict[str, dict[str, str]] = {}
    has_character_callback = False

    # Validate all actions exist
    for selection in actions_selected:
        name = selection["name"]
        selection_instructions[name] = selection.get("instructions") or ""
        node_registry = director_chat_actions.get(name)
        if not node_registry:
            raise UnknownAction(name)

    # Build callbacks
    for selection in actions_selected:
        name = selection["name"]
        selection_instructions[name] = selection.get("instructions") or ""
        node_registry = director_chat_actions.get(name)
        node = get_node(node_registry)()

        fn = FunctionWrapper(node, node, state)

        try:
            arg_nodes = await fn.get_argument_nodes(
                filter_fn=lambda node: isinstance(node, DirectorChatActionArgument)
            )
        except Exception as e:
            log.error(
                "action_core.get_argument_nodes.error",
                error=e,
                action=name,
            )
            arg_nodes = []

        arguments = [
            focal.Argument(name=arg.get_property("name"), type=arg.get_property("typ"))
            for arg in arg_nodes
        ]

        has_character_callback = has_character_callback or any(
            arg.get_property("name") == "character" for arg in arg_nodes
        )

        async def _make_fn(wrapper, action_name: str):
            async def _call(**kwargs):
                try:
                    return await wrapper(**kwargs)
                except ActionRejected:
                    raise
                except InputValueError as e:
                    log.error(
                        "action_core.action.error",
                        error=traceback.format_exc(),
                        action=action_name,
                    )
                    return f"Error executing action: {e}"

            _call.__name__ = f"action_{action_name}"
            return _call

        cb_fn = await _make_fn(fn, name)
        cb = focal.Callback(name=name, arguments=arguments, fn=cb_fn, multiple=True)
        callbacks.append(cb)
        ordered_callbacks.append(cb)

        try:
            inst = node.get_property("instructions") or ""
        except Exception:
            inst = ""
        ordered_instructions[name] = inst
        ordered_argument_usage[name] = {
            arg.get_property("name"): (arg.normalized_input_value("instructions") or "")
            for arg in arg_nodes
        }

        try:
            examples_raw = node.get_property("example_json") or ""
            ex_list = []
            if isinstance(examples_raw, str) and examples_raw.strip():
                try:
                    ex = json.loads(examples_raw)
                    if isinstance(ex, dict):
                        ex_list = [ex]
                    elif isinstance(ex, list):
                        ex_list = ex
                except Exception as e:
                    log.error(
                        "action_core.example_json.parse.error",
                        action=name,
                        error=e,
                    )
                    ex_list = []
            ordered_examples[name] = ex_list
        except Exception:
            ordered_examples[name] = []

    if not ordered_callbacks:
        return []

    log.debug(
        "action_core.actions.execute.start",
        selections=actions_selected,
        callbacks=[cb.name for cb in callbacks],
    )

    result_messages: list[Any] = []

    focal_handler = focal.Focal(
        client,
        callbacks=callbacks,
        max_calls=len(ordered_callbacks) + 2,
        retries=0,
        response_length=2048,
        scene=scene,
        history=history_for_prompt,
        selections=actions_selected,
        ordered_callbacks=ordered_callbacks,
        callbacks_unique=callbacks,
        ordered_instructions=ordered_instructions,
        ordered_examples=ordered_examples,
        ordered_reasons=selection_instructions,
        ordered_argument_usage=ordered_argument_usage,
        has_character_callback=has_character_callback,
    )

    async def on_call_complete(call: focal.Call):
        if call.name not in ordered_instructions:
            return
        action_msg = create_result(
            name=call.name,
            arguments=call.arguments or {},
            result=call.result,
            instructions=selection_instructions.get(call.name),
        )
        result_messages.append(action_msg)
        if on_action_complete:
            await on_action_complete(action_msg)

    with focal.FocalContext() as focal_context:
        focal_context.hooks_after_call.append(on_call_complete)
        await focal_handler.request("director.chat-execute-actions")

    log.debug(
        "action_core.actions.execute.done",
        calls=[
            {"name": c.name, "called": c.called}
            for c in getattr(focal_handler.state, "calls", [])
        ],
    )

    return result_messages


def serialize_history(
    messages: list[Any],
    serialize_fn: Callable[[Any], Any | None],
) -> list[Any]:
    """
    Prepare history for the prompt template.
    Returns a list of normalized message objects.
    """
    serialized: list[Any] = []
    for raw_message in messages:
        item = serialize_fn(raw_message)
        if item:
            serialized.append(item)
    return serialized
