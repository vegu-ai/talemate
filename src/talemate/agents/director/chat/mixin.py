import re
import json
import structlog
import traceback
from typing import Any, TYPE_CHECKING, Callable, Awaitable

from talemate.prompts.base import Prompt
from talemate.agents.base import set_processing, AgentAction, AgentActionConfig
from .schema import (
    DirectorChat,
    DirectorChatMessage,
    DirectorChatFunctionAvailable,
    DirectorChatActionResultMessage,
    DirectorChatBudgets,
)
from talemate.game.engine.nodes.registry import get_nodes_by_base_type, get_node
from talemate.game.engine.nodes.core import GraphState, UNRESOLVED
import talemate.game.focal as focal
from talemate.game.engine.nodes.run import FunctionWrapper
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.context_id import get_meta_groups
from talemate.util.data import extract_data_with_ai_fallback
import talemate.util as util
from talemate.instance import get_agent

from talemate.agents.director.chat.nodes import DirectorChatActionArgument
from talemate.agents.director.chat.exceptions import (
    DirectorChatActionRejected,
    UnknownDirectorChatAction,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.agent.director.chat")


class DirectorChatMixin:
    """
    Agent mixin that provides director chat management stored in scene agent state.

    Storage layout in scene.agent_state:
        scene.agent_state["director"]["chat"] = DirectorChat.model_dump()
    """

    CHAT_STATE_KEY = "chat"

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["chat"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Director Chat",
            icon="mdi-chat",
            description="Interactive chat interface for discussing and analyzing scenes with the director.",
            config={
                "enable_analysis": AgentActionConfig(
                    type="bool",
                    label="Enable Analysis Step",
                    description="Director does additional analysis before responding.",
                    value=True,
                ),
                "response_length": AgentActionConfig(
                    type="number",
                    label="Response token budget",
                    description="Maximum response length for director responses.",
                    value=2048,
                    step=256,
                    min=512,
                    max=4096,
                ),
                "auto_iterations_limit": AgentActionConfig(
                    type="number",
                    label="Auto-iteration limit",
                    description="Maximum number of response→actions→response cycles after a user message.",
                    value=1,
                    step=1,
                    min=1,
                    max=10,
                ),
                "missing_response_retry_max": AgentActionConfig(
                    type="number",
                    label="Retries",
                    description="How often to retry on malformed director responses.",
                    value=1,
                    step=1,
                    min=1,
                    max=10,
                ),
                "scene_context_ratio": AgentActionConfig(
                    type="number",
                    label="Scene context ratio",
                    description="Fraction of remaining token budget (after fixed context/instructions) reserved for scene context. The rest is for chat history. Example: 0.3 = 30% scene, 70% chat.",
                    value=0.3,
                    step=0.05,
                    min=0.05,
                    max=0.95,
                ),
                "staleness_threshold": AgentActionConfig(
                    type="number",
                    label="Stale history share",
                    description="When compacting, fraction of the chat-history budget treated as stale to summarize. The remainder is kept verbatim as recent tail. Higher values summarize less often but bigger chunks.",
                    value=0.7,
                    step=0.05,
                    min=0.05,
                    max=0.95,
                ),
                "custom_instructions": AgentActionConfig(
                    type="blob",
                    label="Custom instructions",
                    description="Custom instructions to add to the director chat.",
                    value="",
                ),
            },
        )

    # config property helpers

    @property
    def chat_missing_response_retry_max(self) -> int:
        """Maximum number of retries when <MESSAGE> tag is missing (only when analysis enabled)."""
        return int(self.actions["chat"].config["missing_response_retry_max"].value)

    @property
    def chat_auto_iterations_limit(self) -> int:
        """Maximum number of generate→act→generate cycles after a user message."""
        return int(self.actions["chat"].config["auto_iterations_limit"].value)

    @property
    def chat_response_length(self) -> int:
        """Stable response token budget for all director chat turns."""
        return int(self.actions["chat"].config["response_length"].value)

    @property
    def chat_scene_context_ratio(self) -> float:
        """Ratio of scene context versus director chat (0-1)."""
        return self.actions["chat"].config["scene_context_ratio"].value

    @property
    def chat_enable_analysis(self) -> bool:
        """Get whether analysis step is enabled"""
        return self.actions["chat"].config["enable_analysis"].value

    @property
    def chat_staleness_threshold(self) -> float:
        return self.actions["chat"].config["staleness_threshold"].value

    @property
    def chat_custom_instructions(self) -> str:
        return self.actions["chat"].config["custom_instructions"].value

    @classmethod
    async def init_nodes(cls, scene: "Scene", state: GraphState):
        log.debug("director.chat.init_nodes")

        director_chat_actions = {}

        for node_cls in get_nodes_by_base_type("agents/director/DirectorChatAction"):
            _node = node_cls()
            action_name = _node.get_property("name")
            director_chat_actions[action_name] = _node.registry
            log.debug("director.chat.init_nodes.action", action_name=action_name)

        state.shared["_director_chat_actions"] = director_chat_actions

    @property
    def chat_available_actions(self) -> list[DirectorChatFunctionAvailable]:
        state: GraphState = self.scene.nodegraph_state

        actions: list[DirectorChatFunctionAvailable] = []

        director_chat_actions = state.shared.get("_director_chat_actions", {})
        log.debug(
            "director.chat.available_actions.director_chat_actions",
            director_chat_actions=director_chat_actions,
        )

        for name, node_registry in director_chat_actions.items():
            node = get_node(node_registry)()
            description = node.get_property("description")

            if description is UNRESOLVED or not description:
                description = ""

            actions.append(
                DirectorChatFunctionAvailable(name=name, description=description)
            )

        # sort by name
        actions.sort(key=lambda x: x.name)

        return actions

    def chat_get_chat_state(self) -> dict[str, Any] | None:
        """Return the single chat dict if present, else None."""
        state = self.get_scene_state(self.CHAT_STATE_KEY, default=None)
        return state

    def chat_set_chat_state(self, state: dict[str, Any] | None):
        self.set_scene_states(**{self.CHAT_STATE_KEY: state})

    def _chat_initial_message(self) -> str:
        """Return initial Director chat message using persona override when present."""
        default_message = "Hey, how can I help you with this scene?"
        persona = self.scene.agent_persona("director")
        if persona and getattr(persona, "initial_chat_message", None):
            try:
                return persona.formatted("initial_chat_message", self.scene, "director")
            except Exception:
                return persona.initial_chat_message or default_message
        return default_message

    def chat_list(self) -> list[str]:
        """Return a list containing the single chat id if it exists."""
        raw = self.chat_get_chat_state()
        if not raw:
            return []
        try:
            if isinstance(raw, DirectorChat):
                return [raw.id]
            return [str(raw.get("id"))] if raw.get("id") else []
        except Exception:
            return []

    def _chat_singleton_id(self) -> str | None:
        ids = self.chat_list()
        return ids[0] if ids else None

    def chat_get(self, chat_id: str) -> DirectorChat | None:
        raw = self.chat_get_chat_state()
        if not raw:
            return None
        try:
            chat = raw if isinstance(raw, DirectorChat) else DirectorChat(**raw)
            # Honor the requested id if provided
            if chat_id and chat.id != chat_id:
                return None
            return chat
        except Exception as e:
            log.error("director.chat.get.error", chat_id=chat_id, error=e)
            return None

    def chat_create(self) -> DirectorChat:
        """Create a chat if none exists; otherwise return the existing one."""
        raw = self.chat_get_chat_state()
        if raw:
            return raw if isinstance(raw, DirectorChat) else DirectorChat(**raw)
        chat = DirectorChat(
            messages=[
                DirectorChatMessage(
                    message=self._chat_initial_message(),
                    source="director",
                ),
            ]
        )
        self.chat_set_chat_state(chat.model_dump())
        return chat

    def chat_clear(self, chat_id: str) -> bool:
        """Clear all messages from the chat while keeping the same chat id and preserving mode."""
        raw = self.chat_get_chat_state()
        if not raw:
            return False
        try:
            chat = raw if isinstance(raw, DirectorChat) else DirectorChat(**raw)
            if chat.id != chat_id:
                return False
            # Preserve the current mode when clearing messages
            current_mode = chat.mode
            chat.messages = [
                DirectorChatMessage(
                    message=self._chat_initial_message(),
                    source="director",
                )
            ]
            chat.mode = current_mode
        except Exception:
            return False
        self.chat_set_chat_state(chat.model_dump())
        return True

    # ------ Messages ------
    def chat_history(self, chat_id: str) -> list[DirectorChatMessage]:
        chat = self.chat_get(chat_id)
        return chat.messages if chat else []

    async def chat_append_message(
        self,
        chat_id: str,
        message: DirectorChatMessage,
        on_update: Callable[
            [str, list[DirectorChatMessage | DirectorChatActionResultMessage]],
            Awaitable[None],
        ]
        | None = None,
    ):
        chat: DirectorChat = self.chat_get(chat_id)
        chat.messages.append(message)
        self.chat_set_chat_state(chat.model_dump())
        if on_update:
            await on_update(chat_id, [message])

        return chat

    # ------ Compaction ------
    async def chat_compact_if_needed(
        self,
        chat_id: str,
        budgets_snapshot: DirectorChatBudgets,
        on_compacted: Callable[
            [str, list[DirectorChatMessage | DirectorChatActionResultMessage]],
            Awaitable[None],
        ]
        | None = None,
        on_compacting: Callable[[str], Awaitable[None]] | None = None,
    ) -> bool:
        """
        If chat token size exceeds stale+active thresholds, summarize the stale part
        into a single director message and replace it. Returns True when compaction occurred.
        """
        chat = self.chat_get(chat_id)
        if not chat or not chat.messages:
            return False

        # Build per-message token lengths and total directly on objects
        token_lengths: list[int] = [util.count_tokens(str(m)) for m in chat.messages]

        total_tokens = sum(token_lengths)
        # Derive thresholds strictly from provided budgets snapshot
        available = budgets_snapshot.available
        ratio = budgets_snapshot.scene_context_ratio
        history_budget = int((1 - ratio) * available)

        stale_threshold = int(self.chat_staleness_threshold * history_budget)
        active_threshold = max(1, history_budget - stale_threshold)

        log.debug(
            "director.chat.compact.total_tokens",
            total_tokens=total_tokens,
            stale_threshold=stale_threshold,
            active_threshold=active_threshold,
        )

        if total_tokens <= stale_threshold + active_threshold:
            return False

        # Notify UI that compaction will occur
        if on_compacting:
            try:
                await on_compacting(chat_id)
            except Exception:
                pass

        # Determine split index so that tail tokens <= active_threshold
        running = 0
        split_idx = len(chat.messages)
        for i in range(len(chat.messages) - 1, -1, -1):
            running += token_lengths[i]
            if running > active_threshold:
                split_idx = i + 1
                break

        # Ensure at least one message remains in active tail
        split_idx = min(max(1, split_idx), len(chat.messages))

        stale_messages = chat.messages[:split_idx]
        summary_text: str = ""
        try:
            summarizer = get_agent("summarizer")
            # Pass the stale chat history directly; template will render it
            summary_text = await summarizer.summarize_director_chat(
                history=stale_messages
            )
        except Exception as e:
            log.error("director.chat.compact.summarize.error", error=e)
            return False

        # Insert a single summary message to replace the stale region
        summary_message = DirectorChatMessage(
            message=f"Summary of earlier conversation: {summary_text}",
            source="director",
        )
        new_messages = [summary_message] + chat.messages[split_idx:]

        chat.messages = new_messages
        self.chat_set_chat_state(chat.model_dump())

        # Emit full history update to frontend if callback provided
        if on_compacted:
            try:
                await on_compacted(chat_id, new_messages)
            except Exception as e:
                log.error("director.chat.compact.on_compacted.error", error=e)

        # Also append a small note via normal update channel if available
        # so the user sees that compaction occurred in the stream.
        try:
            log.info(
                "director.chat.compacted",
                total_tokens=total_tokens,
                split_index=split_idx,
                stale_threshold=stale_threshold,
                active_threshold=active_threshold,
            )
        except Exception:
            pass

        return True

    # ------ Response parsing ------
    def chat_parse_response_section(self, response: str) -> str | None:
        """
        Extract the <MESSAGE> section using greedy regex preference:
        1) last <MESSAGE>...</MESSAGE> after </ANALYSIS>
        2) open-ended <MESSAGE>... to end after </ANALYSIS>
        3) same two fallbacks over entire response.
        """
        try:
            # Prefer only content after a closed analysis block.</analysis>
            # Find the index right after the first closing </ANALYSIS> (case-insensitive).
            tail_start = 0
            m_after = re.search(r"</ANALYSIS>", response, re.IGNORECASE)
            if m_after:
                tail_start = m_after.end()
            tail = response[tail_start:]

            # Step 1: Greedily capture the last closed <MESSAGE>...</MESSAGE> after </ANALYSIS>.
            # (?is) enables DOTALL and IGNORECASE. We match lazily inside to find each pair, then take the last.
            matches = re.findall(r"(?is)<MESSAGE>\s*([\s\S]*?)\s*</MESSAGE>", tail)
            if matches:
                return matches[-1].strip()

            # Step 2: If no closed block, capture everything after the first <MESSAGE> to the end (still after </ANALYSIS> if present).
            m_open = re.search(r"(?is)<MESSAGE>\s*([\s\S]*)$", tail)
            if m_open:
                return m_open.group(1).strip()

            # Step 3: Fall back to searching the entire response for a closed block and take the last one.
            matches_all = re.findall(
                r"(?is)<MESSAGE>\s*([\s\S]*?)\s*</MESSAGE>", response
            )
            if matches_all:
                return matches_all[-1].strip()

            # Step 4: Last resort, open-ended from <MESSAGE> to the end over the whole response.
            m_open_all = re.search(r"(?is)<MESSAGE>\s*([\s\S]*)$", response)
            if m_open_all:
                return m_open_all.group(1).strip()

            return None
        except Exception:
            log.error("director.chat.parse_response_section.error", response=response)
            return None

    async def chat_extract_actions_block(self, response: str) -> list[dict] | None:
        """
        Extract and parse an <ACTIONS> section containing a typed JSON or YAML code block.
        - Supports full <ACTIONS>...</ACTIONS>
        - Falls back to legacy ```actions ... ``` block
        - Tolerates a missing </ACTIONS> closing tag if the ACTIONS block is the final block
        - Tolerates a missing closing code fence ``` by capturing to </ACTIONS> or end-of-text
        Returns a list of {name, instructions} dicts or None if not found/parsable.
        """
        try:
            content: str | None = None

            # Prefer new <ACTIONS> ... ```(json|yaml) ... ``` ... </ACTIONS>
            match = re.search(
                r"<ACTIONS>\s*```(?:json|yaml)?\s*([\s\S]*?)\s*```\s*</ACTIONS>",
                response,
                re.IGNORECASE,
            )
            if match:
                content = match.group(1).strip()

            if content is None:
                # Accept missing </ACTIONS> if it's the final block and we at least have a closing code fence
                partial_fenced = re.search(
                    r"<ACTIONS>\s*```(?:json|yaml)?\s*([\s\S]*?)\s*```",
                    response,
                    re.IGNORECASE,
                )
                if partial_fenced:
                    content = partial_fenced.group(1).strip()

            if content is None:
                # Accept missing closing code fence by capturing to </ACTIONS> or end-of-text
                open_fence_to_end = re.search(
                    r"<ACTIONS>\s*```(?:json|yaml)?\s*([\s\S]*?)(?:</ACTIONS>|$)",
                    response,
                    re.IGNORECASE,
                )
                if open_fence_to_end:
                    content = open_fence_to_end.group(1).strip()

            if not content:
                return None

            # Prefer client-configured format when available
            schema_format = (
                getattr(self.client, "data_format", None) or "json"
            ).lower()

            # Single path: try strict parse first, then AI repair inside the helper
            data_items = await extract_data_with_ai_fallback(
                self.client, content, Prompt, schema_format
            )

            # Normalize to list of dicts
            if isinstance(data_items, dict):
                data_items = [data_items]
            if not isinstance(data_items, list):
                return None
            normalized = []
            for item in data_items:
                if isinstance(item, list):
                    # some models might wrap list-of-dicts within another list
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

    def chat_clean_visible_response(self, text: str) -> str:
        """Remove any action selection blocks from user-visible text and trim."""
        try:
            # remove new-style <ACTIONS> blocks
            cleaned = re.sub(
                r"<ACTIONS>[\s\S]*?</ACTIONS>", "", text, flags=re.IGNORECASE
            ).strip()
            # also remove any legacy ```actions``` blocks if present
            cleaned = re.sub(
                r"```actions[\s\S]*?```", "", cleaned, flags=re.IGNORECASE
            ).strip()
            return cleaned
        except Exception:
            return text.strip()

    async def chat_build_prompt_vars(
        self,
        history_for_prompt: list[dict],
        scene_snapshot: str,
        chat_id: str | None = None,
    ) -> dict:
        """Construct prompt variables for director.chat requests."""
        mode = "normal"
        if chat_id:
            chat = self.chat_get(chat_id)
            if chat:
                mode = chat.mode

        return {
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "history": history_for_prompt,
            "scene_snapshot": scene_snapshot,
            "available_functions": self.chat_available_actions,
            "chat_enable_analysis": self.chat_enable_analysis,
            "scene_context_ratio": self.chat_scene_context_ratio,
            "custom_instructions": self.chat_custom_instructions,
            "useful_context_ids": await get_meta_groups(
                self.scene,
                filter_fn=lambda meta: meta.permanent,
            ),
            "mode": mode,
            "budgets": DirectorChatBudgets(
                max_tokens=self.client.max_token_length,
                scene_context_ratio=self.chat_scene_context_ratio,
            ),
            # Provide callable to trim history inside the template (returns items)
            "director_history_trim": self.chat_reverse_trim_history_items,
        }

    def chat_reverse_trim_history_items(
        self,
        history: list["DirectorChatMessage | DirectorChatActionResultMessage"],
        budget_tokens: int,
    ) -> list[Any]:
        """
        Reverse-trim the director chat history to fit within a token budget.
        Walk from the end, include items until the token count of the core
        fields would exceed the budget. Returns items in chronological order.
        Assumes history items are Pydantic models (already normalized).
        """
        try:
            if not history or budget_tokens <= 0:
                return []

            def _count_item_tokens(message: Any) -> int:
                if message.type == "action_result":
                    # Count essential fields only; no template formatting
                    name_text = message.name or ""
                    instr_text = message.instructions or ""
                    try:
                        result_text = json.dumps(message.result, default=str)
                    except Exception:
                        result_text = str(message.result)
                    return util.count_tokens(
                        "\n".join([name_text, instr_text, result_text])
                    )
                # Text message
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
            try:
                log.error("director.chat.reverse_trim_items.error", error=e)
            except Exception:
                pass
            return [history[-1]] if history else []

    async def chat_request_and_parse(
        self,
        kind: str,
        history_for_prompt: list[dict],
        scene_snapshot: str,
        chat_id: str | None = None,
    ) -> tuple[str | None, list[dict] | None, str, DirectorChatBudgets | None]:
        """
        Make a Prompt.request for the given kind, retrying when <RESPONSE> is missing (if analysis enabled).
        Returns (parsed_response|None, actions_selected|None, raw_response, budgets).
        """
        max_retries = (
            self.chat_missing_response_retry_max if self.chat_enable_analysis else 0
        )
        attempt = 0
        raw_response = ""
        parsed_response: str | None = None
        actions_selected: list[dict] | None = None
        budgets: DirectorChatBudgets | None = None

        while True:
            try:
                vars = await self.chat_build_prompt_vars(
                    history_for_prompt, scene_snapshot, chat_id
                )
                raw_response = await Prompt.request(
                    "director.chat",
                    self.client,
                    kind=kind,
                    vars=vars,
                    dedupe_enabled=False,
                )
                budgets = vars["budgets"]
                log.debug("director.chat.request.budgets", budgets=budgets.model_dump())
            except Exception as e:
                log.error("director.chat.request.error", error=e, kind=kind)
                raw_response = ""

            actions_selected = (
                await self.chat_extract_actions_block(raw_response)
                if raw_response
                else None
            )
            parsed_response = self.chat_parse_response_section(raw_response or "")
            has_actions = bool(actions_selected)
            # Valid when we have a non-empty <MESSAGE>, OR when there is at least one action
            is_valid = bool(
                (parsed_response and parsed_response.strip()) or has_actions
            )
            if is_valid or attempt >= max_retries:
                break
            attempt += 1
            log.warn(
                "director.chat.retry_missing_response",
                attempt=attempt,
                max_retries=max_retries,
                kind=kind,
            )

        if parsed_response:
            parsed_response = self.chat_clean_visible_response(parsed_response)
        return parsed_response, actions_selected, raw_response, budgets

    def chat_history_for_prompt(self, chat_id: str) -> list[Any]:
        """
        Prepare chat history for the prompt template.
        Returns a list of message objects (DirectorChatMessage or DirectorChatActionResultMessage)
        so that the template can decide how to render each message type.
        """
        serialized: list[Any] = []
        chat = self.chat_get(chat_id)
        if not chat:
            return serialized

        for raw_message in chat.messages:
            item = self.chat_serialize_history_message(raw_message)
            if item:
                serialized.append(item)

        return serialized

    def chat_serialize_history_message(self, message: Any) -> Any | None:
        """
        Normalize a chat message input (dict or Pydantic model) into a Pydantic message object.
        Dicts are cast into the appropriate Pydantic model when possible; existing models are returned as-is.
        """
        try:
            # Handle dicts by casting into Pydantic models
            if isinstance(message, dict):
                msg_type = message.get("type", "text")
                if msg_type == "action_result":
                    return DirectorChatActionResultMessage(**message)
                else:
                    return DirectorChatMessage(**message)
            return message
        except Exception as e:
            log.error("director.chat.serialize_history.error", error=e)
            return None

    async def chat_execute_actions_and_append(
        self,
        chat_id: str,
        actions_selected: list[dict],
        on_update: Callable[
            [str, list[DirectorChatMessage | DirectorChatActionResultMessage]],
            Awaitable[None],
        ]
        | None = None,
    ) -> None:
        """Execute selected actions via FOCAL, append structured results to chat, and emit update."""
        state: GraphState = self.scene.nodegraph_state
        director_chat_actions = state.shared.get("_director_chat_actions", {})
        log.debug(
            "director.chat.available_actions",
            available=list(director_chat_actions.keys()),
        )

        callbacks: list[focal.Callback] = []
        ordered_callbacks: list[focal.Callback] = []
        ordered_instructions: dict[str, str] = {}
        ordered_examples: dict[str, list] = {}
        selection_instructions: dict[str, str] = {}
        ordered_argument_usage: dict[str, dict[str, str]] = {}
        has_character_callback = False
        action_names: set[str] = set()

        for selection in actions_selected:
            name = selection["name"]
            action_names.add(name)
            selection_instructions[name] = selection.get("instructions") or ""
            node_registry = director_chat_actions.get(name)
            if not node_registry:
                raise UnknownDirectorChatAction(name)

        for selection in actions_selected:
            name = selection["name"]
            selection_instructions[name] = selection.get("instructions") or ""
            node_registry = director_chat_actions.get(name)
            node = get_node(node_registry)()

            fn = FunctionWrapper(node, node, state)

            # discover argument nodes
            try:
                arg_nodes = await fn.get_argument_nodes(
                    filter_fn=lambda node: isinstance(node, DirectorChatActionArgument)
                )
            except Exception as e:
                log.error(
                    "director.chat.get_argument_nodes.error", error=e, action=name
                )
                arg_nodes = []

            arguments = [
                focal.Argument(
                    name=arg.get_property("name"), type=arg.get_property("typ")
                )
                for arg in arg_nodes
            ]

            has_character_callback = has_character_callback or any(
                arg.get_property("name") == "character" for arg in arg_nodes
            )

            async def _make_fn(wrapper, action_name: str):
                async def _call(**kwargs):
                    try:
                        return await wrapper(**kwargs)
                    except DirectorChatActionRejected as e:
                        log.error(
                            "director.chat.action.rejected",
                            description=e.action_description,
                            action=action_name,
                        )
                        raise
                    except InputValueError as e:
                        log.error(
                            "director.chat.action.error",
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

            # per-node instructions and examples
            try:
                inst = node.get_property("instructions") or ""
            except Exception:
                inst = ""
            ordered_instructions[name] = inst
            ordered_argument_usage[name] = {
                arg.get_property("name"): (
                    arg.normalized_input_value("instructions") or ""
                )
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
                            "director.chat.example_json.parse.error",
                            action=name,
                            error=e,
                        )
                        ex_list = []
                ordered_examples[name] = ex_list
            except Exception:
                ordered_examples[name] = []

        if not ordered_callbacks:
            return

        log.debug(
            "director.chat.actions.execute.start",
            selections=actions_selected,
            callbacks=[cb.name for cb in callbacks],
            max_calls=len(ordered_callbacks),
        )

        focal_handler = focal.Focal(
            self.client,
            callbacks=callbacks,
            max_calls=len(ordered_callbacks) + 2,
            retries=0,
            response_length=2048,
            scene=self.scene,
            history=self.chat_history_for_prompt(chat_id),
            selections=actions_selected,
            ordered_callbacks=ordered_callbacks,
            callbacks_unique=callbacks,
            ordered_instructions=ordered_instructions,
            ordered_examples=ordered_examples,
            ordered_reasons=selection_instructions,
            ordered_argument_usage=ordered_argument_usage,
            has_character_callback=has_character_callback,
        )

        chat = self.chat_get(chat_id)

        async def on_update_wrapper(call: focal.Call):
            # we only want send back feedback for top level actions
            if call.name not in ordered_instructions:
                return

            action_msg = DirectorChatActionResultMessage(
                name=call.name,
                arguments=getattr(call, "arguments", {}) or {},
                result=getattr(call, "result", None),
                instructions=selection_instructions.get(call.name),
            )
            await on_update(chat_id, [action_msg])
            chat.messages.append(action_msg)

        with focal.FocalContext() as focal_context:
            if on_update:
                focal_context.hooks_after_call.append(on_update_wrapper)
            await focal_handler.request("director.chat-execute-actions")

        self.chat_set_chat_state(chat.model_dump())

        log.debug(
            "director.chat.actions.execute.done",
            calls=[
                {"name": c.name, "called": c.called}
                for c in getattr(focal_handler.state, "calls", [])
            ],
        )

    # ------ Generation ------
    @set_processing
    async def chat_send(
        self,
        chat_id: str,
        message: str,
        on_update: Callable[
            [str, list[DirectorChatMessage | DirectorChatActionResultMessage]],
            Awaitable[None],
        ]
        | None = None,
        on_done: Callable[[str, DirectorChatBudgets | None], Awaitable[None]]
        | None = None,
        on_compacting: Callable[[str], Awaitable[None]] | None = None,
        on_compacted: Callable[
            [
                str,
                list[DirectorChatMessage | DirectorChatActionResultMessage],
            ],
            Awaitable[None],
        ]
        | None = None,
    ) -> DirectorChat:
        """
        Append a user message and generate a director response via prompt.
        Returns the updated chat.
        """
        chat = await self.chat_append_message(
            chat_id, DirectorChatMessage(message=message, source="user")
        )

        scene_snapshot = (
            self.scene.snapshot(lines=15) if getattr(self, "scene", None) else ""
        )

        # Iterate: generate → act → follow-up → (maybe continue) up to limit
        iterations_done = 0
        pending_actions: list[dict] | None = None
        budgets: DirectorChatBudgets | None = None

        while True:
            actions_selected: list[dict] | None
            # If we don't already have actions to process from a prior follow-up, generate a response now
            if pending_actions is None:
                kind = f"direction_{self.chat_response_length}"
                (
                    parsed_response,
                    actions_selected,
                    _raw,
                    budgets,
                ) = await self.chat_request_and_parse(
                    kind=kind,
                    history_for_prompt=self.chat_history_for_prompt(chat_id),
                    scene_snapshot=scene_snapshot,
                    chat_id=chat_id,
                )

                log.debug(
                    "director.chat.actions_selected",
                    iteration=iterations_done,
                    actions_selected=actions_selected,
                )

                if parsed_response:
                    chat = await self.chat_append_message(
                        chat_id,
                        DirectorChatMessage(message=parsed_response, source="director"),
                        on_update=on_update,
                    )
            else:
                # Use previously announced actions from the follow-up
                actions_selected = pending_actions
                pending_actions = None

            if not actions_selected:
                break

            try:
                await self.chat_execute_actions_and_append(
                    chat_id, actions_selected, on_update
                )
            except UnknownDirectorChatAction as e:
                log.error("director.chat.actions.execute.unknown_action", error=e)
                chat = await self.chat_append_message(
                    chat_id,
                    DirectorChatActionResultMessage(
                        name=e.action_name,
                        result=f"Error executing actions: {e}",
                        instructions=e.action_name,
                        status="error",
                    ),
                    on_update=on_update,
                )
            except DirectorChatActionRejected as e:
                # immediately yield back to the user
                chat = await self.chat_append_message(
                    chat_id,
                    DirectorChatActionResultMessage(
                        name=e.action_name,
                        result=f"User rejected the following action: {e}",
                        instructions=e.action_name,
                        status="rejected",
                    ),
                    on_update=on_update,
                )
                break
            except Exception as e:
                log.error("director.chat.actions.execute.error", error=e)
                # Also append an error message to the chat
                chat = await self.chat_append_message(
                    chat_id,
                    DirectorChatActionResultMessage(
                        name="ERROR",
                        result=f"Error executing actions: {e}. This is an internal error, so please inform the user.",
                        instructions="ERROR",
                        status="error",
                    ),
                    on_update=on_update,
                )

            # After executing actions, immediately follow-up so the director can incorporate results
            try:
                (
                    follow_parsed,
                    follow_actions,
                    _raw_follow,
                    budgets,
                ) = await self.chat_request_and_parse(
                    kind=f"direction_{self.chat_response_length}",
                    history_for_prompt=self.chat_history_for_prompt(chat_id),
                    scene_snapshot=scene_snapshot,
                    chat_id=chat_id,
                )
            except Exception as e:
                log.error("director.chat.followup.unhandled_error", error=e)
                follow_parsed, follow_actions = None, None

            if follow_parsed:
                chat = await self.chat_append_message(
                    chat_id,
                    DirectorChatMessage(message=follow_parsed, source="director"),
                    on_update=on_update,
                )

            # Count this action cycle and decide whether to continue
            iterations_done += 1
            if iterations_done >= max(1, self.chat_auto_iterations_limit):
                break

            # Prepare potential additional actions from follow-up for the next cycle
            pending_actions = follow_actions
            if not pending_actions:
                break

        # Compact chat history if needed after this turn
        try:
            await self.chat_compact_if_needed(
                chat_id, budgets, on_compacted, on_compacting
            )
        except Exception as e:
            log.error("director.chat.compact.error", error=e)

        # signal done to caller
        if on_done:
            try:
                await on_done(chat_id, budgets)
            except Exception as e:
                log.error("director.chat.on_done.error", error=e)
        return chat
