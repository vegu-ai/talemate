import os
import functools
import tempfile
import uuid
import asyncio
import structlog
import pydantic

from f5_tts.api import F5TTS

from talemate.agents.base import (
    AgentAction,
)
from talemate.ux.schema import Field

from .schema import Voice, Chunk, GenerationContext, VoiceProvider
from .voice_library import add_default_voices
from .providers import register, provider
from .util import voice_is_talemate_asset

log = structlog.get_logger("talemate.agents.tts.f5tts")

REF_TEXT = "You awaken aboard your ship, the Starlight Nomad."

add_default_voices(
    [
        # Adam, Bradford, Amelia, Lisa and Eva
        Voice(
            label="Adam",
            provider="f5tts",
            provider_id="tts/voice/f5tts/adam.wav",
            tags=["male", "calm", "mature", "deep", "thoughtful"],
            parameters={
                "speed": 1,
                "ref_text": REF_TEXT,
            },
        ),
        Voice(
            label="Bradford",
            provider="f5tts",
            provider_id="tts/voice/f5tts/bradford.wav",
            tags=["male", "calm", "mature"],
            parameters={
                "speed": 1,
                "ref_text": REF_TEXT,
            },
        ),
        Voice(
            label="Amelia",
            provider="f5tts",
            provider_id="tts/voice/f5tts/amelia.wav",
            tags=["female", "calm", "mature"],
            parameters={
                "speed": 1,
                "ref_text": REF_TEXT,
            },
        ),
        Voice(
            label="Lisa",
            provider="f5tts",
            provider_id="tts/voice/f5tts/lisa.wav",
            tags=["female", "young", "energetic"],
            parameters={
                "speed": 1,
                "ref_text": REF_TEXT,
            },
        ),
        Voice(
            label="Eva",
            provider="f5tts",
            provider_id="tts/voice/f5tts/eva.wav",
            tags=["female", "mature", "thoughtful"],
            parameters={
                "speed": 1,
                "ref_text": REF_TEXT,
            },
        ),
    ]
)

F5TTS_INFO = """
F5-TTS is a local text-to-speech model.

The voice id is the path to the reference *.wav* file that contains a short
voice sample (≈3-5 s). You can place new samples in the
`tts/voice/f5tts` directory of your Talemate workspace or supply an absolute
path that is accessible to the backend.

The first generation will download the model weights (≈4 GB) if they are not
cached yet.
"""


@register()
class F5TTSProvider(VoiceProvider):
    """Metadata for the F5-TTS provider."""

    name: str = "f5tts"
    allow_model_override: bool = False
    allow_file_upload: bool = True
    upload_file_types: list[str] = ["audio/wav"]

    # Provider-specific tunable parameters that can be stored per-voice
    voice_parameters: list[Field] = [
        Field(
            name="speed",
            type="number",
            label="Speed",
            value=1.0,
            min=0.25,
            max=2.0,
            step=0.05,
            description="If the speech is too fast or slow, adjust this value. 1.0 is normal speed.",
        ),
        Field(
            name="ref_text",
            type="text",
            label="Reference text",
            value="",
            description="Text that matches the reference audio sample (improves synthesis quality).",
        ),
    ]


class F5TTSInstance(pydantic.BaseModel):
    """Holds a single F5-TTS model instance (lazy-initialised)."""

    model: F5TTS

    class Config:
        arbitrary_types_allowed = True


class F5TTSMixin:
    """F5-TTS agent mixin for local text-to-speech generation."""

    # ---------------------------------------------------------------------
    # UI integration / configuration helpers
    # ---------------------------------------------------------------------

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        """Expose the F5-TTS backend in the global TTS agent settings."""

        actions["_config"].config["apis"].choices.append(
            {
                "value": "f5tts",
                "label": "F5-TTS (Local)",
                "help": "F5-TTS is a local text-to-speech model.",
            }
        )

        # No additional per-API settings (model/device) required for F5-TTS.
        return actions

    # ------------------------------------------------------------------
    # Convenience properties consumed by the core TTS agent
    # ------------------------------------------------------------------

    @property
    def f5tts_configured(self) -> bool:
        # Local backend – always available once the model weights are present.
        return True

    @property
    def f5tts_max_generation_length(self) -> int:
        return 512  # Safe default

    @property
    def f5tts_info(self) -> str:
        return F5TTS_INFO

    @property
    def f5tts_agent_details(self) -> dict:
        # Currently nothing configurable, return empty dict so UI doesn’t break.
        return {}

    # ------------------------------------------------------------------
    # Voice housekeeping helpers
    # ------------------------------------------------------------------

    def f5tts_delete_voice(self, voice: Voice):
        """Delete *voice* reference file if it is inside the Talemate workspace."""

        is_talemate_asset, resolved = voice_is_talemate_asset(
            voice, provider(voice.provider)
        )

        log.debug(
            "f5tts_delete_voice",
            voice_id=voice.provider_id,
            is_talemate_asset=is_talemate_asset,
            resolved=resolved,
        )

        if not is_talemate_asset:
            return

        try:
            if resolved.exists() and resolved.is_file():
                resolved.unlink()
                log.debug("Deleted F5-TTS voice file", path=str(resolved))
        except Exception as e:
            log.error("Failed to delete F5-TTS voice file", error=e, path=str(resolved))

    # ------------------------------------------------------------------
    # Generation helpers
    # ------------------------------------------------------------------

    def _f5tts_generate_file(
        self,
        model: F5TTS,
        chunk: Chunk,
        voice: Voice,
        output_path: str,
    ) -> str:
        """Blocking generation helper executed in a thread-pool."""

        wav, sr, _ = model.infer(
            ref_file=voice.provider_id,
            ref_text=voice.parameters.get("ref_text", ""),
            gen_text=chunk.cleaned_text,
            file_wave=output_path,
            speed=voice.parameters.get("speed", 1.0),
        )

        # Some versions of F5-TTS don’t write *file_wave*. Drop-in save as fallback.
        #if not os.path.exists(output_path):
        #    ta.save(output_path, wav, sr)

        return output_path

    async def f5tts_generate(self, chunk: Chunk, context: GenerationContext) -> bytes | None:
        """Asynchronously synthesise *chunk* using F5-TTS."""

        # Lazy initialisation & caching across invocations
        f5tts_instance: F5TTSInstance | None = getattr(self, "f5tts_instance", None)

        if f5tts_instance is None:
            log.debug("Initialising F5-TTS backend")
            f5tts_instance = F5TTSInstance(model=F5TTS())
            self.f5tts_instance = f5tts_instance

        model: F5TTS = f5tts_instance.model

        loop = asyncio.get_event_loop()

        voice = chunk.voice

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")

            # Delegate blocking work to the default ThreadPoolExecutor
            await loop.run_in_executor(
                None,
                functools.partial(self._f5tts_generate_file, model, chunk, voice, file_path),
            )

            # Read the generated WAV and return bytes for websocket playback
            with open(file_path, "rb") as f:
                return f.read()
            
    async def f5tts_prepare_chunk(self, chunk: Chunk):
        # Replace ellipses with periods
        chunk.text[0] = chunk.text[0].replace("…", "...").replace("...", ".")

        print("f5tts_prepare_chunk", chunk.text)