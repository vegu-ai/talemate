import pydantic
import asyncio
import structlog
from typing import TYPE_CHECKING

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from talemate.context import interaction
from talemate.status import set_loading

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "DirectorWebsocketHandler",
]

log = structlog.get_logger("talemate.server.director")

class InstructionPayload(pydantic.BaseModel):
    instructions:str = ""

class SelectChoicePayload(pydantic.BaseModel):
    choice: str
    character:str = ""

class CharacterPayload(InstructionPayload):
    character:str = ""

class PersistCharacterPayload(pydantic.BaseModel):
    name: str
    templates: list[str] | None = None
    narrate_entry: bool = True
    narrate_entry_direction: str = ""
    
    active: bool = True
    determine_name: bool = True
    augment_attributes: str = ""
    generate_attributes: bool = True
    
    content: str = ""
    description: str = ""


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
        payload = CharacterPayload(**data)
        await self.director.generate_choices(**payload.model_dump())
        
    async def handle_select_choice(self, data: dict):
        payload = SelectChoicePayload(**data)
        
        log.debug("selecting choice", payload=payload)
        
        if payload.character:
            character = self.scene.get_character(payload.character)
        else:
            character = self.scene.get_player_character()
        
        if not character:
            log.error("handle_select_choice: could not find character", payload=payload)
            return
        
        # hijack the interaction state
        try:
            interaction_state = interaction.get()
        except LookupError:
            # no interaction state
            log.error("handle_select_choice: no interaction state", payload=payload)
            return
        
        interaction_state.from_choice = payload.choice
        interaction_state.act_as = character.name if not character.is_player else None
        interaction_state.input = f"@{payload.choice}"
        
    async def handle_persist_character(self, data: dict):
        payload = PersistCharacterPayload(**data)
        scene: "Scene" = self.scene
        
        if not payload.content:
            payload.content = scene.snapshot(lines=15)
        
        # add as asyncio task
        task = asyncio.create_task(self.director.persist_character(**payload.model_dump()))
        async def handle_task_done(task):
            if task.exception():
                log.exception("Error persisting character", error=task.exception())
                await self.signal_operation_failed("Error persisting character")
            else:
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": "character_persisted",
                        "character": task.result(),
                    }
                )
                await self.signal_operation_done()

        task.add_done_callback(lambda task: asyncio.create_task(handle_task_done(task)))

