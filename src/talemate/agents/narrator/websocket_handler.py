import pydantic
import structlog

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.status import set_loading


from talemate.scene_message import ContextInvestigationMessage

__all__ = [
    "NarratorWebsocketHandler",
]

log = structlog.get_logger("talemate.server.narrator")


class QueryPayload(pydantic.BaseModel):
    query: str
    at_the_end: bool = True


class NarrativeDirectionPayload(pydantic.BaseModel):
    narrative_direction: str = ""


class CharacterPayload(NarrativeDirectionPayload):
    character: str = ""


class NarratorWebsocketHandler(Plugin):
    """
    Handles narrator actions
    """

    router = "narrator"

    @property
    def narrator(self):
        return get_agent("narrator")

    @set_loading("Progressing the story", cancellable=True, as_async=True)
    async def handle_progress(self, data: dict):
        """
        Progress the story (optionally to a specific direction)
        """
        payload = NarrativeDirectionPayload(**data)
        await self.narrator.action_to_narration(
            "progress_story",
            narrative_direction=payload.narrative_direction,
            emit_message=True,
        )

    @set_loading("Narrating the environment", cancellable=True, as_async=True)
    async def handle_narrate_environment(self, data: dict):
        """
        Narrate the environment (optionally to a specific direction)
        """
        payload = NarrativeDirectionPayload(**data)
        await self.narrator.action_to_narration(
            "narrate_environment",
            narrative_direction=payload.narrative_direction,
            emit_message=True,
        )

    @set_loading("Working on a query", cancellable=True, as_async=True)
    async def handle_query(self, data: dict):
        """
        Give a query or instruction to the narrator that results in a context investigation
        message.
        """
        payload = QueryPayload(**data)

        narration = await self.narrator.narrate_query(**payload.model_dump())
        message: ContextInvestigationMessage = ContextInvestigationMessage(
            narration, sub_type="query"
        )
        message.set_source("narrator", "narrate_query", **payload.model_dump())

        emit("context_investigation", message=message)
        self.scene.push_history(message)

    @set_loading("Looking at the scene", cancellable=True, as_async=True)
    async def handle_look_at_scene(self, data: dict):
        """
        Look at the scene (optionally to a specific direction)

        This will result in a context investigation message.
        """
        payload = NarrativeDirectionPayload(**data)

        narration = await self.narrator.narrate_scene(
            narrative_direction=payload.narrative_direction
        )

        message: ContextInvestigationMessage = ContextInvestigationMessage(
            narration, sub_type="visual-scene"
        )
        message.set_source("narrator", "narrate_scene", **payload.model_dump())

        emit("context_investigation", message=message)
        self.scene.push_history(message)

    @set_loading("Looking at a character", cancellable=True, as_async=True)
    async def handle_look_at_character(self, data: dict):
        """
        Look at a character (optionally to a specific direction)

        This will result in a context investigation message.
        """
        payload = CharacterPayload(**data)

        narration = await self.narrator.narrate_character(
            character=self.scene.get_character(payload.character),
            narrative_direction=payload.narrative_direction,
        )

        message: ContextInvestigationMessage = ContextInvestigationMessage(
            narration, sub_type="visual-character"
        )
        message.set_source("narrator", "narrate_character", **payload.model_dump())

        emit("context_investigation", message=message)
        self.scene.push_history(message)
