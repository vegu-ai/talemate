import structlog
from typing import ClassVar
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
    TYPE_CHOICES,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode
from talemate.character import Character
from talemate.agents.tts.schema import Voice

TYPE_CHOICES.extend(
    [
        "director/direction",
    ]
)

log = structlog.get_logger("talemate.game.engine.nodes.agents.director")


@register("agents/director/Settings")
class DirectorSettings(AgentSettingsNode):
    """
    Base node to render director agent settings.
    """

    _agent_name: ClassVar[str] = "director"

    def __init__(self, title="Director Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/director/PersistCharacter")
class PersistCharacter(AgentNode):
    """
    Persists a character that currently only exists as part of the given context
    as a real character that can actively participate in the scene.
    """

    _agent_name: ClassVar[str] = "director"

    class Fields:
        determine_name = PropertyField(
            name="determine_name",
            type="bool",
            description="Whether to determine the name of the character",
            default=True,
        )

    def __init__(self, title="Persist Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character_name", socket_type="str")
        self.add_input("context", socket_type="str", optional=True)
        self.add_input("attributes", socket_type="dict,str", optional=True)

        self.set_property("determine_name", True)

        self.add_output("state")
        self.add_output("character", socket_type="character")

    async def run(self, state: GraphState):
        character_name = self.get_input_value("character_name")
        context = self.normalized_input_value("context")
        attributes = self.normalized_input_value("attributes")
        determine_name = self.normalized_input_value("determine_name")

        character = await self.agent.persist_character(
            name=character_name,
            content=context,
            attributes="\n".join([f"{k}: {v}" for k, v in attributes.items()])
            if attributes
            else None,
            determine_name=determine_name,
        )

        self.set_output_values({"state": state, "character": character})

@register("agents/director/AssignVoice")
class AssignVoice(AgentNode):
    """
    Assigns a voice to a character.
    """

    _agent_name: ClassVar[str] = "director"

    def __init__(self, title="Assign Voice", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")

        self.add_output("state")
        self.add_output("character", socket_type="character")
        self.add_output("voice", socket_type="tts/voice")
        
    async def run(self, state: GraphState):
        character: "Character" = self.require_input("character")

        await self.agent.assign_voice_to_character(character)

        voice = character.voice

        self.set_output_values({"state": state, "character": character, "voice": voice})