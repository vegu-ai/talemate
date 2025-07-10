import os
import functools
import tempfile
import uuid
import asyncio
import structlog
from TTS.api import TTS
import pydantic

from talemate.ux.schema import Column

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentDetail,
)

from .schema import Voice, VoiceLibrary, Chunk, GenerationContext

log = structlog.get_logger("talemate.agents.tts.xtts2")


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
        actions["_config"].config["api"].choices.append(
            {"value": "xtts2", "label": "XTTS2 (Local)"}
        )

        actions["xtts2"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            condition=AgentActionConditional(
                attribute="_config.config.api", value="xtts2"
            ),
            label="XTTS2",
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
                "voices": AgentActionConfig(
                    type="table",
                    value=[
                        {
                            "label": "Annabelle",
                            "path": "templates/voice/xtts2/annabelle.wav",
                        },
                    ],
                    columns=[
                        Column(
                            name="label",
                            label="Label",
                            type="text",
                        ),
                        Column(
                            name="path",
                            label="Path (.wav)",
                            type="text",
                        ),
                    ],
                    label="Voice Samples",
                    description="Voice samples to use for XTTS2. The path can be relative to the talemate base directory and should point to a .wav file. For official xtts2 samples see https://huggingface.co/coqui/XTTS-v2/tree/main/samples.",
                ),
            },
        )
        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["xtts2"] = VoiceLibrary(api="xtts2")

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
        details: dict = {}

        if self.ready:
            details["device"] = AgentDetail(
                icon="mdi-memory",
                value=self.xtts2_device,
                description="The device to use for XTTS2",
            ).model_dump()

        return details

    async def xtts2_generate(self, chunk: Chunk, context: GenerationContext) -> bytes | None:
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

        voice = self.voice(chunk.voice_id, api="xtts2")

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")

            await loop.run_in_executor(
                None,
                functools.partial(
                    tts.tts_to_file,
                    text=chunk.cleaned_text,
                    speaker_wav=voice.value,
                    language="en",
                    file_path=file_path,
                ),
            )
            # tts.tts_to_file(text=text, speaker_wav=voice.value, language="en", file_path=file_path)

            with open(file_path, "rb") as f:
                return f.read()

    async def xtts2_list_voices(self) -> list[Voice]:
        return [
            Voice(
                label=voice["label"],
                value=voice["path"],
            )
            for voice in self.actions["xtts2"].config["voices"].value
        ]
