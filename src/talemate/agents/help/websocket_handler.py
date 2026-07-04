import pydantic
import structlog

import talemate.util as util
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

from .schema import HelpChat

log = structlog.get_logger("talemate.server.help")


class ChatSelectPayload(pydantic.BaseModel):
    chat_id: str


class ChatHistoryPayload(pydantic.BaseModel):
    chat_id: str


class ChatSendPayload(pydantic.BaseModel):
    chat_id: str
    message: str
    ux_snapshot: dict | None = None


class ChatRegeneratePayload(pydantic.BaseModel):
    chat_id: str
    ux_snapshot: dict | None = None


class ChatClearPayload(pydantic.BaseModel):
    chat_id: str


class ChatDeletePayload(pydantic.BaseModel):
    chat_id: str


class ChatUpdateSceneAwarePayload(pydantic.BaseModel):
    chat_id: str
    scene_aware: bool


class HelpWebsocketHandler(Plugin):
    """
    Websocket handler for the help agent chat.

    Generation runs as a tracked background task on the agent so it never
    blocks the websocket receive loop or the main talemate loop.
    """

    router = "help"

    @property
    def help_agent(self):
        return get_agent("help")

    def _chat_history_payload(self, chat: HelpChat, **overrides) -> dict:
        payload = {
            "type": "help",
            "action": "chat_history",
            "chat_id": chat.id,
            "messages": [message.model_dump() for message in chat.messages],
            "title": chat.title,
            "scene_aware": chat.scene_aware,
            "token_total": sum(
                util.count_tokens(str(message)) for message in chat.messages
            ),
        }
        payload.update(overrides)
        return payload

    def _chat_list_payload(self) -> list[dict]:
        return [entry.model_dump() for entry in self.help_agent.chat_list()]

    def _make_generation_callbacks(self):
        async def _on_update(chat_id, new_messages):
            try:
                self.websocket_handler.queue_put(
                    {
                        "type": "help",
                        "action": "chat_append",
                        "chat_id": chat_id,
                        "messages": [message.model_dump() for message in new_messages],
                    }
                )
            except Exception as e:
                log.error("help.chat.websocket.on_update.error", error=e)

        async def _on_done(chat_id):
            try:
                self.websocket_handler.queue_put(
                    {
                        "type": "help",
                        "action": "chat_done",
                        "chat_id": chat_id,
                    }
                )
            except Exception as e:
                log.error("help.chat.websocket.on_done.error", error=e)

        async def _on_title_generated(chat_id, title):
            try:
                self.websocket_handler.queue_put(
                    {
                        "type": "help",
                        "action": "chat_title_updated",
                        "chat_id": chat_id,
                        "title": title,
                    }
                )
            except Exception as e:
                log.error("help.chat.websocket.on_title_generated.error", error=e)

        return _on_update, _on_done, _on_title_generated

    def _make_error_handler(self, chat_id: str):
        async def _on_error(exc):
            self.websocket_handler.queue_put(
                {
                    "type": "help",
                    "action": "chat_done",
                    "chat_id": chat_id,
                    "error": str(exc),
                }
            )

        return _on_error

    async def handle_chat_list(self, data: dict):
        self.websocket_handler.queue_put(
            {
                "type": "help",
                "action": "chat_list",
                "chat_list": self._chat_list_payload(),
                "last_active_chat_id": self.help_agent.chat_get_last_active_id(),
            }
        )

    async def handle_chat_create(self, data: dict):
        chat = self.help_agent.chat_create()
        self.websocket_handler.queue_put(
            {
                "type": "help",
                "action": "chat_created",
                "chat_id": chat.id,
                "chat_list": self._chat_list_payload(),
            }
        )
        self.websocket_handler.queue_put(self._chat_history_payload(chat))

    async def handle_chat_select(self, data: dict):
        payload = ChatSelectPayload(**data)
        chat = self.help_agent.chat_get(payload.chat_id)
        if not chat:
            return
        self.help_agent.chat_set_last_active_id(payload.chat_id)
        self.websocket_handler.queue_put(self._chat_history_payload(chat))

    async def handle_chat_history(self, data: dict):
        payload = ChatHistoryPayload(**data)
        chat = self.help_agent.chat_get(payload.chat_id)
        if not chat:
            return
        self.websocket_handler.queue_put(self._chat_history_payload(chat))

    async def handle_chat_send(self, data: dict):
        payload = ChatSendPayload(**data)
        agent = self.help_agent

        _on_update, _on_done, _on_title_generated = self._make_generation_callbacks()

        task = await agent.run_tracked_task(
            f"help_chat_{payload.chat_id}",
            lambda: agent.chat_send(
                payload.chat_id,
                payload.message,
                ux_snapshot=payload.ux_snapshot,
                on_update=_on_update,
                on_done=_on_done,
                on_title_generated=_on_title_generated,
            ),
            background=True,
            error_handler=self._make_error_handler(payload.chat_id),
        )
        if task is None:
            self._reject_busy_chat(payload.chat_id, "send")

    async def handle_chat_regenerate(self, data: dict):
        payload = ChatRegeneratePayload(**data)
        agent = self.help_agent

        _on_update, _on_done, _on_title_generated = self._make_generation_callbacks()

        task = await agent.run_tracked_task(
            f"help_chat_{payload.chat_id}",
            lambda: agent.chat_regenerate_last(
                payload.chat_id,
                ux_snapshot=payload.ux_snapshot,
                on_update=_on_update,
                on_done=_on_done,
                on_title_generated=_on_title_generated,
            ),
            background=True,
            error_handler=self._make_error_handler(payload.chat_id),
        )
        if task is None:
            self._reject_busy_chat(payload.chat_id, "regenerate")

    def _reject_busy_chat(self, chat_id: str, action: str):
        """
        A generation is already in flight for this chat (single-flight skip),
        so the request was dropped - tell the frontend, otherwise the
        optimistic user message vanishes without explanation on the next
        history sync.
        """
        log.warning(
            "help.chat.websocket.already_generating", chat_id=chat_id, action=action
        )
        self.websocket_handler.queue_put(
            {
                "type": "help",
                "action": "chat_done",
                "chat_id": chat_id,
                "error": "Still generating a response in this chat - wait for it to finish, then send again.",
            }
        )

    async def handle_chat_clear(self, data: dict):
        payload = ChatClearPayload(**data)
        if not self.help_agent.chat_clear(payload.chat_id):
            return
        chat = self.help_agent.chat_get(payload.chat_id)
        self.websocket_handler.queue_put(self._chat_history_payload(chat))

    async def handle_chat_delete(self, data: dict):
        payload = ChatDeletePayload(**data)
        if not self.help_agent.chat_delete(payload.chat_id):
            return

        active_chat = self.help_agent.chat_get_or_create_active()
        self.websocket_handler.queue_put(
            {
                "type": "help",
                "action": "chat_deleted",
                "chat_id": payload.chat_id,
                "chat_list": self._chat_list_payload(),
                "active_chat_id": active_chat.id,
            }
        )
        self.websocket_handler.queue_put(self._chat_history_payload(active_chat))

    async def handle_chat_update_scene_aware(self, data: dict):
        payload = ChatUpdateSceneAwarePayload(**data)
        self.help_agent.chat_update_scene_aware(payload.chat_id, payload.scene_aware)
