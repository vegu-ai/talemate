from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input, emit
from talemate.util import colored_text, wrap_text
from talemate.scene_message import DirectorMessage


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
        
        if ask_for_input:
            goal = await wait_for_input(f"Enter a new goal for the director to direct {character.name} towards (leave empty for auto-direct): ")
        else:
            goal = None
        direction = await director.agent.direct(character, goal_override=goal)
        
        if direction is None:
            self.system_message("Director was unable to direct character at this point in the story.")
            return True
        
        if direction is True:
            return True
        
        message = DirectorMessage(direction, source=character.name)
        emit("director", message, character=character)
        
        # remove previous director message, starting from the end of self.history
        for i in range(len(self.scene.history) - 1, -1, -1):
            if isinstance(self.scene.history[i], DirectorMessage):
                self.scene.history.pop(i)
                break
        
        self.scene.push_history(message)
        
@register
class CmdDirectorDirectWithOverride(CmdDirectorDirect):
    """
    Command class for the 'director' command
    """

    name = "director_with_goal"
    description = "Calls a director to give directionts to a character (with goal specified)"
    aliases = ["direct_g"]

    async def run(self):
        await super().run(ask_for_input=True)
