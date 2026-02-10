import structlog

from talemate.agents.summarize.context_history import ContextHistoryPreviewOverrides
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

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

    async def handle_context_review(self, data: dict):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No scene loaded")
            return

        overrides = None
        if "overrides" in data:
            overrides = ContextHistoryPreviewOverrides(**data["overrides"])

        preview = self.summarizer.context_history_preview(scene, overrides=overrides)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "context_review",
                "data": preview,
            }
        )
