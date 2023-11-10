import asyncio
import random

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.util import colored_text, wrap_text
from talemate.scene_message import NarratorMessage
from talemate.emit import wait_for_input
import talemate.instance as instance


@register
class CmdWorldState(TalemateCommand):
    """
    Command class for the 'world_state' command
    """

    name = "world_state"
    description = "Request an update to the world state"
    aliases = ["ws"]

    async def run(self):
        
        inline = self.args[0] == "inline" if self.args else False
        reset = self.args[0] == "reset" if self.args else False
        
        if inline:
            await self.scene.world_state.request_update_inline()
            return True
        
        if reset:
            self.scene.world_state.reset()
        
        await self.scene.world_state.request_update()

@register
class CmdPersistCharacter(TalemateCommand):
    
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.
    
    Once persisted this character can then participate in the scene.
    """
    
    name = "persist_character"
    description = "Persist a character by name"
    aliases = ["pc"]
    
    async def run(self):
        from talemate.tale_mate import Character, Actor
        
        scene = self.scene
        world_state = instance.get_agent("world_state")
        creator = instance.get_agent("creator")
        
        if not len(self.args):
            characters = await world_state.identify_characters()
            available_names = [character["name"] for character in characters.get("characters") if not scene.get_character(character["name"])]
            
            if not len(available_names):
                raise ValueError("No characters available to persist.")
            
            name = await wait_for_input("Which character would you like to persist?", data={
                "input_type": "select",
                "choices": available_names,
                "multi_select": False,  
            })
        else:
            name = self.args[0]
            
        scene.log.debug("persist_character", name=name)
        
        character = Character(name=name)
        character.color = random.choice(['#F08080', '#FFD700', '#90EE90', '#ADD8E6', '#DDA0DD', '#FFB6C1', '#FAFAD2', '#D3D3D3', '#B0E0E6', '#FFDEAD'])
        
        attributes = await world_state.extract_character_sheet(name=name)
        scene.log.debug("persist_character", attributes=attributes)
        
        character.base_attributes = attributes
        
        description = await creator.determine_character_description(character)
        
        character.description = description
        
        scene.log.debug("persist_character", description=description)
        
        actor = Actor(character=character, agent=instance.get_agent("conversation"))
        
        await scene.add_actor(actor)
        
        self.emit("system", f"Added character {name} to the scene.")
        
        scene.emit_status()