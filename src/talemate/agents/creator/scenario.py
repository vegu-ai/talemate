from talemate.agents.base import set_processing
from talemate.prompts import Prompt


class ScenarioCreatorMixin:
    """
    Adds scenario creation functionality to the creator agent
    """

    @set_processing
    async def determine_scenario_description(self, text: str):
        response, extracted = await Prompt.request(
            "creator.determine-scenario-description",
            self.client,
            "analyze_long",
            vars={
                "text": text,
            },
        )
        return extracted["response"].strip()

    @set_processing
    async def determine_content_context_for_description(
        self,
        description: str,
    ):
        response, extracted = await Prompt.request(
            "creator.determine-content-context",
            self.client,
            "create_short",
            vars={
                "description": description,
            },
        )
        return extracted["response"].lstrip().split("\n")[0].strip('"').strip()
