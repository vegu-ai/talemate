import os
import functools
import tempfile
import uuid
import asyncio
import structlog
from TTS.api import TTS
import pydantic

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentDetail,
)

from .schema import Voice, Chunk, GenerationContext
from .voice_library import add_default_voices

log = structlog.get_logger("talemate.agents.tts.xtts2")

add_default_voices(
    [
        Voice(
            label="Annabelle",
            provider="xtts2",
            provider_id="templates/voice/xtts2/annabelle.wav",
            tags=["female"],
        ),
    ]
)


class XTTS2Instance(pydantic.BaseModel):
    model: str
    device: str
    tts_instance: TTS | None = None

    class Config:
        arbitrary_types_allowed = True


class XTTS2Mixin:
    """
    XTTS2 agent mixin for local text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["apis"].choices.append(
            {
                "value": "xtts2",
                "label": "XTTS2 (Local)",
                "help": "XTTS2 is a local text to speech model that uses the TTS library.",
            }
        )

        actions["xtts2"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="XTTS2",
            description="XTTS2 is a local text to speech model that uses the TTS library where new voices are provided in the form of a small .wav sample. Find out more at https://github.com/coqui-ai/TTS.",
            config={
                "model": AgentActionConfig(
                    type="text",
                    value="tts_models/multilingual/multi-dataset/xtts_v2",
                    label="Model",
                    description="Model to use for TTS",
                ),
                "device": AgentActionConfig(
                    type="text",
                    value="cpu",
                    label="Device",
                    choices=[
                        {"value": "cpu", "label": "CPU"},
                        {"value": "cuda", "label": "CUDA"},
                    ],
                    description="Device to use for TTS",
                ),
            },
        )
        return actions

    @property
    def xtts2_configured(self) -> bool:
        return True

    @property
    def xtts2_max_generation_length(self) -> int:
        return 250

    @property
    def xtts2_model(self) -> str:
        return self.actions["xtts2"].config["model"].value

    @property
    def xtts2_device(self) -> str:
        return self.actions["xtts2"].config["device"].value

    @property
    def xtts2_agent_details(self) -> dict:
        if not self.xtts2_configured:
            return {}
        details = {}

        details["xtts2_device"] = AgentDetail(
            icon="mdi-memory",
            value=f"XTTS2: {self.xtts2_device}",
            description="The device to use for XTTS2",
        ).model_dump()

        return details

    async def xtts2_generate(
        self, chunk: Chunk, context: GenerationContext
    ) -> bytes | None:
        log.debug("xtts2", model=self.xtts2_model, device=self.xtts2_device)

        xtts2_instance = getattr(self, "xtts2_instance", None)

        reload: bool = False

        if not xtts2_instance:
            reload = True
        elif xtts2_instance.model != self.xtts2_model:
            reload = True
        elif xtts2_instance.device != self.xtts2_device:
            reload = True

        if reload:
            log.debug(
                "xtts2 - reinitializing tts instance",
                model=self.xtts2_model,
                device=self.xtts2_device,
            )
            self.xtts2_instance = XTTS2Instance(
                model=self.xtts2_model,
                device=self.xtts2_device,
                tts_instance=TTS(self.xtts2_model).to(self.xtts2_device),
            )

        tts = self.xtts2_instance.tts_instance

        loop = asyncio.get_event_loop()

        voice = chunk.voice

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")

            await loop.run_in_executor(
                None,
                functools.partial(
                    tts.tts_to_file,
                    text=chunk.cleaned_text,
                    speaker_wav=voice.provider_id,
                    language="en",
                    file_path=file_path,
                ),
            )
            # tts.tts_to_file(text=text, speaker_wav=voice.value, language="en", file_path=file_path)

            with open(file_path, "rb") as f:
                return f.read()
