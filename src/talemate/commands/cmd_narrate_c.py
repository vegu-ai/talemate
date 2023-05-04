from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input
from talemate.util import colored_text, wrap_text
from talemate.scene_message import NarratorMessage


@register
class CmdNarrateC(TalemateCommand):
    """
    Command class for the 'narrate_c' command
    """

    name = "narrate_c"
    description = "Calls a narrator to narrate a character"
    aliases = ["nc"]
    label = "Look at"

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        if self.args:
            name = self.args[0]
        else:
            name = await wait_for_input("Enter character name: ")

        character = self.scene.get_character(name, partial=True)

        if not character:
            self.system_message(f"Character not found: {name}")
            return True

        narration = await narrator.agent.narrate_character(character)
        message = NarratorMessage(narration, source=f"narrate_character:{name}")

        self.narrator_message(message)
        self.scene.push_history(message)