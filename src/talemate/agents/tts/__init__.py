from __future__ import annotations

import asyncio
import base64
import re
from typing import TYPE_CHECKING

import structlog
from nltk.tokenize import sent_tokenize

import talemate.util.dialogue as dialogue_utils
import talemate.config as config
import talemate.emit.async_signals as async_signals
import talemate.instance as instance
from talemate.ux.schema import Note
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

from .schema import (
    APIStatus,
    Voice,
    VoiceLibrary,
    GenerationContext,
    Chunk,
    VoiceGenerationEmission,
)


import talemate.agents.tts.voice_library as voice_library

from .elevenlabs import ElevenLabsMixin
from .openai import OpenAIMixin
from .xtts2 import XTTS2Mixin
from .piper import PiperMixin
from .google import GoogleMixin
from .kokoro import KokoroMixin
from .websocket_handler import VoiceLibraryWebsocketHandler

if TYPE_CHECKING:
    from talemate.character import Character

log = structlog.get_logger("talemate.agents.tts")

HOT_SWAP_NOTIFICATION_TIME = 60

VOICE_LIBRARY_NOTE = "IMPORTANT: Voices are not managed here, but in the voice library which can be accessed through the Talemate application bar at the top."

async_signals.register(
    "agent.tts.generate.before",
    "agent.tts.generate.after",
)


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


def rejoin_chunks(chunks: list[str], chunk_size: int = 250):
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


