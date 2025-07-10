import io
from typing import Union

import structlog
from elevenlabs.client import AsyncElevenLabs
from elevenlabs.types.get_voices_v_2_response import GetVoicesV2Response

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentDetail,
)
from .schema import Voice, VoiceLibrary, GenerationContext

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
            },
        )

        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["elevenlabs"] = VoiceLibrary(api="elevenlabs")

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

    async def elevenlabs_generate(
        self, text: str, context: GenerationContext, chunk_size: int = 1024
    ) -> Union[bytes, None]:
        api_key = self.token
        if not api_key:
            return

        client = AsyncElevenLabs(api_key=api_key)

        response_async_iter = client.text_to_speech.convert(
            text=text,
            voice_id=context.voice_id,
            model_id=context.model or self.elevenlabs_model,
        )

        bytes_io = io.BytesIO()

        async for chunk in response_async_iter:
            if chunk:
                bytes_io.write(chunk)

        return bytes_io.getvalue()

    async def elevenlabs_list_voices(self) -> list[Voice]:
        client = AsyncElevenLabs(api_key=self.token)

        log.debug("elevenlabs_list_voices", token=self.token)

        response: GetVoicesV2Response = await client.voices.search(page_size=100)

        voices = [
            Voice(value=voice.voice_id, label=voice.name) for voice in response.voices
        ]

        voices.sort(key=lambda x: x.label)

        log.debug("elevenlabs_list_voices", num_voices=len(voices))

        return voices
