import pydantic
import structlog

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.scene_message import CharacterMessage

log = structlog.get_logger("talemate.server.director")


class SelectChoicePayload(pydantic.BaseModel):
    choice: str

class DirectorPlugin:
    router = "director"

    @property
    def scene(self):
        return self.websocket_handler.scene

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    async def handle(self, data: dict):
        log.info("director action", action=data.get("action"))

        fn = getattr(self, f"handle_{data.get('action')}", None)

        if fn is None:
            return

        await fn(data)

    async def handle_generate_choices(self, data: dict):
        director = get_agent("director")
        await director.generate_choices()
        
    async def handle_select_choice(self, data: dict):
        payload = SelectChoicePayload(**data)
        conversation = get_agent("conversation")
        
        character = self.scene.get_player_character()
        actor = character.actor
        
        messages = await conversation.converse(actor, only_generate=True, instruction=payload.choice)
        
        for message in messages:
            character_message = CharacterMessage(
                message, source="player"
            )
            self.scene.push_history(character_message)
            emit("character", character_message, character=character)
            
        