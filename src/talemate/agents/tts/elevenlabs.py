import io
from typing import Union

import structlog
from elevenlabs.client import AsyncElevenLabs
from talemate.ux.schema import Action

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentDetail,
)
from .schema import Voice, VoiceLibrary, GenerationContext, Chunk
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.elevenlabs")


add_default_voices(
    [
        Voice(
            label="Adam",
            provider="elevenlabs",
            provider_id="wBXNqKUATyqu0RtYt25i",
            tags=["male", "deep"],
        ),
        Voice(
            label="Amy",
            provider="elevenlabs",
            provider_id="oGn4Ha2pe2vSJkmIJgLQ",
            tags=["female"],
        ),
    ]
)


class ElevenLabsMixin:
    """
    ElevenLabs TTS agent mixin for cloud-based text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["apis"].choices.append(
            {
                "value": "elevenlabs",
                "label": "ElevenLabs",
                "help": "ElevenLabs is a cloud-based text to speech model that uses the ElevenLabs API. (API key required)",
            }
        )

        actions["elevenlabs"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="ElevenLabs",
            description="ElevenLabs is a cloud-based text to speech API. (API key required and must be set in the Talemate Settings -> Application -> ElevenLabs)",
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
        voices["elevenlabs"] = VoiceLibrary(api="elevenlabs", local=True)

    @property
    def elevenlabs_configured(self) -> bool:
        api_key_set = bool(self.elevenlabs_api_key)
        model_set = bool(self.elevenlabs_model)
        return api_key_set and model_set

    @property
    def elevenlabs_not_configured_reason(self) -> str | None:
        if not self.elevenlabs_api_key:
            return "ElevenLabs API key not set"
        if not self.elevenlabs_model:
            return "ElevenLabs model not set"
        return None

    @property
    def elevenlabs_not_configured_action(self) -> Action | None:
        if not self.elevenlabs_api_key:
            return Action(
                action_name="openAppConfig",
                arguments=["application", "elevenlabs_api"],
            )
        if not self.elevenlabs_model:
            return Action(
                action_name="openAgentSettings",
                arguments=["tts", "elevenlabs"],
            )
        return None

    @property
    def elevenlabs_max_generation_length(self) -> int:
        return 1024

    @property
    def elevenlabs_model(self) -> str:
        return self.actions["elevenlabs"].config["model"].value

    @property
    def elevenlabs_agent_details(self) -> dict:
        details = {}

        if not self.elevenlabs_configured:
            details["elevenlabs_api_key"] = AgentDetail(
                icon="mdi-key",
                value="ElevenLabs API key not set",
                description="ElevenLabs API key not set. You can set it in the Talemate Settings -> Application -> ElevenLabs",
                color="error",
            ).model_dump()
        else:
            details["elevenlabs_model"] = AgentDetail(
                icon="mdi-brain",
                value=self.elevenlabs_model,
                description="The model to use for ElevenLabs",
            ).model_dump()

        return details

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
            voice_id=chunk.voice.provider_id,
            model_id=chunk.model or self.elevenlabs_model,
        )

        bytes_io = io.BytesIO()

        async for chunk in response_async_iter:
            if chunk:
                bytes_io.write(chunk)

        return bytes_io.getvalue()
