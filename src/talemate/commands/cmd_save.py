from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdSave(TalemateCommand):
    """
    Command class for the 'save' command
    """

    name = "save"
    description = "Save the scene"
    aliases = ["s"]
    sets_scene_unsaved = False

    async def run(self):
        await self.scene.save()
