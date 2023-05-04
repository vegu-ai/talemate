import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.util import colored_text


@register
class CmdRm(TalemateCommand):
    """
    Command class for the 'rm' command
    """

    name = "rm"
    description = "Removes most recent entry from history"
    aliases = []

    async def run(self):
        self.scene.history.pop(-1)
        self.system_message("Removed most recent entry from history")
        await asyncio.sleep(0)
