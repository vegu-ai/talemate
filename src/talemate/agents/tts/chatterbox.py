import os
import tempfile
import asyncio
import structlog
import pydantic
from typing import Any, Literal
import gc
import threading

import soundfile

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentDetail,
)
from talemate.ux.schema import Field
from talemate.util.gpu import cuda_available
from talemate.emit import emit
from talemate.path import TALEMATE_ROOT

from .schema import Voice, Chunk, GenerationContext, VoiceProvider, INFO_CHUNK_SIZE
from .voice_library import add_default_voices, DEFAULT_VOICES
from .providers import register, provider
from .util import voice_is_talemate_asset

log = structlog.get_logger("talemate.agents.tts.chatterbox")

TURBO_AUDIO_TAGS = (
    "clear throat",
    "sigh",
    "shush",
    "cough",
    "groan",
    "sniff",
    "gasp",
    "chuckle",
    "laugh",
)

CHATTERBOX_TURBO_INFO = """
Chatterbox Turbo is an opt-in local English voice-cloning model.

Use a clear, single-speaker WAV reference longer than five seconds.
The bundled Chatterbox references are also available as separate Turbo voices.

The first generation downloads separate Turbo model files (approximately 4 GB).
Standard and Turbo share one loaded model slot; switching model or device unloads
it and loads the selected model again. Every chunk refreshes voice conditioning.

Turbo supports temperature, top-k, top-p, repetition penalty and reference
loudness normalization. CFG/Pace, exaggeration and min-p are not used.
Each chunk is returned as a complete waveform, not streamed during synthesis.
"""

ChatterboxVariant = Literal["chatterbox", "chatterbox_turbo"]


def _load_chatterbox_model(variant: ChatterboxVariant, device: str):
    if variant == "chatterbox_turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        class TalemateChatterboxTurboTTS(ChatterboxTurboTTS):
            def norm_loudness(self, wav, sr, target_lufs=-27):
                # NumPy 2 promotes upstream loudness scaling to float64; the
                # speech tokenizer's mel filters require the original float32.
                return (
                    super()
                    .norm_loudness(wav, sr, target_lufs)
                    .astype(wav.dtype, copy=False)
                )

        return TalemateChatterboxTurboTTS.from_pretrained(device=device)
    from chatterbox.tts import ChatterboxTTS

    return ChatterboxTTS.from_pretrained(device=device)


add_default_voices(
    [
        Voice(
            label="Eva",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/eva.wav",
            tags=["female", "calm", "mature", "thoughtful"],
        ),
        Voice(
            label="Lisa",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/lisa.wav",
            tags=["female", "energetic", "young"],
        ),
        Voice(
            label="Adam",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/adam.wav",
            tags=["male", "calm", "mature", "thoughtful", "deep"],
        ),
        Voice(
            label="Bradford",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/bradford.wav",
            tags=["male", "calm", "mature", "thoughtful", "deep"],
        ),
        Voice(
            label="Julia",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/julia.wav",
            tags=["female", "calm", "mature"],
        ),
        Voice(
            label="Zoe",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/zoe.wav",
            tags=["female"],
        ),
        Voice(
            label="William",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/william.wav",
            tags=["male", "young"],
        ),
    ]
)

add_default_voices(
    [
        voice.model_copy(deep=True, update={"provider": "chatterbox_turbo"})
        for voice in list(DEFAULT_VOICES.values())
        if voice.provider == "chatterbox"
    ]
)

CHATTERBOX_INFO = """
Chatterbox is a local text to speech model.

The voice id is the path to the .wav file for the voice.

The path can be relative to the talemate root directory, and you can put new *.wav samples
in the `tts/voice/chatterbox` directory. It is also ok if you want to load the files from somewhere else as long as the filepath is available to the talemate backend.

First generation will download the models (2.13GB + 1.06GB).

Uses about 4GB of VRAM.
"""


@register()
class ChatterboxProvider(VoiceProvider):
    name: str = "chatterbox"
    allow_model_override: bool = False
    allow_file_upload: bool = True
    upload_file_types: list[str] = ["audio/wav"]
    voice_parameters: list[Field] = [
        Field(
            name="exaggeration",
            type="number",
            label="Exaggeration level",
            value=0.5,
            min=0.25,
            max=2.0,
            step=0.05,
        ),
        Field(
            name="cfg_weight",
            type="number",
            label="CFG/Pace",
            value=0.5,
            min=0.2,
            max=1.0,
            step=0.1,
        ),
        Field(
            name="temperature",
            type="number",
            label="Temperature",
            value=0.8,
            min=0.05,
            max=5.0,
            step=0.05,
        ),
    ]


