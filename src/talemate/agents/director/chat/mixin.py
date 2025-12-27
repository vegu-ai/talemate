import structlog
from typing import Any, TYPE_CHECKING, Callable, Awaitable

from talemate.agents.base import set_processing, AgentAction, AgentActionConfig
from talemate.game.engine.nodes.core import GraphState

from talemate.agents.director.action_core import utils as action_utils
from talemate.agents.director.action_core.exceptions import (
    ActionRejected,
    UnknownAction,
)

from .schema import (
    DirectorChat,
    DirectorChatMessage,
    DirectorChatActionResultMessage,
    DirectorChatBudgets,
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
                    value=10,
                    step=1,
                    min=1,
                    max=30,
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

    # === Config property helpers ===

    @property
    def chat_missing_response_retry_max(self) -> int:
        return int(self.actions["chat"].config["missing_response_retry_max"].value)

    @property
    def chat_auto_iterations_limit(self) -> int:
        return int(self.actions["chat"].config["auto_iterations_limit"].value)

    @property
    def chat_response_length(self) -> int:
        return int(self.actions["chat"].config["response_length"].value)

    @property
    def chat_scene_context_ratio(self) -> float:
        return self.actions["chat"].config["scene_context_ratio"].value

    @property
    def chat_enable_analysis(self) -> bool:
        return self.actions["chat"].config["enable_analysis"].value

    @property
    def chat_staleness_threshold(self) -> float:
        return self.actions["chat"].config["staleness_threshold"].value

    @property
    def chat_custom_instructions(self) -> str:
        return self.actions["chat"].config["custom_instructions"].value

    # === Node initialization ===

    @classmethod
    async def chat_init_nodes(cls, scene: "Scene", state: GraphState):
        """Initialize chat action nodes from the registry."""
        await action_utils.init_action_nodes(scene, state)

    # === State management ===

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
        if persona and persona.initial_chat_message:
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

    # === Message management ===

    def chat_history(
        self, chat_id: str
    ) -> list[DirectorChatMessage | DirectorChatActionResultMessage]:
        chat = self.chat_get(chat_id)
        return chat.messages if chat else []

    def chat_remove_message(
        self, chat_id: str, message_id: str
    ) -> "DirectorChat | None":
        """Remove a single message by id from the director chat history and persist state."""
        chat: DirectorChat | None = self.chat_get(chat_id)
        if not chat:
            return None
        try:
            remove_idx = -1
            for i, m in enumerate(chat.messages):
                if m.id == message_id:
                    remove_idx = i
                    break
            if remove_idx == -1:
                return None
            del chat.messages[remove_idx]
            self.chat_set_chat_state(chat.model_dump())
            return chat
        except Exception:
            return None

    async def chat_append_message(
        self,
        chat_id: str,
        message: DirectorChatMessage | DirectorChatActionResultMessage,
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

    # === Helper methods ===

    def _create_chat_message(
        self, message: str, source: str = "director", **kwargs
    ) -> DirectorChatMessage:
        """Factory method for creating chat messages."""
        return DirectorChatMessage(message=message, source=source, **kwargs)

    def _create_chat_result(self, **kwargs) -> DirectorChatActionResultMessage:
        """Factory method for creating action result messages."""
        return DirectorChatActionResultMessage(**kwargs)

    def _create_chat_budgets(self) -> DirectorChatBudgets:
        """Create budgets for this chat session."""
        return DirectorChatBudgets(
            max_tokens=self.client.max_token_length,
            scene_context_ratio=self.chat_scene_context_ratio,
        )

    def _serialize_chat_message(
        self, message: Any
    ) -> DirectorChatMessage | DirectorChatActionResultMessage | None:
        """Normalize a chat message into a Pydantic model."""
        try:
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

    def chat_history_for_prompt(self, chat_id: str) -> list[Any]:
        """Prepare chat history for the prompt template."""
        chat = self.chat_get(chat_id)
        if not chat:
            return []
        return action_utils.serialize_history(
            chat.messages, self._serialize_chat_message
        )

    # === Generation ===

    async def chat_generate_next(
        self,
        chat_id: str,
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
        Generate the next director response (and optional actions), without appending a user message.
        """
        scene_snapshot = self.scene.snapshot(lines=15) if hasattr(self, "scene") else ""

        iterations_done = 0
        pending_actions: list[dict] | None = None
        budgets: DirectorChatBudgets | None = None

        # Chat-specific template variables
        chat = self.chat_get(chat_id)
        mode = chat.mode if chat else "normal"
        extra_vars = {
            "chat_enable_analysis": self.chat_enable_analysis,
            "custom_instructions": self.chat_custom_instructions,
            "mode": mode,
            "director_history_trim": action_utils.reverse_trim_history,
        }

        while True:
            actions_selected: list[dict] | None
            if pending_actions is None:
                kind = f"direction_{self.chat_response_length}"
                max_retries = (
                    self.chat_missing_response_retry_max
                    if self.chat_enable_analysis
                    else 0
                )

                # Build prompt vars
                budgets = self._create_chat_budgets()
                prompt_vars = await action_utils.build_prompt_vars(
                    scene=self.scene,
                    client=self.client,
                    history_for_prompt=self.chat_history_for_prompt(chat_id),
                    scene_snapshot=scene_snapshot,
                    budgets=budgets,
                    enable_analysis=self.chat_enable_analysis,
                    scene_context_ratio=self.chat_scene_context_ratio,
                    history_trim_fn=action_utils.reverse_trim_history,
                    extra_vars=extra_vars,
                    mode="chat",
                )

                # Make request
                (
                    parsed_response,
                    actions_selected,
                    _raw,
                ) = await action_utils.request_and_parse(
                    client=self.client,
                    prompt_template="director.chat",
                    kind=kind,
                    prompt_vars=prompt_vars,
                    max_retries=max_retries,
                )

                log.debug(
                    "director.chat.actions_selected",
                    iteration=iterations_done,
                    actions_selected=actions_selected,
                )

                if parsed_response:
                    await self.chat_append_message(
                        chat_id,
                        DirectorChatMessage(message=parsed_response, source="director"),
                        on_update=on_update,
                    )
            else:
                actions_selected = pending_actions
                pending_actions = None

            if not actions_selected:
                break

            try:
                await self._chat_execute_actions(chat_id, actions_selected, on_update)
            except UnknownAction as e:
                log.error("director.chat.actions.execute.unknown_action", error=e)
                await self.chat_append_message(
                    chat_id,
                    DirectorChatActionResultMessage(
                        name=e.action_name,
                        result=f"Error executing actions: {e}",
                        instructions=e.action_name,
                        status="error",
                    ),
                    on_update=on_update,
                )
            except ActionRejected as e:
                await self.chat_append_message(
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
                await self.chat_append_message(
                    chat_id,
                    DirectorChatActionResultMessage(
                        name="ERROR",
                        result=f"Error executing actions: {e}. This is an internal error, so please inform the user.",
                        instructions="ERROR",
                        status="error",
                    ),
                    on_update=on_update,
                )

            # Follow-up request
            try:
                budgets = self._create_chat_budgets()
                prompt_vars = await action_utils.build_prompt_vars(
                    scene=self.scene,
                    client=self.client,
                    history_for_prompt=self.chat_history_for_prompt(chat_id),
                    scene_snapshot=scene_snapshot,
                    budgets=budgets,
                    enable_analysis=self.chat_enable_analysis,
                    scene_context_ratio=self.chat_scene_context_ratio,
                    history_trim_fn=action_utils.reverse_trim_history,
                    extra_vars=extra_vars,
                    mode="chat",
                )

                (
                    follow_parsed,
                    follow_actions,
                    _raw_follow,
                ) = await action_utils.request_and_parse(
                    client=self.client,
                    prompt_template="director.chat",
                    kind=f"direction_{self.chat_response_length}",
                    prompt_vars=prompt_vars,
                )
            except Exception as e:
                log.error("director.chat.followup.unhandled_error", error=e)
                follow_parsed, follow_actions = None, None

            if follow_parsed:
                await self.chat_append_message(
                    chat_id,
                    DirectorChatMessage(message=follow_parsed, source="director"),
                    on_update=on_update,
                )

            iterations_done += 1
            if iterations_done >= max(1, self.chat_auto_iterations_limit):
                break

            pending_actions = follow_actions
            if not pending_actions:
                break

        # Compact if needed
        try:
            await self._chat_compact_if_needed(
                chat_id, budgets, on_compacted, on_compacting
            )
        except Exception as e:
            log.error("director.chat.compact.error", error=e)

        if on_done:
            try:
                await on_done(chat_id, budgets)
            except Exception as e:
                log.error("director.chat.on_done.error", error=e)

        return self.chat_get(chat_id)

    @set_processing
    async def chat_regenerate_last(
        self,
        chat_id: str,
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
    ) -> DirectorChat | None:
        """
        Regenerate the most recent director text message by removing it and generating a new one.
        """
        chat = self.chat_get(chat_id)
        if not chat or not chat.messages:
            return chat

        # Find the last director text message
        last_dir_idx = -1
        for i in range(len(chat.messages) - 1, -1, -1):
            msg = chat.messages[i]
            try:
                if (msg.type == "text") and (msg.source == "director"):
                    last_dir_idx = i
                    break
            except Exception:
                continue

        if last_dir_idx == -1:
            return chat

        try:
            del chat.messages[last_dir_idx]
        except Exception:
            return chat

        self.chat_set_chat_state(chat.model_dump())
        return await self.chat_generate_next(
            chat_id,
            on_update=on_update,
            on_done=on_done,
            on_compacting=on_compacting,
            on_compacted=on_compacted,
        )

    # === Compaction ===

    async def _chat_compact_if_needed(
        self,
        chat_id: str,
        budgets_snapshot: DirectorChatBudgets | None,
        on_compacted: Callable[
            [str, list[DirectorChatMessage | DirectorChatActionResultMessage]],
            Awaitable[None],
        ]
        | None = None,
        on_compacting: Callable[[str], Awaitable[None]] | None = None,
    ) -> bool:
        """Compact chat history if needed."""
        chat = self.chat_get(chat_id)
        if not chat or not chat.messages or not budgets_snapshot:
            return False

        def set_messages(new_messages):
            chat.messages = new_messages
            self.chat_set_chat_state(chat.model_dump())

        async def wrapped_on_compacted(new_messages):
            if on_compacted:
                await on_compacted(chat_id, new_messages)

        async def wrapped_on_compacting():
            if on_compacting:
                await on_compacting(chat_id)

        return await action_utils.compact_if_needed(
            messages=chat.messages,
            budgets=budgets_snapshot,
            staleness_threshold=self.chat_staleness_threshold,
            create_message=self._create_chat_message,
            set_messages=set_messages,
            on_compacted=wrapped_on_compacted,
            on_compacting=wrapped_on_compacting,
        )

    # === Action execution ===

    async def _chat_execute_actions(
        self,
        chat_id: str,
        actions_selected: list[dict],
        on_update: Callable[
            [str, list[DirectorChatMessage | DirectorChatActionResultMessage]],
            Awaitable[None],
        ]
        | None = None,
    ) -> None:
        """Execute selected actions via FOCAL, append results to chat."""
        chat = self.chat_get(chat_id)

        async def on_action_complete(action_msg: DirectorChatActionResultMessage):
            if on_update:
                await on_update(chat_id, [action_msg])
            chat.messages.append(action_msg)

        await action_utils.execute_actions(
            client=self.client,
            scene=self.scene,
            actions_selected=actions_selected,
            history_for_prompt=self.chat_history_for_prompt(chat_id),
            create_result=self._create_chat_result,
            on_action_complete=on_action_complete,
        )

        self.chat_set_chat_state(chat.model_dump())

    # === Send message ===

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
        """
        await self.chat_append_message(
            chat_id, DirectorChatMessage(message=message, source="user")
        )
        return await self.chat_generate_next(
            chat_id,
            on_update=on_update,
            on_done=on_done,
            on_compacting=on_compacting,
            on_compacted=on_compacted,
        )
