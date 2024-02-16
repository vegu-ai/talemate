from talemate.agents.visual.context import VIS_TYPES, VisualContext
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
        with VisualContext(vis_type=VIS_TYPES.UNSPECIFIED):
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
        await visual.generate_environment_background(
            instructions=self.args[0] if len(self.args) > 0 else None
        )
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
        await visual.generate_character_portrait(character_name, instructions)
        return True
