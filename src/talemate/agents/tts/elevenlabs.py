import io
from typing import Union

import structlog


# Lazy imports for heavy dependencies
def _import_heavy_deps():
    global AsyncElevenLabs, ApiError
    from elevenlabs.client import AsyncElevenLabs

    # Added explicit ApiError import for clearer error handling
    from elevenlabs.core.api_error import ApiError


from talemate.ux.schema import Action

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentDetail,
)
from .schema import Voice, VoiceLibrary, GenerationContext, Chunk, INFO_CHUNK_SIZE
from .voice_library import add_default_voices

# emit helper to propagate status messages to the UX
from talemate.emit import emit

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


ELEVENLABS_INFO = """
ElevenLabs is a cloud-based text to speech API.

To add new voices, head to their voice library at [https://elevenlabs.io/app/voice-library](https://elevenlabs.io/app/voice-library) and note the voice id of the voice you want to use. (Click 'More Actions -> Copy Voice ID')

**About elevenlabs voices**
Your elevenlabs subscription allows you to maintain a set number of voices (10 for cheapest plan). 

Any voice that you generate audio for is automatically added to your voices at [https://elevenlabs.io/app/voice-lab](https://elevenlabs.io/app/voice-lab). This also happens when you use the "Test" button above. It is recommend testing via their voice library instead.
"""


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
                "api_key": AgentActionConfig(
                    type="unified_api_key",
                    value="elevenlabs.api_key",
                    label="ElevenLabs API Key",
                ),
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
                "chunk_size": AgentActionConfig(
                    type="number",
                    min=0,
                    step=64,
                    max=2048,
                    value=0,
                    label="Chunk size",
                    note=INFO_CHUNK_SIZE,
                ),
            },
        )

        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["elevenlabs"] = VoiceLibrary(api="elevenlabs", local=True)

    @property
    def elevenlabs_chunk_size(self) -> int:
        return self.actions["elevenlabs"].config["chunk_size"].value

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
                label="Set API Key",
                icon="mdi-key",
            )
        if not self.elevenlabs_model:
            return Action(
                action_name="openAgentSettings",
                arguments=["tts", "elevenlabs"],
                label="Set Model",
                icon="mdi-brain",
            )
        return None

    @property
    def elevenlabs_max_generation_length(self) -> int:
        return 1024

    @property
    def elevenlabs_model(self) -> str:
        return self.actions["elevenlabs"].config["model"].value

    @property
    def elevenlabs_model_choices(self) -> list[str]:
        return [
            {"label": choice["label"], "value": choice["value"]}
            for choice in self.actions["elevenlabs"].config["model"].choices
        ]

    @property
    def elevenlabs_info(self) -> str:
        return ELEVENLABS_INFO

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
        return self.config.elevenlabs.api_key

    async def elevenlabs_generate(
        self, chunk: Chunk, context: GenerationContext, chunk_size: int = 1024
    ) -> Union[bytes, None]:
        api_key = self.elevenlabs_api_key
        if not api_key:
            return

        # Lazy import heavy dependencies only when needed
        _import_heavy_deps()

        client = AsyncElevenLabs(api_key=api_key)

        try:
            response_async_iter = client.text_to_speech.convert(
                text=chunk.cleaned_text,
                voice_id=chunk.voice.provider_id,
                model_id=chunk.model or self.elevenlabs_model,
            )

            bytes_io = io.BytesIO()

            async for _chunk_bytes in response_async_iter:
                if _chunk_bytes:
                    bytes_io.write(_chunk_bytes)

            return bytes_io.getvalue()

        except ApiError as e:
            # Emit detailed status message to the frontend UI
            error_message = "ElevenLabs API Error"
            try:
                # The ElevenLabs ApiError often contains a JSON body with details
                detail = e.body.get("detail", {}) if hasattr(e, "body") else {}
                error_message = detail.get("message", str(e)) or str(e)
            except Exception:
                error_message = str(e)

            log.error("ElevenLabs API error", error=str(e))
            emit(
                "status",
                message=f"ElevenLabs TTS: {error_message}",
                status="error",
            )
            raise e

        except Exception as e:
            # Catch-all to ensure the app does not crash on unexpected errors
            log.error("ElevenLabs TTS generation error", error=str(e))
            emit(
                "status",
                message=f"ElevenLabs TTS: Unexpected error – {str(e)}",
                status="error",
            )
            raise e
