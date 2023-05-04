from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.client.context import ClientContext

@register
class CmdRerun(TalemateCommand):
    """
    Command class for the 'rerun' command
    """

    name = "rerun"
    description = "Rerun the scene"
    aliases = ["rr"]

    async def run(self):
        nuke_repetition = self.args[0] if self.args else 0.0
        with ClientContext(nuke_repetition=nuke_repetition):
            await self.scene.rerun()