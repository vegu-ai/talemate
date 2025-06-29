from talemate.commands.base import TalemateCommand
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

        self.scene.reset()

        raise ResetScene()
