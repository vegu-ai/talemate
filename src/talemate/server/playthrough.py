"""
Websocket plugin for playthrough mode.

Playthrough is a walkthrough of an existing scene: the frontend collapses the
message list to the first message and reveals the rest one at a time. It drives
the whole mode itself - the backend only hands it the material to walk through
and records where it was left off.
"""

import pydantic
import structlog

from talemate.server.websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.playthrough")

__all__ = ["PlaythroughPlugin"]


class SaveProgressPayload(pydantic.BaseModel):
    # the id of the message the reveal cursor is on; an index would not
    # survive the history being edited between two playthroughs
    message_id: int | str | None = None


class PlaythroughPlugin(Plugin):
    router = "playthrough"

    async def handle_start(self, data: dict):
        if not self.scene:
            await self.signal_operation_failed(
                "No scene loaded", request_id=data.get("request_id")
            )
            return

        # The reveal cursor can reach any message, so the frontend needs the
        # whole history rather than the max_backscroll tail it loads with.
        await self.scene.emit_history(uncapped=True)
        # The history arrives message by message with no end to it, so this is
        # what tells a client when the replay is all there, and where it can
        # place a resumed reveal cursor.
        self.websocket_handler.queue_put(
            {"type": self.router, "action": "replay_complete"}
        )
        await self.signal_operation_done(
            signal_only=True, request_id=data.get("request_id")
        )

    async def handle_save_progress(self, data: dict):
        if not self.scene:
            await self.signal_operation_failed(
                "No scene loaded", request_id=data.get("request_id")
            )
            return

        payload = SaveProgressPayload(**data)

        try:
            self.scene.write_playthrough_progress(payload.message_id)
        except Exception as e:
            log.error("playthrough: could not record progress", error=str(e))
            await self.signal_operation_failed(
                f"Could not record playthrough progress: {e}",
                request_id=data.get("request_id"),
            )
            return

        self.scene.emit_status()
        await self.signal_operation_done(
            signal_only=True, request_id=data.get("request_id")
        )
