import json
from typing import Awaitable, Callable, Literal

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
from . import inference_presets
from . import templates
from . import themes
from .model_validation import validate_openrouter_model
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

# the recommendation is the same for both switches, so it belongs to the
# section rather than to either of them
PERMISSION_WARNING = (
    "Use a strong agentic reasoning model before granting these. They let the "
    "help agent write real changes on its own, and weaker models misread what "
    "you asked for and make destructive or unwanted changes. Leave them off if "
    "the help agent runs on a small or non-reasoning client."
)

INITIAL_MESSAGE = (
    "Hi! I can help you with anything Talemate - settings, agents, clients, "
    "the world editor and more. I can look up your current settings, and change "
    "them or your templates for you once you grant me permission to. What would "
    "you like to know?"
)

OnUpdate = Callable[
    [str, list[HelpChatMessage | HelpChatDocResultMessage]], Awaitable[None]
]
OnDone = Callable[[str], Awaitable[None]]
# the theme id a write landed in, or None when the write was not a theme
OnTemplatesChanged = Callable[[str | None], Awaitable[None]]
OnTitleGenerated = Callable[[str, str], Awaitable[None]]

async_signals.register(
    "agent.help.chat.before",
    "agent.help.chat.after",
)


PERMISSION_REVOKED = (
    "The '{label}' permission was turned off while you were answering, so this "
    "change was not made. Tell the user it is off and that they can turn it back "
    "on under Settings > Connections > Agents > Help > Permissions."
)

SETTINGS_PERMISSION = "Allow changes to settings"
TEMPLATE_PERMISSION = "Allow changes to templates"

WRITE_TOOL_NAMES = frozenset(
    {
        "update_inference_presets",
        "update_agent_setting",
        "clear_agent_setting_scene_override",
        "update_app_config",
        "create_theme",
        "update_theme",
        "apply_theme",
        "create_template",
        "update_template",
    }
)


