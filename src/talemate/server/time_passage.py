"""
Websocket plugin for scene-level time passage operations.

Handles insert, delete, and update of TimePassageMessage entries in scene.history
when triggered from the live scene view (as opposed to the world state manager
history view, which uses archive-index-based operations defined in
server/world_state_manager/history.py).
"""

import pydantic
import structlog

from talemate.emit import emit
from talemate.history import (
    delete_time_passage_by_id,
    insert_time_passage_after_message,
    update_time_passage_by_id,
)
from talemate.server.websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.time_passage")

__all__ = ["TimePassagePlugin"]


class InsertAfterPayload(pydantic.BaseModel):
    message_id: int
    amount: int
    unit: str


class DeletePayload(pydantic.BaseModel):
    message_id: int


class UpdatePayload(pydantic.BaseModel):
    message_id: int
    amount: int
    unit: str


class TimePassagePlugin(Plugin):
    router = "time_passage"

    async def handle_insert_after(self, data: dict):
        """Insert a time passage after a specific scene message."""

        payload = InsertAfterPayload(**data)

        try:
            insert_time_passage_after_message(
                self.scene,
                payload.message_id,
                payload.amount,
                payload.unit,
            )
        except (ValueError, IndexError) as e:
            await self.signal_operation_failed(str(e))
            return

        self.scene.emit_status()
        await self.scene.emit_history()
        await self.signal_operation_done()

    async def handle_delete(self, data: dict):
        """Delete a time passage by its message id."""

        payload = DeletePayload(**data)

        try:
            delete_time_passage_by_id(self.scene, payload.message_id)
        except (ValueError, IndexError) as e:
            await self.signal_operation_failed(str(e))
            return

        emit("remove_message", "", id=payload.message_id)
        self.scene.emit_status()
        await self.scene.emit_history()
        await self.signal_operation_done()

    async def handle_update(self, data: dict):
        """Update a time passage's duration by its message id."""

        payload = UpdatePayload(**data)

        try:
            update_time_passage_by_id(
                self.scene,
                payload.message_id,
                payload.amount,
                payload.unit,
            )
        except (ValueError, IndexError) as e:
            await self.signal_operation_failed(str(e))
            return

        self.scene.emit_status()
        await self.scene.emit_history()
        await self.signal_operation_done()
