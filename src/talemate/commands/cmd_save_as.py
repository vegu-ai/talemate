import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdSaveAs(TalemateCommand):
    """
    Command class for the 'save_as' command
    """

    name = "save_as"
    description = "Save the scene with a new name"
    aliases = ["sa"]

    async def run(self):
        self.scene.filename = ""
        await self.scene.save()
