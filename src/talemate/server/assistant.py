import pydantic
import structlog

from talemate.agents.creator.assistant import ContentGenerationContext
from talemate.instance import get_agent
from talemate.emit import emit

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


    async def handle_autocomplete(self, data: dict):
        data = ContentGenerationContext(**data)
        try:
            creator = self.scene.get_helper("creator").agent
            context_type, context_name = data.computed_context
            
            if context_type == "dialogue":
                
                if not data.character:
                    character = self.scene.get_player_character()
                else:
                    character = self.scene.get_character(data.character)
                
                log.info("Running autocomplete dialogue", partial=data.partial, character=character)
                await creator.autocomplete_dialogue(data.partial, character, emit_signal=True)
                return
            elif context_type == "narrative":
                log.info("Running autocomplete narrative", partial=data.partial)
                await creator.autocomplete_narrative(data.partial, emit_signal=True)
                return
            
            # force length to 35
            data.length = 35
            log.info("Running autocomplete context", args=data)
            completion = await creator.contextual_generate(data)
            log.info("Autocomplete context complete", completion=completion)
            completion = completion.replace(f"{context_name}: {data.partial}","").lstrip(".").strip()
            
            emit("autocomplete_suggestion", completion)
        except Exception as e:
            log.error("Error running autocomplete", error=str(e))
            emit("autocomplete_suggestion", "")