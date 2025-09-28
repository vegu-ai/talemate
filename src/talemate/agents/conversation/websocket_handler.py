import pydantic
import structlog
import random
from typing import TYPE_CHECKING

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.status import set_loading
from talemate.scene_message import DirectorMessage

if TYPE_CHECKING:
    from talemate.agents.conversation import ConversationAgent

__all__ = [
    "ConversationWebsocketHandler",
]

log = structlog.get_logger("talemate.server.conversation")


class RequestActorActionPayload(pydantic.BaseModel):
    character: str = ""
    instructions: str = ""
    emit_signals: bool = True
    instructions_through_director: bool = True


class ConversationWebsocketHandler(Plugin):
    """
    Handles narrator actions
    """

    router = "conversation"

    @property
    def agent(self) -> "ConversationAgent":
        return get_agent("conversation")

    @set_loading("Generating actor action", cancellable=True, as_async=True)
    async def handle_request_actor_action(self, data: dict):
        """
        Generate an actor action
        """
        payload = RequestActorActionPayload(**data)
        character = None
        actor = None

        if payload.character:
            character = self.scene.get_character(payload.character)
            actor = character.actor
        else:
            actor = random.choice(list(self.scene.get_npc_characters())).actor

            if not actor:
                log.error("handle_request_actor_action: No actor found")
                return

            character = actor.character

        if payload.instructions_through_director:
            director_message = DirectorMessage(
                payload.instructions,
                source="player",
                meta={"character": character.name},
            )
            emit("director", message=director_message, character=character)
            await self.scene.push_history(director_message)
            generated_messages = await self.agent.converse(
                actor, emit_signals=payload.emit_signals
            )
        else:
            generated_messages = await self.agent.converse(
                actor,
                instruction=payload.instructions,
                emit_signals=payload.emit_signals,
            )

        for message in generated_messages:
            await self.scene.push_history(message)
            emit("character", message=message, character=character)
