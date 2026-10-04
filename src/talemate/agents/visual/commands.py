from talemate.agents.visual.schema import VIS_TYPE
from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.instance import get_agent
from .schema import GenerationRequest, GEN_TYPE

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
        gen_type = GEN_TYPE.TEXT_TO_IMAGE
        if len(self.args) > 1:
            gen_type = GEN_TYPE.IMAGE_EDIT
            reference_assets = self.args[1].split(",")
        else:
            reference_assets = []
        await visual.generate(
            GenerationRequest(
                prompt=prompt,
                vis_type=VIS_TYPE.UNSPECIFIED,
                gen_type=gen_type,
                reference_assets=reference_assets,
            )
        )
        return True
