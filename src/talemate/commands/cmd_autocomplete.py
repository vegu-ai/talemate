from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import emit

from talemate.agents.creator.assistant import ContentGenerationContext

__all__ = [
    "CmdAutocompleteDialogue",
    "CmdAutocomplete"
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
        if len(self.args) > 1:
            character_name = self.args[1]
            character = self.scene.get_character(character_name)
        else:
            character = self.scene.get_player_character()
        
        creator = self.scene.get_helper("creator").agent

        await creator.autocomplete_dialogue(input, character, emit_signal=True)


@register
class CmdAutocomplete(TalemateCommand):
    """
    Command class for the 'autocomplete' command
    """

    name = "autocomplete"
    description = "Generate information for an AI selected actor"
    aliases = ["ac"]
    argument_cls = ContentGenerationContext

    async def run(self):
        
        try:
            creator = self.scene.get_helper("creator").agent
            context_type, context_name = self.args.computed_context
            
            if context_type == "dialogue":
                
                if not self.args.character:
                    character = self.scene.get_player_character()
                else:
                    character = self.scene.get_character(self.args.character)
                
                self.scene.log.info("Running autocomplete dialogue", partial=self.args.partial, character=character)
                await creator.autocomplete_dialogue(self.args.partial, character, emit_signal=True)
                return
            
            # force length to 35
            self.args.length = 35
            self.scene.log.info("Running autocomplete context", args=self.args)
            completion = await creator.contextual_generate(self.args)
            self.scene.log.info("Autocomplete context complete", completion=completion)
            completion = completion.replace(f"{context_name}: {self.args.partial}","").lstrip(".").strip()
            
            emit("autocomplete_suggestion", completion)
        except Exception as e:
            self.scene.log.error("Error running autocomplete", error=str(e))
            emit("autocomplete_suggestion", "")