@register()
class TTSAgent(
    ElevenLabsMixin,
    OpenAIMixin,
    XTTS2Mixin,
    PiperMixin,
    GoogleMixin,
    KokoroMixin,
    Agent,
):
    """
    Text to speech agent
    """

    agent_type = "tts"
    verbose_name = "Voice"
    requires_llm_client = False
    essential = False
    voice_library: VoiceLibrary = None

    # websocket handler for frontend voice library management
    websocket_handler = VoiceLibraryWebsocketHandler

    @classmethod
    def config_options(cls, agent=None):
        config_options = super().config_options(agent=agent)

        if not agent:
            return config_options

        narrator_voice_id = config_options["actions"]["_config"]["config"][
            "narrator_voice_id"
        ]

        choices = voice_library.voices_for_apis(agent.ready_apis, agent.voice_library)
        narrator_voice_id["choices"] = [
            {
                "label": f"{voice.label} ({voice.provider})",
                "value": voice.id,
            }
            for voice in choices
        ]

        return config_options

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "_config": AgentAction(
                enabled=True,
                label="Configure",
                description="TTS agent configuration",
                config={
                    "apis": AgentActionConfig(
                        type="flags",
                        value=[
                            "elevenlabs",
                            "openai",
                            "xtts2",
                            "piper",
                            "google",
                            "kokoro",
                        ],
                        label="Enabled APIs",
                        description="APIs to use for TTS",
                        choices=[],
                    ),
                    "narrator_voice_id": AgentActionConfig(
                        type="autocomplete",
                        value="kokoro:am_adam",
                        label="Narrator Voice",
                        description="Voice to use for narration",
                        choices=[],
                        note=VOICE_LIBRARY_NOTE,
                    ),
                    "separate_narrator_voice": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Separate narrator voice",
                        description="Always use narrator voice for exposition, only using custom character voices for their dialogue. Since this effectively segments the content this may cause loss of context between segments.",
                        quick_toggle=True,
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
                    "force_chunking": AgentActionConfig(
                        type="number",
                        value=0,
                        min=0,
                        step=128,
                        max=8192,
                        label="Enforce chunk size",
                        note="Force the generation of chunks of this size. This will increase responsiveness at the cost of lost context between chunks. (Stuff like appropriate inflection, etc.). 0 = no chunking.",
                    ),
                },
            ),
        }

        ElevenLabsMixin.add_actions(actions)
        OpenAIMixin.add_actions(actions)
        XTTS2Mixin.add_actions(actions)
        PiperMixin.add_actions(actions)
        GoogleMixin.add_actions(actions)
        KokoroMixin.add_actions(actions)

        return actions

    def __init__(self, **kwargs):
        self.is_enabled = False  # tts agent is disabled by default
        self.actions = TTSAgent.init_actions()
        self.config = config.load_config()
        self.playback_done_event = asyncio.Event()
        self.voice_library = voice_library.get_instance()

        self.actions["_config"].model_dump()
        handlers["config_saved"].connect(self.on_config_saved)

    # general helpers

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
    def narrator_voice_id(self) -> str:
        return self.actions["_config"].config["narrator_voice_id"].value

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
    def force_chunking(self) -> int:
        return self.actions["_config"].config["force_chunking"].value

    @property
    def apis(self) -> list[str]:
        return self.actions["_config"].config["apis"].value

    @property
    def all_apis(self) -> list[str]:
        return [api["value"] for api in self.actions["_config"].config["apis"].choices]

    @property
    def agent_details(self):
        details = {}

        if not self.enabled:
            return details

        used_apis: set[str] = set()

        used_disabled_apis: set[str] = set()

        if self.narrator_voice:
            #

            label = self.narrator_voice.label
            color = "primary"
            used_apis.add(self.narrator_voice.provider)

            if not self.api_enabled(self.narrator_voice.provider):
                used_disabled_apis.add(self.narrator_voice.provider)

            if not self.api_ready(self.narrator_voice.provider):
                color = "error"

            details["narrator_voice"] = AgentDetail(
                icon="mdi-script-text",
                value=label,
                description="Default voice",
                color=color,
            ).model_dump()

        scene = getattr(self, "scene", None)
        if scene:
            for character in scene.characters:
                if character.voice:
                    label = character.voice.label
                    color = "primary"
                    used_apis.add(character.voice.provider)
                    if not self.api_enabled(character.voice.provider):
                        used_disabled_apis.add(character.voice.provider)
                    if not self.api_ready(character.voice.provider):
                        color = "error"

                    details[f"{character.name}_voice"] = AgentDetail(
                        icon="mdi-account-voice",
                        value=f"{character.name}",
                        description=f"{character.name}'s voice: {label} ({character.voice.provider})",
                        color=color,
                    ).model_dump()

        for api in used_disabled_apis:
            details[f"{api}_disabled"] = AgentDetail(
                icon="mdi-alert-circle",
                value=f"{api} disabled",
                description=f"{api} disabled - at least one voice is attempting to use this api but is not enabled",
                color="error",
            ).model_dump()

        for api in used_apis:
            fn = getattr(self, f"{api}_agent_details", None)
            if fn:
                details.update(fn)
        return details

    @property
    def status(self):
        if not self.enabled:
            return "disabled"
        if self.ready:
            if getattr(self, "processing_bg", 0) > 0:
                return "busy_bg" if not getattr(self, "processing", False) else "busy"
            return "active" if not getattr(self, "processing", False) else "busy"
        return "uninitialized"

    @property
    def narrator_voice(self) -> Voice | None:
        return self.voice_library.get_voice(self.narrator_voice_id)

    @property
    def api_status(self) -> list[APIStatus]:
        api_status: list[APIStatus] = []

        for api in self.all_apis:
            not_configured_reason = getattr(self, f"{api}_not_configured_reason", None)
            not_configured_action = getattr(self, f"{api}_not_configured_action", None)
            api_info: str | None = getattr(self, f"{api}_info", None)
            messages: list[Note] = []
            if not_configured_reason:
                messages.append(
                    Note(
                        text=not_configured_reason,
                        color="error",
                        icon="mdi-alert-circle-outline",
                        actions=[not_configured_action]
                        if not_configured_action
                        else None,
                    )
                )
            if api_info:
                messages.append(
                    Note(
                        text=api_info.strip(),
                        color="muted",
                        icon="mdi-information-outline",
                    )
                )
            _status = APIStatus(
                api=api,
                enabled=self.api_enabled(api),
                ready=self.api_ready(api),
                configured=self.api_configured(api),
                messages=messages,
                supports_mixing=getattr(self, f"{api}_supports_mixing", False),
            )
            api_status.append(_status)

        # order by api
        api_status.sort(key=lambda x: x.api)

        return api_status

    # events

    def connect(self, scene):
        super().connect(scene)
        async_signals.get("game_loop_new_message").connect(
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

    # voice helpers

    @property
    def ready_apis(self) -> list[str]:
        """
        Returns a list of apis that are ready
        """
        return [api for api in self.apis if self.api_ready(api)]

    @property
    def used_apis(self) -> list[str]:
        """
        Returns a list of apis that are in use

        The api is in use if it is the narrator voice or if any of the active characters in the scene use a voice from the api.
        """
        return [api for api in self.apis if self.api_used(api)]

    def api_enabled(self, api: str) -> bool:
        """
        Returns whether the api is currently in the .apis list, which means it is enabled.
        """
        return api in self.apis

    def api_ready(self, api: str) -> bool:
        """
        Returns whether the api is ready.

        The api must be enabled and configured.
        """

        if not self.api_enabled(api):
            return False

        return self.api_configured(api)

    def api_configured(self, api: str) -> bool:
        return getattr(self, f"{api}_configured", True)

    def api_used(self, api: str) -> bool:
        """
        Returns whether the narrator or any of the active characters in the scene
        use a voice from the given api

        Args:
            api (str): The api to check

        Returns:
            bool: Whether the api is in use
        """

        if self.narrator_voice and self.narrator_voice.provider == api:
            return True

        if not getattr(self, "scene", None):
            return False

        for character in self.scene.characters:
            if not character.voice:
                continue
            voice = self.voice_library.get_voice(character.voice.id)
            if voice and voice.provider == api:
                return True

        return False

    # generation

    @set_processing
    async def generate(self, text: str, character: Character | None = None):
        if not self.enabled or not self.ready or not text:
            return

        self.playback_done_event.set()

        context = GenerationContext(voice_id=self.narrator_voice_id)
        character_voice: Voice = self.narrator_voice

        if character and character.voice:
            voice = character.voice
            if voice and self.api_ready(voice.provider):
                character_voice = voice
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
                    voice=_voice,
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
                    voice=_voice,
                    model=_voice.provider_model,
                    generate_fn=getattr(self, f"{_api}_generate"),
                    character_name=character.name if character else None,
                    text=[text],
                    type="dialogue" if character else "exposition",
                )
            ]

        # second chunking by splitting into chunks of max_generation_length

        for chunk in chunks:
            _text = []

            max_generation_length = getattr(self, f"{chunk.api}_max_generation_length")

            if self.force_chunking > 0:
                max_generation_length = min(max_generation_length, self.force_chunking)

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

                # skip empty chunks
                if not _chunk.cleaned_text.strip():
                    continue

                emission: VoiceGenerationEmission = VoiceGenerationEmission(
                    context=context
                )
                log.info("Generating audio", api=chunk.api, chunk=_chunk)
                await async_signals.get("agent.tts.generate.before").send(emission)
                emission.wav_bytes = await _chunk.generate_fn(_chunk, context)
                await async_signals.get("agent.tts.generate.after").send(emission)
                self.play_audio(emission.wav_bytes)

    def play_audio(self, audio_data):
        # play audio through the websocket (browser)

        emit(
            "audio_queue",
            data={"audio_data": base64.b64encode(audio_data).decode("utf-8")},
        )

        self.playback_done_event.set()  # Signal that playback is finished
