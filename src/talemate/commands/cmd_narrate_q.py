from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input
from talemate.scene_message import NarratorMessage


@register
class CmdNarrateQ(TalemateCommand):
    """
    Command class for the 'narrate_q' command
    """

    name = "narrate_q"
    description = "Will attempt to narrate using a specific question prompt"
    aliases = ["nq"]
    label = "Look at"

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        if self.args:
            query = self.args[0]
            at_the_end = (self.args[1].lower() == "true") if len(self.args) > 1 else False
        else:
            query = await wait_for_input("Enter query: ")
            at_the_end = False

        narration = await narrator.agent.narrate_query(query, at_the_end=at_the_end)
        message = NarratorMessage(narration, source=f"narrate_query:{query.replace(':', '-')}")
        
        self.narrator_message(message)
        self.scene.push_history(message)