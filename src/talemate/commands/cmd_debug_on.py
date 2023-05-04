import asyncio
import logging

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdDebugOn(TalemateCommand):
    """
    Command class for the 'debug_on' command
    """

    name = "debug_on"
    description = "Turn on debug mode"
    aliases = []

    async def run(self):
        logging.getLogger().setLevel(logging.DEBUG)
        await asyncio.sleep(0)
