from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional, Union
import asyncio
import traceback
import httpx
import io
import threading

from elevenlabs.utils import play
import talemate.data_objects as data_objects
import talemate.util as util
import talemate.config as config
import talemate.emit.async_signals
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage

from .base import Agent, set_processing, AgentAction, AgentActionConfig
from .registry import register

import structlog

import time
import re

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character, Scene
    from talemate.agents.conversation import ConversationAgentEmission

log = structlog.get_logger("talemate.agents.tts")


async def play_audio_chunk(audio_data, play_event):
    play(audio_data)
    play_event.set()  # Signal that the chunk has finished playing

def parse_chunks(text):
    # Modified regular expression to match chunks based on double quotes or sentence endings,
    # and to capture the last chunk of a line regardless of its ending character
    pattern = r'"[^"]*"|[\w0-9 ,\']*(?:[\.\!\?\,]|$)'
    # Find all matches
    matches = re.findall(pattern, text)
    # Remove empty matches that might occur due to the end-of-line capture
    matches = [match for match in matches if match.strip()]
    return matches


@register()
class TTSAgent(Agent):
    
    """
    Text to speech agent
    """
    
    agent_type = "tts"
    verbose_name = "Text to speech"
    
    def __init__(self, **kwargs):
        
        self.is_enabled = False
        
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
                            {"value": "tts", "label": "TTS (Local)"},
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
                        label="Voice ID",
                        description="Voice ID/Name to use for TTS",
                    ),
                    "generate_chunks": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Generate chunks",
                        description="Generate audio chunks for each sentence - will be much more responsive but may loose context to inform inflection",
                    )
                }  
            ),
        }


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


    @set_processing
    async def generate(self, text: str):
        if not self.enabled or not self.ready or not text:
            return


        self.playback_done_event.set()
        
        generate_fn = getattr(self, f"_generate_{self.api}")
        
        if self.actions["_config"].config["generate_chunks"].value:
            chunks = parse_chunks(text)
        else:
            chunks = [text]

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