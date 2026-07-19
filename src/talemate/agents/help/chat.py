from typing import Awaitable, Callable

import structlog

import talemate.emit.async_signals as async_signals
import talemate.game.focal as focal
import talemate.instance as instance
import talemate.util as util
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    set_processing,
)
from talemate.agents.chat_title import generate_chat_title
from talemate.client.context import ClientContext
from talemate.game.focal.util import strip_call_blocks

from . import docs
from . import settings
from .schema import (
    HelpChat,
    HelpChatDocResultMessage,
    HelpChatListEntry,
    HelpChatMessage,
    HelpChatStore,
)
from .storage import load_store, save_store

__all__ = ["HelpChatMixin", "HelpChatEmission"]

log = structlog.get_logger("talemate.agents.help.chat")

INITIAL_MESSAGE = (
    "Hi! I can help you with anything Talemate - settings, agents, clients, "
    "the world editor and more. I can also look up your current settings and "
    "change them for you if you ask. What would you like to know?"
)

OnUpdate = Callable[
    [str, list[HelpChatMessage | HelpChatDocResultMessage]], Awaitable[None]
]
OnDone = Callable[[str], Awaitable[None]]
OnTitleGenerated = Callable[[str, str], Awaitable[None]]

async_signals.register(
    "agent.help.chat.before",
    "agent.help.chat.after",
)


class HelpChatEmission(AgentEmission):
    chat_id: str
    chat: HelpChat | None = None


