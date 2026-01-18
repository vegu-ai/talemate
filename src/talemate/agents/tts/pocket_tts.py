import asyncio
import functools
import io
from pathlib import Path

import numpy as np
import pydantic
import structlog
import torch
from pydantic import ConfigDict
from talemate.agents.base import AgentAction, AgentActionConfig, AgentDetail
from talemate.ux.schema import Field

from .providers import register, provider
from .schema import Chunk, GenerationContext, INFO_CHUNK_SIZE, Voice, VoiceProvider
from .util import voice_is_talemate_asset
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.pocket_tts")


def _import_heavy_deps():
    global sf, TTSModel
    import soundfile as sf
    from pocket_tts import TTSModel


POCKET_TTS_INFO = """
Pocket TTS is a local CPU text-to-speech model from Kyutai.

The voice id is an audio prompt used for voice cloning. It can be:
- a local *.wav* file path (relative to the Talemate workspace or absolute), or
- a HuggingFace `hf://...` URL (see Kyutai's voice catalog).

The first generation will download model weights if they are not cached yet.

Talemate includes a few example prompt WAV files in `tts/voice/pocket_tts/` (copied from the Chatterbox samples) so you can try Pocket TTS without needing to download prompt audio files.

If the **voice cloning** model download is blocked by Hugging Face, you need to:
1. Log in to Hugging Face and accept the model terms on the Pocket TTS model page.
2. Create a Hugging Face token.
3. Set it in your environment as `HF_TOKEN`.
4. Restart Talemate and try again.

Commands / links:
- Accept terms: https://huggingface.co/kyutai/pocket-tts
- Create token: https://huggingface.co/settings/tokens
- Login locally: `uvx hf auth login`
"""


add_default_voices(
    [
        Voice(
            label="Eva",
            provider="pocket_tts",
            provider_id="tts/voice/pocket_tts/eva.wav",
            tags=["female", "calm", "mature", "thoughtful"],
        ),
        Voice(
            label="Lisa",
            provider="pocket_tts",
            provider_id="tts/voice/pocket_tts/lisa.wav",
            tags=["female", "energetic", "young"],
        ),
        Voice(
            label="Adam",
            provider="pocket_tts",
            provider_id="tts/voice/pocket_tts/adam.wav",
            tags=["male", "calm", "mature", "thoughtful", "deep"],
        ),
        Voice(
            label="Bradford",
            provider="pocket_tts",
            provider_id="tts/voice/pocket_tts/bradford.wav",
            tags=["male", "calm", "mature", "thoughtful", "deep"],
        ),
        Voice(
            label="Julia",
            provider="pocket_tts",
            provider_id="tts/voice/pocket_tts/julia.wav",
            tags=["female", "calm", "mature"],
        ),
        Voice(
            label="Zoe",
            provider="pocket_tts",
            provider_id="tts/voice/pocket_tts/zoe.wav",
            tags=["female"],
        ),
        Voice(
            label="William",
            provider="pocket_tts",
            provider_id="tts/voice/pocket_tts/william.wav",
            tags=["male", "young"],
        ),
    ]
)


@register()
class PocketTTSProvider(VoiceProvider):
    name: str = "pocket_tts"
    allow_model_override: bool = False
    allow_file_upload: bool = True
    upload_file_types: list[str] = ["audio/wav"]
    voice_parameters: list[Field] = [
        Field(
            name="truncate_prompt",
            type="bool",
            label="Truncate prompt audio",
            value=False,
            description="Whether to truncate the voice prompt audio when extracting the voice state.",
        )
    ]


