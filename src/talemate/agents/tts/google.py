import io
import wave
from typing import Union, List, Optional

import structlog
from google import genai
from google.genai import types

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentDetail,
)
from .schema import Voice, VoiceLibrary, Chunk, GenerationContext

log = structlog.get_logger("talemate.agents.tts.google")

# Complete static list of Gemini preview voices (until an official endpoint exists)
_PREBUILT_VOICE_NAMES: List[str] = [
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
]


class GoogleMixin:
    """Google Gemini TTS mixin (Flash/Pro preview models)."""

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["api"].choices.append(
            {"value": "google", "label": "Google Gemini"}
        )

        actions["google"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-google",
            condition=AgentActionConditional(
                attribute="_config.config.api",
                value="google",
            ),
            label="Google Gemini TTS",
            config={
                "model": AgentActionConfig(
                    type="text",
                    value="gemini-2.5-flash-preview-tts",
                    choices=[
                        {
                            "value": "gemini-2.5-flash-preview-tts",
                            "label": "Gemini 2.5 Flash TTS (Preview)",
                        },
                        {
                            "value": "gemini-2.5-pro-preview-tts",
                            "label": "Gemini 2.5 Pro TTS (Preview)",
                        },
                    ],
                    label="Model",
                    description="Google TTS model to use",
                ),
            },
        )

        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["google"] = VoiceLibrary(api="google")

    @property
    def google_max_generation_length(self) -> int:
        return 1024  # safe default (≈ 4 k chars)

    @property
    def google_model(self) -> str:
        return self.actions["google"].config["model"].value

    @property
    def google_api_key(self) -> Optional[str]:
        return self.config.get("google", {}).get("api_key")

    @property
    def google_agent_details(self) -> dict:
        return {
            "model": AgentDetail(
                icon="mdi-brain",
                value=self.google_model,
                description="The model to use for Google",
            ).model_dump(),
        }

    def _make_google_client(self) -> genai.Client:
        """Return a fresh genai.Client so updated creds propagate immediately."""
        return genai.Client(api_key=self.google_api_key or None)

    async def google_generate(
        self,
        chunk: Chunk,
        context: GenerationContext,
        chunk_size: int = 1024,  # kept for signature parity
    ) -> Union[bytes, None]:
        """Generate audio and wrap raw PCM into a playable WAV container."""

        voice_name = chunk.voice_id or "Kore"
        client = self._make_google_client()

        try:
            response = await client.aio.models.generate_content(
                model=chunk.model or self.google_model,
                contents=chunk.cleaned_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice_name,
                            )
                        )
                    ),
                ),
            )

            # Extract raw 24 kHz 16‑bit PCM (mono) bytes from first candidate
            part = response.candidates[0].content.parts[0].inline_data
            if not part or not part.data:
                return None
            pcm_bytes: bytes = part.data

            # Wrap into a WAV container that browsers can decode
            wav_io = io.BytesIO()
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16‑bit
                wf.setframerate(24000)  # Hz
                wf.writeframes(pcm_bytes)
            return wav_io.getvalue()

        except Exception as e:
            import traceback

            traceback.print_exc()
            log.error("google_generate failed", error=str(e))
            return None

    async def google_list_voices(self) -> list[Voice]:
        voices = [Voice(value=name, label=name) for name in _PREBUILT_VOICE_NAMES]
        voices.sort(key=lambda v: v.label)
        return voices
