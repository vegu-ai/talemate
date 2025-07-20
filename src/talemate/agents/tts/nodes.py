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
    Gets a voice from the TTS agent.
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
    Unpacks a voice from the TTS agent.
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
    Generates a voice from the TTS agent.
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