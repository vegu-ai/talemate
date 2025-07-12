import io
from typing import Union

import structlog
from openai import AsyncOpenAI

from talemate.agents.base import AgentAction, AgentActionConfig, AgentDetail
from .schema import Voice, VoiceLibrary, Chunk, GenerationContext
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.openai")

add_default_voices(
    [
        Voice(
            label="Alloy",
            provider="openai",
            provider_id="alloy",
        ),
        Voice(
            label="Ash",
            provider="openai",
            provider_id="ash",
        ),
        Voice(
            label="Ballad",
            provider="openai",
            provider_id="ballad",
        ),
        Voice(
            label="Coral",
            provider="openai",
            provider_id="coral",
        ),
        Voice(
            label="Echo",
            provider="openai",
            provider_id="echo",
        ),
        Voice(
            label="Fable",
            provider="openai",
            provider_id="fable",
        ),
        Voice(
            label="Onyx",
            provider="openai",
            provider_id="onyx",
        ),
        Voice(
            label="Nova",
            provider="openai",
            provider_id="nova",
        ),
        Voice(
            label="Sage",
            provider="openai",
            provider_id="sage",
        ),
        Voice(
            label="Shimmer",
            provider="openai",
            provider_id="shimmer",
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
            config={
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
            },
        )

        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["openai"] = VoiceLibrary(api="openai")

    @property
    def openai_max_generation_length(self) -> int:
        # XXX: Check limits
        return 1024

    @property
    def openai_model(self) -> str:
        return self.actions["openai"].config["model"].value

    @property
    def openai_api_key(self) -> str:
        return self.config.get("openai", {}).get("api_key")

    @property
    def openai_ready(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def openai_agent_details(self) -> dict:
        details = {}

        if not self.openai_ready:
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
