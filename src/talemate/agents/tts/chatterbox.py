import os
import functools
import tempfile
import uuid
import asyncio
import structlog
import torchaudio as ta
from chatterbox.tts import ChatterboxTTS
import pydantic
import torch

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentDetail,
)
from talemate.ux.schema import Field

from .schema import Voice, Chunk, GenerationContext, VoiceProvider
from .voice_library import add_default_voices
from .providers import register

log = structlog.get_logger("talemate.agents.tts.chatterbox")

add_default_voices(
    [
        Voice(
            label="Eva",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/eva.wav",
            tags=["female","calm","mature","thoughtful"],
            parameters={
                "exaggeration": 0.65,
                "cfg_weight": 0.6,
                "temperature": 1.0,
            },
        ),
        Voice(
            label="Lisa",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/lisa.wav",
            tags=["female","energetic","young"],
        ),
        Voice(
            label="Adam",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/adam.wav",
            tags=["male","calm","mature","thoughtful","deep"],
        ),
        Voice(
            label="Bradford",
            provider="chatterbox",
            provider_id="tts/voice/chatterbox/bradford.wav",
            tags=["male","calm","mature","thoughtful","deep"],
        ),
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

CUDA_AVAILABLE = torch.cuda.is_available()


@register()
class ChatterboxProvider(VoiceProvider):
    name: str = "chatterbox"
    allow_model_override: bool = False
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


class ChatterboxInstance(pydantic.BaseModel):
    model: ChatterboxTTS
    device: str

    class Config:
        arbitrary_types_allowed = True


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
                    value="cuda" if CUDA_AVAILABLE else "cpu",
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
    def chatterbox_configured(self) -> bool:
        return True

    @property
    def chatterbox_max_generation_length(self) -> int:
        return 250

    @property
    def chatterbox_device(self) -> str:
        return self.actions["chatterbox"].config["device"].value

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

    def _chatterbox_generate_file(
        self,
        model: ChatterboxTTS,
        text: str,
        audio_prompt_path: str,
        output_path: str,
        **kwargs,
    ):
        wav = model.generate(text=text, audio_prompt_path=audio_prompt_path, **kwargs)
        ta.save(output_path, wav, model.sr)
        return output_path

    async def chatterbox_generate(
        self, chunk: Chunk, context: GenerationContext
    ) -> bytes | None:
        log.debug("chatterbox", device=self.chatterbox_device, voice=chunk.voice)

        chatterbox_instance: ChatterboxInstance | None = getattr(
            self, "chatterbox_instance", None
        )

        reload: bool = False

        if not chatterbox_instance:
            reload = True
        elif chatterbox_instance.device != self.chatterbox_device:
            reload = True

        if reload:
            log.debug(
                "chatterbox - reinitializing tts instance",
                device=self.chatterbox_device,
            )
            self.chatterbox_instance = ChatterboxInstance(
                model=ChatterboxTTS.from_pretrained(device=self.chatterbox_device),
                device=self.chatterbox_device,
            )

        model: ChatterboxTTS = self.chatterbox_instance.model

        loop = asyncio.get_event_loop()

        voice = chunk.voice

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")

            await loop.run_in_executor(
                None,
                functools.partial(
                    self._chatterbox_generate_file,
                    model=model,
                    text=chunk.cleaned_text,
                    audio_prompt_path=voice.provider_id,
                    output_path=file_path,
                    **voice.parameters,
                ),
            )

            with open(file_path, "rb") as f:
                return f.read()


    async def chatterbox_prepare_chunk(self, chunk: Chunk):
        
        voice = chunk.voice
        
        if chunk.intensity == 1:
            voice.parameters["exaggeration"] -= 0.25
        elif chunk.intensity == 3:
            voice.parameters["exaggeration"] += 0.25
        elif chunk.intensity == 4:
            voice.parameters["exaggeration"] += 0.5