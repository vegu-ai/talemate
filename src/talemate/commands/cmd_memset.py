from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdMemset(TalemateCommand):
    """
    Command class for the 'memset' command
    """

    name = "dbg_memset"
    description = "Sets the memory of a character"
    aliases = []

    def run(self):
        memory = input("memory:")
        self.scene.get_helper("memory").agent.add(memory)
