from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register

@register
class CmdMemget(TalemateCommand):
    """
    Command class for the 'memget' command
    """

    name = "dbg_memget"
    description = "Gets the memory of a character"
    aliases = []

    def run(self):
        query = input("query:")
        memories = self.scene.get_helper("memory").agent.get(query)

        for memory in memories:
            self.emit("narrator", memory["text"])