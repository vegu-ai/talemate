import io
from typing import Union

import structlog
from elevenlabs.client import AsyncElevenLabs

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentDetail,
)
from talemate.ux.schema import Column
from .schema import Voice, VoiceLibrary, GenerationContext, Chunk

log = structlog.get_logger("talemate.agents.tts.elevenlabs")


class ElevenLabsMixin:
    """
    ElevenLabs TTS agent mixin for cloud-based text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["api"].choices.append(
            {"value": "elevenlabs", "label": "Eleven Labs"}
        )

        actions["elevenlabs"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            condition=AgentActionConditional(
                attribute="_config.config.api", value="elevenlabs"
            ),
            label="Eleven Labs",
            config={
                "model": AgentActionConfig(
                    type="text",
                    value="eleven_flash_v2_5",
                    label="Model",
                    description="Model to use for TTS",
                    choices=[
                        {
                            "value": "eleven_multilingual_v2",
                            "label": "Eleven Multilingual V2",
                        },
                        {"value": "eleven_flash_v2_5", "label": "Eleven Flash V2.5"},
                        {"value": "eleven_turbo_v2_5", "label": "Eleven Turbo V2.5"},
                    ],
                ),
                "voices": AgentActionConfig(
                    type="table",
                    value=[
                        {
                            "label": "Adam",
                            "voice_id": "wBXNqKUATyqu0RtYt25i",
                        },
                        {
                            "label": "Amy",
                            "voice_id": "oGn4Ha2pe2vSJkmIJgLQ",
                        },
                    ],
                    columns=[
                        Column(
                            name="label",
                            label="Label",
                            type="text",
                        ),
                        Column(
                            name="voice_id",
                            label="Voice ID",
                            type="text",
                        ),
                    ],
                    label="Voices",
                    description="Configured ElevenLabs voices. You can add more voices by finding their Voice ID from the ElevenLabs platform in the voice library: https://elevenlabs.io/app/voice-library",
                ),
            },
        )

        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["elevenlabs"] = VoiceLibrary(api="elevenlabs", local=True)

    @property
    def elevenlabs_max_generation_length(self) -> int:
        return 1024

    @property
    def elevenlabs_model(self) -> str:
        return self.actions["elevenlabs"].config["model"].value

    @property
    def elevenlabs_agent_details(self) -> dict:
        return {
            "model": AgentDetail(
                icon="mdi-brain",
                value=self.elevenlabs_model,
                description="The model to use for Eleven Labs",
            ).model_dump(),
        }

    @property
    def elevenlabs_api_key(self) -> str:
        return self.config.get("elevenlabs", {}).get("api_key")

    async def elevenlabs_generate(
        self, chunk: Chunk, context: GenerationContext, chunk_size: int = 1024
    ) -> Union[bytes, None]:
        api_key = self.elevenlabs_api_key
        if not api_key:
            return

        client = AsyncElevenLabs(api_key=api_key)

        response_async_iter = client.text_to_speech.convert(
            text=chunk.cleaned_text,
            voice_id=chunk.voice_id,
            model_id=chunk.model or self.elevenlabs_model,
        )

        bytes_io = io.BytesIO()

        async for chunk in response_async_iter:
            if chunk:
                bytes_io.write(chunk)

        return bytes_io.getvalue()

    async def elevenlabs_list_voices(self) -> list[Voice]:
        """
        Return the configured voices from the voices table.
        """
        voices = [
            Voice(value=voice["voice_id"], label=voice["label"])
            for voice in self.actions["elevenlabs"].config["voices"].value
        ]

        voices.sort(key=lambda x: x.label)

        log.debug("elevenlabs_list_voices", num_voices=len(voices))

        return voices
