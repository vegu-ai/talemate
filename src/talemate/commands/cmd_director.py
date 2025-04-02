from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import emit, wait_for_input
from talemate.scene_message import DirectorMessage

__all__ = [
    "CmdDirectorDirect",
    "CmdDirectorDirectWithOverride",
    "CmdDirectorGenerateChoices",
]

@register
class CmdDirectorDirect(TalemateCommand):
    """
    Command class for the 'director' command
    """

    name = "director"
    description = "Calls a director to give directionts to a character"
    aliases = ["direct"]

    async def run(self, ask_for_input=True):
        director = self.scene.get_helper("director")

        if not director:
            self.system_message("No director found")
            return True

        npc_count = self.scene.num_npc_characters()

        if npc_count == 1:
            character = list(self.scene.get_npc_characters())[0]
        elif npc_count > 1:
            name = await wait_for_input("Enter character name: ")
            character = self.scene.get_character(name)
        else:
            self.system_message("No characters to direct")
            return True

        if not character:
            self.system_message(f"Character not found: {name}")
            return True

        goal = await wait_for_input(
            f"Enter a new goal for the director to direct {character.name}"
        )

        if not goal.strip():
            self.system_message("No goal specified")
            return True

        director.agent.actions["direct"].config["prompt"].value = goal

        await director.agent.direct_character(character, goal)


@register
class CmdDirectorDirectWithOverride(CmdDirectorDirect):
    """
    Command class for the 'director' command
    """

    name = "director_with_goal"
    description = (
        "Calls a director to give directionts to a character (with goal specified)"
    )
    aliases = ["direct_g"]

    async def run(self):
        await super().run(ask_for_input=True)

@register
class CmdDirectorGenerateChoices(TalemateCommand):
    """
    Command class for the 'director' command
    """

    name = "director_generate_choices"
    description = "Calls a director to generate choices for a character"
    aliases = ["generate_choices"]

    async def run(self, ask_for_input=True):
        director = self.scene.get_helper("director")

        if not director:
            self.system_message("No director found")
            return True

        choices = await director.agent.generate_choices()