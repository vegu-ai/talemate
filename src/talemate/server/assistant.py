import pydantic
import structlog
import traceback

from talemate.agents.creator.assistant import ContentGenerationContext
from talemate.emit import emit
from talemate.instance import get_agent

log = structlog.get_logger("talemate.server.assistant")


class ForkScenePayload(pydantic.BaseModel):
    message_id: int
    save_name: str | None = None


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

        if payload.computed_context[0] == "acting_instructions":
            content = await creator.determine_character_dialogue_instructions(
                self.scene.get_character(payload.character),
                instructions=payload.instructions,
            )
        else:
            content = await creator.contextual_generate(payload)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "contextual_generate_done",
                "data": {
                    "generated_content": content,
                    "uid": payload.uid,
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

                log.info(
                    "Running autocomplete for dialogue",
                    partial=data.partial,
                    character=character,
                )
                await creator.autocomplete_dialogue(
                    data.partial, character, emit_signal=True
                )
                return
            elif context_type == "narrative":
                log.info("Running autocomplete for narrative", partial=data.partial)
                await creator.autocomplete_narrative(data.partial, emit_signal=True)
                return

            # force length to 35
            data.length = 35
            log.info("Running autocomplete for contextual generation", args=data)
            completion = await creator.contextual_generate(data)
            log.info(
                "Autocomplete for contextual generation complete", completion=completion
            )
            completion = (
                completion.replace(f"{context_name}: {data.partial}", "")
                .lstrip(".")
                .strip()
            )

            emit("autocomplete_suggestion", completion)
        except Exception:
            log.error("Error running autocomplete", error=traceback.format_exc())
            emit("autocomplete_suggestion", "")

    async def handle_fork_new_scene(self, data: dict):
        """
        Allows to fork a new scene from a specific message
        in the current scene.

        All content after the message will be removed and the
        context database will be re imported ensuring a clean state.

        All state reinforcements will be reset to their most recent
        state before the message.
        """

        payload = ForkScenePayload(**data)

        creator = get_agent("creator")

        await creator.fork_scene(payload.message_id, payload.save_name)
