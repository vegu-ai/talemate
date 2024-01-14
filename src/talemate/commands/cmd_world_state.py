import asyncio
import random

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.util import colored_text, wrap_text
from talemate.scene_message import NarratorMessage
from talemate.emit import wait_for_input, emit
from talemate.instance import get_agent
import talemate.instance as instance

__all__ = [
    "CmdWorldState",
    "CmdPersistCharacter",
    "CmdAddReinforcement",
    "CmdRemoveReinforcement",
    "CmdUpdateReinforcements",
    "CmdCheckPinConditions",
    "CmdApplyWorldStateTemplate",
    "CmdSummarizeAndPin",
]

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
        
@register
class CmdAddReinforcement(TalemateCommand):
    
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.
    
    Once persisted this character can then participate in the scene.
    """
    
    name = "add_reinforcement"
    description = "Add a reinforcement to the world state"
    aliases = ["ws_ar"]
    
    async def run(self):
        
        scene = self.scene
        
        world_state = scene.world_state
        
        if not len(self.args):
            question = await wait_for_input("Ask reinforcement question")
        else:
            question = self.args[0]
        
        await world_state.add_reinforcement(question)
        
        
@register
class CmdRemoveReinforcement(TalemateCommand):
    
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.
    
    Once persisted this character can then participate in the scene.
    """
    
    name = "remove_reinforcement"
    description = "Remove a reinforcement from the world state"
    aliases = ["ws_rr"]
    
    async def run(self):
        
        scene = self.scene
        
        world_state = scene.world_state
        
        if not len(self.args):
            question = await wait_for_input("Ask reinforcement question")
        else:
            question = self.args[0]
            
        idx, reinforcement = await world_state.find_reinforcement(question)
        
        if idx is None:
            raise ValueError(f"Reinforcement {question} not found.")
        
        await world_state.remove_reinforcement(idx)
        
@register
class CmdUpdateReinforcements(TalemateCommand):
    
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.
    
    Once persisted this character can then participate in the scene.
    """
    
    name = "update_reinforcements"
    description = "Update the reinforcements in the world state"
    aliases = ["ws_ur"]
    
    async def run(self):
        
        scene = self.scene
        
        world_state = get_agent("world_state")
        
        await world_state.update_reinforcements(force=True)
        
@register
class CmdCheckPinConditions(TalemateCommand):
    
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.
    
    Once persisted this character can then participate in the scene.
    """
    
    name = "check_pin_conditions"
    description = "Check the pin conditions in the world state"
    aliases = ["ws_cpc"]
    
    async def run(self):
        world_state = get_agent("world_state")
        await world_state.check_pin_conditions()
        
@register
class CmdApplyWorldStateTemplate(TalemateCommand):
    
    """
    Will apply a world state template setting up
    automatic state tracking.
    """
    
    name = "apply_world_state_template"
    description = "Apply a world state template, creating an auto state reinforcement."
    aliases = ["ws_awst"]
    label = "Add state"
    
    async def run(self):
        
        scene = self.scene
        
        if not len(self.args):
            raise ValueError("No template name provided.")
        
        template_name = self.args[0]
        template_type = self.args[1] if len(self.args) > 1 else None
        
        character_name = self.args[2] if len(self.args) > 2 else None
        
        templates = await self.scene.world_state_manager.get_templates()
        
        try:
            template = getattr(templates,template_type)[template_name]
        except KeyError:
            raise ValueError(f"Template {template_name} not found.")
        
        reinforcement = await scene.world_state_manager.apply_template_state_reinforcement(
            template, character_name=character_name, run_immediately=True
        )
        
        if reinforcement is None:
            emit("status", message="State already tracked.", status="info")
        else:
            emit("status", message="Auto state added.", status="success")

@register
class CmdSummarizeAndPin(TalemateCommand):
    
    """
    Will take a message index and then walk back N messages
    summarizing the scene and pinning it to the context.
    """
    
    name = "summarize_and_pin"
    label = "Summarize and pin"
    description = "Summarize a snapshot of the scene and pin it to the world state"
    aliases = ["ws_sap"]
    
    async def run(self):
        
        scene = self.scene
        
        world_state = get_agent("world_state")
        
        if not self.scene.history:
            raise ValueError("No history to summarize.")
        
        message_id = int(self.args[0]) if len(self.args) else scene.history[-1].id
        num_messages = int(self.args[1]) if len(self.args) > 1 else 3
        
        await world_state.summarize_and_pin(message_id, num_messages=num_messages)