from talemate.agents.base import set_processing
from talemate.prompts import Prompt

class ScenarioCreatorMixin:
    """
    Adds scenario creation functionality to the creator agent
    """

    @set_processing
    async def determine_scenario_description(self, text: str):
        description = await Prompt.request(
            f"creator.determine-scenario-description",
            self.client,
            "analyze_long",
            vars={
                "text": text,
            },
        )
        return description.strip()

    @set_processing
    async def determine_content_context_for_description(
        self,
        description: str,
    ):
        content_context = await Prompt.request(
            f"creator.determine-content-context",
            self.client,
            "create_short",
            vars={
                "description": description,
            },
        )
        return content_context.lstrip().split("\n")[0].strip('"').strip()
