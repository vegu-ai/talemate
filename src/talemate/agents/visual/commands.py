from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register

from talemate.instance import get_agent

__all__ = [
    "CmdVisualizeTestGenerate",
]

@register
class CmdVisualizeTestGenerate(TalemateCommand):
    """
    Generates a visual test
    """

    name = "visual_test_generate"
    description = "Will generate a visual test"
    aliases = ["vis_test", "vtg"]

    label = "Visualize test"

    async def run(self):
        visual = get_agent("visual")
        prompt = self.args[0]
        await visual.generate(prompt)
        return True
    
@register
class CmdVisualizeEnvironment(TalemateCommand):
    """
    Shows the environment
    """

    name = "visual_environment"
    description = "Will show the environment"
    aliases = ["vis_env"]

    label = "Visualize environment"

    async def run(self):
        visual = get_agent("visual")
        prompt = await visual.generate_environment_prompt()
        await visual.generate(prompt, format="landscape")
        return True
    
@register
class CmdVisualizeCharacter(TalemateCommand):
    """
    Shows a character
    """

    name = "visual_character"
    description = "Will show a character"
    aliases = ["vis_char"]

    label = "Visualize character"

    async def run(self):
        visual = get_agent("visual")
        character_name = self.args[0]
        instructions = self.args[1] if len(self.args) > 1 else None
        prompt = await visual.generate_character_prompt(character_name, instructions=instructions)
        await visual.generate(prompt, format="portrait")
        return True