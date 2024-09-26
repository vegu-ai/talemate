import pydantic
import structlog

import talemate.util as util
from talemate.emit import emit
from talemate.context import interaction
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
        character = self.scene.get_player_character()
        actor = character.actor
        
        await actor.generate_from_choice(payload.choice)