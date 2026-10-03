import structlog

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.knowledge.review import character_context_review
from talemate.knowledge.step import repair_knowledge
from talemate.status import background_task

__all__ = [
    "SummarizeWebsocketHandler",
]

log = structlog.get_logger("talemate.server.summarize")


class SummarizeWebsocketHandler(Plugin):
    """
    Handles summarize actions
    """

    router = "summarizer"

    @property
    def summarizer(self):
        return get_agent("summarizer")

    @background_task("Repairing character knowledge")
    async def handle_repair_knowledge(self, data: dict):
        """Rebuild every out-of-sync perspective and summary; a Stop keeps the rest flagged."""
        scene = self.scene
        try:
            await repair_knowledge(scene)
        finally:
            scene.emit_status()
        await self.signal_operation_done()

    async def handle_context_review(self, data: dict):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed(
                "No scene loaded",
                request_id=data.get("request_id"),
                failed_action="context_review",
            )
            return

        name = data.get("character")
        if name is not None:
            if not isinstance(name, str) or name not in scene.active_characters:
                raise ValueError("Select an active character for the context preview")
            preview = await character_context_review(scene, scene.character_data[name])
        else:
            preview = self.summarizer.context_history_preview(scene)
            preview.update({"perspective": None, "exclusions": []})
        preview["scene_id"] = scene.id
        preview["characters"] = list(scene.active_characters)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "context_review",
                "data": preview,
                "request_id": data.get("request_id"),
            }
        )
