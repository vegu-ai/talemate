from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
)
from talemate.decisions.gate import decision_gate


class AvatarMixin:
    """
    World-state manager agent mixin that handles avatar selection
    for new scene message generation.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["avatars"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Character Portraits",
            icon="mdi-image-auto-adjust",
            description="Portrait-related features for world state management.",
            config={
                "decision_model": AgentActionConfig(
                    type="bool",
                    label="Use Decision Model",
                    description="Keep the portrait or pick another existing one with the decision model when it is sure, without the usual request. A wrong answer can miss a portrait change.",
                    value=True,
                ),
                "selection_frequency": AgentActionConfig(
                    type="number",
                    label="Selection Frequency",
                    title="Portrait Selection",
                    description="Setting a frequency of 1 or higher will cause the world state agent to determine the most appropriate portrait for the character based on the current moment in the scene. A frequency of 1 means this is evaluated with every new message. 0 = Never, 10 = Every 10th message.",
                    value=1,
                    min=0,
                    max=10,
                    step=1,
                    note=AgentActionNote(
                        text="A character needs at least 2 portraits in their visual configuration for this feature to activate. Portraits can be set in the World Editor → Character → Visual → Portrait view.",
                    ),
                ),
                "generate_new": AgentActionConfig(
                    type="bool",
                    label="Generate New Portraits",
                    description="Request the director to generate new portraits when no suitable portrait is found. Requires the director's character management -> generate visuals feature to be enabled.",
                    value=False,
                ),
            },
        )

    # config property helpers

    @property
    def avatars_enabled(self) -> bool:
        return self.resolve_enabled("avatars")

    @property
    def avatar_selection_frequency(self) -> int:
        return self.resolve_config("avatars", "selection_frequency")

    async def determine_avatar_with_decisions(
        self, character, content, assets, fallback
    ):
        scene = self.scene
        current = character.current_avatar
        portraits = {
            asset.id: {"name": asset.meta.name, "tags": asset.meta.tags}
            for asset in assets
        }
        result = await decision_gate(
            "world_state.decision-avatar",
            enabled=self.resolve_config("avatars", "decision_model"),
            candidates={"avatar": list(portraits)},
            variables=lambda: {
                "state": {
                    "character": character.name,
                    "content": content,
                    "current_avatar": current if current in portraits else None,
                    "portraits": portraits,
                },
            },
            fallback=fallback,
            is_current=lambda: self.scene is scene
            and character.current_avatar == current,
        )
        return result["avatar"]