class HelpChatMixin:
    """
    Agent mixin providing multi-turn help chats backed by the bundled
    documentation via focal function calling.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["chat"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Help Chat",
            icon="mdi-help-circle",
            description="Interactive help chat that answers questions about Talemate using the bundled documentation.",
            config={
                "response_length": AgentActionConfig(
                    type="number",
                    label="Response token budget",
                    description="Maximum response length for help responses.",
                    value=1024,
                    step=256,
                    min=512,
                    max=4096,
                ),
                "doc_lookup_iterations": AgentActionConfig(
                    type="number",
                    label="Tool call rounds",
                    description="How many rounds of tool calls (documentation lookups, settings reads and updates) the help agent may perform before it must answer.",
                    value=3,
                    step=1,
                    min=1,
                    max=10,
                ),
                "max_doc_lookups": AgentActionConfig(
                    type="number",
                    label="Tool calls per round",
                    description="Maximum tool calls per round. Read-only calls in a round run concurrently when the client supports concurrent inference.",
                    value=5,
                    step=1,
                    min=1,
                    max=16,
                ),
                "custom_instructions": AgentActionConfig(
                    type="blob",
                    label="Custom instructions",
                    description="Custom instructions to add to the help chat.",
                    value="",
                ),
            },
        )

    # === Config property helpers ===

    @property
    def chat_response_length(self) -> int:
        return int(self.resolve_config("chat", "response_length"))

    @property
    def chat_doc_lookup_iterations(self) -> int:
        return int(self.resolve_config("chat", "doc_lookup_iterations"))

    @property
    def chat_max_doc_lookups(self) -> int:
        return int(self.resolve_config("chat", "max_doc_lookups"))

    @property
    def chat_custom_instructions(self) -> str:
        return self.resolve_config("chat", "custom_instructions")

    # === Store access ===

    @property
    def chat_store(self) -> HelpChatStore:
        if not hasattr(self, "_chat_store"):
            self._chat_store = load_store()
        return self._chat_store

    def _chat_persist(self):
        save_store(self.chat_store)

    # === Chat CRUD ===

    def chat_list(self) -> list[HelpChatListEntry]:
        """Return chat entries sorted by created_at descending (most recent first)."""
        entries = [
            HelpChatListEntry(id=chat.id, title=chat.title, created_at=chat.created_at)
            for chat in self.chat_store.chats.values()
        ]
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def chat_get(self, chat_id: str) -> HelpChat | None:
        return self.chat_store.chats.get(chat_id)

    def chat_get_last_active_id(self) -> str | None:
        return self.chat_store.last_active_chat_id

    def chat_set_last_active_id(self, chat_id: str | None):
        self.chat_store.last_active_chat_id = chat_id
        self._chat_persist()

    def chat_create(self) -> HelpChat:
        chat = HelpChat(
            messages=[HelpChatMessage(message=INITIAL_MESSAGE, source="help")],
            scene_aware=self.scene_loaded,
        )
        self.chat_store.chats[chat.id] = chat
        self.chat_store.last_active_chat_id = chat.id
        self._chat_persist()
        return chat

    def chat_delete(self, chat_id: str) -> bool:
        if chat_id not in self.chat_store.chats:
            return False
        del self.chat_store.chats[chat_id]
        if self.chat_store.last_active_chat_id == chat_id:
            remaining = self.chat_list()
            self.chat_store.last_active_chat_id = remaining[0].id if remaining else None
        self._chat_persist()
        return True

    def chat_clear(self, chat_id: str) -> bool:
        chat = self.chat_get(chat_id)
        if not chat:
            return False
        chat.messages = [HelpChatMessage(message=INITIAL_MESSAGE, source="help")]
        self._chat_persist()
        return True

    def chat_get_or_create_active(self) -> HelpChat:
        last_id = self.chat_store.last_active_chat_id
        if last_id:
            chat = self.chat_get(last_id)
            if chat:
                return chat
        entries = self.chat_list()
        if entries:
            chat = self.chat_get(entries[0].id)
            if chat:
                self.chat_set_last_active_id(chat.id)
                return chat
        return self.chat_create()

    def chat_update_title(self, chat_id: str, title: str) -> bool:
        chat = self.chat_get(chat_id)
        if not chat:
            return False
        chat.title = title
        self._chat_persist()
        return True

    def chat_update_scene_aware(self, chat_id: str, scene_aware: bool) -> bool:
        chat = self.chat_get(chat_id)
        if not chat:
            return False
        chat.scene_aware = scene_aware
        self._chat_persist()
        return True

    async def chat_append_message(
        self,
        chat_id: str,
        message: HelpChatMessage | HelpChatDocResultMessage,
        on_update: OnUpdate | None = None,
    ) -> HelpChat | None:
        chat = self.chat_get(chat_id)
        if not chat:
            return None
        chat.messages.append(message)
        self._chat_persist()
        if on_update:
            await on_update(chat_id, [message])
        return chat

    # === Context helpers ===

    @property
    def scene_loaded(self) -> bool:
        return bool(self.scene and self.scene.name)

    def _chat_scene_context(self, chat: HelpChat) -> dict | None:
        """Build scene context for the prompt when the chat is scene aware."""
        if not chat.scene_aware or not self.scene_loaded:
            return None
        try:
            return {
                "title": self.scene.title or self.scene.name,
                "characters": self.scene.character_names,
                "snapshot": self.scene.snapshot(lines=10),
            }
        except Exception as e:
            log.error("help.chat.scene_context.error", error=e)
            return None

    def _chat_doc_callbacks(self) -> list[focal.Callback]:
        async def search_docs(query: str):
            return docs.search_docs(query)

        async def read_doc(path: str):
            return docs.read_doc(path)

        async def read_doc_section(path: str, section: str):
            return docs.read_doc_section(path, section)

        return [
            focal.Callback(
                name="search_docs",
                arguments=[focal.Argument(name="query", type="str")],
                fn=search_docs,
                concurrent=True,
            ),
            focal.Callback(
                name="read_doc",
                arguments=[focal.Argument(name="path", type="str")],
                fn=read_doc,
                concurrent=True,
            ),
            focal.Callback(
                name="read_doc_section",
                arguments=[
                    focal.Argument(name="path", type="str"),
                    focal.Argument(name="section", type="str"),
                ],
                fn=read_doc_section,
                concurrent=True,
            ),
        ]

    def _chat_settings_callbacks(
        self, ux_snapshot: dict | None = None
    ) -> list[focal.Callback]:
        # writes targeting the agent whose settings dialog is open would be
        # invisible in (and overwritable by) that dialog - refuse them.
        # best-effort: the snapshot is from message-send time, so a dialog
        # opened mid-generation is not seen
        open_agent_modal = ((ux_snapshot or {}).get("agent_settings_modal") or {}).get(
            "agent"
        )
        # the settings view lives in the main viewport now — merely having it
        # open is fine (incoming config pushes are handled cleanly); only
        # unsaved edits there conflict with a config write
        app_settings_dirty = bool(
            ((ux_snapshot or {}).get("app_settings_modal") or {}).get("dirty")
        )

        async def read_agent_settings(agent: str):
            return settings.read_agent_settings(agent)

        async def update_agent_setting(
            agent: str, action: str, setting: str, value, scope: str = "global"
        ):
            return await settings.update_agent_setting(
                agent, action, setting, value, scope, open_agent_modal=open_agent_modal
            )

        async def clear_agent_setting_scene_override(
            agent: str, action: str, setting: str
        ):
            return await settings.clear_agent_setting_scene_override(
                agent, action, setting, open_agent_modal=open_agent_modal
            )

        async def read_app_config(section: str):
            return settings.read_app_config(section)

        async def update_app_config(path: str, value):
            return await settings.update_app_config(
                path, value, app_settings_dirty=app_settings_dirty
            )

        async def read_clients():
            return settings.read_clients()

        # reads may run concurrently; writes stay sequential so config
        # mutations never race each other
        return [
            focal.Callback(
                name="read_agent_settings",
                arguments=[focal.Argument(name="agent", type="str")],
                fn=read_agent_settings,
                concurrent=True,
            ),
            focal.Callback(
                name="update_agent_setting",
                arguments=[
                    focal.Argument(name="agent", type="str"),
                    focal.Argument(name="action", type="str"),
                    focal.Argument(name="setting", type="str"),
                    focal.Argument(
                        name="value", type="str | int | float | bool | list"
                    ),
                    focal.Argument(name="scope", type="str"),
                ],
                fn=update_agent_setting,
            ),
            focal.Callback(
                name="clear_agent_setting_scene_override",
                arguments=[
                    focal.Argument(name="agent", type="str"),
                    focal.Argument(name="action", type="str"),
                    focal.Argument(name="setting", type="str"),
                ],
                fn=clear_agent_setting_scene_override,
            ),
            focal.Callback(
                name="read_app_config",
                arguments=[focal.Argument(name="section", type="str")],
                fn=read_app_config,
                concurrent=True,
            ),
            focal.Callback(
                name="update_app_config",
                arguments=[
                    focal.Argument(name="path", type="str"),
                    focal.Argument(
                        name="value", type="str | int | float | bool | list"
                    ),
                ],
                fn=update_app_config,
            ),
            focal.Callback(
                name="read_clients",
                arguments=[],
                fn=read_clients,
                concurrent=True,
            ),
        ]

    # === Generation ===

    async def chat_generate_next(
        self,
        chat_id: str,
        ux_snapshot: dict | None = None,
        on_update: OnUpdate | None = None,
        on_done: OnDone | None = None,
        on_title_generated: OnTitleGenerated | None = None,
    ) -> HelpChat | None:
        """
        Generate the next help response. Documentation lookups append their
        results to the chat and trigger a follow-up round so the response can
        incorporate them, up to the configured number of rounds.
        """
        chat = self.chat_get(chat_id)
        if not chat:
            return None

        await async_signals.get("agent.help.chat.before").send(
            HelpChatEmission(agent=self, chat_id=chat_id, chat=chat)
        )

        rounds = 0

        # help chats must work without a loaded scene, so lift the
        # client's active-scene requirement for the whole generation
        with ClientContext(requires_active_scene=False):
            while True:
                scene_context = self._chat_scene_context(chat)

                focal_handler = focal.Focal(
                    self.client,
                    callbacks=self._chat_doc_callbacks()
                    + self._chat_settings_callbacks(ux_snapshot),
                    max_calls=self.chat_max_doc_lookups,
                    max_concurrent=self.chat_max_doc_lookups,
                    retries=0,
                    response_length=self.chat_response_length,
                    scene=self.scene,
                    history=chat.messages,
                    history_trim=util.reverse_trim_history,
                    docs_index=docs.load_docs_index(),
                    docs_available=docs.docs_available(),
                    docs_site_url=docs.DOCS_SITE_URL,
                    agent_types=sorted(instance.AGENTS.keys()),
                    ux_snapshot=ux_snapshot,
                    scene_context=scene_context,
                    custom_instructions=self.chat_custom_instructions,
                    final_round=rounds >= self.chat_doc_lookup_iterations,
                )

                response = await focal_handler.request("help.chat")

                visible = strip_call_blocks(response, focal_handler.state.schema_format)
                if visible:
                    await self.chat_append_message(
                        chat_id,
                        HelpChatMessage(message=visible, source="help"),
                        on_update=on_update,
                    )

                calls = focal_handler.state.calls
                for call in calls:
                    result = (
                        call.result
                        if call.called
                        else f"Tool call failed: {call.error or 'unknown error'}"
                    )
                    await self.chat_append_message(
                        chat_id,
                        HelpChatDocResultMessage(
                            name=call.name,
                            arguments=call.arguments,
                            result=result,
                        ),
                        on_update=on_update,
                    )

                rounds += 1

                if not calls or rounds > self.chat_doc_lookup_iterations:
                    if calls:
                        log.warning(
                            "help.chat.lookup_rounds_exhausted", chat_id=chat_id
                        )
                    break

            chat = self.chat_get(chat_id)
            if chat and not chat.title and self._chat_has_enough_for_title(chat):
                try:
                    title = await self.chat_generate_title(chat_id)
                    if title and on_title_generated:
                        await on_title_generated(chat_id, title)
                except Exception:
                    pass  # title generation is best-effort

        await async_signals.get("agent.help.chat.after").send(
            HelpChatEmission(agent=self, chat_id=chat_id, chat=self.chat_get(chat_id))
        )

        # only on success - on failure the tracked task's error handler emits
        # the chat_done carrying the error, and a success-shaped chat_done
        # would trigger a history re-sync that wipes the error message
        if on_done:
            try:
                await on_done(chat_id)
            except Exception as e:
                log.error("help.chat.on_done.error", error=e)

        return self.chat_get(chat_id)

    @set_processing
    async def chat_send(
        self,
        chat_id: str,
        message: str,
        ux_snapshot: dict | None = None,
        on_update: OnUpdate | None = None,
        on_done: OnDone | None = None,
        on_title_generated: OnTitleGenerated | None = None,
    ) -> HelpChat | None:
        """Append a user message and generate a help response."""
        await self.chat_append_message(
            chat_id, HelpChatMessage(message=message, source="user")
        )
        return await self.chat_generate_next(
            chat_id,
            ux_snapshot=ux_snapshot,
            on_update=on_update,
            on_done=on_done,
            on_title_generated=on_title_generated,
        )

    @set_processing
    async def chat_regenerate_last(
        self,
        chat_id: str,
        ux_snapshot: dict | None = None,
        on_update: OnUpdate | None = None,
        on_done: OnDone | None = None,
        on_title_generated: OnTitleGenerated | None = None,
    ) -> HelpChat | None:
        """Remove the most recent help text message and generate a new one."""
        chat = self.chat_get(chat_id)
        if not chat or not chat.messages:
            return chat

        for i in range(len(chat.messages) - 1, -1, -1):
            message = chat.messages[i]
            if message.type == "text" and message.source == "help":
                del chat.messages[i]
                self._chat_persist()
                break
        else:
            return chat

        return await self.chat_generate_next(
            chat_id,
            ux_snapshot=ux_snapshot,
            on_update=on_update,
            on_done=on_done,
            on_title_generated=on_title_generated,
        )

    # === Title generation ===

    def _chat_has_enough_for_title(self, chat: HelpChat) -> bool:
        has_user = any(m.type == "text" and m.source == "user" for m in chat.messages)
        has_help = any(
            m.type == "text" and m.source == "help" and m.message != INITIAL_MESSAGE
            for m in chat.messages
        )
        return has_user and has_help

    async def chat_generate_title(self, chat_id: str) -> str | None:
        chat = self.chat_get(chat_id)
        if not chat:
            return None

        excerpt_parts = []
        for message in chat.messages[:6]:
            if message.type != "text":
                continue
            excerpt_parts.append(f"{message.source}: {message.message}")

        title = await generate_chat_title(
            self.client, "\n".join(excerpt_parts), "the Talemate help assistant"
        )
        if title:
            self.chat_update_title(chat_id, title)

        return title
