from typing import TYPE_CHECKING
import pydantic

from talemate.instance import get_agent
from talemate.world_state import Reinforcement

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

class CharacterSelect(pydantic.BaseModel):
    name: str
    active: bool = True
    is_player: bool = False
    
class LoreItem(pydantic.BaseModel):
    text: str
    meta: dict
    
class CharacterDetails(pydantic.BaseModel):
    name: str
    active: bool = True
    is_player: bool = False
    description: str = ""
    base_attributes: dict[str,str] = {}
    details: dict[str,str] = {}
    reinforcements: dict[str, Reinforcement] = {}
    lore: list[LoreItem] = []
    
    
class HistoryEntry(pydantic.BaseModel):
    text: str
    start: int = None
    end: int = None
    ts: str = None    
    
class CharacterList(pydantic.BaseModel):
    characters: dict[str, CharacterSelect] = {}
    
class History(pydantic.BaseModel):
    history: list[HistoryEntry] = []
    
    
    
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
    
    async def update_character_attribute(self, character_name:str, attribute:str, value:str):
        character = self.scene.get_character(character_name)
        await character.set_base_attribute(attribute, value)
        
    async def update_character_detail(self, character_name:str, detail:str, value:str):
        character = self.scene.get_character(character_name)
        await character.set_detail(detail, value)
        
    async def update_character_description(self, character_name:str, description:str):
        character = self.scene.get_character(character_name)
        await character.set_description(description)
        
    async def add_detail_reinforcement(self, character_name:str, question:str, instructions:str=None, interval:int=10, answer:str="",
                                       run_immediately:bool=False):
        character = self.scene.get_character(character_name)
        world_state_agent = get_agent("world_state")
        await self.world_state.add_reinforcement(question, character_name, instructions, interval, answer)
        
        if run_immediately:
            await world_state_agent.update_reinforcement(question, character_name)
            
    async def run_detail_reinforcement(self, character_name:str, question:str):
        world_state_agent = get_agent("world_state")
        await world_state_agent.update_reinforcement(question, character_name)
        
    async def delete_detail_reinforcement(self, character_name:str, question:str):
        
        idx, reinforcement = await self.world_state.find_reinforcement(question, character_name)
        if idx is not None:
            await self.world_state.remove_reinforcement(idx)