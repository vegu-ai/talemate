from __future__ import annotations

import asyncio
import base64
import functools
import io
import os
import tempfile
import time
import uuid
from typing import Union

import httpx
import nltk
import pydantic
import structlog
from nltk.tokenize import sent_tokenize
from openai import AsyncOpenAI

import talemate.config as config
import talemate.emit.async_signals
import talemate.instance as instance
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.events import GameLoopNewMessageEvent
from talemate.scene_message import CharacterMessage, NarratorMessage

from .base import (
    Agent,
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)
from .registry import register

try:
    from TTS.api import TTS
except ImportError:
    TTS = None

log = structlog.get_logger("talemate.agents.tts")  #

if not TTS:
    # TTS installation is massive and requires a lot of dependencies
    # so we don't want to require it unless the user wants to use it
    log.info(
        "TTS (local) requires the TTS package, please install with `pip install TTS` if you want to use the local api"
    )


def parse_chunks(text: str) -> list[str]:

    """
    Takes a string and splits it into chunks based on punctuation.
    
    In case of an error it will return the original text as a single chunk and 
    the error will be logged.
    """

    try:
        text = text.replace("...", "__ellipsis__")
        chunks = sent_tokenize(text)
        cleaned_chunks = []

        for chunk in chunks:
            chunk = chunk.replace("*", "")
            if not chunk:
                continue
            cleaned_chunks.append(chunk)

        for i, chunk in enumerate(cleaned_chunks):
            chunk = chunk.replace("__ellipsis__", "...")
            cleaned_chunks[i] = chunk

        return cleaned_chunks
    except Exception as e:
        log.error("chunking error", error=e, text=text)
        return [text.replace("__ellipsis__", "...").replace("*", "")]


def clean_quotes(chunk: str):
    # if there is an uneven number of quotes, remove the last one if its
    # at the end of the chunk. If its in the middle, add a quote to the end
    if chunk.count('"') % 2 == 1:
        if chunk.endswith('"'):
            chunk = chunk[:-1]
        else:
            chunk += '"'

    return chunk


def rejoin_chunks(chunks: list[str], chunk_size: int = 250):
    """
    Will combine chunks split by punctuation into a single chunk until
    max chunk size is reached
    """

    joined_chunks = []

    current_chunk = ""

    for chunk in chunks:
        if len(current_chunk) + len(chunk) > chunk_size:
            joined_chunks.append(clean_quotes(current_chunk))
            current_chunk = ""

        current_chunk += chunk

    if current_chunk:
        joined_chunks.append(clean_quotes(current_chunk))
    return joined_chunks


