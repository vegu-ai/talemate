import os
import functools
import tempfile
import uuid
import asyncio
import structlog
from TTS.api import TTS

from talemate.agents.base import AgentAction

from .schema import Voice, VoiceLibrary

log = structlog.get_logger("talemate.agents.tts.xtts2")

class XTTS2Mixin:
    """
    XTTS2 agent mixin for local text to speech.
    """
    
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["api"].choices.append(
            {"value": "xtts2", "label": "XTTS2 (Local)"}
        )
        return actions
    
    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["xtts2"] = VoiceLibrary(api="xtts2")
    
    @property
    def xtts2_max_generation_length(self) -> int:
        return 250
    
    async def xtts2_generate(self, text: str) -> bytes | None:
        tts_config = self.config.get("tts", {})
        model = tts_config.get("model")
        device = tts_config.get("device", "cpu")

        log.debug("xtts2", model=model, device=device)

        if not hasattr(self, "tts_instance"):
            self.tts_instance = TTS(model).to(device)

        tts = self.tts_instance

        loop = asyncio.get_event_loop()

        voice = self.voice(self.default_voice_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")

            await loop.run_in_executor(
                None,
                functools.partial(
                    tts.tts_to_file,
                    text=text,
                    speaker_wav=voice.value,
                    language="en",
                    file_path=file_path,
                ),
            )
            # tts.tts_to_file(text=text, speaker_wav=voice.value, language="en", file_path=file_path)

            with open(file_path, "rb") as f:
                return f.read()

    async def xtts2_list_voices(self) -> dict[str, str]:
        return [
            Voice(**voice) for voice in self.config.get("tts", {}).get("voices", [])
        ]
    
    
    
    