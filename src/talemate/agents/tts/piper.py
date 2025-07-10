import os
import functools
import tempfile
import uuid
import asyncio
import wave
import structlog
from piper import PiperVoice
from piper.download_voices import download_voice, _needs_download
from pathlib import Path
import pydantic

from talemate.ux.schema import Column

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentDetail,
)

from .schema import Voice, VoiceLibrary, Chunk, GenerationContext

log = structlog.get_logger("talemate.agents.tts.piper")

DEFAULT_DOWNLOAD_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / "templates" / "voice" / "piper"
)


class PiperInstance(pydantic.BaseModel):
    device: str
    piper_voice: PiperVoice | None = None
    voice_id: str | None = None

    class Config:
        arbitrary_types_allowed = True


class PiperMixin:
    """
    Piper agent mixin for local text to speech.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["api"].choices.append(
            {"value": "piper", "label": "Piper (Local)"}
        )

        actions["piper"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            condition=AgentActionConditional(
                attribute="_config.config.api", value="piper"
            ),
            label="Piper",
            config={
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
                "download_path": AgentActionConfig(
                    type="text",
                    value=str(DEFAULT_DOWNLOAD_PATH),
                    label="Download Path",
                    description="Path to download voices to. If not provided, voices will be downloaded to the default location.",
                ),
                "voices": AgentActionConfig(
                    type="table",
                    value=[
                        {"label": "Amy", "id": "en_US-amy-medium"},
                        {"label": "John", "id": "en_US-john-medium"},
                    ],
                    columns=[
                        Column(
                            name="label",
                            label="Label",
                            type="text",
                        ),
                        Column(
                            name="id",
                            label="ID",
                            type="text",
                        ),
                    ],
                    label="Voice Samples",
                    description="Voice models to use for Piper. IDs are always formatted as {language}-{voice_name}-{quality}. Each voice will need to be downloaded once before use. For a full list of voices see https://huggingface.co/rhasspy/piper-voices/tree/main/en",
                ),
            },
        )
        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["piper"] = VoiceLibrary(api="piper", local=True)

    @property
    def piper_max_generation_length(self) -> int:
        return 250

    @property
    def piper_device(self) -> str:
        return self.actions["piper"].config["device"].value

    @property
    def piper_download_path(self) -> Path:
        return Path(self.actions["piper"].config["download_path"].value)

    @property
    def piper_agent_details(self) -> dict:
        details: dict = {}

        if self.ready:
            details["device"] = AgentDetail(
                icon="mdi-memory",
                value=self.piper_device,
                description="The device to use for Piper",
            ).model_dump()

        return details

    async def piper_generate(
        self, chunk: Chunk, context: GenerationContext
    ) -> bytes | None:
        log.debug("piper", device=self.piper_device)

        piper_instance = getattr(self, "piper_instance", None)

        reload: bool = False

        if not piper_instance:
            reload = True
        elif piper_instance.device != self.piper_device:
            reload = True
        elif piper_instance.voice_id != chunk.voice_id:
            reload = True

        voice = self.voice(chunk.voice_id, api="piper")

        loop = asyncio.get_event_loop()

        if reload:
            log.debug(
                "piper - reinitializing instance",
                device=self.piper_device,
            )

            full_file_path = self.piper_download_path / f"{voice.value}.onnx"
            if _needs_download(full_file_path):
                log.info("piper - downloading voice", voice=voice.value)

                await loop.run_in_executor(
                    None,
                    functools.partial(
                        download_voice,
                        voice.value,
                        self.piper_download_path,
                    ),
                )

            self.piper_instance = PiperInstance(
                device=self.piper_device,
                piper_voice=PiperVoice.load(
                    full_file_path, use_cuda=self.piper_device == "cuda"
                ),
                voice_id=voice.value,
            )

        piper_voice = self.piper_instance.piper_voice

        with tempfile.TemporaryDirectory() as temp_dir:
            wav_outfile = os.path.join(temp_dir, f"piper-{uuid.uuid4()}.wav")

            with wave.open(wav_outfile, "wb") as wav_file:
                try:
                    await loop.run_in_executor(
                        None,
                        functools.partial(
                            piper_voice.synthesize_wav,
                            text=chunk.cleaned_text,
                            wav_file=wav_file,
                        ),
                    )
                except Exception as e:
                    import traceback

                    traceback.print_exc()
                    raise e

            with open(wav_outfile, "rb") as f:
                return f.read()

    async def piper_list_voices(self) -> list[Voice]:
        return [
            Voice(
                label=voice["label"],
                value=voice["id"],
            )
            for voice in self.actions["piper"].config["voices"].value
        ]
