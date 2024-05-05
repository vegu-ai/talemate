import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import emit


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

        self.scene.ts = (
            self.scene.archived_history[-1].ts
            if self.scene.archived_history
            else "PT0S"
        )

        entries = 0
        total_entries = summarizer.agent.estimated_entry_count
        while True:
            emit(
                "status",
                message=f"Rebuilding historical archive... {entries}/{total_entries}",
                status="busy",
            )
            more = await summarizer.agent.build_archive(self.scene)
            entries += 1
            if not more:
                break

        self.scene.sync_time()
        await self.scene.commit_to_memory()
        emit("status", message="Historical archive rebuilt", status="success")
