from __future__ import annotations

from typing import Union
import asyncio
import httpx
import io
import os
import pydantic
import nltk
import tempfile
import base64
import uuid
import functools
from nltk.tokenize import sent_tokenize

import talemate.config as config
import talemate.emit.async_signals
from talemate.emit import emit
from talemate.events import GameLoopNewMessageEvent
from talemate.scene_message import CharacterMessage, NarratorMessage

from .base import Agent, set_processing, AgentAction, AgentActionConfig
from .registry import register

import structlog

import time

try:
    from TTS.api import TTS
except ImportError:
    TTS = None

log = structlog.get_logger("talemate.agents.tts")#

if not TTS:
    # TTS installation is massive and requires a lot of dependencies
    # so we don't want to require it unless the user wants to use it
    log.info("TTS (local) requires the TTS package, please install with `pip install TTS` if you want to use the local api")

nltk.download("punkt")

def parse_chunks(text):
    
    text = text.replace("...", "__ellipsis__")
    
    chunks = sent_tokenize(text)
    cleaned_chunks = []
    
    for chunk in chunks:
        chunk = chunk.replace("*","")
        if not chunk:
            continue
        cleaned_chunks.append(chunk)
    
    
    for i, chunk in enumerate(cleaned_chunks):
        chunk = chunk.replace("__ellipsis__", "...")
        cleaned_chunks[i] = chunk
    
    return cleaned_chunks

def rejoin_chunks(chunks:list[str], chunk_size:int=250):
    
    """
    Will combine chunks split by punctuation into a single chunk until
    max chunk size is reached
    """
    
    joined_chunks = []
    
    current_chunk = ""
    
    for chunk in chunks:
            
        if len(current_chunk) + len(chunk) > chunk_size:
            joined_chunks.append(current_chunk)
            current_chunk = ""
        
        current_chunk += chunk
        
    if current_chunk:
        joined_chunks.append(current_chunk)
        
    return joined_chunks


class Voice(pydantic.BaseModel):
    value:str
    label:str

class VoiceLibrary(pydantic.BaseModel):
    
    api: str
    voices: list[Voice] = pydantic.Field(default_factory=list)
    last_synced: float = None


