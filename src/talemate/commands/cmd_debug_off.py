import asyncio
import logging

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdDebugOff(TalemateCommand):
    """
    Command class for the 'debug_off' command
    """

    name = "debug_off"
    description = "Turn off debug mode"
    aliases = []

    async def run(self):
        logging.getLogger().setLevel(logging.INFO)
        await asyncio.sleep(0)
