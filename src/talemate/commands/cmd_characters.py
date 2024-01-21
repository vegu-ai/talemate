import structlog

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input, emit
from talemate.character import deactivate_character, activate_character
from talemate.instance import get_agent

log = structlog.get_logger("talemate.cmd.characters")

__all__ = [
    "CmdDeactivateCharacter",
    "CmdActivateCharacter",
]

@register
class CmdDeactivateCharacter(TalemateCommand):
    """
    Deactivates a character
    """

    name = "character_deactivate"
    description = "Will deactivate a character"
    aliases = ["char_d"]
    
    label = "Character exit"

    async def run(self):
        
        narrator = get_agent("narrator")
        world_state = get_agent("world_state")
        characters = list([character.name for character in self.scene.get_npc_characters()])
        
        if not characters:
            emit("status", message="No characters found", status="error")
            return True
        
        if self.args:
            character_name = self.args[0]
        else:
            character_name = await wait_for_input("Which character do you want to deactivate?", data={
                "input_type": "select",
                "choices": characters,  
            })
        
        if not character_name:
            emit("status", message="No character selected", status="error")
            return True
        
        is_present = await world_state.is_character_present(character_name)
        is_leaving = await world_state.is_character_leaving(character_name)
        
        if is_present and not is_leaving:
            direction = await wait_for_input(f"How does {character_name} exit the scene? (leave blank for AI to decide)")
            message = await narrator.action_to_narration(
                "narrate_character_exit",
                self.scene.get_character(character_name),
                direction = direction,
            )
            self.narrator_message(message)
        
        await deactivate_character(self.scene, character_name)  
        
        emit("status", message=f"Deactivated {character_name}", status="success")

        self.scene.emit_status()
        self.scene.world_state.emit()        

        return True
    
@register
class CmdActivateCharacter(TalemateCommand):
    """
    Activates a character
    """

    name = "character_activate"
    description = "Will activate a character"
    aliases = ["char_a"]
    
    label = "Character enter"

    async def run(self):
        
        world_state = get_agent("world_state")
        narrator = get_agent("narrator")
        characters = list(self.scene.inactive_characters.keys())
        
        if not characters:
            emit("status", message="No characters found", status="error")
            return True
        
        if self.args:
            character_name = self.args[0]
            if character_name not in characters:
                emit("status", message="Character not found", status="error")
                return True
        else:
            character_name = await wait_for_input("Which character do you want to activate?", data={
                "input_type": "select",
                "choices": characters,  
            })
        
        if not character_name:
            emit("status", message="No character selected", status="error")
            return True
        
        is_present = await world_state.is_character_present(character_name)
        
        await activate_character(self.scene, character_name)
        
        if not is_present:
            direction = await wait_for_input(f"How does {character_name} enter the scene? (leave blank for AI to decide)")
            message = await narrator.action_to_narration(
                "narrate_character_entry",
                self.scene.get_character(character_name),
                direction = direction,
            )
            self.narrator_message(message)
        
        emit("status", message=f"Activated {character_name}", status="success")
        
        self.scene.emit_status()
        self.scene.world_state.emit()
        
        return True