import io
from typing import Union

import structlog
from openai import AsyncOpenAI

from talemate.agents.base import AgentAction, AgentActionConfig, AgentActionConditional
from .schema import Voice, VoiceLibrary, Chunk, GenerationContext

log = structlog.get_logger("talemate.agents.tts.openai")


class OpenAIMixin:
    """
    OpenAI TTS agent mixin for cloud-based text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["api"].choices.append(
            {"value": "openai", "label": "OpenAI"}
        )

        actions["openai"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            condition=AgentActionConditional(
                attribute="_config.config.api", value="openai"
            ),
            label="OpenAI",
            config={
                "model": AgentActionConfig(
                    type="text",
                    value="tts-1",
                    choices=[
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

    async def openai_generate(
        self, chunk: Chunk, context: GenerationContext, chunk_size: int = 1024
    ) -> Union[bytes, None]:
        client = AsyncOpenAI(api_key=self.openai_api_key)

        model = chunk.model or self.openai_model

        response = await client.audio.speech.create(
            model=model, voice=chunk.voice_id, input=chunk.cleaned_text
        )

        bytes_io = io.BytesIO()
        for chunk in response.iter_bytes(chunk_size=chunk_size):
            if chunk:
                bytes_io.write(chunk)

        # Put the audio data in the queue for playback
        return bytes_io.getvalue()

    async def openai_list_voices(self) -> list[Voice]:
        return [
            Voice(value="alloy", label="Alloy"),
            Voice(value="echo", label="Echo"),
            Voice(value="fable", label="Fable"),
            Voice(value="onyx", label="Onyx"),
            Voice(value="nova", label="Nova"),
            Voice(value="shimmer", label="Shimmer"),
        ]