@register()
class ChatterboxTurboProvider(VoiceProvider):
    name: str = "chatterbox_turbo"
    allow_model_override: bool = False
    allow_file_upload: bool = True
    upload_file_types: list[str] = ["audio/wav"]
    voice_parameters: list[Field] = [
        Field(
            name="temperature",
            type="number",
            label="Temperature",
            value=0.8,
            min=0.05,
            max=5.0,
            step=0.05,
        ),
        Field(
            name="top_k",
            type="number",
            label="Top K",
            value=1000,
            min=0,
            max=6563,
            step=1,
            description="0 disables top-k filtering.",
        ),
        Field(
            name="top_p",
            type="number",
            label="Top P",
            value=0.95,
            min=0.01,
            max=1.0,
            step=0.01,
        ),
        Field(
            name="repetition_penalty",
            type="number",
            label="Repetition penalty",
            value=1.2,
            min=0.1,
            max=3.0,
            step=0.05,
        ),
        Field(
            name="norm_loudness",
            type="bool",
            label="Normalize reference loudness",
            value=True,
        ),
    ]


class TurboParameters(pydantic.BaseModel):
    temperature: float = pydantic.Field(default=0.8, ge=0.05, le=5.0)
    top_k: int = pydantic.Field(default=1000, ge=0, le=6563)
    top_p: float = pydantic.Field(default=0.95, ge=0.01, le=1.0)
    repetition_penalty: float = pydantic.Field(default=1.2, ge=0.1, le=3.0)
    norm_loudness: bool = True


def validate_turbo_reference(path: str):
    try:
        info = soundfile.info(path)
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"Cannot read Chatterbox Turbo voice reference '{path}': {exc}"
        ) from exc
    if info.duration <= 5.0:
        raise ValueError(
            f"Chatterbox Turbo requires a voice reference longer than 5 seconds "
            f"(received {info.duration:.2f}s). Choose or upload a longer WAV sample."
        )


class ChatterboxInstance(pydantic.BaseModel):
    model: Any
    device: str
    variant: ChatterboxVariant = "chatterbox"


