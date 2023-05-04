import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register


@register
class CmdSaveCharacters(TalemateCommand):
    """
    Command class for the 'save_characters' command
    """

    name = "save_characters"
    description = "Save all characters in the scene"
    aliases = ["sc"]

    async def run(self):
        for actor in self.scene.actors:
            if isinstance(actor, Player):
                continue

            character = actor.character

            # replace special characters in name to make it filename valid
            name = character.name.replace(" ", "-").lower()

            character.save(f"./tales/characters/talemate.{name}.json")
            self.system_message(f"Saved character: {name}")
            await asyncio.sleep(0)
