from pydantic import BaseModel
from talemate.emit import emit
import structlog
from typing import Union

import talemate.instance as instance
from talemate.prompts import Prompt
import talemate.automated_action as automated_action

log = structlog.get_logger("talemate")

class CharacterState(BaseModel):
    snapshot: Union[str, None] = None
    emotion: Union[str, None] = None
    
class ObjectState(BaseModel):
    snapshot: Union[str, None] = None

class WorldState(BaseModel):
    
    # characters in the scene by name
    characters: dict[str, CharacterState] = {}
    
    # objects in the scene by name
    items: dict[str, ObjectState] = {}
    
    # location description
    location: Union[str, None] = None
    
    @property
    def agent(self):
        return instance.get_agent("world_state")
    
    @property
    def pretty_json(self):
        return self.model_dump_json(indent=2)
    
    @property
    def as_list(self):
        return self.render().as_list
    
    def reset(self):
        self.characters = {}
        self.items = {}
        self.location = None    
    
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
        
        previous_characters = self.characters
        previous_items = self.items
        scene = self.agent.scene
        character_names = scene.character_names
        self.characters = {}
        self.items = {}
        
        for character_name, character in world_state.get("characters", {}).items():
            
            # character name may not always come back exactly as we have
            # it defined in the scene. We assign the correct name by checking occurences
            # of both names in each other.
            
            if character_name not in character_names:
                for _character_name in character_names:
                    if _character_name.lower() in character_name.lower() or character_name.lower() in _character_name.lower():
                        log.debug("world_state adjusting character name", from_name=character_name, to_name=_character_name)
                        character_name = _character_name
                        break
            
            if not character:
                continue
            
            # if emotion is not set, see if a previous state exists
            # and use that emotion
            
            if "emotion" not in character:
                log.debug("emotion not set", character_name=character_name, character=character, characters=previous_characters)
                if character_name in previous_characters:
                    character["emotion"] = previous_characters[character_name].emotion
            
            self.characters[character_name] = CharacterState(**character)
            log.debug("world_state", character=character)
            
        for item_name, item in world_state.get("items", {}).items():
            if not item:
                continue
            self.items[item_name] = ObjectState(**item)
            log.debug("world_state", item=item)
        
        
        await self.persist()
        self.emit()
     
    async def persist(self):
        
        memory = instance.get_agent("memory")
        world_state = instance.get_agent("world_state")
        
        # first we check if any of the characters were refered
        # to with an alias
        
        states = []
        scene = self.agent.scene

        for character_name in self.characters.keys():
            states.append(
                {
                    "text": f"{character_name}: {self.characters[character_name].snapshot}",
                    "id": f"{character_name}.world_state.snapshot",
                    "meta": {
                        "typ": "world_state",
                        "character": character_name,
                        "ts": scene.ts,
                    }
                }
            )
        
        for item_name in self.items.keys():
            states.append(
                {
                    "text": f"{item_name}: {self.items[item_name].snapshot}",
                    "id": f"{item_name}.world_state.snapshot",
                    "meta": {
                        "typ": "world_state",
                        "item": item_name,
                        "ts": scene.ts,
                    }
                }
            )
        
        log.debug("world_state.persist", states=states)
        
        if not states:
            return

        await memory.add_many(states)            
               
    
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