class PocketTTSInstance(pydantic.BaseModel):
    model: "TTSModel"
    model_variant: str
    temp: float
    lsd_decode_steps: int
    noise_clamp: float | None
    eos_threshold: float
    voice_states: dict[str, dict] = pydantic.Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PocketTTSMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["apis"].choices.append(
            {
                "value": "pocket_tts",
                "label": "Pocket TTS (Local)",
                "help": "Pocket TTS is a local CPU text-to-speech model.",
            }
        )

        actions["pocket_tts"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="Pocket TTS",
            description="Pocket TTS is a local CPU text-to-speech model (voice cloning via audio prompt).",
            config={
                "variant": AgentActionConfig(
                    type="text",
                    value="b6369a24",
                    label="Variant",
                    description="Pocket TTS model variant identifier (downloads weights on first use).",
                ),
                "temp": AgentActionConfig(
                    type="number",
                    value=0.7,
                    min=0.0,
                    max=2.0,
                    step=0.05,
                    label="Temperature",
                    description="Sampling temperature. Higher values can sound more varied but less stable.",
                ),
                "lsd_decode_steps": AgentActionConfig(
                    type="number",
                    value=1,
                    min=1,
                    max=10,
                    step=1,
                    label="LSD decode steps",
                    description="Number of decoding steps. Higher can improve quality but is slower.",
                ),
                "noise_clamp": AgentActionConfig(
                    type="number",
                    value=0.0,
                    min=0.0,
                    max=10.0,
                    step=0.1,
                    label="Noise clamp",
                    description="0 = disabled. If >0, clamps noise sampling to this maximum.",
                ),
                "eos_threshold": AgentActionConfig(
                    type="number",
                    value=-4.0,
                    min=-20.0,
                    max=0.0,
                    step=0.1,
                    label="EOS threshold",
                    description="End-of-sequence detection threshold.",
                ),
                "frames_after_eos": AgentActionConfig(
                    type="number",
                    value=0,
                    min=0,
                    max=10,
                    step=1,
                    label="Frames after EOS",
                    description="0 = auto. If >0, generates additional frames after EOS detection.",
                ),
                "chunk_size": AgentActionConfig(
                    type="number",
                    min=0,
                    step=64,
                    max=4096,
                    value=256,
                    label="Chunk size",
                    note=INFO_CHUNK_SIZE,
                ),
            },
        )

        return actions

    @property
    def pocket_tts_chunk_size(self) -> int:
        return self.actions["pocket_tts"].config["chunk_size"].value

    @property
    def pocket_tts_max_generation_length(self) -> int:
        return 512

    @property
    def pocket_tts_variant(self) -> str:
        return self.actions["pocket_tts"].config["variant"].value

    @property
    def pocket_tts_temp(self) -> float:
        return float(self.actions["pocket_tts"].config["temp"].value)

    @property
    def pocket_tts_lsd_decode_steps(self) -> int:
        return int(self.actions["pocket_tts"].config["lsd_decode_steps"].value)

    @property
    def pocket_tts_noise_clamp(self) -> float | None:
        value = float(self.actions["pocket_tts"].config["noise_clamp"].value)
        return None if value <= 0 else value

    @property
    def pocket_tts_eos_threshold(self) -> float:
        return float(self.actions["pocket_tts"].config["eos_threshold"].value)

    @property
    def pocket_tts_frames_after_eos(self) -> int | None:
        value = int(self.actions["pocket_tts"].config["frames_after_eos"].value)
        return None if value <= 0 else value

    @property
    def pocket_tts_configured(self) -> bool:
        try:
            _import_heavy_deps()
        except Exception:
            return False
        return True

    @property
    def pocket_tts_info(self) -> str:
        return POCKET_TTS_INFO

    @property
    def pocket_tts_not_configured_reason(self) -> str | None:
        if not self.pocket_tts_configured:
            return "Pocket TTS is not available (missing dependency)."
        return None

    @property
    def pocket_tts_agent_details(self) -> dict:
        details: dict = {}

        instance: PocketTTSInstance | None = getattr(self, "pocket_tts_instance", None)
        if instance is None:
            return details

        details["pocket_tts_model"] = AgentDetail(
            icon="mdi-brain",
            value=f"{instance.model_variant}@{instance.model.device}",
            description="Loaded Pocket TTS model and device",
        ).model_dump()

        details["pocket_tts_voice_cache"] = AgentDetail(
            icon="mdi-account-voice",
            value=str(len(instance.voice_states)),
            description="Cached Pocket TTS voice states",
        ).model_dump()

        return details

    def pocket_tts_delete_voice(self, voice: Voice):
        is_talemate_asset, resolved = voice_is_talemate_asset(
            voice, provider(voice.provider)
        )
        if not is_talemate_asset or resolved is None:
            return
        try:
            if resolved.exists() and resolved.is_file():
                resolved.unlink()
                log.debug("Deleted Pocket TTS voice prompt", path=str(resolved))
        except Exception as e:
            log.error(
                "Failed to delete Pocket TTS voice prompt", error=e, path=str(resolved)
            )

    def _pocket_tts_voice_prompt_key(self, voice: Voice) -> str:
        truncate = bool(
            provider(voice.provider).voice_parameter(voice, "truncate_prompt")
        )
        return f"{voice.provider_id}::truncate={int(truncate)}"

    def _pocket_tts_generate_wav_bytes(self, chunk: Chunk) -> bytes:
        _import_heavy_deps()

        if not chunk.voice:
            raise ValueError("Pocket TTS requires a voice prompt (voice.provider_id).")

        voice = chunk.voice
        P = provider(voice.provider)

        truncate_prompt = bool(P.voice_parameter(voice, "truncate_prompt"))
        voice_key = self._pocket_tts_voice_prompt_key(voice)

        instance: PocketTTSInstance | None = getattr(self, "pocket_tts_instance", None)

        reload_model = (
            instance is None
            or instance.model_variant != self.pocket_tts_variant
            or instance.temp != self.pocket_tts_temp
            or instance.lsd_decode_steps != self.pocket_tts_lsd_decode_steps
            or instance.noise_clamp != self.pocket_tts_noise_clamp
            or instance.eos_threshold != self.pocket_tts_eos_threshold
        )

        if reload_model:
            log.debug(
                "Loading Pocket TTS model",
                variant=self.pocket_tts_variant,
                temp=self.pocket_tts_temp,
                lsd_decode_steps=self.pocket_tts_lsd_decode_steps,
                noise_clamp=self.pocket_tts_noise_clamp,
                eos_threshold=self.pocket_tts_eos_threshold,
            )
            model = TTSModel.load_model(
                variant=self.pocket_tts_variant,
                temp=self.pocket_tts_temp,
                lsd_decode_steps=self.pocket_tts_lsd_decode_steps,
                noise_clamp=self.pocket_tts_noise_clamp,
                eos_threshold=self.pocket_tts_eos_threshold,
            )
            instance = PocketTTSInstance(
                model=model,
                model_variant=self.pocket_tts_variant,
                temp=self.pocket_tts_temp,
                lsd_decode_steps=self.pocket_tts_lsd_decode_steps,
                noise_clamp=self.pocket_tts_noise_clamp,
                eos_threshold=self.pocket_tts_eos_threshold,
            )
            self.pocket_tts_instance = instance

        model = instance.model

        # Resolve prompt path / URL
        prompt = voice.provider_id
        if not (
            prompt.startswith("hf://")
            or prompt.startswith("http://")
            or prompt.startswith("https://")
        ):
            # If it's a local relative path, resolve relative to TALEMATE_ROOT via standard logic
            # (voice_is_talemate_asset only works when provider allows upload).
            try:
                from talemate.path import TALEMATE_ROOT

                p = Path(prompt)
                if not p.is_absolute():
                    p = (TALEMATE_ROOT / p).resolve(strict=False)
                prompt = str(p)
            except Exception:
                prompt = voice.provider_id

        # Cache voice state (voice cloning embedding)
        voice_state = instance.voice_states.get(voice_key)
        if voice_state is None:
            log.debug(
                "Pocket TTS - computing voice state",
                prompt=prompt,
                truncate=truncate_prompt,
            )
            voice_state = model.get_state_for_audio_prompt(
                prompt, truncate=truncate_prompt
            )
            instance.voice_states[voice_key] = voice_state

        audio = model.generate_audio(
            voice_state,
            chunk.cleaned_text,
            frames_after_eos=self.pocket_tts_frames_after_eos,
            copy_state=True,
        )

        # Normalize shape and convert to PCM16 WAV bytes
        if isinstance(audio, torch.Tensor):
            if audio.ndim > 1:
                audio = audio.reshape(-1)
            audio = audio.detach().to(device="cpu", dtype=torch.float32)
            audio = torch.clamp(audio, -1.0, 1.0)
            audio_np: np.ndarray = (audio.numpy() * 32767.0).astype(np.int16)
        else:
            raise TypeError(f"Unexpected Pocket TTS audio type: {type(audio)}")

        with io.BytesIO() as bio:
            sf.write(
                bio,
                audio_np,
                model.sample_rate,
                format="WAV",
                subtype="PCM_16",
            )
            return bio.getvalue()

    async def pocket_tts_generate(
        self, chunk: Chunk, context: GenerationContext
    ) -> bytes | None:
        if not self.pocket_tts_configured:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, functools.partial(self._pocket_tts_generate_wav_bytes, chunk)
        )
