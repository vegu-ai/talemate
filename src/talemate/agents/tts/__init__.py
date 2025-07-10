from __future__ import annotations

import asyncio
import base64
import time
import re
from typing import Union

import structlog
from nltk.tokenize import sent_tokenize

import talemate.util.dialogue as dialogue_utils
import talemate.config as config
import talemate.emit.async_signals
import talemate.instance as instance
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.events import GameLoopNewMessageEvent
from talemate.scene_message import CharacterMessage, NarratorMessage

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)
from talemate.agents.registry import register
from .schema import Voice, VoiceLibrary, GenerationContext, Chunk

from .elevenlabs import ElevenLabsMixin
from .openai import OpenAIMixin
from .xtts2 import XTTS2Mixin
from talemate.character import Character, CharacterVoice

log = structlog.get_logger("talemate.agents.tts")


HOT_SWAP_NOTIFICATION_TIME = 60


def parse_chunks(text: str) -> list[str]:
    """
    Takes a string and splits it into chunks based on punctuation.

    In case of an error it will return the original text as a single chunk and
    the error will be logged.
    """

    try:
        text = text.replace("*", "")

        # ensure sentence terminators are before quotes
        # otherwise the beginning of dialog will bleed into narration
        text = re.sub(r'([^.?!]+) "', r'\1. "', text)

        text = text.replace("...", "__ellipsis__")
        chunks = sent_tokenize(text)
        cleaned_chunks = []

        for chunk in chunks:
            if not chunk.strip():
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


