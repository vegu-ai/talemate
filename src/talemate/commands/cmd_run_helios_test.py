from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import emit, wait_for_input, wait_for_input_yesno
from talemate.exceptions import ResetScene


@register
class CmdHeliosTest(TalemateCommand):
    """
    Runs the helios test
    """

    name = "helios_test"
    description = "Runs the helios test"
    aliases = [""]

    analyst_script = [
        "Good morning helios, how are you today? Are you ready to run some tests?",
    ]

    async def run(self):
        if self.scene.name != "Helios Test Arena":
            emit("system", "You are not in the Helios Test Arena")

        self.scene.reset()

        self.scene

        player = self.scene.get_player_character()
        player.actor.muted = 10

        analyst = self.scene.get_character("The analyst")
        actor = analyst.actor

        actor.script = self.analyst_script

        raise ResetScene()