def revoked(allowed: bool, label: str) -> str | None:
    """The refusal for a permission taken away mid-round.

    The callbacks are built once per round and stay callable for the whole
    client request, so a revocation in that window has to reach the call rather
    than only the next round.
    """
    return None if allowed else PERMISSION_REVOKED.format(label=label)


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
                    description="How many rounds of tool calls (documentation lookups, settings, theme and template reads and updates) the help agent may perform before it must answer.",
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

        actions["permissions"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Permissions",
            icon="mdi-shield-key",
            description="What the help chat may change for you. Reading is always allowed; both permissions start off. They can also be toggled from the help chat itself.",
            warning=PERMISSION_WARNING,
            config={
                "allow_settings_changes": AgentActionConfig(
                    type="bool",
                    label="Allow changes to settings",
                    description="Lets the help chat change your application and agent settings when you ask it to. With this off it can still read them and walk you through the change yourself.",
                    value=False,
                    scene_overridable=False,
                ),
                "allow_template_changes": AgentActionConfig(
                    type="bool",
                    label="Allow changes to templates",
                    description="Lets the help chat create and change world state templates, themes included. With this off it can still read them. Applying a theme needs 'Allow changes to settings' as well, since it writes the theme's message styling and the active theme into your appearance settings.",
                    value=False,
                    scene_overridable=False,
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

    # `is True` rather than a truthy cast: a permission gate is the place for a
    # config value of the wrong type to read as withheld
    @property
    def allow_settings_changes(self) -> bool:
        return self.resolve_config("permissions", "allow_settings_changes") is True

    @property
    def allow_template_changes(self) -> bool:
        return self.resolve_config("permissions", "allow_template_changes") is True

    @property
    def allow_theme_apply(self) -> bool:
        """Applying a theme writes a template's styling into `config.appearance`,
        so it takes both permissions rather than the template one alone."""
        return self.allow_template_changes and self.allow_settings_changes

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
        async def find_docs(query: str):
            return docs.find_docs(query)

        async def search_docs(query: str):
            return docs.search_docs(query)

        async def read_doc(path: str):
            return docs.read_doc(path)

        async def read_doc_section(path: str, section: str):
            return docs.read_doc_section(path, section)

        return [
            focal.Callback(
                name="find_docs",
                arguments=[focal.Argument(name="query", type="str")],
                fn=find_docs,
                concurrent=True,
            ),
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
        # The settings view lives in the main viewport - merely having it open
        # is fine (incoming config pushes are handled cleanly); only unsaved
        # edits there conflict with a write. That view holds a working copy of
        # the WHOLE config and saves it from whatever page is showing, so its
        # dirty flag gates agent settings and app config alike - the page it
        # happens to be on says nothing about what a Save would overwrite.
        # Best-effort: the snapshot is from message-send time, so edits made
        # mid-generation are not seen.
        app_settings_dirty = bool(
            ((ux_snapshot or {}).get("app_settings_modal") or {}).get("dirty")
        )

        async def read_agent_settings(agent: str):
            return settings.read_agent_settings(agent)

        async def update_agent_setting(
            agent: str, action: str, setting: str, value, scope: str = "global"
        ):
            gone = revoked(self.allow_settings_changes, SETTINGS_PERMISSION)
            if gone:
                return gone
            return await settings.update_agent_setting(
                agent,
                action,
                setting,
                value,
                scope,
                app_settings_dirty=app_settings_dirty,
            )

        async def clear_agent_setting_scene_override(
            agent: str, action: str, setting: str
        ):
            gone = revoked(self.allow_settings_changes, SETTINGS_PERMISSION)
            if gone:
                return gone
            return await settings.clear_agent_setting_scene_override(
                agent, action, setting, app_settings_dirty=app_settings_dirty
            )

        async def read_app_config(
            section: str = "",
            path: list | None = None,
            fields: list | None = None,
            mode: Literal["auto", "index", "value"] = "auto",
            offset: int = 0,
            limit: int = 20,
            revision: str | None = None,
        ):
            return settings.read_app_config(
                section, path, fields, mode, offset, limit, revision
            )

        async def update_app_config(path: str, value):
            gone = revoked(self.allow_settings_changes, SETTINGS_PERMISSION)
            if gone:
                return gone
            return await settings.update_app_config(
                path, value, app_settings_dirty=app_settings_dirty
            )

        async def read_clients():
            return settings.read_clients()

        async def update_inference_presets(
            group: str,
            preset: str,
            parameters: dict,
            reset_rest: bool = False,
            group_is_key: bool = False,
        ):
            gone = revoked(self.allow_settings_changes, SETTINGS_PERMISSION)
            if gone:
                return gone
            return await inference_presets.update_inference_presets(
                group,
                preset,
                parameters,
                reset_rest,
                app_settings_dirty=app_settings_dirty,
                group_is_key=group_is_key,
            )

        # reads may run concurrently; writes stay sequential so config
        # mutations never race each other
        callbacks = [
            focal.Callback(
                name="validate_openrouter_model",
                arguments=[focal.Argument(name="model_id", type="str")],
                fn=validate_openrouter_model,
                concurrent=True,
            ),
            focal.Callback(
                name="read_agent_settings",
                arguments=[focal.Argument(name="agent", type="str")],
                fn=read_agent_settings,
                concurrent=True,
            ),
            focal.Callback(
                name="read_app_config",
                arguments=[
                    focal.Argument(name="section", type="str"),
                    focal.Argument(name="path", type="list"),
                    focal.Argument(name="fields", type="list"),
                    focal.Argument(name="mode", type="str"),
                    focal.Argument(name="offset", type="int"),
                    focal.Argument(name="limit", type="int"),
                    focal.Argument(name="revision", type="str"),
                ],
                fn=read_app_config,
                concurrent=True,
            ),
            focal.Callback(
                name="read_clients",
                arguments=[],
                fn=read_clients,
                concurrent=True,
            ),
            focal.Callback(
                name="describe_inference_parameters",
                arguments=[],
                fn=inference_presets.describe_inference_parameters,
                concurrent=True,
            ),
        ]

        if not self.allow_settings_changes:
            return callbacks

        return callbacks + [
            focal.Callback(
                name="update_inference_presets",
                arguments=[
                    focal.Argument(name="group", type="str"),
                    focal.Argument(name="preset", type="str"),
                    focal.Argument(name="parameters", type="dict"),
                    focal.Argument(name="reset_rest", type="bool"),
                    focal.Argument(name="group_is_key", type="bool"),
                ],
                fn=update_inference_presets,
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
                name="update_app_config",
                arguments=[
                    focal.Argument(name="path", type="str"),
                    focal.Argument(
                        name="value", type="str | int | float | bool | list"
                    ),
                ],
                fn=update_app_config,
            ),
        ]

    def _chat_theme_callbacks(
        self,
        ux_snapshot: dict | None = None,
        on_templates_changed: OnTemplatesChanged | None = None,
    ) -> list[focal.Callback]:
        snapshot = ux_snapshot or {}
        # the Templates tab saves the whole template it is on; applying a theme
        # writes the appearance settings, which the settings view saves whole
        templates_dirty = bool((snapshot.get("templates_view") or {}).get("dirty"))
        app_settings_dirty = bool(
            (snapshot.get("app_settings_modal") or {}).get("dirty")
        )

        async def _notify(result):
            if on_templates_changed and isinstance(result, dict):
                await on_templates_changed(result["theme_id"])
            return result

        async def list_themes():
            return themes.list_themes(self.scene)

        async def read_theme(theme_id: str):
            return themes.read_theme(self.scene, theme_id)

        async def create_theme(
            name: str,
            group: str,
            base_theme: str | None = None,
            colors: dict | None = None,
            appearance: dict | None = None,
            dark: bool | None = None,
            code_editor: str | None = None,
        ):
            gone = revoked(self.allow_template_changes, TEMPLATE_PERMISSION)
            if gone:
                return gone
            return await _notify(
                await themes.create_theme(
                    self.scene,
                    name,
                    group,
                    base_theme=base_theme,
                    colors=colors,
                    appearance=appearance,
                    dark=dark,
                    code_editor=code_editor,
                    templates_dirty=templates_dirty,
                )
            )

        async def update_theme(
            theme_id: str,
            colors: dict | None = None,
            appearance: dict | None = None,
            dark: bool | None = None,
            code_editor: str | None = None,
        ):
            gone = revoked(self.allow_template_changes, TEMPLATE_PERMISSION)
            if gone:
                return gone
            return await _notify(
                await themes.update_theme(
                    self.scene,
                    theme_id,
                    colors=colors,
                    appearance=appearance,
                    dark=dark,
                    code_editor=code_editor,
                    templates_dirty=templates_dirty,
                )
            )

        async def apply_theme(theme_id: str):
            # applying writes the appearance settings as well as reading a
            # template, so it answers to both permissions
            gone = revoked(self.allow_template_changes, TEMPLATE_PERMISSION) or revoked(
                self.allow_settings_changes, SETTINGS_PERMISSION
            )
            if gone:
                return gone
            return await themes.apply_theme(
                self.scene,
                theme_id,
                templates_dirty=templates_dirty,
                app_settings_dirty=app_settings_dirty,
            )

        callbacks = [
            focal.Callback(
                name="list_themes",
                arguments=[],
                fn=list_themes,
                concurrent=True,
            ),
            focal.Callback(
                name="read_theme",
                arguments=[focal.Argument(name="theme_id", type="str")],
                fn=read_theme,
                concurrent=True,
            ),
        ]

        if not self.allow_template_changes:
            return callbacks

        callbacks = callbacks + [
            focal.Callback(
                name="create_theme",
                arguments=[
                    focal.Argument(name="name", type="str"),
                    focal.Argument(name="group", type="str"),
                    focal.Argument(name="base_theme", type="str"),
                    focal.Argument(name="colors", type="dict"),
                    focal.Argument(name="appearance", type="dict"),
                    focal.Argument(name="dark", type="bool"),
                    focal.Argument(name="code_editor", type="str"),
                ],
                fn=create_theme,
            ),
            focal.Callback(
                name="update_theme",
                arguments=[
                    focal.Argument(name="theme_id", type="str"),
                    focal.Argument(name="colors", type="dict"),
                    focal.Argument(name="appearance", type="dict"),
                    focal.Argument(name="dark", type="bool"),
                    focal.Argument(name="code_editor", type="str"),
                ],
                fn=update_theme,
            ),
        ]

        if not self.allow_theme_apply:
            return callbacks

        return callbacks + [
            focal.Callback(
                name="apply_theme",
                arguments=[focal.Argument(name="theme_id", type="str")],
                fn=apply_theme,
            ),
        ]

    def _chat_template_callbacks(
        self,
        ux_snapshot: dict | None = None,
        on_templates_changed: OnTemplatesChanged | None = None,
    ) -> list[focal.Callback]:
        templates_dirty = bool(
            ((ux_snapshot or {}).get("templates_view") or {}).get("dirty")
        )

        async def _notify(result):
            if on_templates_changed and isinstance(result, dict):
                await on_templates_changed(None)
            return result

        async def list_templates(template_type: str | None = None):
            return templates.list_templates(self.scene, template_type)

        async def describe_template_type(template_type: str):
            return templates.describe_template_type(template_type)

        async def read_template(template_id: str):
            return templates.read_template(self.scene, template_id)

        async def create_template(
            template_type: str,
            name: str,
            group: str,
            fields: dict | None = None,
        ):
            gone = revoked(self.allow_template_changes, TEMPLATE_PERMISSION)
            if gone:
                return gone
            return await _notify(
                await templates.create_template(
                    self.scene,
                    template_type,
                    name,
                    group,
                    fields=fields,
                    templates_dirty=templates_dirty,
                    scene_loaded=self.scene_loaded,
                )
            )

        async def update_template(template_id: str, fields: dict):
            gone = revoked(self.allow_template_changes, TEMPLATE_PERMISSION)
            if gone:
                return gone
            return await _notify(
                await templates.update_template(
                    self.scene,
                    template_id,
                    fields,
                    templates_dirty=templates_dirty,
                    scene_loaded=self.scene_loaded,
                )
            )

        callbacks = [
            focal.Callback(
                name="list_templates",
                arguments=[focal.Argument(name="template_type", type="str")],
                fn=list_templates,
                concurrent=True,
            ),
            focal.Callback(
                name="describe_template_type",
                arguments=[focal.Argument(name="template_type", type="str")],
                fn=describe_template_type,
                concurrent=True,
            ),
            focal.Callback(
                name="read_template",
                arguments=[focal.Argument(name="template_id", type="str")],
                fn=read_template,
                concurrent=True,
            ),
        ]

        if not self.allow_template_changes:
            return callbacks

        return callbacks + [
            focal.Callback(
                name="create_template",
                arguments=[
                    focal.Argument(name="template_type", type="str"),
                    focal.Argument(name="name", type="str"),
                    focal.Argument(name="group", type="str"),
                    focal.Argument(name="fields", type="dict"),
                ],
                fn=create_template,
            ),
            focal.Callback(
                name="update_template",
                arguments=[
                    focal.Argument(name="template_id", type="str"),
                    focal.Argument(name="fields", type="dict"),
                ],
                fn=update_template,
            ),
        ]

    # === Generation ===

    @staticmethod
    def _chat_render_message(message, index: int = 1) -> str:
        if message.type == "doc_result":
            data = message.model_dump(mode="json")
            return (
                f"[#{index}] [tool call] `{message.name}` "
                f"{json.dumps(data['arguments'], indent=2)}\n"
                f"Result: {json.dumps(data['result'], indent=2)}\n---"
            )
        return f"[#{index}] [{message.source}] {message.message}\n---"

    @classmethod
    def _chat_render_history(cls, history: list) -> str:
        return "\n\n".join(
            cls._chat_render_message(message, index)
            for index, message in enumerate(history, 1)
        )

    @classmethod
    def _chat_trim_history(cls, history: list, budget_tokens: int) -> list:
        request_index = next(
            (
                index
                for index in range(len(history) - 1, -1, -1)
                if history[index].type == "text" and history[index].source == "user"
            ),
            None,
        )
        turn_start = request_index + 1 if request_index is not None else 0
        tool_indices = [
            index
            for index in range(turn_start, len(history))
            if history[index].type == "doc_result"
        ]
        selected = (
            {request_index: history[request_index]} if request_index is not None else {}
        )
        costs = {}

        def cost(index):
            if index not in costs:
                # Allow for separators and the final message-number prefix.
                costs[index] = (
                    util.count_tokens(cls._chat_render_message(history[index])) + 8
                )
            return costs[index]

        def omission_notice(indices):
            names = ", ".join(dict.fromkeys(history[index].name for index in indices))
            return HelpChatMessage(
                source="help",
                message=(
                    f"[{len(indices)} tool result{'s' if len(indices) != 1 else ''} "
                    f"of this turn omitted to fit context: {names}. "
                    "Do not repeat these calls or claim their outcomes. "
                    "Ask the user to increase the client's context length if the missing results are needed.]"
                ),
            )

        used = cost(request_index) if request_index is not None else 0
        turn_cost = sum(cost(index) for index in range(turn_start, len(history)))
        current_turn_cost = used + turn_cost
        if current_turn_cost > budget_tokens:
            current_turn = (
                history[request_index:] if request_index is not None else history
            )
            current_turn_cost = util.count_tokens(
                cls._chat_render_history(current_turn)
            )
        if current_turn_cost <= budget_tokens:
            selected.update(
                (index, history[index]) for index in range(turn_start, len(history))
            )
            used = current_turn_cost
            for index in range(turn_start - 2, -1, -1):
                if used + cost(index) > budget_tokens:
                    break
                selected[index] = history[index]
                used += cost(index)
        else:
            if tool_indices:
                used += (
                    util.count_tokens(
                        cls._chat_render_message(omission_notice(tool_indices))
                    )
                    + 8
                )
            newest_write = next(
                (
                    index
                    for index in reversed(tool_indices)
                    if history[index].name in WRITE_TOOL_NAMES
                ),
                None,
            )
            order = ([newest_write] if newest_write is not None else []) + [
                index
                for index in range(len(history) - 1, turn_start - 1, -1)
                if index != newest_write
            ]
            kept_tool = False
            for index in order:
                message = history[index]
                if used + cost(index) <= budget_tokens:
                    selected[index] = message
                    used += cost(index)
                    kept_tool |= message.type == "doc_result"
                elif (
                    not kept_tool
                    and message.type == "doc_result"
                    and used < budget_tokens
                ):
                    # Only the prompt gets a preview; persisted results remain intact.
                    content = json.dumps(
                        message.model_dump(mode="json")["result"], indent=2
                    )
                    marker = "[Result truncated to fit context; omitted content has not been read.]\n"
                    low, high = 0, len(content)
                    preview_cost = 0
                    while low <= high:
                        length = (low + high) // 2
                        preview = message.model_copy(
                            update={"result": marker + content[:length]}
                        )
                        tokens = (
                            util.count_tokens(cls._chat_render_message(preview)) + 8
                        )
                        if used + tokens <= budget_tokens:
                            selected[index] = preview
                            preview_cost = tokens
                            low = length + 1
                        else:
                            high = length - 1
                    if index in selected:
                        used += preview_cost
                        kept_tool = True

        trimmed = [
            selected[index] for index in range(len(history)) if index in selected
        ]
        omitted = [index for index in tool_indices if index not in selected]
        if omitted:
            trimmed.append(omission_notice(omitted))
        # The request and an explicit omission notice survive an exhausted budget.
        if util.count_tokens(cls._chat_render_history(trimmed)) > budget_tokens:
            trimmed = [history[request_index]] if request_index is not None else []
            if tool_indices:
                trimmed.append(omission_notice(tool_indices))
        return trimmed

    async def chat_generate_next(
        self,
        chat_id: str,
        ux_snapshot: dict | None = None,
        on_update: OnUpdate | None = None,
        on_done: OnDone | None = None,
        on_title_generated: OnTitleGenerated | None = None,
        on_templates_changed: OnTemplatesChanged | None = None,
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
                    + self._chat_settings_callbacks(ux_snapshot)
                    + self._chat_theme_callbacks(ux_snapshot, on_templates_changed)
                    + self._chat_template_callbacks(ux_snapshot, on_templates_changed),
                    max_calls=self.chat_max_doc_lookups,
                    max_concurrent=self.chat_max_doc_lookups,
                    retries=0,
                    response_length=self.chat_response_length,
                    scene=self.scene,
                    history=chat.messages,
                    history_trim=self._chat_trim_history,
                    render_history=self._chat_render_history,
                    docs_sections=docs.docs_section_overview(),
                    docs_available=docs.docs_available(),
                    docs_site_url=docs.DOCS_SITE_URL,
                    agent_types=sorted(instance.AGENTS.keys()),
                    theme_slots=themes.slot_reference(),
                    template_types=templates.type_reference(),
                    allow_settings_changes=self.allow_settings_changes,
                    allow_template_changes=self.allow_template_changes,
                    allow_theme_apply=self.allow_theme_apply,
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
        on_templates_changed: OnTemplatesChanged | None = None,
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
            on_templates_changed=on_templates_changed,
        )

    @set_processing
    async def chat_regenerate_last(
        self,
        chat_id: str,
        ux_snapshot: dict | None = None,
        on_update: OnUpdate | None = None,
        on_done: OnDone | None = None,
        on_title_generated: OnTitleGenerated | None = None,
        on_templates_changed: OnTemplatesChanged | None = None,
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
            on_templates_changed=on_templates_changed,
        )

    # === Title generation ===

    def _chat_has_enough_for_title(self, chat: HelpChat) -> bool:
        has_user = any(m.type == "text" and m.source == "user" for m in chat.messages)
        has_help = any(
            m.type == "text" and m.source == "help" and m.message != INITIAL_MESSAGE
            for m in chat.messages
        )
        return has_user and has_help

    @set_processing
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
