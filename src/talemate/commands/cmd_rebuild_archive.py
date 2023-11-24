import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdRebuildArchive(TalemateCommand):
    """
    Command class for the 'rebuild_archive' command
    """

    name = "rebuild_archive"
    description = "Rebuilds the archive of the scene"
    aliases = ["rebuild"]

    async def run(self):
        summarizer = self.scene.get_helper("summarizer")

        if not summarizer:
            self.system_message("No summarizer found")
            return True
        
        # clear out archived history, but keep pre-established history
        self.scene.archived_history = [
            ah for ah in self.scene.archived_history if ah.get("end") is None
        ]

        while True:
            more = await summarizer.agent.build_archive(self.scene)

            if not more:
                break

        self.scene.sync_time()
        await self.scene.commit_to_memory()
