import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdInfo(TalemateCommand):
    """
    Command class for the 'info' command
    """

    name = "info"
    description = "Prints description of the scene and each character"
    aliases = ["i"]

    async def run(self):
        self.narrator_message(self.scene.description)

        for actor in self.scene.actors:
            self.narrator_message(actor.character.name)
            self.narrator_message(actor.character.description)

        await asyncio.sleep(0)
