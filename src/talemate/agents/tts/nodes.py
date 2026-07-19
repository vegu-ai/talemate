import structlog
from typing import ClassVar
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
    TYPE_CHOICES,
    UNRESOLVED,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode
from talemate.agents.tts.schema import Voice, VoiceLibrary

TYPE_CHOICES.extend(
    [
        "tts/voice",
    ]
)

log = structlog.get_logger("talemate.game.engine.nodes.agents.tts")


@register("agents/tts/Settings")
class TTSAgentSettings(AgentSettingsNode):
    """
    Base node to render TTS agent settings.
    """

    _agent_name: ClassVar[str] = "tts"

    def __init__(self, title="TTS Agent Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/tts/GetVoice")
class GetVoice(AgentNode):
    """
    Looks up a voice in the TTS agent's voice library by voice ID.

    Inputs:

    - voice_id: The ID of the voice to get (required at runtime despite
      the optional socket)

    Outputs:

    - voice: The voice object (None if no voice with that ID exists)
    """

    _agent_name: ClassVar[str] = "tts"

    class Fields:
        voice_id = PropertyField(
            name="voice_id",
            type="str",
            description="The ID of the voice to get",
            default=UNRESOLVED,
        )

    def __init__(self, title="Get Voice", **kwargs):
        super().__init__(title=title, **kwargs)

    @property
    def voice_library(self) -> VoiceLibrary:
        return self.agent.voice_library

    def setup(self):
        self.add_input("voice_id", socket_type="str", optional=True)
        self.set_property("voice_id", UNRESOLVED)

        self.add_output("voice", socket_type="tts/voice")

    async def run(self, state: GraphState):
        voice_id = self.require_input("voice_id")

        voice = self.voice_library.get_voice(voice_id)

        self.set_output_values({"voice": voice})


@register("agents/tts/GetNarratorVoice")
class GetNarratorVoice(AgentNode):
    """
    Gets the narrator voice from the TTS agent.
    """

    _agent_name: ClassVar[str] = "tts"

    def __init__(self, title="Get Narrator Voice", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("voice", socket_type="tts/voice")

    async def run(self, state: GraphState):
        voice = self.agent.narrator_voice

        self.set_output_values({"voice": voice})


@register("agents/tts/UnpackVoice")
class UnpackVoice(AgentNode):
    """
    Unpacks a voice object into its individual fields.

    Inputs:

    - voice: The voice to unpack

    Outputs:

    - voice: The voice, passed through
    - label: The voice's display label
    - provider: The TTS provider (API) the voice belongs to
    - provider_id: The voice's ID at the provider
    - provider_model: The provider model the voice uses
    - tags: The voice's tags
    - parameters: The voice's generation parameters
    - is_scene_asset: Whether the voice is stored as a scene asset
    """

    _agent_name: ClassVar[str] = "tts"

    def __init__(self, title="Unpack Voice", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("voice", socket_type="tts/voice")
        self.add_output("voice", socket_type="tts/voice")
        self.add_output("label", socket_type="str")
        self.add_output("provider", socket_type="str")
        self.add_output("provider_id", socket_type="str")
        self.add_output("provider_model", socket_type="str")
        self.add_output("tags", socket_type="list")
        self.add_output("parameters", socket_type="dict")
        self.add_output("is_scene_asset", socket_type="bool")

    async def run(self, state: GraphState):
        voice: Voice = self.require_input("voice")

        self.set_output_values(
            {
                "voice": voice,
                **voice.model_dump(),
            }
        )


@register("agents/tts/Generate")
class Generate(AgentNode):
    """
    Generates speech audio for the given text via the TTS agent and queues
    it for playback in the frontend. Either a voice or a character must be
    provided; when a character is given its assigned voice is used, while
    an explicit voice input overrides it. Does nothing when the TTS agent
    is disabled or not ready.

    Inputs:

    - state: The graph state
    - text: The text to speak (required at runtime despite the optional socket)
    - voice: The voice to use (optional)
    - character: The character to speak as (optional)

    Outputs:

    - state: The state input, passed through
    """

    _agent_name: ClassVar[str] = "tts"

    class Fields:
        text = PropertyField(
            name="text",
            type="text",
            description="The text to generate",
            default=UNRESOLVED,
        )

    def __init__(self, title="Generate TTS", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("text", socket_type="text", optional=True)
        self.add_input("voice", socket_type="tts/voice", optional=True)
        self.add_input("character", socket_type="character", optional=True)
        self.set_property("text", UNRESOLVED)
        self.add_output("state")

    async def run(self, state: GraphState):
        text = self.require_input("text")
        voice = self.normalized_input_value("voice")
        character = self.normalized_input_value("character")

        if not voice and not character:
            raise ValueError("Either voice or character must be provided")

        await self.agent.generate(
            text=text,
            character=character,
            force_voice=voice,
        )

        self.set_output_values({"state": state})
