from typing import TYPE_CHECKING, Any
import pydantic
import structlog

from talemate.instance import get_agent
from talemate.world_state import Reinforcement, ManualContext, ContextPin, InsertionMode

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.server.world_state_manager")

class CharacterSelect(pydantic.BaseModel):
    name: str
    active: bool = True
    is_player: bool = False
    
class ContextDBEntry(pydantic.BaseModel):
    text: str
    meta: dict
    id: Any
    
class ContextDB(pydantic.BaseModel):
    entries: list[ContextDBEntry] = []
    
class CharacterDetails(pydantic.BaseModel):
    name: str
    active: bool = True
    is_player: bool = False
    description: str = ""
    base_attributes: dict[str,str] = {}
    details: dict[str,str] = {}
    reinforcements: dict[str, Reinforcement] = {}
    
    
class HistoryEntry(pydantic.BaseModel):
    text: str
    start: int = None
    end: int = None
    ts: str = None    
    
class CharacterList(pydantic.BaseModel):
    characters: dict[str, CharacterSelect] = {}
    
class History(pydantic.BaseModel):
    history: list[HistoryEntry] = []
    

class AnnotatedContextPin(pydantic.BaseModel):
    pin: ContextPin
    text: str
    
class ContextPins(pydantic.BaseModel):
    pins: dict[str, AnnotatedContextPin] = []
    
class WorldStateManager:
    
    @property
    def memory_agent(self):
        return get_agent("memory")
    
    def __init__(self, scene:'Scene'):
        self.scene = scene
        self.world_state = scene.world_state
    
    async def get_character_list(self) -> CharacterList:
        
        characters = CharacterList()
        
        for character in self.scene.get_characters():
            characters.characters[character.name] = CharacterSelect(name=character.name, active=True, is_player=character.is_player)
            
        return characters
    
    async def get_character_details(self, character_name:str) -> CharacterDetails:
        
        character = self.scene.get_character(character_name)
        
        details = CharacterDetails(name=character.name, active=True, description=character.description, is_player=character.is_player)
        
        for key, value in character.base_attributes.items():
            details.base_attributes[key] = value
            
        for key, value in character.details.items():
            details.details[key] = value
            
        details.reinforcements = self.world_state.reinforcements_for_character(character_name)
            
        return details
    
    async def get_context_db_entries(self, query:str, limit:int=20, **meta) -> ContextDB:
        
        if query.startswith("id:"):
            _entries = await self.memory_agent.get_document(id=query[3:])
            _entries = list(_entries.values())
        else:
            _entries = await self.memory_agent.multi_query([query], iterate=limit, max_tokens=9999999, **meta)
        
        entries = []
        for entry in _entries:
            entries.append(ContextDBEntry(text=entry.raw, meta=entry.meta, id=entry.id))
        
        context_db = ContextDB(entries=entries)
        
        return context_db
    
    async def get_pins(self, active:bool=None) -> ContextPins:
        
        pins = self.world_state.pins
        
        candidates = [pin for pin in pins.values() if pin.active == active or active is None]
        
        _ids = [pin.entry_id for pin in candidates]
        _pins = {}
        documents = await self.memory_agent.get_document(id=_ids)
        
        for pin in sorted(candidates, key=lambda x: x.active, reverse=True):
            
            if pin.entry_id not in documents:
                text = ""
            else:
                text = documents[pin.entry_id].raw
                
            annotated_pin = AnnotatedContextPin(pin=pin, text=text)
            
            _pins[pin.entry_id] = annotated_pin
            
        return ContextPins(pins=_pins)
    
    async def update_character_attribute(self, character_name:str, attribute:str, value:str):
        character = self.scene.get_character(character_name)
        await character.set_base_attribute(attribute, value)
        
    async def update_character_detail(self, character_name:str, detail:str, value:str):
        character = self.scene.get_character(character_name)
        await character.set_detail(detail, value)
        
    async def update_character_description(self, character_name:str, description:str):
        character = self.scene.get_character(character_name)
        await character.set_description(description)
        
    async def add_detail_reinforcement(
        self, 
        character_name:str, 
        question:str, 
        instructions:str=None, 
        interval:int=10,
        answer:str="",            
        insert:str="sequential", 
        run_immediately:bool=False
    ):
        character = self.scene.get_character(character_name)
        world_state_agent = get_agent("world_state")
        await self.world_state.add_reinforcement(question, character_name, instructions, interval, answer, insert)
        
        if run_immediately:
            await world_state_agent.update_reinforcement(question, character_name)
            
    async def run_detail_reinforcement(self, character_name:str, question:str):
        world_state_agent = get_agent("world_state")
        await world_state_agent.update_reinforcement(question, character_name)
        
    async def delete_detail_reinforcement(self, character_name:str, question:str):
        
        idx, reinforcement = await self.world_state.find_reinforcement(question, character_name)
        if idx is not None:
            await self.world_state.remove_reinforcement(idx)
            
            
    async def update_context_db_entry(self, entry_id:str, text:str, meta:dict):
        
        if meta.get("source") == "manual":
            self.world_state.manual_context[entry_id] = ManualContext(
                text=text,
                meta=meta,
                id=entry_id
            )
            
        
        await self.memory_agent.add_many([
            {
                "id": entry_id,
                "text": text,
                "meta": meta
            }
        ])
        
    async def delete_context_db_entry(self, entry_id:str):
        await self.memory_agent.delete({
            "ids": entry_id
        })
        
        if entry_id in self.world_state.manual_context:
            del self.world_state.manual_context[entry_id]
            
    async def set_pin(self, entry_id:str, condition:str=None, condition_state:bool=False, active:bool=False):
        
        if not condition:
            condition = None
            condition_state = False
        
        pin = ContextPin(
            entry_id=entry_id,
            condition=condition,
            condition_state=condition_state,
            active=active
        )
        
        self.world_state.pins[entry_id] = pin
        
    async def remove_pin(self, entry_id:str):
        if entry_id in self.world_state.pins:
            del self.world_state.pins[entry_id]