@register()
class TTSAgent(ElevenLabsMixin, OpenAIMixin, XTTS2Mixin, Agent):
    """
    Text to speech agent
    """

    agent_type = "tts"
    verbose_name = "Voice"
    requires_llm_client = False
    essential = False

    # timestamp of last hot swap
    last_hot_swap: float = 0

    @classmethod
    def config_options(cls, agent=None):
        config_options = super().config_options(agent=agent)

        if agent:
            config_options["actions"]["_config"]["config"]["voice_id"]["choices"] = [
                voice.model_dump() for voice in agent.list_voices_sync()
            ]

        return config_options

    @classmethod
    def init_voices(cls) -> dict[str, VoiceLibrary]:
        voices = {}
        ElevenLabsMixin.add_voices(voices)
        OpenAIMixin.add_voices(voices)
        XTTS2Mixin.add_voices(voices)
        return voices

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "_config": AgentAction(
                enabled=True,
                label="Configure",
                description="TTS agent configuration",
                config={
                    "api": AgentActionConfig(
                        type="text",
                        choices=[],
                        value_migration=lambda v: "xtts2" if v == "tts" else v,
                        value="xtts2",
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
                    "separate_narrator_voice": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Separate narrator voice",
                        description="If a character is set up with a custom voice it will be used for narration as well. Check this to use the narrator voice for exposition regardless.",
                    ),
                    "allow_hot_swap": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Allow hot swap",
                        description="Allow API hot swapping - Allows characters to use voices on APIs other than the one currently selected.",
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
                },
            ),
        }

        ElevenLabsMixin.add_actions(actions)
        OpenAIMixin.add_actions(actions)
        XTTS2Mixin.add_actions(actions)

        return actions

    def __init__(self, **kwargs):
        self.is_enabled = False  # tts agent is disabled by default
        self.actions = TTSAgent.init_actions()
        self.voices = TTSAgent.init_voices()
        self.config = config.load_config()
        self.playback_done_event = asyncio.Event()
        self.preselect_voice = None

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

    # config helpers

    @property
    def api(self) -> str:
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
    def voice_id(self) -> str:
        return self.actions["_config"].config["voice_id"].value

    @property
    def generate_for_player(self) -> bool:
        return self.actions["_config"].config["generate_for_player"].value

    @property
    def generate_for_npc(self) -> bool:
        return self.actions["_config"].config["generate_for_npc"].value

    @property
    def generate_for_narration(self) -> bool:
        return self.actions["_config"].config["generate_for_narration"].value

    @property
    def separate_narrator_voice(self) -> bool:
        return self.actions["_config"].config["separate_narrator_voice"].value

    @property
    def allow_hot_swap(self) -> bool:
        return self.actions["_config"].config["allow_hot_swap"].value

    @property
    def not_ready_reason(self) -> str:
        """
        Returns a string explaining why the agent is not ready
        """

        if self.ready:
            return ""

        elif self.requires_token and not self.token:
            return "No API token"

        elif not self.voice_id:
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
                value=self.voice_id_to_label(self.voice_id) or "",
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

        fn = getattr(self, f"{self.api}_agent_details", None)
        if fn:
            details.update(fn)

        if self.recent_hot_swap:
            details["hot_swap"] = AgentDetail(
                icon="mdi-swap-horizontal",
                value="Hot swap",
                description=f"At least one character has used a voice from a different API in the last {HOT_SWAP_NOTIFICATION_TIME} seconds",
                color="warning",
            ).model_dump()

        return details

    @property
    def token(self):
        api = self.api
        return self.config.get(api, {}).get("api_key")

    @property
    def requires_token(self):
        return self.api != "xtts2"

    @property
    def ready(self):
        return (not self.requires_token or self.token) and self.voice_id

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
        return "uninitialized"

    @property
    def max_generation_length(self):
        return getattr(self, f"{self.api}_max_generation_length")

    @property
    def narrator_voice(self) -> CharacterVoice:
        return CharacterVoice(
            provider=self.api,
            provider_id=self.voice_id,
            provider_model=None,
            label="Narrator",
        )

    @property
    def recent_hot_swap(self) -> bool:
        return time.time() - self.last_hot_swap < 10

    async def apply_config(self, *args, **kwargs):
        try:
            api = kwargs["actions"]["_config"]["config"]["api"]["value"]
        except KeyError:
            api = self.api

        if api == "tts":
            # migrate old tts value to xtts2
            api = "xtts2"

        api_changed = api != self.api

        try:
            self.preselect_voice = kwargs["actions"]["_config"]["config"]["voice_id"][
                "value"
            ]
        except KeyError:
            self.preselect_voice = self.voice_id

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

    async def voice_available(self, api: str, voice_id: str) -> bool:
        """
        Check if a voice is available for a given TTS API

        Args:
            api (str): TTS API to check
            voice_id (str): Voice ID to check

        Returns:
            bool: True if the voice is available, False otherwise
        """

        is_hot_swap = api != self.api

        if not self.allow_hot_swap and is_hot_swap:
            return False

        if is_hot_swap:
            self.last_hot_swap = time.time()

        await self.list_voices(api)

        if api not in self.voices:
            log.warning("voice_available", error="Invalid TTS API", api=api)
            return False

        voices = self.voices[api].voices
        for voice in voices:
            if voice.value == voice_id:
                return True

        return False

    async def on_game_loop_new_message(self, emission: GameLoopNewMessageEvent):
        """
        Called when a conversation is generated
        """

        character: Character | None = None

        if not self.enabled or not self.ready:
            return

        if not isinstance(emission.message, (CharacterMessage, NarratorMessage)):
            return

        if (
            isinstance(emission.message, NarratorMessage)
            and not self.generate_for_narration
        ):
            return

        if isinstance(emission.message, CharacterMessage):
            if emission.message.source == "player" and not self.generate_for_player:
                return
            elif emission.message.source == "ai" and not self.generate_for_npc:
                return

            character = self.scene.get_character(emission.message.character_name)

        if isinstance(emission.message, CharacterMessage):
            character_prefix = emission.message.split(":", 1)[0]
        else:
            character_prefix = ""

        log.info(
            "reactive tts", message=emission.message, character_prefix=character_prefix
        )

        await self.generate(
            str(emission.message).replace(character_prefix + ": ", ""),
            character=character,
        )

    def voice(self, voice_id: str, api: str = None) -> Union[Voice, None]:
        if not api:
            api = self.api
        for voice in self.voices[api].voices:
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

    async def list_voices(self, api: str = None):
        if self.requires_token and not self.token:
            return []

        if not api:
            api = self.api

        library = self.voices[api]

        # TODO: allow re-syncing voices
        if library.last_synced:
            return library.voices

        list_fn = getattr(self, f"{api}_list_voices")
        log.info("Listing voices", api=api)

        library.voices = await list_fn()
        library.last_synced = time.time()

        if self.preselect_voice:
            if self.voice(self.preselect_voice):
                self.actions["_config"].config["voice_id"].value = self.preselect_voice
                self.preselect_voice = None

        # if the current voice cannot be found, reset it
        if not self.voice(self.voice_id):
            self.actions["_config"].config["voice_id"].value = ""

        # set loading to false
        return library.voices

    @set_processing
    async def generate(self, text: str, character: Character | None = None):
        if not self.enabled or not self.ready or not text:
            return

        self.playback_done_event.set()

        context = GenerationContext(voice_id=self.voice_id)
        character_voice: CharacterVoice = self.narrator_voice

        if character and character.voice:
            if await self.voice_available(
                character.voice.provider, character.voice.provider_id
            ):
                character_voice = character.voice
            else:
                log.warning(
                    "Character voice not available",
                    character=character.name,
                    voice=character.voice,
                )

        log.debug("Voice routing", character=character, voice=character_voice)

        # initial chunking by separating dialogue from exposition

        chunks: list[Chunk] = []
        if self.separate_narrator_voice:
            for _dlg_chunk in dialogue_utils.separate_dialogue_from_exposition(text):
                _voice = (
                    character_voice
                    if _dlg_chunk.type == "dialogue"
                    else self.narrator_voice
                )
                _api: str = _voice.provider if _voice else self.api
                chunk = Chunk(
                    api=_api,
                    voice_id=_voice.provider_id,
                    model=_voice.provider_model,
                    generate_fn=getattr(self, f"{_api}_generate"),
                    character_name=character.name if character else None,
                    text=[_dlg_chunk.text],
                    type=_dlg_chunk.type,
                )
                chunks.append(chunk)
        else:
            _voice = character_voice if character else self.narrator_voice
            _api: str = _voice.provider if _voice else self.api
            chunks = [
                Chunk(
                    api=_api,
                    voice_id=_voice.provider_id,
                    model=_voice.provider_model,
                    generate_fn=getattr(self, f"{_api}_generate"),
                    character_name=character.name if character else None,
                    text=[text],
                    type="dialogue" if character else "exposition",
                )
            ]

        max_generation_length = getattr(self, f"{self.api}_max_generation_length")

        # second chunking by splitting into chunks of max_generation_length

        for chunk in chunks:
            _text = []

            for _chunk_text in chunk.text:
                if len(_chunk_text) <= max_generation_length:
                    _text.append(_chunk_text)
                    continue

                _parsed = parse_chunks(_chunk_text)
                _joined = rejoin_chunks(_parsed, chunk_size=max_generation_length)
                _text.extend(_joined)

            log.debug("chunked for size", before=chunk.text, after=_text)

            chunk.text = _text

        context.chunks = chunks

        generation_task = asyncio.create_task(self.generate_chunks(context))
        await self.set_background_processing(generation_task)

        # Wait for both tasks to complete
        # await asyncio.gather(generation_task)

    async def generate_chunks(
        self,
        context: GenerationContext,
    ):
        for chunk in context.chunks:
            for _chunk in chunk.sub_chunks:
                log.info("Generating audio", api=self.api, chunk=_chunk)
                audio_data = await _chunk.generate_fn(_chunk, context)
                self.play_audio(audio_data)

    def play_audio(self, audio_data):
        # play audio through the python audio player
        # play(audio_data)

        emit(
            "audio_queue",
            data={"audio_data": base64.b64encode(audio_data).decode("utf-8")},
        )

        self.playback_done_event.set()  # Signal that playback is finished
