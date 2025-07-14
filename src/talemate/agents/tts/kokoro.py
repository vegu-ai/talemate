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
            label="AF Heart",
            provider="kokoro",
            provider_id="af_heart",
            tags=["female"],
        ),
    ]
)


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
