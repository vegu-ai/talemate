import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.util import colored_text, wrap_text
from talemate.scene_message import NarratorMessage


@register
class CmdWorldState(TalemateCommand):
    """
    Command class for the 'world_state' command
    """

    name = "world_state"
    description = "Request an update to the world state"
    aliases = ["ws"]

    async def run(self):
        
        inline = self.args[0] == "inline" if self.args else False
        
        if inline:
            await self.scene.world_state.request_update_inline()
            return True
        await self.scene.world_state.request_update()
    