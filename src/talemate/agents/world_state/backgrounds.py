from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
)


class BackgroundMixin:
    """
    World-state manager agent mixin that keeps the scene background fitting
    the story during play.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["backgrounds"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Scene Backgrounds",
            icon="mdi-image-filter-hdr",
            description="Scene background features for world state management.",
            config={
                "decision_model": AgentActionConfig(
                    type="bool",
                    label="Use Decision Model",
                    description="Keep the background or pick another existing one with the decision model when it is sure, without the usual request. A wrong answer can miss a change of setting.",
                    value=True,
                ),
                "selection_frequency": AgentActionConfig(
                    type="number",
                    label="Selection Frequency",
                    title="Background Selection",
                    description="Setting a frequency of 1 or higher will cause the world state agent to check whether the scene background still fits the current moment, and pick a better one if not. A frequency of 1 means this is evaluated with every new character or narrator message. 0 = Never, 10 = Every 10th message.",
                    value=0,
                    min=0,
                    max=10,
                    step=1,
                    note=AgentActionNote(
                        text="Off by default. Each check sends a model request. Backgrounds are picked from the scene's Scene Background images (World Editor → Scene → Visuals).",
                    ),
                ),
                "generate_new": AgentActionConfig(
                    type="bool",
                    label="Generate New Backgrounds",
                    description="Generate a new scene background with the Visualizer when no existing one fits. Each new background is an extra model and image request. Requires a Visualizer image backend.",
                    value=False,
                ),
            },
        )
