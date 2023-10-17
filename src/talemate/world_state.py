from pydantic import BaseModel
from talemate.emit import emit
import structlog
from typing import Union

import talemate.instance as instance
from talemate.prompts import Prompt
import talemate.automated_action as automated_action

log = structlog.get_logger("talemate")

class CharacterState(BaseModel):
    snapshot: str = None
    emotion: str = None
    
class ObjectState(BaseModel):
    snapshot: str = None

class WorldState(BaseModel):
    
    # characters in the scene by name
    characters: dict[str, CharacterState] = {}
    
    # objects in the scene by name
    items: dict[str, ObjectState] = {}
    
    # location description
    location: Union[str, None] = None
    
    @property
    def agent(self):
        return instance.get_agent("summarizer")
    
    @property
    def pretty_json(self):
        return self.json(indent=2)
    
    @property
    def as_list(self):
        return self.render().as_list
        
    
    def emit(self, status="update"):
        emit("world_state", status=status, data=self.dict())
        
    async def request_update(self, initial_only:bool=False):
        
        
        if initial_only and self.characters:
            self.emit()
            return
        
        self.emit(status="requested")
        
        try:
            world_state = await self.agent.request_world_state()
        except Exception as e:
            self.emit()
            raise e
        
        self.characters = {}
        self.items = {}
        
        for character in world_state.get("characters", []):
            self.characters[character["name"]] = CharacterState(**character)
            log.debug("world_state", character=character)
            
        for item in world_state.get("items", []):
            self.items[item["name"]] = ObjectState(**item)
            log.debug("world_state", item=item)
        
        self.emit()
        
    
    async def request_update_inline(self):
        
        self.emit(status="requested")
        
        world_state = await self.agent.request_world_state_inline()
        
        self.emit()
        
    
    def render(self):
        
        """
        Renders the world state as a string.
        """
        
        return Prompt.get(
            "world_state.render",
            vars={
                "characters": self.characters,
                "items": self.items,
                "location": self.location,
            }
        )
        
    
@automated_action.register("world_state", frequency=5, call_initially=False)
class WorldStateAction(automated_action.AutomatedAction):
    async def action(self):
        await self.scene.world_state.request_update()
        return True