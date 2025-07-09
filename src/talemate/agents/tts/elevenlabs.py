import io
from typing import Union

import httpx
import structlog

from talemate.agents.base import AgentAction
from .schema import Voice, VoiceLibrary

log = structlog.get_logger("talemate.agents.tts.elevenlabs")


class ElevenLabsMixin:
    """
    ElevenLabs TTS agent mixin for cloud-based text to speech.
    """
    
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_config"].config["api"].choices.append(
            {"value": "elevenlabs", "label": "Eleven Labs"}
        )
        return actions
    
    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        voices["elevenlabs"] = VoiceLibrary(api="elevenlabs")
    
    @property
    def elevenlabs_max_generation_length(self) -> int:
        return 1024
    
    async def elevenlabs_generate(
        self, text: str, chunk_size: int = 1024
    ) -> Union[bytes, None]:
        api_key = self.token
        if not api_key:
            return

        async with httpx.AsyncClient() as client:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": api_key,
            }
            data = {
                "text": text,
                "model_id": self.config.get("elevenlabs", {}).get("model"),
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.5},
            }

            response = await client.post(url, json=data, headers=headers, timeout=300)

            if response.status_code == 200:
                bytes_io = io.BytesIO()
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    if chunk:
                        bytes_io.write(chunk)

                # Put the audio data in the queue for playback
                return bytes_io.getvalue()
            else:
                log.error(f"Error generating audio: {response.text}")

    async def elevenlabs_list_voices(self) -> list[Voice]:
        url_voices = "https://api.elevenlabs.io/v1/voices"

        voices = []

        async with httpx.AsyncClient() as client:
            headers = {
                "Accept": "application/json",
                "xi-api-key": self.token,
            }
            response = await client.get(
                url_voices, headers=headers, params={"per_page": 1000}
            )
            speakers = response.json()["voices"]
            voices.extend(
                [
                    Voice(value=speaker["voice_id"], label=speaker["name"])
                    for speaker in speakers
                ]
            )

        # sort by name
        voices.sort(key=lambda x: x.label)

        return voices 