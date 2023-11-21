from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional, Union
import asyncio
import traceback
import httpx
import io
import threading
import pydantic
import nltk
from nltk.tokenize import sent_tokenize

from elevenlabs.utils import play
import talemate.data_objects as data_objects
import talemate.util as util
import talemate.config as config
import talemate.emit.async_signals
from talemate.events import GameLoopNewMessageEvent
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage

from .base import Agent, set_processing, AgentAction, AgentActionConfig, CallableConfigValue
from .registry import register

import structlog

import time
import re

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character, Scene
    from talemate.agents.conversation import ConversationAgentEmission

log = structlog.get_logger("talemate.agents.tts")

nltk.download("punkt")

async def play_audio_chunk(audio_data, play_event):
    play(audio_data)
    play_event.set()  # Signal that the chunk has finished playing

def parse_chunks(text):
    chunks = sent_tokenize(text)
    cleaned_chunks = []
    
    for chunk in chunks:
        chunk = chunk.strip("*")
        
        if not chunk:
            continue
        
        if chunk[0] == '"' and chunk[-1] != '"':
            chunk += '"'
        elif chunk[-1] == '"' and chunk[0] != '"':
            chunk = '"' + chunk
        cleaned_chunks.append(chunk)
    
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
        self.audio_queue = asyncio.Queue()
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
                            #{"value": "tts", "label": "TTS (Local)"},
                            {"value": "elevenlabs", "label": "Eleven Labs"},
                            {"value": "coqui", "label": "Coqui Studio"},
                        ],
                        value="tts",
                        label="API",
                        description="Which TTS API to use",
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
    def agent_details(self):
        suffix = ""
        if not self.ready and not self.token:
            suffix = " (no token)"
        elif not self.ready and not self.default_voice_id:
            suffix = " (no voice id)"
        elif self.default_voice_id:
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
    def requires_llm_client(self):
        return False
    
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
        return (not self.requires_token or self.token) and self.default_voice_id

    @property
    def status(self):
        if not self.enabled:
            return "disabled"
        if self.ready:
            return "active" if not getattr(self, "processing", False) else "busy"
        if self.requires_token and not self.token:
            return "error"

    @property
    def max_generation_length(self):
        if self.api == "elevenlabs":
            return 1024
        elif self.api == "coqui":
            return 250
            
        return 250

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop_new_message").connect(self.on_game_loop_new_message)
        
    async def on_game_loop_new_message(self, emission:GameLoopNewMessageEvent):
        """
        Called when a conversation is generated
        """
        
        if not self.enabled:
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

    def voice_id_to_label(self, voice_id:str):
        for voice in self.voices[self.api].voices:
            if voice.value == voice_id:
                return voice.label
        return None
    
    def list_voices_sync(self):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.list_voices())
    
    async def list_voices(self):
        if not self.enabled or not self.ready:
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

        # Start playing audio chunks as they become available
        playback_task = asyncio.create_task(self.play_audio_chunks())

        # Wait for both tasks to complete
        await asyncio.gather(generation_task, playback_task)

    async def generate_chunks(self, generate_fn, chunks):
        for chunk in chunks:
            chunk = chunk.replace("*","")
            log.info("Generating audio", api=self.api, chunk=chunk)
            await generate_fn(chunk)
        await self.audio_queue.put(None)  # Signal the end of generation

    async def play_audio_chunks(self):
        while True:
            await self.playback_done_event.wait()  # Wait for previous playback to finish
            self.playback_done_event.clear()

            audio_data = await self.audio_queue.get()
            if audio_data is None:  # Signal to stop playback
                break
            play_thread = threading.Thread(target=self.play_audio, args=(audio_data,))
            play_thread.start()

    def play_audio(self, audio_data):
        play(audio_data)
        self.playback_done_event.set()  # Signal that playback is finished

    async def _generate_elevenlabs(self, text: str, chunk_size: int = 1024):
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
                await self.audio_queue.put(bytes_io.getvalue())
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
                
    async def _generate_coqui(self, text: str):
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
                        # Put the audio data in the queue for playback
                        await self.audio_queue.put(audio_response.content)
                        # delete the sample from Coqui Studio
                        # await self._cleanup_coqui(response_data.get('id'))
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