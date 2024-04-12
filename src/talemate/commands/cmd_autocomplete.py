from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import emit

__all__ = [
    "CmdAutocompleteDialogue",
]

@register
class CmdAutocompleteDialogue(TalemateCommand):
    """
    Command class for the 'autocomplete_dialogue' command
    """

    name = "autocomplete_dialogue"
    description = "Generate dialogue for an AI selected actor"
    aliases = ["acdlg"]

    async def run(self):
        
        input = self.args[0]
        creator = self.scene.get_helper("creator").agent
        character = self.scene.get_player_character()
        
        await creator.autocomplete_dialogue(input, character, emit_signal=True)
        
        
