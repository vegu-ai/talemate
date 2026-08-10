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
from talemate.agents.tts.schema import Voice, VoiceGenerationEmission, VoiceLibrary

TYPE_CHOICES.extend(
    [
        "tts/voice",
        "tts/generation_emission",
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


@register("agents/tts/UnpackGenerationEmission")
class UnpackGenerationEmission(AgentNode):
    """
    Unpacks a TTS generation emission into the fields of the chunk that is
    about to be spoken.

    Inputs:

    - emission: The generation emission

    Outputs:

    - emission: The emission, passed through
    - text: The text of the chunk
    - character_name: The name of the character speaking the chunk
    - type: The chunk type (dialogue or exposition)
    - api: The TTS provider (API) generating the chunk
    - message_id: The ID of the message the chunk belongs to
    - voice: The voice the chunk will be spoken with
    """

    _agent_name: ClassVar[str] = "tts"

    def __init__(self, title="Unpack Generation Emission", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("emission", socket_type="event,tts/generation_emission")

        self.add_output("emission", socket_type="tts/generation_emission")
        self.add_output("text", socket_type="str,text")
        self.add_output("character_name", socket_type="str")
        self.add_output("type", socket_type="str")
        self.add_output("api", socket_type="str")
        self.add_output("message_id", socket_type="int,str")
        self.add_output("voice", socket_type="tts/voice")

    async def run(self, state: GraphState):
        emission: VoiceGenerationEmission = self.require_input("emission")
        chunk = emission.chunk

        self.set_output_values(
            {
                "emission": emission,
                "text": chunk.text[0],
                "character_name": chunk.character_name,
                "type": chunk.type,
                "api": chunk.api,
                "message_id": chunk.message_id,
                "voice": chunk.voice,
            }
        )


@register("agents/tts/SetChunkText")
class SetChunkText(AgentNode):
    """
    Replaces the text of the chunk carried by a TTS generation emission,
    letting a graph rewrite what is spoken before the audio is generated.
    Empty text still reaches the backend and produces no audio for that
    chunk.

    Inputs:

    - state: The graph state (required — wire through any gating switch so
      the node is skipped when the chunk should be left alone)
    - emission: The generation emission
    - text: The text to speak instead (required at runtime despite the
      optional socket)

    Outputs:

    - state: The state input, passed through
    - emission: The emission, passed through
    """

    _agent_name: ClassVar[str] = "tts"

    class Fields:
        text = PropertyField(
            name="text",
            type="text",
            description="The text to speak instead",
            default=UNRESOLVED,
        )

    def __init__(self, title="Set Chunk Text", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("emission", socket_type="event,tts/generation_emission")
        self.add_input("text", socket_type="str,text", optional=True)
        self.set_property("text", UNRESOLVED)

        self.add_output("state")
        self.add_output("emission", socket_type="tts/generation_emission")

    async def run(self, state: GraphState):
        emission: VoiceGenerationEmission = self.require_input("emission")
        text = self.require_input("text")

        emission.chunk.text[0] = text

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "emission": emission,
            }
        )
