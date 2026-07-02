import structlog
from typing import Any, Literal, TYPE_CHECKING, Callable, Awaitable

import talemate.instance as instance
from talemate.agents.base import set_processing, AgentAction, AgentActionConfig
from talemate.emit import emit
from talemate.game.engine.nodes.core import GraphState

from talemate.agents.director.action_core import utils as action_utils
from talemate.agents.director.action_core.exceptions import (
    ActionFailed,
    ActionRejected,
    UnknownAction,
)

from talemate.prompts import Prompt
from talemate.agents.director.plan.util import get_plan, cleanup_orphaned_plans
from .context import director_chat_context

from .response_specs import CHAT_TITLE_SPEC
from .schema import (
    DirectorChat,
    DirectorChatMessage,
    DirectorChatActionResultMessage,
    DirectorChatBudgets,
    DirectorChatListEntry,
)
from .settings import ChatModeSettings

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.agent.director.chat")


class DirectorChatMixin:
    """
    Agent mixin that provides director chat management stored in scene agent state.

    Storage layout in scene.agent_state:
        scene.agent_state["director"]["chats"] = {chat_id: DirectorChat.model_dump(), ...}
        scene.agent_state["director"]["last_active_chat_id"] = "abc123"
    """

    CHATS_STATE_KEY = "chats"
    LAST_ACTIVE_CHAT_KEY = "last_active_chat_id"

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
                    description="Maximum number of response\u2192actions\u2192response cycles after a user message.",
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
                "action_confirm_timeout": AgentActionConfig(
                    type="number",
                    label="Action confirm timeout",
                    description="How long to wait (in minutes) for user confirmation of write actions. 0 means wait indefinitely.",
                    value=3,
                    step=1,
                    min=0,
                    max=60,
                ),
                "custom_instructions": AgentActionConfig(
                    type="blob",
                    label="Custom instructions",
                    description="Custom instructions to add to the director chat.",
                    value="",
                ),
                "generate_arc_iterations_limit": AgentActionConfig(
                    type="number",
                    label="Arc generation iteration limit",
                    description="Maximum iterations for autonomous arc generation. Should be high enough to complete all beats.",
                    value=200,
                    step=10,
                    min=20,
                    max=500,
                ),
            },
        )

    # === Config property helpers ===

    @property
    def chat_missing_response_retry_max(self) -> int:
        return int(self.resolve_config("chat", "missing_response_retry_max"))

    @property
    def chat_auto_iterations_limit(self) -> int:
        return int(self.resolve_config("chat", "auto_iterations_limit"))

    @property
    def chat_generate_arc_iterations_limit(self) -> int:
        return int(self.resolve_config("chat", "generate_arc_iterations_limit"))

    @property
    def chat_response_length(self) -> int:
        return int(self.resolve_config("chat", "response_length"))

    @property
    def chat_scene_context_ratio(self) -> float:
        return self.resolve_config("chat", "scene_context_ratio")

    @property
    def chat_enable_analysis(self) -> bool:
        return self.resolve_config("chat", "enable_analysis")

    @property
    def chat_staleness_threshold(self) -> float:
        return self.resolve_config("chat", "staleness_threshold")

    @property
    def chat_custom_instructions(self) -> str:
        return self.resolve_config("chat", "custom_instructions")

    @property
    def chat_action_confirm_timeout(self) -> int:
        """Timeout in seconds. 0 means wait indefinitely."""
        return int(self.resolve_config("chat", "action_confirm_timeout")) * 60

    # === Node initialization ===

    @classmethod
    async def chat_init_nodes(cls, scene: "Scene", state: GraphState):
        """Initialize chat action nodes from the registry."""
        await action_utils.init_action_nodes(scene, state)

    # === State management (collection-based) ===

    def chat_get_all_chats(self) -> dict[str, Any]:
        """Return the full chats dict {chat_id: chat_dict} from scene state."""
        return self.get_scene_state(self.CHATS_STATE_KEY, default={}) or {}

    def chat_set_all_chats(self, chats: dict[str, Any]):
        """Write the full chats dict to scene state."""
        self.set_scene_states(**{self.CHATS_STATE_KEY: chats})

    def chat_get_last_active_id(self) -> str | None:
        """Return the last active chat id, or None."""
        return self.get_scene_state(self.LAST_ACTIVE_CHAT_KEY, default=None)

    def chat_set_last_active_id(self, chat_id: str | None):
        """Set the last active chat id."""
        self.set_scene_states(**{self.LAST_ACTIVE_CHAT_KEY: chat_id})

    @property
    def active_chat_plan_id(self) -> str | None:
        """Return the plan_id linked to the active chat, or None."""
        chat_id = self.chat_get_last_active_id()
        if not chat_id:
            return None
        chat = self.chat_get(chat_id)
        return chat.plan_id if chat else None

    @active_chat_plan_id.setter
    def active_chat_plan_id(self, plan_id: str | None):
        """Set the plan_id on the active chat."""
        chat_id = self.chat_get_last_active_id()
        if not chat_id:
            return
        chat = self.chat_get(chat_id)
        if chat:
            chat.plan_id = plan_id
            self._chat_save(chat)

    def _chat_save(self, chat: DirectorChat):
        """Persist a single chat back into the chats collection."""
        chats = self.chat_get_all_chats()
        chats[chat.id] = chat.model_dump()
        self.chat_set_all_chats(chats)

    def _chat_initial_message(
        self,
        default_message: str = "Hey, how can I help you with this scene?",
        persona_field: str = "initial_chat_message",
    ) -> str:
        """Return initial Director chat message using persona override when present."""
        persona = self.scene.agent_persona("director")
        persona_value = getattr(persona, persona_field) if persona else None
        if persona_value:
            try:
                return persona.formatted(persona_field, self.scene, "director")
            except Exception:
                return persona_value or default_message
        return default_message

    def chat_list(self) -> list[DirectorChatListEntry]:
        """Return a list of chat entries sorted by created_at descending (most recent first)."""
        chats = self.chat_get_all_chats()
        entries = []
        for chat_id, raw in chats.items():
            try:
                if isinstance(raw, DirectorChat):
                    entries.append(
                        DirectorChatListEntry(
                            id=raw.id,
                            title=raw.title,
                            mode=raw.mode,
                            created_at=raw.created_at,
                        )
                    )
                else:
                    entries.append(
                        DirectorChatListEntry(
                            id=raw.get("id", chat_id),
                            title=raw.get("title"),
                            mode=raw.get("mode", "normal"),
                            created_at=raw.get("created_at", 0.0),
                        )
                    )
            except Exception:
                continue
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def chat_get(self, chat_id: str) -> DirectorChat | None:
        """Look up a chat by id from the collection."""
        chats = self.chat_get_all_chats()
        raw = chats.get(chat_id)
        if not raw:
            return None
        try:
            return raw if isinstance(raw, DirectorChat) else DirectorChat(**raw)
        except Exception as e:
            log.error("director.chat.get.error", chat_id=chat_id, error=e)
            return None

    def chat_create(self) -> DirectorChat:
        """Create a new chat, add it to the collection, and set it as last active."""
        chat = DirectorChat(
            messages=[
                DirectorChatMessage(
                    message=self._chat_initial_message(),
                    source="director",
                ),
            ]
        )
        self._chat_save(chat)
        self.chat_set_last_active_id(chat.id)
        cleanup_orphaned_plans(self.scene, self.chat_get_all_chats())
        return chat

    def chat_create_generate_arc(
        self,
        instructions: str,
        beat_count: int = 8,
        mode: Literal["generate_arc", "generate_arc_expand"] = "generate_arc",
        modes: ChatModeSettings | None = None,
    ) -> DirectorChat:
        """Create a new chat in generate_arc mode with planning instructions as initial user message."""
        chat = DirectorChat(
            messages=[
                DirectorChatMessage(
                    message=self._chat_initial_message(
                        "I'm ready to plan and generate your scene. "
                        "I'll create an outline, then execute each beat to produce the actual scene content.",
                        persona_field="initial_arc_chat_message",
                    ),
                    source="director",
                ),
                DirectorChatMessage(
                    message=(
                        f"Plan and generate a scene with {beat_count} beats using the following instructions:\n\n"
                        f"{instructions}"
                    ),
                    source="user",
                ),
            ],
            mode=mode,
            confirm_write_actions=False,
            modes=modes or ChatModeSettings(),
        )
        self._chat_save(chat)
        self.chat_set_last_active_id(chat.id)
        cleanup_orphaned_plans(self.scene, self.chat_get_all_chats())
        return chat

    def chat_delete(self, chat_id: str) -> bool:
        """Remove a chat from the collection. Updates last_active_chat_id if needed."""
        chats = self.chat_get_all_chats()
        if chat_id not in chats:
            return False
        del chats[chat_id]
        self.chat_set_all_chats(chats)

        # If we deleted the active chat, pick the most recent remaining one
        if self.chat_get_last_active_id() == chat_id:
            remaining = self.chat_list()
            if remaining:
                self.chat_set_last_active_id(remaining[0].id)
            else:
                self.chat_set_last_active_id(None)
        cleanup_orphaned_plans(self.scene, self.chat_get_all_chats())
        return True

    def chat_clear(self, chat_id: str) -> bool:
        """Clear all messages from a chat while keeping the same chat id and preserving mode."""
        chat = self.chat_get(chat_id)
        if not chat:
            return False
        current_mode = chat.mode
        chat.messages = [
            DirectorChatMessage(
                message=self._chat_initial_message(),
                source="director",
            )
        ]
        chat.mode = current_mode
        self._chat_save(chat)
        return True

    def chat_get_or_create_active(self) -> DirectorChat:
        """
        Get the active chat for initial load:
        1. If last_active_chat_id points to a valid chat, return it
        2. Otherwise, if any chats exist, return the most recent
        3. If no chats exist, create one
        """
        last_id = self.chat_get_last_active_id()
        if last_id:
            chat = self.chat_get(last_id)
            if chat:
                return chat

        # Fall back to most recent
        entries = self.chat_list()
        if entries:
            chat = self.chat_get(entries[0].id)
            if chat:
                self.chat_set_last_active_id(chat.id)
                return chat

        # Nothing exists, create
        return self.chat_create()

    def chat_update_title(self, chat_id: str, title: str) -> bool:
        """Set the title on a chat."""
        chat = self.chat_get(chat_id)
        if not chat:
            return False
        chat.title = title
        self._chat_save(chat)
        return True

    def _chat_has_enough_for_title(self, chat: DirectorChat) -> bool:
        """Check if a chat has at least 1 user message + 1 director text response."""
        has_user = False
        has_director = False
        for msg in chat.messages:
            try:
                if msg.source == "user":
                    has_user = True
                elif msg.source == "director" and msg.type == "text":
                    has_director = True
            except Exception:
                continue
            if has_user and has_director:
                return True
        return False

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
            self._chat_save(chat)
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
        self._chat_save(chat)
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
        on_title_generated: Callable[[str, str], Awaitable[None]] | None = None,
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

        def _sync_plan_to_context():
            """Inject active plan into extra_vars for the prompt template."""
            nonlocal chat
            # Re-fetch chat to avoid overwriting messages appended by other methods
            chat = self.chat_get(chat_id) or chat
            chat_ctx = director_chat_context.get()
            plan_id = (chat_ctx.plan_id if chat_ctx else None) or (
                chat.plan_id if chat else None
            )
            if plan_id:
                if chat and chat.plan_id != plan_id:
                    chat.plan_id = plan_id
                    self._chat_save(chat)
                extra_vars["scene_plan"] = get_plan(self.scene, plan_id)
            else:
                extra_vars.pop("scene_plan", None)

        while True:
            _sync_plan_to_context()

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
            except ActionFailed as e:
                log.warning("director.chat.actions.execute.action_failed", error=e)
                await self.chat_append_message(
                    chat_id,
                    DirectorChatActionResultMessage(
                        name="action_failed",
                        result=str(e),
                        instructions="",
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

            _sync_plan_to_context()

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

            # generate_arc mode: unlocked iteration (up to hard safety limit)
            # normal modes: respect the configured auto-iteration limit
            if mode in ("generate_arc", "generate_arc_expand"):
                if iterations_done >= self.chat_generate_arc_iterations_limit:
                    log.warning("director.chat.generate_arc.hard_limit_reached")
                    break
                if hasattr(self, "scene") and not self.scene.active:
                    log.warning("director.chat.generate_arc.scene_inactive")
                    break
            elif iterations_done >= max(1, self.chat_auto_iterations_limit):
                break

            pending_actions = follow_actions
            if not pending_actions:
                break

        # Generate title if this is the first real exchange
        chat = self.chat_get(chat_id)
        if chat and not chat.title and self._chat_has_enough_for_title(chat):
            try:
                title = await self.chat_generate_title(chat_id)
                if title and on_title_generated:
                    await on_title_generated(chat_id, title)
            except Exception:
                pass  # title generation is best-effort

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
        on_title_generated: Callable[[str, str], Awaitable[None]] | None = None,
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

        self._chat_save(chat)
        return await self.chat_generate_next(
            chat_id,
            on_update=on_update,
            on_done=on_done,
            on_compacting=on_compacting,
            on_compacted=on_compacted,
            on_title_generated=on_title_generated,
        )

    # === Title generation ===

    async def chat_generate_title(self, chat_id: str) -> str | None:
        """Generate a title for the chat based on its initial messages."""
        chat = self.chat_get(chat_id)
        if not chat:
            return None

        # Build a short excerpt from the first few messages
        excerpt_parts = []
        for msg in chat.messages[:6]:
            try:
                source = msg.source if hasattr(msg, "source") else "unknown"
                text = msg.message if hasattr(msg, "message") else str(msg)
                excerpt_parts.append(f"{source}: {text}")
            except Exception:
                continue

        chat_excerpt = "\n".join(excerpt_parts)

        response, extracted = await Prompt.request(
            "director.chat-title",
            self.client,
            "create_92",
            vars={"chat_excerpt": chat_excerpt},
            response_spec=CHAT_TITLE_SPEC,
        )

        title = extracted.get("title")
        if not title:
            title = response.strip() if response else None

        if title:
            # Clean up and truncate
            title = title.strip().strip("\"'")
            if len(title) > 60:
                title = title[:57] + "..."
            self.chat_update_title(chat_id, title)

        return title

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
            self._chat_save(chat)

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

        self._chat_save(chat)

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
        on_title_generated: Callable[[str, str], Awaitable[None]] | None = None,
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
            on_title_generated=on_title_generated,
        )

    @set_processing
    async def chat_start_generate_arc(
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
        on_title_generated: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> DirectorChat:
        """
        Start arc generation. Like chat_generate_next but with @set_processing
        to ensure active_agent context is available.

        Suppresses automatic TTS generation while arcs are being generated to
        avoid noisy voice synthesis during long multi-step planning.
        """
        tts_agent = instance.get_agent("tts")
        if tts_agent.enabled and tts_agent.has_auto_generation:
            emit(
                "status",
                "Automatic voice generation is paused during multi-turn generation.",
                status="info",
            )
        with tts_agent.suppress_auto_generation():
            return await self.chat_generate_next(
                chat_id,
                on_update=on_update,
                on_done=on_done,
                on_compacting=on_compacting,
                on_compacted=on_compacted,
                on_title_generated=on_title_generated,
            )
