import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdExit(TalemateCommand):
    """
    Command class for the 'exit' command
    """

    name = "exit"
    description = "Exit the scene"
    aliases = []

    async def run(self):
        await asyncio.sleep(0)
        raise self.scene.ExitScene()
