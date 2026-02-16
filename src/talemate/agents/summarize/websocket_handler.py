import pydantic
import structlog

from talemate.agents.summarize.context_history import ContextHistoryPreviewOverrides
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

__all__ = [
    "SummarizeWebsocketHandler",
]

log = structlog.get_logger("talemate.server.summarize")


class ApplyContextHistoryConfigPayload(pydantic.BaseModel):
    dialogue_ratio: int
    summary_detail_ratio: int
    max_budget: int
    enforce_boundary: bool
    best_fit: bool


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

    async def handle_apply_context_history_config(self, data: dict):
        """Apply context history config overrides to the summarizer agent and persist."""
        payload = ApplyContextHistoryConfigPayload(**data.get("config", {}))
        action_config = self.summarizer.actions["manage_scene_history"].config

        action_config["dialogue_ratio"].value = payload.dialogue_ratio
        action_config["summary_detail_ratio"].value = payload.summary_detail_ratio
        action_config["max_budget"].value = payload.max_budget
        action_config["enforce_boundary"].value = payload.enforce_boundary
        action_config["best_fit"].value = payload.best_fit

        await self.summarizer.save_config()
        await self.summarizer.emit_status()
