import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.util import colored_text, wrap_text
from talemate.scene_message import NarratorMessage


@register
class CmdNarrateProgress(TalemateCommand):
    """
    Command class for the 'narrate_progress' command
    """

    name = "narrate_progress"
    description = "Calls a narrator to narrate the scene"
    aliases = ["np"]

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        narration = await narrator.agent.progress_story()

        message = NarratorMessage(narration, source="progress_story")
        
        self.narrator_message(message)
        self.scene.push_history(message)
        await asyncio.sleep(0)
