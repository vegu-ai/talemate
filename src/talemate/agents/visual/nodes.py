import structlog
from typing import ClassVar
from talemate.game.engine.nodes.core import GraphState, PropertyField, UNRESOLVED
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode

log = structlog.get_logger("talemate.game.engine.nodes.agents.visual")


@register("agents/visual/Settings")
class VisualSettings(AgentSettingsNode):
    """
    Base node to render visual agent settings.
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Visual Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/visual/GenerateCharacterPortrait")
class GenerateCharacterPortrait(AgentNode):
    """
    Generates a portrait for a character
    """

    _agent_name: ClassVar[str] = "visual"

    class Fields:
        instructions = PropertyField(
            name="instructions",
            type="text",
            description="instructions for the portrait",
            default=UNRESOLVED,
        )

    def __init__(self, title="Generate Character Portrait", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("instructions", socket_type="str", optional=True)

        self.set_property("instructions", UNRESOLVED)

        self.add_output("state")
        self.add_output("character", socket_type="character")
        self.add_output("portrait", socket_type="image")

    async def run(self, state: GraphState):
        character = self.get_input_value("character")
        instructions = self.normalized_input_value("instructions")

        portrait = await self.agent.generate_character_portrait(
            character_name=character.name,
            instructions=instructions,
        )

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "character": character,
                "portrait": portrait,
            }
        )
