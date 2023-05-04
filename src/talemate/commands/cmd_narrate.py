import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.util import colored_text, wrap_text
from talemate.scene_message import NarratorMessage


@register
class CmdNarrate(TalemateCommand):
    """
    Command class for the 'narrate' command
    """

    name = "narrate"
    description = "Calls a narrator to narrate the scene"
    aliases = ["n"]

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        narration = await narrator.agent.narrate_scene()
        message = NarratorMessage(narration, source="narrate_scene")
        
        self.narrator_message(message)
        self.scene.push_history(message)
        await asyncio.sleep(0)