@register()
class TTSAgent(Agent):
    
    """
    Text to speech agent
    """
    
    agent_type = "tts"
    verbose_name = "Text to speech"
    requires_llm_client = False
    
    @classmethod
    def config_options(cls, agent=None):
        config_options = super().config_options(agent=agent)
        
        if agent:
            config_options["actions"]["_config"]["config"]["voice_id"]["choices"] = [
                voice.model_dump() for voice in agent.list_voices_sync()
            ]
        
        return config_options

    def __init__(self, **kwargs):
        
        self.is_enabled = False
        
        self.voices = {
            "elevenlabs": VoiceLibrary(api="elevenlabs"),
            "coqui": VoiceLibrary(api="coqui"),
            "tts": VoiceLibrary(api="tts"),
        }
        self.config = config.load_config()
        self.playback_done_event = asyncio.Event()
        self.actions = {
            "_config": AgentAction(
                enabled=True, 
                label="Configure", 
                description="TTS agent configuration",
                config={
                    "api": AgentActionConfig(
                        type="text",
                        choices=[
                            # TODO at local TTS support
                            {"value": "tts", "label": "TTS (Local)"},
                            {"value": "elevenlabs", "label": "Eleven Labs"},
                            {"value": "coqui", "label": "Coqui Studio"},
                        ],
                        value="tts",
                        label="API",
                        description="Which TTS API to use",
                        onchange="emit",
                    ),
                    "voice_id": AgentActionConfig(
                        type="text",
                        value="default",
                        label="Narrator Voice",
                        description="Voice ID/Name to use for TTS",
                        choices=[]
                    ),
                    "generate_for_player": AgentActionConfig(
                        type="bool",
                        value=False,
                        label="Generate for player",
                        description="Generate audio for player messages",
                    ),
                    "generate_for_npc": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Generate for NPCs",
                        description="Generate audio for NPC messages",
                    ),
                    "generate_for_narration": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Generate for narration",
                        description="Generate audio for narration messages",
                    ),
                    "generate_chunks": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Split generation",
                        description="Generate audio chunks for each sentence - will be much more responsive but may loose context to inform inflection",
                    )
                }  
            ),
        }
        
        self.actions["_config"].model_dump()


    @property
    def enabled(self):
        return self.is_enabled
    
    @property
    def has_toggle(self):
        return True
        
    @property
    def experimental(self):
        return False
    
    @property
    def not_ready_reason(self) -> str:
        """
        Returns a string explaining why the agent is not ready
        """
        
        if self.ready:
            return ""
        
        if self.api == "tts":
            if not TTS:
                return "TTS not installed"
        
        elif self.requires_token and not self.token:
            return "No API token"
        
        elif not self.default_voice_id:
            return "No voice selected"
            
    @property
    def agent_details(self):
        suffix = ""
        
        if not self.ready:
            suffix = f"  - {self.not_ready_reason}"
        else:
            suffix = f"  - {self.voice_id_to_label(self.default_voice_id)}"
        
        api = self.api
        choices = self.actions["_config"].config["api"].choices
        api_label = api
        for choice in choices:
            if choice["value"] == api:
                api_label = choice["label"]
                break
        
        return f"{api_label}{suffix}"

    @property
    def api(self):
        return self.actions["_config"].config["api"].value
    
    @property
    def token(self):
        api = self.api
        return self.config.get(api,{}).get("api_key")
    
    @property
    def default_voice_id(self):
        return self.actions["_config"].config["voice_id"].value
    
    @property
    def requires_token(self):
        return self.api != "tts"
    
    @property
    def ready(self):
        
        if self.api == "tts":
            if not TTS:
                return False
            return True
        
        return (not self.requires_token or self.token) and self.default_voice_id

    @property
    def status(self):
        if not self.enabled:
            return "disabled"
        if self.ready:
            return "active" if not getattr(self, "processing", False) else "busy"
        if self.requires_token and not self.token:
            return "error"
        if self.api == "tts":
            if not TTS:
                return "error"
        return "uninitialized"

    @property
    def max_generation_length(self):
        if self.api == "elevenlabs":
            return 1024
        elif self.api == "coqui":
            return 250
            
        return 250

    def apply_config(self, *args, **kwargs):
        
        try:
            api = kwargs["actions"]["_config"]["config"]["api"]["value"]
        except KeyError:
            api = self.api
        
        api_changed = api != self.api
        
        log.debug("apply_config", api=api, api_changed=api != self.api, current_api=self.api)

        super().apply_config(*args, **kwargs)
        
        
        if api_changed:
            try:
                self.actions["_config"].config["voice_id"].value = self.voices[api].voices[0].value
            except IndexError:
                self.actions["_config"].config["voice_id"].value = ""

        
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop_new_message").connect(self.on_game_loop_new_message)
        
    async def on_game_loop_new_message(self, emission:GameLoopNewMessageEvent):
        """
        Called when a conversation is generated
        """
        
        if not self.enabled or not self.ready:
            return
        
        if not isinstance(emission.message, (CharacterMessage, NarratorMessage)):
            return
    
        if isinstance(emission.message, NarratorMessage) and not self.actions["_config"].config["generate_for_narration"].value:
            return
        
        if isinstance(emission.message, CharacterMessage):
            
            if emission.message.source == "player" and not self.actions["_config"].config["generate_for_player"].value:
                return
            elif emission.message.source == "ai" and not self.actions["_config"].config["generate_for_npc"].value:
                return
        
        if isinstance(emission.message, CharacterMessage):
            character_prefix = emission.message.split(":", 1)[0]
        else:
            character_prefix = ""
        
        log.info("reactive tts", message=emission.message, character_prefix=character_prefix)
        
        await self.generate(str(emission.message).replace(character_prefix+": ", ""))


    def voice(self, voice_id:str) -> Union[Voice, None]:
        for voice in self.voices[self.api].voices:
            if voice.value == voice_id:
                return voice
        return None
    
    def voice_id_to_label(self, voice_id:str):
        for voice in self.voices[self.api].voices:
            if voice.value == voice_id:
                return voice.label
        return None
    
    def list_voices_sync(self):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.list_voices())
    
    async def list_voices(self):
        if self.requires_token and not self.token:
            return []
        
        library = self.voices[self.api]
        
        log.info("Listing voices", api=self.api, last_synced=library.last_synced)
        
        # TODO: allow re-syncing voices
        if library.last_synced:
            return library.voices
        
        list_fn = getattr(self, f"_list_voices_{self.api}")
        log.info("Listing voices", api=self.api)
        library.voices = await list_fn()
        library.last_synced = time.time()
        
        # if the current voice cannot be found, reset it
        if not self.voice(self.default_voice_id):
            self.actions["_config"].config["voice_id"].value = ""
        
        # set loading to false
        return library.voices

    @set_processing
    async def generate(self, text: str):
        if not self.enabled or not self.ready or not text:
            return


        self.playback_done_event.set()
        
        generate_fn = getattr(self, f"_generate_{self.api}")
        
        if self.actions["_config"].config["generate_chunks"].value:
            chunks = parse_chunks(text)
            chunks = rejoin_chunks(chunks)
        else:
            chunks = parse_chunks(text)
            chunks = rejoin_chunks(chunks, chunk_size=self.max_generation_length)

        # Start generating audio chunks in the background
        generation_task = asyncio.create_task(self.generate_chunks(generate_fn, chunks))

        # Wait for both tasks to complete
        await asyncio.gather(generation_task)

    async def generate_chunks(self, generate_fn, chunks):
        for chunk in chunks:
            chunk = chunk.replace("*","").strip()
            log.info("Generating audio", api=self.api, chunk=chunk)
            audio_data = await generate_fn(chunk)
            self.play_audio(audio_data)

    def play_audio(self, audio_data):
        # play audio through the python audio player
        #play(audio_data)
        
        emit("audio_queue", data={"audio_data": base64.b64encode(audio_data).decode("utf-8")})
        
        self.playback_done_event.set()  # Signal that playback is finished

    # LOCAL
    
    async def _generate_tts(self, text: str) -> Union[bytes, None]:
        
        if not TTS:
            return
        
        tts_config = self.config.get("tts",{})
        model = tts_config.get("model")
        device = tts_config.get("device", "cpu")
        
        log.debug("tts local", model=model, device=device)
        
        if not hasattr(self, "tts_instance"):
            self.tts_instance = TTS(model).to(device)
        
        tts = self.tts_instance
        
        loop = asyncio.get_event_loop()
        
        voice = self.voice(self.default_voice_id)
        
        
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"tts-{uuid.uuid4()}.wav")
            
            await loop.run_in_executor(None, functools.partial(tts.tts_to_file, text=text, speaker_wav=voice.value, language="en", file_path=file_path))
            #tts.tts_to_file(text=text, speaker_wav=voice.value, language="en", file_path=file_path)
            
            
            with open(file_path, "rb") as f:
                return f.read()
        
            
    async def _list_voices_tts(self) -> dict[str, str]:
        return [Voice(**voice) for voice in self.config.get("tts",{}).get("voices",[])]
        
    # ELEVENLABS

    async def _generate_elevenlabs(self, text: str, chunk_size: int = 1024) -> Union[bytes, None]:
        api_key = self.token
        if not api_key:
            return

        async with httpx.AsyncClient() as client:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.default_voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": api_key,
            }
            data = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.5
                }
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

    async def _list_voices_elevenlabs(self) -> dict[str, str]:
        
        url_voices = "https://api.elevenlabs.io/v1/voices"
        
        voices = []
        
        async with httpx.AsyncClient() as client:
            headers = {
                "Accept": "application/json",
                "xi-api-key": self.token,
            }
            response = await client.get(url_voices, headers=headers, params={"per_page":1000})
            speakers = response.json()["voices"]
            voices.extend([Voice(value=speaker["voice_id"], label=speaker["name"]) for speaker in speakers])
            
        # sort by name
        voices.sort(key=lambda x: x.label)
            
        return voices    
            
    # COQUI STUDIO
                
    async def _generate_coqui(self, text: str) -> Union[bytes, None]:
        api_key = self.token
        if not api_key:
            return

        async with httpx.AsyncClient() as client:
            url = "https://app.coqui.ai/api/v2/samples/xtts/render/"
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            data = {
                "voice_id": self.default_voice_id,
                "text": text,
                "language": "en"  # Assuming English language for simplicity; this could be parameterized
            }

            # Make the POST request to Coqui API
            response = await client.post(url, json=data, headers=headers, timeout=300)
            if response.status_code in [200, 201]:
                # Parse the JSON response to get the audio URL
                response_data = response.json()
                audio_url = response_data.get('audio_url')
                if audio_url:
                    # Make a GET request to download the audio file
                    audio_response = await client.get(audio_url)
                    if audio_response.status_code == 200:
                        # delete the sample from Coqui Studio
                        # await self._cleanup_coqui(response_data.get('id'))
                        return audio_response.content
                    else:
                        log.error(f"Error downloading audio: {audio_response.text}")
                else:
                    log.error("No audio URL in response")
            else:
                log.error(f"Error generating audio: {response.text}")
                
    async def _cleanup_coqui(self, sample_id: str):
        api_key = self.token
        if not api_key or not sample_id:
            return

        async with httpx.AsyncClient() as client:
            url = f"https://app.coqui.ai/api/v2/samples/xtts/{sample_id}"
            headers = {
                "Authorization": f"Bearer {api_key}"
            }

            # Make the DELETE request to Coqui API
            response = await client.delete(url, headers=headers)

            if response.status_code == 204:
                log.info(f"Successfully deleted sample with ID: {sample_id}")
            else:
                log.error(f"Error deleting sample with ID: {sample_id}: {response.text}")

    async def _list_voices_coqui(self) -> dict[str, str]:
        
        url_speakers = "https://app.coqui.ai/api/v2/speakers"
        url_custom_voices = "https://app.coqui.ai/api/v2/voices"
        
        voices = []
        
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {self.token}"
            }
            response = await client.get(url_speakers, headers=headers, params={"per_page":1000})
            speakers = response.json()["result"]
            voices.extend([Voice(value=speaker["id"], label=speaker["name"]) for speaker in speakers])
            
            response = await client.get(url_custom_voices, headers=headers, params={"per_page":1000})
            custom_voices = response.json()["result"]
            voices.extend([Voice(value=voice["id"], label=voice["name"]) for voice in custom_voices])
            
        # sort by name
        voices.sort(key=lambda x: x.label)
            
        return voices