import os
import functools
import tempfile
import uuid
import asyncio
import structlog
import pydantic
import traceback
import soundfile as sf
from kokoro import KPipeline

from talemate.agents.base import (
    AgentAction,
)

from .schema import Voice, Chunk, GenerationContext
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.kokoro")

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

A list of available voices can be found at [https://kokorotts.net/models/Kokoro/text-to-speech](https://kokorotts.net/models/Kokoro/text-to-speech).

**WILL DOWNLOAD**: Voices will be downloaded on first use, so the first generation will take longer to complete.
"""


class KokoroInstance(pydantic.BaseModel):
    pipeline: KPipeline

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

        return actions

    @property
    def kokoro_configured(self) -> bool:
        return True

    @property
    def kokoro_max_generation_length(self) -> int:
        return 1024

    @property
    def kokoro_agent_details(self) -> dict:
        return {}

    @property
    def kokoro_supports_mixing(self) -> bool:
        return True

    @property
    def kokoro_info(self) -> str:
        return KOKORO_INFO

    def _kokoro_generate(
        self, pipeline: KPipeline, chunk: Chunk, file_path: str
    ) -> bytes:
        try:
            generator = pipeline(chunk.cleaned_text, voice=chunk.voice.provider_id)
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
                    chunk,
                    file_path,
                ),
            )

            with open(file_path, "rb") as f:
                return f.read()
