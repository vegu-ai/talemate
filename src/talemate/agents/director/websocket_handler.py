import pydantic
import structlog

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.status import set_loading

__all__ = [
    "DirectorWebsocketHandler",
]

log = structlog.get_logger("talemate.server.director")

class InstructionPayload(pydantic.BaseModel):
    instructions:str = ""

class SelectChoicePayload(pydantic.BaseModel):
    choice: str

class CharacterPayload(InstructionPayload):
    character:str = ""

class DirectorWebsocketHandler(Plugin):
    """
    Handles director actions
    """
    
    router = "director"
    
    @property
    def director(self):
        return get_agent("director")
    
    @set_loading("Generating dynamic actions", cancellable=True, as_async=True)
    async def handle_request_dynamic_choices(self, data: dict):
        """
        Generate clickable actions for the user
        """
        payload = InstructionPayload(**data)
        await self.director.generate_choices(instructions=payload.instructions)
        
    async def handle_select_choice(self, data: dict):
        payload = SelectChoicePayload(**data)
        character = self.scene.get_player_character()
        actor = character.actor
        
        await actor.generate_from_choice(payload.choice)