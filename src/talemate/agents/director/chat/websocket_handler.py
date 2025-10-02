import pydantic
import asyncio
import structlog
from typing import Literal, TYPE_CHECKING

from talemate.instance import get_agent
from .context import create_task_with_chat_context
import talemate.util as util

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.server.director.chat")


class ChatHistoryPayload(pydantic.BaseModel):
    chat_id: str


class ChatSendPayload(pydantic.BaseModel):
    chat_id: str
    message: str


class ChatClearPayload(pydantic.BaseModel):
    chat_id: str


class ChatRemoveMessagePayload(pydantic.BaseModel):
    chat_id: str
    message_id: str


class ChatRegeneratePayload(pydantic.BaseModel):
    chat_id: str


class ConfirmActionPayload(pydantic.BaseModel):
    chat_id: str
    id: str
    decision: Literal["confirm", "reject"]


class ChatUpdateModePayload(pydantic.BaseModel):
    chat_id: str
    mode: Literal["normal", "decisive", "nospoilers"]


class ChatUpdateConfirmWriteActionsPayload(pydantic.BaseModel):
    chat_id: str
    confirm_write_actions: bool


class DirectorChatWebsocketMixin:
    """
    Mixin for chat-related websocket handlers (router remains 'director').
    Expects the concrete handler to provide:
    - property `director` returning the DirectorAgent
    - attributes `scene` and `websocket_handler` (provided by base Plugin)
    """

    @property
    def director(self):
        return get_agent("director")

    def _make_generation_callbacks(self, payload_chat_id: str):
        async def _on_update(chat_id, new_messages):
            try:
                self.websocket_handler.queue_put(
                    {
                        "type": "director",
                        "action": "chat_append",
                        "chat_id": chat_id,
                        "messages": [m.model_dump() for m in new_messages],
                        "token_total": sum(
                            util.count_tokens(str(m))
                            for m in self.director.chat_history(chat_id)
                        ),
                    }
                )
            except Exception as e:
                log.error("director.chat.websocket.on_update.error", error=e)

        async def _on_done(chat_id, budgets):
            try:
                self.websocket_handler.queue_put(
                    {
                        "type": "director",
                        "action": "chat_done",
                        "chat_id": chat_id,
                        "budgets": budgets.model_dump() if budgets else None,
                    }
                )
            except Exception as e:
                log.error("director.chat.websocket.on_done.error", error=e)

        async def _on_compacting(chat_id):
            try:
                self.websocket_handler.queue_put(
                    {
                        "type": "director",
                        "action": "chat_compacting",
                        "chat_id": chat_id,
                    }
                )
            except Exception as e:
                log.error("director.chat.websocket.on_compacting.error", error=e)

        async def _on_compacted(chat_id, new_messages):
            try:
                self.websocket_handler.queue_put(
                    {
                        "type": "director",
                        "action": "chat_history",
                        "chat_id": chat_id,
                        "messages": [m.model_dump() for m in new_messages],
                        "token_total": sum(
                            util.count_tokens(str(m)) for m in new_messages
                        ),
                    }
                )
                self.websocket_handler.queue_put(
                    {
                        "type": "director",
                        "action": "chat_append",
                        "chat_id": chat_id,
                        "messages": [
                            {
                                "source": "director",
                                "type": "compaction_notice",
                                "message": "Older chat was summarized to keep context within limits.",
                            }
                        ],
                        "token_delta": util.count_tokens(
                            "Older chat was summarized to keep context within limits."
                        ),
                    }
                )
            except Exception as e:
                log.error("director.chat.websocket.on_compacted.error", error=e)

        return _on_update, _on_done, _on_compacting, _on_compacted

    def _attach_task_done_callback(self, task, chat_id: str):
        async def handle_task_done(task):
            if task.exception():
                exc = task.exception()
                log.error("director.chat.websocket.task.error", error=exc)
                try:
                    self.websocket_handler.queue_put(
                        {
                            "type": "director",
                            "action": "chat_done",
                            "chat_id": chat_id,
                        }
                    )
                except Exception as e:
                    log.error("director.chat.websocket.task.done_emit.error", error=e)

        task.add_done_callback(lambda task: asyncio.create_task(handle_task_done(task)))

    async def handle_chat_create(self, data: dict):
        chat = self.director.chat_create()

        # emit updated list and history for the new chat
        self.websocket_handler.queue_put(
            {
                "type": "director",
                "action": "chat_created",
                "chat_id": chat.id,
                "chats": self.director.chat_list(),
            }
        )
        self.websocket_handler.queue_put(
            {
                "type": "director",
                "action": "chat_history",
                "chat_id": chat.id,
                "messages": [m.model_dump() for m in chat.messages],
                "mode": chat.mode,
                "confirm_write_actions": getattr(chat, "confirm_write_actions", True),
            }
        )

    async def handle_chat_history(self, data: dict):
        payload = ChatHistoryPayload(**data)
        messages = self.director.chat_history(payload.chat_id)
        chat = self.director.chat_get(payload.chat_id)
        mode = chat.mode if chat else "normal"
        confirm_write_actions = chat.confirm_write_actions if chat else True

        self.websocket_handler.queue_put(
            {
                "type": "director",
                "action": "chat_history",
                "chat_id": payload.chat_id,
                "messages": [m.model_dump() for m in messages],
                "token_total": sum(util.count_tokens(str(m)) for m in messages),
                "mode": mode,
                "confirm_write_actions": confirm_write_actions,
            }
        )

    async def handle_chat_send(self, data: dict):
        payload = ChatSendPayload(**data)

        _on_update, _on_done, _on_compacting, _on_compacted = self._make_generation_callbacks(
            payload.chat_id
        )

        # delegate the generation to the agent mixin method in background
        # Determine confirm_write_actions for this chat context
        chat = self.director.chat_get(payload.chat_id)
        cwa = chat.confirm_write_actions if chat else True

        task = create_task_with_chat_context(
            self.director.chat_send,
            payload.chat_id,
            payload.chat_id,
            payload.message,
            on_update=_on_update,
            on_done=_on_done,
            on_compacting=_on_compacting,
            on_compacted=_on_compacted,
            confirm_write_actions=cwa,
        )
        self._attach_task_done_callback(task, payload.chat_id)

    async def handle_chat_clear(self, data: dict):
        payload = ChatClearPayload(**data)
        cleared = self.director.chat_clear(payload.chat_id)
        self.websocket_handler.queue_put(
            {
                "type": "director",
                "action": "chat_cleared",
                "chat_id": payload.chat_id,
                "cleared": cleared,
            }
        )
        if cleared:
            # Emit the reset greeting history so UI updates immediately
            messages = self.director.chat_history(payload.chat_id)
            chat = self.director.chat_get(payload.chat_id)
            mode = chat.mode if chat else "normal"
            confirm_write_actions = chat.confirm_write_actions if chat else True
            self.websocket_handler.queue_put(
                {
                    "type": "director",
                    "action": "chat_history",
                    "chat_id": payload.chat_id,
                    "messages": [m.model_dump() for m in messages],
                    "mode": mode,
                    "confirm_write_actions": confirm_write_actions,
                }
            )

    async def handle_chat_remove_message(self, data: dict):
        payload = ChatRemoveMessagePayload(**data)
        chat = self.director.chat_remove_message(payload.chat_id, payload.message_id)
        if not chat:
            return
        self.websocket_handler.queue_put(
            {
                "type": "director",
                "action": "chat_history",
                "chat_id": payload.chat_id,
                "messages": [m.model_dump() for m in chat.messages],
                "token_total": sum(util.count_tokens(str(m)) for m in chat.messages),
                "mode": chat.mode,
                "confirm_write_actions": getattr(chat, "confirm_write_actions", True),
            }
        )

    async def handle_chat_regenerate(self, data: dict):
        payload = ChatRegeneratePayload(**data)

        _on_update, _on_done, _on_compacting, _on_compacted = self._make_generation_callbacks(
            payload.chat_id
        )

        task = create_task_with_chat_context(
            self.director.chat_regenerate_last,
            payload.chat_id,
            payload.chat_id,
            on_update=_on_update,
            on_done=_on_done,
            on_compacting=_on_compacting,
            on_compacted=_on_compacted,
        )
        self._attach_task_done_callback(task, payload.chat_id)


    async def handle_confirm_action(self, data: dict):
        payload = ConfirmActionPayload(**data)

        log.debug("director.chat.websocket.handle_confirm_action", payload=payload)

        scene: "Scene" = self.scene

        key: str = f"_director_chat_action_confirm_{payload.id}"

        if key not in scene.nodegraph_state.shared:
            log.error(
                "director.chat.websocket.handle_confirm_action.key_not_found", key=key
            )
            return

        scene.nodegraph_state.shared[key] = payload.decision

        self.websocket_handler.queue_put(
            {
                "type": "director",
                "action": "confirm_action_processed",
                "chat_id": payload.chat_id,
                "id": payload.id,
                "decision": payload.decision,
            }
        )

    async def handle_chat_update_mode(self, data: dict):
        payload = ChatUpdateModePayload(**data)

        # Update the chat mode in the director
        chat = self.director.chat_get(payload.chat_id)
        if chat:
            chat.mode = payload.mode

            # Persist the updated chat state
            self.director.chat_set_chat_state(chat.model_dump())

    async def handle_chat_update_confirm_write_actions(self, data: dict):
        payload = ChatUpdateConfirmWriteActionsPayload(**data)

        chat = self.director.chat_get(payload.chat_id)
        if chat:
            chat.confirm_write_actions = payload.confirm_write_actions
            self.director.chat_set_chat_state(chat.model_dump())
