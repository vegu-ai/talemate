import io
from typing import Union

import structlog
from openai import AsyncOpenAI
from talemate.ux.schema import Action
from talemate.agents.base import AgentAction, AgentActionConfig, AgentDetail
from .schema import Voice, VoiceLibrary, Chunk, GenerationContext, INFO_CHUNK_SIZE
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.openai")

OPENAI_INFO = """
OpenAI TTS is a cloud-based text to speech model.

A list of available voices can be found at [https://platform.openai.com/docs/guides/text-to-speech#voice-options](https://platform.openai.com/docs/guides/text-to-speech#voice-options).
"""

add_default_voices(
    [
        Voice(
            label="Alloy",
            provider="openai",
            provider_id="alloy",
            tags=["neutral", "female"],
        ),
        Voice(
            label="Ash",
            provider="openai",
            provider_id="ash",
            tags=["male"],
        ),
        Voice(
            label="Ballad",
            provider="openai",
            provider_id="ballad",
            tags=["male", "energetic"],
        ),
        Voice(
            label="Coral",
            provider="openai",
            provider_id="coral",
            tags=["female", "energetic"],
        ),
        Voice(
            label="Echo",
            provider="openai",
            provider_id="echo",
            tags=["male", "neutral"],
        ),
        Voice(
            label="Fable",
            provider="openai",
            provider_id="fable",
            tags=["neutral", "feminine"],
        ),
        Voice(
            label="Onyx",
            provider="openai",
            provider_id="onyx",
            tags=["male"],
        ),
        Voice(
            label="Nova",
            provider="openai",
            provider_id="nova",
            tags=["female"],
        ),
        Voice(
            label="Sage",
            provider="openai",
            provider_id="sage",
            tags=["female"],
        ),
        Voice(
            label="Shimmer",
            provider="openai",
            provider_id="shimmer",
            tags=["female"],
        ),
    ]
)


class OpenAIMixin:
    """
    OpenAI TTS agent mixin for cloud-based text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["apis"].choices.append(
            {
                "value": "openai",
                "label": "OpenAI",
                "help": "OpenAI is a cloud-based text to speech model that uses the OpenAI API. (API key required)",
            }
        )

        actions["openai"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="OpenAI",
            description="OpenAI TTS is a cloud-based text to speech API. (API key required and must be set in the Talemate Settings -> Application -> OpenAI)",
            config={
                "api_key": AgentActionConfig(
                    type="unified_api_key",
                    value="openai.api_key",
                    label="OpenAI API Key",
                ),
                "model": AgentActionConfig(
                    type="text",
                    value="gpt-4o-mini-tts",
                    choices=[
                        {"value": "gpt-4o-mini-tts", "label": "GPT-4o Mini TTS"},
                        {"value": "tts-1", "label": "TTS 1"},
                        {"value": "tts-1-hd", "label": "TTS 1 HD"},
                    ],
                    label="Model",
                    description="TTS model to use",
                ),
                "chunk_size": AgentActionConfig(
                    type="number",
                    min=0,
                    step=64,
                    max=2048,
                    value=512,
                    label="Chunk size",
                    note=INFO_CHUNK_SIZE,
                ),
            },
        )

        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["openai"] = VoiceLibrary(api="openai")

    @property
    def openai_chunk_size(self) -> int:
        return self.actions["openai"].config["chunk_size"].value

    @property
    def openai_max_generation_length(self) -> int:
        return 1024

    @property
    def openai_model(self) -> str:
        return self.actions["openai"].config["model"].value

    @property
    def openai_model_choices(self) -> list[str]:
        return [
            {"label": choice["label"], "value": choice["value"]}
            for choice in self.actions["openai"].config["model"].choices
        ]

    @property
    def openai_api_key(self) -> str:
        return self.config.openai.api_key

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key) and bool(self.openai_model)

    @property
    def openai_info(self) -> str:
        return OPENAI_INFO

    @property
    def openai_not_configured_reason(self) -> str | None:
        if not self.openai_api_key:
            return "OpenAI API key not set"
        if not self.openai_model:
            return "OpenAI model not set"
        return None

    @property
    def openai_not_configured_action(self) -> Action | None:
        if not self.openai_api_key:
            return Action(
                action_name="openAppConfig",
                arguments=["application", "openai_api"],
                label="Set API Key",
                icon="mdi-key",
            )
        if not self.openai_model:
            return Action(
                action_name="openAgentSettings",
                arguments=["tts", "openai"],
                label="Set Model",
                icon="mdi-brain",
            )
        return None

    @property
    def openai_agent_details(self) -> dict:
        details = {}

        if not self.openai_configured:
            details["openai_api_key"] = AgentDetail(
                icon="mdi-key",
                value="OpenAI API key not set",
                description="OpenAI API key not set. You can set it in the Talemate Settings -> Application -> OpenAI",
                color="error",
            ).model_dump()
        else:
            details["openai_model"] = AgentDetail(
                icon="mdi-brain",
                value=self.openai_model,
                description="The model to use for OpenAI",
            ).model_dump()

        return details

    async def openai_generate(
        self, chunk: Chunk, context: GenerationContext, chunk_size: int = 1024
    ) -> Union[bytes, None]:
        client = AsyncOpenAI(api_key=self.openai_api_key)

        model = chunk.model or self.openai_model

        response = await client.audio.speech.create(
            model=model, voice=chunk.voice.provider_id, input=chunk.cleaned_text
        )

        bytes_io = io.BytesIO()
        for chunk in response.iter_bytes(chunk_size=chunk_size):
            if chunk:
                bytes_io.write(chunk)

        # Put the audio data in the queue for playback
        return bytes_io.getvalue()
