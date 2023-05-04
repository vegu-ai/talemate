import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input


@register
class CmdInject(TalemateCommand):
    """
    Command class for the 'inject' command
    """

    name = "inject"
    description = "Injects a message into the history"
    aliases = []

    async def run(self):
        for actor in self.scene.actors:
            if isinstance(actor, Player):
                continue

            character = actor.character
            name = character.name

            message = await wait_for_input(f"{name} [Inject]:")

            # inject message into history
            self.scene.push_history(f"{name}: {message}")
            break
