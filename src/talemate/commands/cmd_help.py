import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import Manager, register
from talemate.util import colored_text, wrap_text


@register
class CmdHelp(TalemateCommand):
    """
    Command class for the 'help' command
    """

    name = "help"
    description = "Lists all commands and their descriptions"
    aliases = ["h"]

    async def run(self):
        for command_cls in Manager.command_classes:
            aliases = ", ".join(command_cls.aliases)
            self.scene.system_message(
                command_cls.name + f" ({aliases}): " + command_cls.description
            )
        await asyncio.sleep(0)
