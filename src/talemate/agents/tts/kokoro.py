import os
import functools
import tempfile
import uuid
import asyncio
import structlog
import pydantic
import traceback
from pathlib import Path


# Lazy imports for heavy dependencies
def _import_heavy_deps():
    global torch, sf, KPipeline
    import torch
    import soundfile as sf
    from kokoro import KPipeline


from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
)
from .schema import (
    Voice,
    Chunk,
    GenerationContext,
    VoiceMixer,
    VoiceProvider,
    INFO_CHUNK_SIZE,
)
from .providers import register
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.kokoro")

CUSTOM_VOICE_STORAGE = (
    Path(__file__).parent.parent.parent.parent.parent / "tts" / "voice" / "kokoro"
)

add_default_voices(
    [
        Voice(
            label="Alloy", provider="kokoro", provider_id="af_alloy", tags=["female"]
        ),
        Voice(
            label="Aoede", provider="kokoro", provider_id="af_aoede", tags=["female"]
        ),
        Voice(
            label="Bella", provider="kokoro", provider_id="af_bella", tags=["female"]
        ),
        Voice(
            label="Heart", provider="kokoro", provider_id="af_heart", tags=["female"]
        ),
        Voice(
            label="Jessica",
            provider="kokoro",
            provider_id="af_jessica",
            tags=["female"],
        ),
        Voice(label="Kore", provider="kokoro", provider_id="af_kore", tags=["female"]),
        Voice(
            label="Nicole", provider="kokoro", provider_id="af_nicole", tags=["female"]
        ),
        Voice(label="Nova", provider="kokoro", provider_id="af_nova", tags=["female"]),
        Voice(
            label="River", provider="kokoro", provider_id="af_river", tags=["female"]
        ),
        Voice(
            label="Sarah", provider="kokoro", provider_id="af_sarah", tags=["female"]
        ),
        Voice(label="Sky", provider="kokoro", provider_id="af_sky", tags=["female"]),
        Voice(label="Adam", provider="kokoro", provider_id="am_adam", tags=["male"]),
        Voice(label="Echo", provider="kokoro", provider_id="am_echo", tags=["male"]),
        Voice(label="Eric", provider="kokoro", provider_id="am_eric", tags=["male"]),
        Voice(
            label="Fenrir", provider="kokoro", provider_id="am_fenrir", tags=["male"]
        ),
        Voice(label="Liam", provider="kokoro", provider_id="am_liam", tags=["male"]),
        Voice(
            label="Michael", provider="kokoro", provider_id="am_michael", tags=["male"]
        ),
        Voice(label="Onyx", provider="kokoro", provider_id="am_onyx", tags=["male"]),
        Voice(label="Puck", provider="kokoro", provider_id="am_puck", tags=["male"]),
        Voice(label="Santa", provider="kokoro", provider_id="am_santa", tags=["male"]),
        Voice(
            label="Alice", provider="kokoro", provider_id="bf_alice", tags=["female"]
        ),
        Voice(label="Emma", provider="kokoro", provider_id="bf_emma", tags=["female"]),
        Voice(
            label="Isabella",
            provider="kokoro",
            provider_id="bf_isabella",
            tags=["female"],
        ),
        Voice(label="Lily", provider="kokoro", provider_id="bf_lily", tags=["female"]),
        Voice(
            label="Daniel", provider="kokoro", provider_id="bm_daniel", tags=["male"]
        ),
        Voice(label="Fable", provider="kokoro", provider_id="bm_fable", tags=["male"]),
        Voice(
            label="George", provider="kokoro", provider_id="bm_george", tags=["male"]
        ),
        Voice(label="Lewis", provider="kokoro", provider_id="bm_lewis", tags=["male"]),
    ]
)

KOKORO_INFO = """
Kokoro is a local text to speech model.

**WILL DOWNLOAD**: Voices will be downloaded on first use, so the first generation will take longer to complete.
"""


@register()
class KokoroProvider(VoiceProvider):
    name: str = "kokoro"
    allow_model_override: bool = False


class KokoroInstance(pydantic.BaseModel):
    pipeline: "KPipeline"  # Forward reference for lazy loading

    class Config:
        arbitrary_types_allowed = True


