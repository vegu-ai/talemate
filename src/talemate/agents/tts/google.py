import io
import wave
from typing import Union, List, Optional

import structlog
from google import genai
from google.genai import types

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentDetail,
)
from .schema import Voice, VoiceLibrary, Chunk, GenerationContext
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.google")

add_default_voices(
    [
        Voice(label="Zephyr", provider="google", provider_id="Zephyr"),
        Voice(label="Puck", provider="google", provider_id="Puck"),
        Voice(label="Charon", provider="google", provider_id="Charon"),
        Voice(label="Kore", provider="google", provider_id="Kore"),
        Voice(label="Fenrir", provider="google", provider_id="Fenrir"),
        Voice(label="Leda", provider="google", provider_id="Leda"),
        Voice(label="Orus", provider="google", provider_id="Orus"),
        Voice(label="Aoede", provider="google", provider_id="Aoede"),
        Voice(label="Callirrhoe", provider="google", provider_id="Callirrhoe"),
        Voice(label="Autonoe", provider="google", provider_id="Autonoe"),
        Voice(label="Enceladus", provider="google", provider_id="Enceladus"),
        Voice(label="Iapetus", provider="google", provider_id="Iapetus"),
        Voice(label="Umbriel", provider="google", provider_id="Umbriel"),
        Voice(label="Algieba", provider="google", provider_id="Algieba"),
        Voice(label="Despina", provider="google", provider_id="Despina"),
        Voice(label="Erinome", provider="google", provider_id="Erinome"),
        Voice(label="Algenib", provider="google", provider_id="Algenib"),
        Voice(label="Rasalgethi", provider="google", provider_id="Rasalgethi"),
        Voice(label="Laomedeia", provider="google", provider_id="Laomedeia"),
        Voice(label="Achernar", provider="google", provider_id="Achernar"),
        Voice(label="Alnilam", provider="google", provider_id="Alnilam"),
        Voice(label="Schedar", provider="google", provider_id="Schedar"),
        Voice(label="Gacrux", provider="google", provider_id="Gacrux"),
        Voice(label="Pulcherrima", provider="google", provider_id="Pulcherrima"),
        Voice(label="Achird", provider="google", provider_id="Achird"),
        Voice(label="Zubenelgenubi", provider="google", provider_id="Zubenelgenubi"),
        Voice(label="Vindemiatrix", provider="google", provider_id="Vindemiatrix"),
        Voice(label="Sadachbia", provider="google", provider_id="Sadachbia"),
        Voice(label="Sadaltager", provider="google", provider_id="Sadaltager"),
        Voice(label="Sulafat", provider="google", provider_id="Sulafat"),
    ]
)


class GoogleMixin:
    """Google Gemini TTS mixin (Flash/Pro preview models)."""

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["apis"].choices.append(
            {
                "value": "google",
                "label": "Google Gemini",
                "help": "Google Gemini is a cloud-based text to speech model that uses the Google Gemini API. (API key required)",
            }
        )

        actions["google"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="Google Gemini",
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
    def google_ready(self) -> bool:
        return bool(self.google_api_key)

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
        details = {}
        
        if not self.google_ready:
            details["google_api_key"] = AgentDetail(
                icon="mdi-key",
                value="Google API key not set",
                description="Google API key not set. You can set it in the Talemate Settings -> Application -> Google",
                color="error",
            ).model_dump()
        else:
            details["google_model"] = AgentDetail(
                icon="mdi-brain",
                value=self.google_model,
                description="The model to use for Google",
            ).model_dump()
            
        return details

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

        voice_name = chunk.voice.provider_id
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