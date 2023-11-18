import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register

from talemate.emit import wait_for_input


@register
class CmdRename(TalemateCommand):
    """
    Command class for the 'rename' command
    """

    name = "rename"
    description = "Rename the main character"
    aliases = []

    async def run(self):
        # collect list of characters in the scene

        if self.args:
            character_name = self.args[0]
        else:
            character_names = self.scene.character_names
            character_name = await wait_for_input("Which character do you want to rename?", data={
                "input_type": "select",
                "choices": character_names,  
            }) 
        
        character = self.scene.get_character(character_name)
        
        if not character:
            self.system_message(f"Character {character_name} not found")
            return True
        
        name = await wait_for_input("Enter new name: ")

        character.rename(name)
        await asyncio.sleep(0)
        
        return True