class KokoroMixin:
    """
    Kokoro agent mixin for local text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["apis"].choices.append(
            {
                "value": "kokoro",
                "label": "Kokoro (Local)",
                "help": "Kokoro is a local text to speech model.",
            }
        )

        actions["kokoro"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="Kokoro",
            description="Kokoro is a local text to speech model.",
            config={
                "chunk_size": AgentActionConfig(
                    type="number",
                    min=0,
                    step=64,
                    max=2048,
                    value=512,
                    label="Chunk size",
                    note=INFO_CHUNK_SIZE,
                ),
            },
        )
        return actions

    @property
    def kokoro_configured(self) -> bool:
        return True

    @property
    def kokoro_chunk_size(self) -> int:
        return self.actions["kokoro"].config["chunk_size"].value

    @property
    def kokoro_max_generation_length(self) -> int:
        return 256

    @property
    def kokoro_agent_details(self) -> dict:
        return {}

    @property
    def kokoro_supports_mixing(self) -> bool:
        return True

    @property
    def kokoro_info(self) -> str:
        return KOKORO_INFO

    def kokoro_delete_voice(self, voice_id: str) -> None:
        """
        If the voice_id is a file in the CUSTOM_VOICE_STORAGE directory, delete it.
        """

        # if voice id is a deletable file it'll be a relative or absolute path
        # to a file in the CUSTOM_VOICE_STORAGE directory

        # we must verify that it is in the CUSTOM_VOICE_STORAGE directory
        voice_path = Path(voice_id).resolve()
        log.debug(
            "Kokoro - Checking if voice id is deletable",
            voice_id=voice_id,
            exists=voice_path.exists(),
            parent=voice_path.parent,
            is_custom_voice_storage=voice_path.parent == CUSTOM_VOICE_STORAGE,
        )
        if voice_path.exists() and voice_path.parent == CUSTOM_VOICE_STORAGE:
            log.debug("Kokoro - Deleting voice file", voice_id=voice_id)
            try:
                voice_path.unlink()
            except FileNotFoundError:
                pass

    def _kokoro_mix(self, mixer: VoiceMixer) -> "torch.Tensor":
        pipeline = KPipeline(lang_code="a")

        packs = [
            {
                "voice_tensor": pipeline.load_single_voice(voice.id),
                "weight": voice.weight,
            }
            for voice in mixer.voices
        ]

        mixed_voice = None
        for pack in packs:
            if mixed_voice is None:
                mixed_voice = pack["voice_tensor"] * pack["weight"]
            else:
                mixed_voice += pack["voice_tensor"] * pack["weight"]

        # TODO: ensure weights sum to 1

        return mixed_voice

    async def kokoro_test_mix(self, mixer: VoiceMixer):
        """Test a mixed voice by generating a sample."""
        mixed_voice_tensor = self._kokoro_mix(mixer)

        loop = asyncio.get_event_loop()

        pipeline = KPipeline(lang_code="a")

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")

            await loop.run_in_executor(
                None,
                functools.partial(
                    self._kokoro_generate,
                    pipeline,
                    "This is a test of the mixed voice.",
                    mixed_voice_tensor,
                    file_path,
                ),
            )

            # Read and play the audio
            with open(file_path, "rb") as f:
                audio_data = f.read()
                self.play_audio(audio_data)

    async def kokoro_save_mix(self, voice_id: str, mixer: VoiceMixer) -> Path:
        """Save a voice tensor to disk."""
        # Ensure the directory exists
        CUSTOM_VOICE_STORAGE.mkdir(parents=True, exist_ok=True)

        save_to_path = CUSTOM_VOICE_STORAGE / f"{voice_id}.pt"
        voice_tensor = self._kokoro_mix(mixer)
        torch.save(voice_tensor, save_to_path)
        return save_to_path

    def _kokoro_generate(
        self,
        pipeline: "KPipeline",
        text: str,
        voice: "str | torch.Tensor",
        file_path: str,
    ) -> None:
        """Generate audio from text using the given voice."""
        try:
            generator = pipeline(text, voice=voice)
            for i, (gs, ps, audio) in enumerate(generator):
                sf.write(file_path, audio, 24000)
        except Exception as e:
            traceback.print_exc()
            raise e

    async def kokoro_generate(
        self, chunk: Chunk, context: GenerationContext
    ) -> bytes | None:
        kokoro_instance = getattr(self, "kokoro_instance", None)

        reload: bool = False

        if not kokoro_instance:
            reload = True

        if reload:
            log.debug(
                "kokoro - reinitializing tts instance",
            )
            # Lazy import heavy dependencies only when needed
            _import_heavy_deps()

            self.kokoro_instance = KokoroInstance(
                # a= American English
                # TODO: allow config of language???
                pipeline=KPipeline(lang_code="a")
            )

        pipeline = self.kokoro_instance.pipeline

        loop = asyncio.get_event_loop()

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")

            await loop.run_in_executor(
                None,
                functools.partial(
                    self._kokoro_generate,
                    pipeline,
                    chunk.cleaned_text,
                    chunk.voice.provider_id,
                    file_path,
                ),
            )

            with open(file_path, "rb") as f:
                return f.read()