class Voice(pydantic.BaseModel):
    value: str
    label: str


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
    verbose_name = "Voice"
    requires_llm_client = False
    essential = False

    @classmethod
    def config_options(cls, agent=None):
        config_options = super().config_options(agent=agent)

        if agent:
            config_options["actions"]["_config"]["config"]["voice_id"]["choices"] = [
                voice.model_dump() for voice in agent.list_voices_sync()
            ]

        return config_options

    def __init__(self, **kwargs):
        self.is_enabled = False  #

        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            try:
                nltk.download("punkt", quiet=True)
            except Exception as e:
                log.error("nltk download error", error=e)
        except Exception as e:
            log.error("nltk find error", error=e)

        self.voices = {
            "elevenlabs": VoiceLibrary(api="elevenlabs"),
            "tts": VoiceLibrary(api="tts"),
            "openai": VoiceLibrary(api="openai"),
        }
        self.config = config.load_config()
        self.playback_done_event = asyncio.Event()
        self.preselect_voice = None
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
                            {"value": "openai", "label": "OpenAI"},
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
                        choices=[],
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
                        value=False,
                        label="Split generation",
                        description="Generate audio chunks for each sentence - will be much more responsive but may loose context to inform inflection",
                    ),
                },
            ),
            "openai": AgentAction(
                enabled=True,
                container=True,
                icon="mdi-server-outline",
                condition=AgentActionConditional(
                    attribute="_config.config.api", value="openai"
                ),
                label="OpenAI",
                config={
                    "model": AgentActionConfig(
                        type="text",
                        value="tts-1",
                        choices=[
                            {"value": "tts-1", "label": "TTS 1"},
                            {"value": "tts-1-hd", "label": "TTS 1 HD"},
                        ],
                        label="Model",
                        description="TTS model to use",
                    ),
                },
            ),
        }

        self.actions["_config"].model_dump()
        handlers["config_saved"].connect(self.on_config_saved)

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

        details = {
            "api": AgentDetail(
                icon="mdi-server-outline",
                value=self.api_label,
                description="The backend to use for TTS",
            ).model_dump(),
        }

        if self.ready and self.enabled:
            details["voice"] = AgentDetail(
                icon="mdi-account-voice",
                value=self.voice_id_to_label(self.default_voice_id) or "",
                description="The voice to use for TTS",
                color="info",
            ).model_dump()
        elif self.enabled:
            details["error"] = AgentDetail(
                icon="mdi-alert",
                value=self.not_ready_reason,
                description=self.not_ready_reason,
                color="error",
            ).model_dump()

        return details

    @property
    def api(self):
        return self.actions["_config"].config["api"].value

    @property
    def api_label(self):
        choices = self.actions["_config"].config["api"].choices
        api = self.api
        for choice in choices:
            if choice["value"] == api:
                return choice["label"]
        return api

    @property
    def token(self):
        api = self.api
        return self.config.get(api, {}).get("api_key")

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
            if getattr(self, "processing_bg", 0) > 0:
                return "busy_bg" if not getattr(self, "processing", False) else "busy"
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

    @property
    def openai_api_key(self):
        return self.config.get("openai", {}).get("api_key")

    async def apply_config(self, *args, **kwargs):
        try:
            api = kwargs["actions"]["_config"]["config"]["api"]["value"]
        except KeyError:
            api = self.api

        api_changed = api != self.api

        # log.debug(
        #    "apply_config",
        #    api=api,
        #    api_changed=api != self.api,
        #    current_api=self.api,
        #    args=args,
        #    kwargs=kwargs,
        # )

        try:
            self.preselect_voice = kwargs["actions"]["_config"]["config"]["voice_id"][
                "value"
            ]
        except KeyError:
            self.preselect_voice = self.default_voice_id

        await super().apply_config(*args, **kwargs)

        if api_changed:
            try:
                self.actions["_config"].config["voice_id"].value = (
                    self.voices[api].voices[0].value
                )
            except IndexError:
                self.actions["_config"].config["voice_id"].value = ""

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop_new_message").connect(
            self.on_game_loop_new_message
        )

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        instance.emit_agent_status(self.__class__, self)

    async def on_game_loop_new_message(self, emission: GameLoopNewMessageEvent):
        """
        Called when a conversation is generated
        """

        if not self.enabled or not self.ready:
            return

        if not isinstance(emission.message, (CharacterMessage, NarratorMessage)):
            return

        if (
            isinstance(emission.message, NarratorMessage)
            and not self.actions["_config"].config["generate_for_narration"].value
        ):
            return

        if isinstance(emission.message, CharacterMessage):
            if (
                emission.message.source == "player"
                and not self.actions["_config"].config["generate_for_player"].value
            ):
                return
            elif (
                emission.message.source == "ai"
                and not self.actions["_config"].config["generate_for_npc"].value
            ):
                return

        if isinstance(emission.message, CharacterMessage):
            character_prefix = emission.message.split(":", 1)[0]
        else:
            character_prefix = ""

        log.info(
            "reactive tts", message=emission.message, character_prefix=character_prefix
        )

        await self.generate(str(emission.message).replace(character_prefix + ": ", ""))

    def voice(self, voice_id: str) -> Union[Voice, None]:
        for voice in self.voices[self.api].voices:
            if voice.value == voice_id:
                return voice
        return None

    def voice_id_to_label(self, voice_id: str):
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

        # TODO: allow re-syncing voices
        if library.last_synced:
            return library.voices

        list_fn = getattr(self, f"_list_voices_{self.api}")
        log.info("Listing voices", api=self.api)

        library.voices = await list_fn()
        library.last_synced = time.time()

        if self.preselect_voice:
            if self.voice(self.preselect_voice):
                self.actions["_config"].config["voice_id"].value = self.preselect_voice
                self.preselect_voice = None

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
        await self.set_background_processing(generation_task)

        # Wait for both tasks to complete
        # await asyncio.gather(generation_task)

    async def generate_chunks(self, generate_fn, chunks):
        for chunk in chunks:
            chunk = chunk.replace("*", "").strip()
            log.info("Generating audio", api=self.api, chunk=chunk)
            audio_data = await generate_fn(chunk)
            self.play_audio(audio_data)

    def play_audio(self, audio_data):
        # play audio through the python audio player
        # play(audio_data)

        emit(
            "audio_queue",
            data={"audio_data": base64.b64encode(audio_data).decode("utf-8")},
        )

        self.playback_done_event.set()  # Signal that playback is finished

    # LOCAL

    async def _generate_tts(self, text: str) -> Union[bytes, None]:
        if not TTS:
            return

        tts_config = self.config.get("tts", {})
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

    async def _list_voices_tts(self) -> dict[str, str]:
        return [
            Voice(**voice) for voice in self.config.get("tts", {}).get("voices", [])
        ]

    # ELEVENLABS

    async def _generate_elevenlabs(
        self, text: str, chunk_size: int = 1024
    ) -> Union[bytes, None]:
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

    async def _list_voices_elevenlabs(self) -> dict[str, str]:
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

    # OPENAI

    async def _generate_openai(self, text: str, chunk_size: int = 1024):

        client = AsyncOpenAI(api_key=self.openai_api_key)

        model = self.actions["openai"].config["model"].value

        response = await client.audio.speech.create(
            model=model, voice=self.default_voice_id, input=text
        )

        bytes_io = io.BytesIO()
        for chunk in response.iter_bytes(chunk_size=chunk_size):
            if chunk:
                bytes_io.write(chunk)

        # Put the audio data in the queue for playback
        return bytes_io.getvalue()

    async def _list_voices_openai(self) -> dict[str, str]:
        return [
            Voice(value="alloy", label="Alloy"),
            Voice(value="echo", label="Echo"),
            Voice(value="fable", label="Fable"),
            Voice(value="onyx", label="Onyx"),
            Voice(value="nova", label="Nova"),
            Voice(value="shimmer", label="Shimmer"),
        ]
