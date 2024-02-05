import pydantic
import structlog

from talemate.agents.creator.assistant import ContentGenerationContext
from talemate.instance import get_agent

log = structlog.get_logger("talemate.server.assistant")


class AssistantPlugin:
    router = "assistant"

    @property
    def scene(self):
        return self.websocket_handler.scene

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    async def handle(self, data: dict):
        log.info("assistant action", action=data.get("action"))

        fn = getattr(self, f"handle_{data.get('action')}", None)

        if fn is None:
            return

        await fn(data)

    async def handle_contextual_generate(self, data: dict):
        payload = ContentGenerationContext(**data)
        creator = get_agent("creator")
        content = await creator.contextual_generate(payload)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "contextual_generate_done",
                "data": {
                    "generated_content": content,
                    **payload.model_dump(),
                },
            }
        )