class ChatterboxMixin:
    """
    Chatterbox agent mixin for local text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["apis"].choices.append(
            {
                "value": "chatterbox",
                "label": "Chatterbox (Local)",
                "help": "Chatterbox is a local text to speech model.",
            }
        )

        actions["chatterbox"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="Chatterbox",
            description="Chatterbox is a local text to speech model.",
            config={
                "device": AgentActionConfig(
                    type="text",
                    value="cuda" if cuda_available() else "cpu",
                    label="Device",
                    choices=[
                        {"value": "cpu", "label": "CPU"},
                        {"value": "cuda", "label": "CUDA"},
                    ],
                    description="Device to use for TTS",
                    scene_overridable=False,
                ),
                "chunk_size": AgentActionConfig(
                    type="number",
                    min=0,
                    step=64,
                    max=2048,
                    value=256,
                    label="Chunk size",
                    note=INFO_CHUNK_SIZE,
                    scene_overridable=False,
                ),
            },
        )
        actions["_config"].config["apis"].choices.append(
            {
                "value": "chatterbox_turbo",
                "label": "Chatterbox Turbo (Local)",
                "help": "Local English voice cloning with the separate Turbo model.",
            }
        )
        actions["chatterbox_turbo"] = actions["chatterbox"].model_copy(deep=True)
        actions["chatterbox_turbo"].label = "Chatterbox Turbo"
        actions[
            "chatterbox_turbo"
        ].description = "Local English voice cloning with Chatterbox Turbo."
        return actions

    @property
    def chatterbox_configured(self) -> bool:
        return True

    @property
    def chatterbox_max_generation_length(self) -> int:
        return 512

    @property
    def chatterbox_device(self) -> str:
        return self.actions["chatterbox"].config["device"].value

    @property
    def chatterbox_chunk_size(self) -> int:
        return self.actions["chatterbox"].config["chunk_size"].value

    @property
    def chatterbox_info(self) -> str:
        return CHATTERBOX_INFO

    @property
    def chatterbox_agent_details(self) -> dict:
        if not self.chatterbox_configured:
            return {}
        details = {}

        details["chatterbox_device"] = AgentDetail(
            icon="mdi-memory",
            value=f"Chatterbox: {self.chatterbox_device}",
            description="The device to use for Chatterbox",
        ).model_dump()

        return details

    def chatterbox_delete_voice(self, voice: Voice):
        """
        Remove the voice from the file system.
        Only do this if the path is within TALEMATE_ROOT.
        """

        is_talemate_asset, resolved = voice_is_talemate_asset(
            voice, provider(voice.provider)
        )

        log.debug(
            "chatterbox_delete_voice",
            voice_id=voice.provider_id,
            is_talemate_asset=is_talemate_asset,
            resolved=resolved,
        )

        if not is_talemate_asset:
            return

        # Standard and Turbo bundled entries share the same reference files.
        bundled_paths = {
            (TALEMATE_ROOT / default.provider_id).resolve()
            for default in DEFAULT_VOICES.values()
            if default.provider in ("chatterbox", "chatterbox_turbo")
        }
        if resolved in bundled_paths:
            return

        try:
            if resolved.exists() and resolved.is_file():
                resolved.unlink()
                log.debug("Deleted chatterbox voice file", path=str(resolved))
        except Exception as e:
            log.error(
                "Failed to delete chatterbox voice file", error=e, path=str(resolved)
            )

    def _chatterbox_generate_sync(
        self,
        variant: ChatterboxVariant,
        device,
        text,
        voice_path,
        parameters,
        cancelled: threading.Event,
    ) -> bytes | None:
        # A cancelled asyncio task cannot stop its worker. Keep the lock and
        # temporary output owned by the worker until synthesis actually finishes.
        with self._chatterbox_lock:
            if cancelled.is_set():
                return None
            if variant == "chatterbox_turbo":
                parameters = TurboParameters.model_validate(parameters).model_dump()
                validate_turbo_reference(voice_path)
            cached = getattr(self, "chatterbox_instance", None)
            if cached is None or (cached.variant, cached.device) != (variant, device):
                self.chatterbox_instance = None
                del cached
                gc.collect()
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self.chatterbox_instance = ChatterboxInstance(
                    model=_load_chatterbox_model(variant, device),
                    device=device,
                    variant=variant,
                )
            model = self.chatterbox_instance.model
            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, "speech.wav")
                wav = model.generate(
                    text=text, audio_prompt_path=voice_path, **parameters
                )
                import torchaudio

                torchaudio.save(file_path, wav, model.sr)
                with open(file_path, "rb") as audio_file:
                    return audio_file.read()

    async def _chatterbox_generate(
        self, variant: ChatterboxVariant, chunk: Chunk
    ) -> bytes | None:
        if not hasattr(self, "_chatterbox_lock"):
            self._chatterbox_lock = threading.Lock()
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(
                self._chatterbox_generate_sync,
                variant,
                self.actions[variant].config["device"].value,
                chunk.cleaned_text,
                chunk.voice.provider_id,
                dict(chunk.voice.parameters),
                cancelled,
            )
        except asyncio.CancelledError:
            cancelled.set()
            raise
        except Exception as exc:
            emit("status", message=f"{variant}: {exc}", status="error")
            raise

    async def chatterbox_generate(
        self, chunk: Chunk, context: GenerationContext
    ) -> bytes | None:
        return await self._chatterbox_generate("chatterbox", chunk)

    async def chatterbox_turbo_generate(
        self, chunk: Chunk, context: GenerationContext
    ) -> bytes | None:
        return await self._chatterbox_generate("chatterbox_turbo", chunk)

    @property
    def chatterbox_turbo_configured(self) -> bool:
        return True

    @property
    def chatterbox_turbo_max_generation_length(self) -> int:
        return 512

    @property
    def chatterbox_turbo_chunk_size(self) -> int:
        return self.actions["chatterbox_turbo"].config["chunk_size"].value

    @property
    def chatterbox_turbo_info(self) -> str:
        return CHATTERBOX_TURBO_INFO

    @property
    def chatterbox_turbo_agent_details(self) -> dict:
        device = self.actions["chatterbox_turbo"].config["device"].value
        return {
            "chatterbox_turbo_device": AgentDetail(
                icon="mdi-memory",
                value=f"Chatterbox Turbo: {device}",
                description="The device to use for Chatterbox Turbo",
            ).model_dump()
        }

    def chatterbox_turbo_supports_audio_tags(self, model: str | None = None) -> bool:
        return True

    def chatterbox_turbo_supported_audio_tags(
        self, model: str | None = None
    ) -> tuple[str, ...]:
        return TURBO_AUDIO_TAGS

    def chatterbox_turbo_delete_voice(self, voice: Voice):
        self.chatterbox_delete_voice(voice)

    async def chatterbox_prepare_chunk(self, chunk: Chunk):
        voice = chunk.voice
        P = provider(voice.provider)
        exaggeration = P.voice_parameter(voice, "exaggeration")

        voice.parameters["exaggeration"] = exaggeration
