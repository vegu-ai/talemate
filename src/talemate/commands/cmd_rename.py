import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register

from talemate.emit import wait_for_input


@register
class CmdRename(TalemateCommand):
    """
    Command class for the 'rename' command
    """

    name = "rename"
    description = "Rename the main character"
    aliases = []

    async def run(self):
        name = await wait_for_input("Enter new name: ")

        self.scene.main_character.character.rename(name)
        await asyncio.sleep(0)
