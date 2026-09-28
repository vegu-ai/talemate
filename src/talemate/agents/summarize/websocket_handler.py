import pydantic
import structlog

from talemate.exceptions import GenerationCancelled
from talemate.agents.summarize.perceptions import (
    PerceptionBacklogDecision,
    resolve_perception_backlog,
)
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.knowledge.review import character_context_review
from talemate.knowledge.readiness import perception_readiness, perception_status_data

__all__ = [
    "SummarizeWebsocketHandler",
]

log = structlog.get_logger("talemate.server.summarize")


class PerceptionBacklogResponsePayload(pydantic.BaseModel):
    request_id: str
    decision: PerceptionBacklogDecision


class SummarizeWebsocketHandler(Plugin):
    """
    Handles summarize actions
    """

    router = "summarizer"

    @property
    def summarizer(self):
        return get_agent("summarizer")

    async def handle_perception_backlog_response(self, data: dict):
        payload = PerceptionBacklogResponsePayload(**data)
        resolve_perception_backlog(payload.request_id, payload.decision)

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
            try:
                preview = await character_context_review(
                    scene, scene.character_data[name]
                )
            except GenerationCancelled as exc:
                if exc.message_id is None or exc.view_status is None:
                    raise
                message = scene.get_message(exc.message_id)
                if message is None:
                    raise
                state = perception_readiness(
                    scene, message, exc.view_status, character=name
                )
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": "context_review_status",
                        "data": perception_status_data(
                            scene, message, state, character=name
                        ),
                        "request_id": data.get("request_id"),
                    }
                )
                return
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
