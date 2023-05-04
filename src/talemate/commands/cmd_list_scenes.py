import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import Manager, register
from talemate.files import list_scenes_directory


@register
class CmdListScenes(TalemateCommand):
    name = "list_scenes"
    description = "Lists all scenes"
    aliases = []

    async def run(self):
        scenes = list_scenes_directory()

        for scene in scenes:
            self.scene.system_message(scene)

        await asyncio.sleep(0)
