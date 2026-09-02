from talemate.commands.base import TalemateCommand
from talemate.instance import get_agent
from talemate.commands.manager import register
from talemate.emit import wait_for_input_yesno
from talemate.exceptions import ResetScene


@register
class CmdReset(TalemateCommand):
    """
    Command class for the 'reset' command
    """

    name = "reset"
    description = "Reset the scene"
    aliases = [""]

    async def run(self):
        reset = await wait_for_input_yesno("Reset the scene?")

        if reset.lower() not in ["yes", "y"]:
            self.system_message("Reset cancelled")
            return True

        dropped_facts = self.scene.reset()
        if dropped_facts:
            await get_agent("memory").delete({"ids": sorted(dropped_facts)})

        raise ResetScene()
