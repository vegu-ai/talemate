from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input, wait_for_input_yesno


@register
class CmdRemoveCharacter(TalemateCommand):
    """
    Removes a character from the scene
    """

    name = "remove_character"
    description = "Will remove a character from the scene"
    aliases = ["rmc"]

    async def run(self):
        
        characters = list([character.name for character in self.scene.get_characters()])
        
        if not characters:
            self.system_message("No characters found")
            return True
        
        if self.args:
            character_name = self.args[0]
        else:
            character_name = await wait_for_input("Which character do you want to remove?", data={
                "input_type": "select",
                "choices": characters,  
            })
        
        if not character_name:
            self.system_message("No character selected")
            return True
        

        character = self.scene.get_character(character_name)
        
        if not character:
            self.system_message(f"Character {character_name} not found")
            return True
    
        await self.scene.remove_actor(character.actor)
        
        self.system_message(f"Removed {character.name} from scene")
        
        self.scene.emit_status()
        
        return True
        
        