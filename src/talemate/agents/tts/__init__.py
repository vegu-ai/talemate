from __future__ import annotations

import asyncio
import base64
import re
from typing import TYPE_CHECKING

import uuid
from collections import deque

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
    AgentActionNote,
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
from .providers import provider

import talemate.agents.tts.voice_library as voice_library

from .elevenlabs import ElevenLabsMixin
from .openai import OpenAIMixin
from .google import GoogleMixin
from .kokoro import KokoroMixin
from .chatterbox import ChatterboxMixin
from .websocket_handler import TTSWebsocketHandler

if TYPE_CHECKING:
    from talemate.character import Character
    from talemate.agents.summarize import SummarizeAgent
    from talemate.game.engine.nodes.scene import SceneLoopEvent

log = structlog.get_logger("talemate.agents.tts")

HOT_SWAP_NOTIFICATION_TIME = 60

VOICE_LIBRARY_NOTE = "Voices are not managed here, but in the voice library which can be accessed through the Talemate application bar at the top."

async_signals.register(
    "agent.tts.prepare.before",
    "agent.tts.prepare.after",
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
    GoogleMixin,
    KokoroMixin,
    ChatterboxMixin,
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
    websocket_handler = TTSWebsocketHandler

    @classmethod
    def config_options(cls, agent=None):
        config_options = super().config_options(agent=agent)

        if not agent:
            return config_options

        narrator_voice_id = config_options["actions"]["_config"]["config"][
            "narrator_voice_id"
        ]

        narrator_voice_id["choices"] = cls.narrator_voice_id_choices(agent)

        return config_options

    @classmethod
    def narrator_voice_id_choices(cls, agent: "TTSAgent") -> list[dict[str, str]]:
        choices = voice_library.voices_for_apis(agent.ready_apis, agent.voice_library)
        choices.sort(key=lambda x: x.label)
        return [
            {
                "label": f"{voice.label} ({voice.provider})",
                "value": voice.id,
            }
            for voice in choices
        ]

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
                            "kokoro",
                        ],
                        label="Enabled APIs",
                        description="APIs to use for TTS",
                        choices=[],
                    ),
                    "narrator_voice_id": AgentActionConfig(
                        type="autocomplete",
                        value="kokoro:af_bella",
                        label="Narrator Voice",
                        description="Voice to use for narration",
                        choices=[],
                        note=VOICE_LIBRARY_NOTE,
                    ),
                    "speaker_separation": AgentActionConfig(
                        type="text",
                        value="simple",
                        label="Speaker separation",
                        description="How to separate speaker dialogue from exposition",
                        choices=[
                            {"label": "No separation", "value": "none"},
                            {"label": "Simple", "value": "simple"},
                            {"label": "AI assisted", "value": "ai_assisted"},
                        ],
                        note_on_value={
                            "none": AgentActionNote(
                                type="primary",
                                text="Character messages will be voiced entirely by the character's voice with a fallback to the narrator voice if the character has no voice selecte. Narrator messages will be voiced exclusively by the narrator voice.",
                            ),
                            "simple": AgentActionNote(
                                type="primary",
                                text="Exposition and dialogue will be separated in character messages. Narrator messages will be voiced exclusively by the narrator voice.",
                            ),
                            "ai_assisted": AgentActionNote(
                                type="primary",
                                text="Appropriate speaker separation will be attempted based on the content of the message with help from the Summarizer agent. This sends an extra prompt to the LLM to determine the appropriate speaker(s).",
                            ),
                        },
                    ),
                    "generate_for_player": AgentActionConfig(
                        type="bool",
                        value=False,
                        label="Auto-generate for player",
                        description="Generate audio for player messages",
                    ),
                    "generate_for_npc": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Auto-generate for AI characters",
                        description="Generate audio for NPC messages",
                    ),
                    "generate_for_narration": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Auto-generate for narration",
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

        KokoroMixin.add_actions(actions)
        ChatterboxMixin.add_actions(actions)
        GoogleMixin.add_actions(actions)
        ElevenLabsMixin.add_actions(actions)
        OpenAIMixin.add_actions(actions)

        return actions

    def __init__(self, **kwargs):
        self.is_enabled = False  # tts agent is disabled by default
        self.actions = TTSAgent.init_actions()
        self.config = config.load_config()
        self.playback_done_event = asyncio.Event()

        # Queue management for voice generation
        # Each queue instance gets a unique id so it can later be referenced
        # (e.g. for cancellation of all remaining items).
        # Only one queue can be active at a time. New generation requests that
        # arrive while a queue is processing will be appended to the same
        # queue. Once the queue is fully processed it is discarded and a new
        # one will be created for subsequent generation requests.
        # Queue now holds individual (context, chunk) pairs so interruption can
        # happen between chunks even when a single context produced many.
        self._generation_queue: deque[tuple[GenerationContext, Chunk]] = deque()
        self._queue_id: str | None = None
        self._queue_task: asyncio.Task | None = None
        self._queue_lock = asyncio.Lock()
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
    def speaker_separation(self) -> str:
        return self.actions["_config"].config["speaker_separation"].value

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

        self.actions["_config"].config[
            "narrator_voice_id"
        ].choices = self.narrator_voice_id_choices(self)

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
            return "idle" if not getattr(self, "processing", False) else "busy"
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
                provider=provider(api),
                default_model=getattr(self, f"{api}_model", None),
                model_choices=getattr(self, f"{api}_model_choices", []),
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
        async_signals.get("voice_library.update.after").connect(
            self.on_voice_library_update
        )
        async_signals.get("scene_loop_init_after").connect(self.on_scene_loop_init)

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        instance.emit_agent_status(self.__class__, self)

    async def on_scene_loop_init(self, event: "SceneLoopEvent"):
        if not self.enabled or not self.ready or not self.generate_for_narration:
            return

        if self.scene.history:
            # we already have a history, so we don't need to generate TTS for the intro
            return

        await self.generate(self.scene.get_intro(), character=None)

    async def on_voice_library_update(self, voice_library: VoiceLibrary):
        log.debug("Voice library updated - refreshing narrator voice choices")
        self.actions["_config"].config[
            "narrator_voice_id"
        ].choices = self.narrator_voice_id_choices(self)
        await self.emit_status()

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
        """
        Public entry-point for voice generation.

        The actual audio generation happens sequentially inside a single
        background queue.  If a queue is currently active, we simply append the
        new request to it; if not, we create a new queue (with its own unique
        id) and start processing.
        """
        if not self.enabled or not self.ready or not text:
            return

        self.playback_done_event.set()

        summarizer: "SummarizeAgent" = instance.get_agent("summarizer")

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
        if self.speaker_separation != "none":
            if self.speaker_separation == "ai_assisted" and not character:
                markup = await summarizer.markup_context_for_tts(text)
            else:
                markup = text

            for _dlg_chunk in dialogue_utils.separate_dialogue_from_exposition(markup):
                _voice = (
                    character_voice
                    if _dlg_chunk.type == "dialogue"
                    else self.narrator_voice
                )

                if _dlg_chunk.speaker is not None:
                    # speaker name has been identified
                    _character = self.scene.get_character(_dlg_chunk.speaker)
                    log.debug(
                        "Identified speaker",
                        speaker=_dlg_chunk.speaker,
                        character=_character,
                    )
                    if (
                        _character
                        and _character.voice
                        and self.api_ready(_character.voice.provider)
                    ):
                        log.debug(
                            "Using character voice",
                            character=_character.name,
                            voice=_character.voice,
                        )
                        _voice = _character.voice

                _api: str = _voice.provider if _voice else self.api
                chunk = Chunk(
                    api=_api,
                    voice=_voice,
                    model=_voice.provider_model,
                    generate_fn=getattr(self, f"{_api}_generate"),
                    prepare_fn=getattr(self, f"{_api}_prepare_chunk", None),
                    character_name=character.name if character else None,
                    text=[_dlg_chunk.text],
                    type=_dlg_chunk.type,
                    intensity=_dlg_chunk.intensity,
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
                    prepare_fn=getattr(self, f"{_api}_prepare_chunk", None),
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

        # Enqueue each chunk individually for fine-grained interruptibility
        async with self._queue_lock:
            if self._queue_id is None:
                self._queue_id = str(uuid.uuid4())

            for chunk in context.chunks:
                self._generation_queue.append((context, chunk))

            # Start processing task if needed
            if self._queue_task is None or self._queue_task.done():
                self._queue_task = asyncio.create_task(
                    self._process_queue(self._queue_id)
                )

            log.debug(
                "tts queue enqueue",
                queue_id=self._queue_id,
                total_items=len(self._generation_queue),
            )

        # The caller doesn't need to wait for the queue to finish; it runs in
        # the background.  We still register the task with Talemate's
        # background-processing tracking so that UI can reflect activity.
        await self.set_background_processing(self._queue_task)

    # ---------------------------------------------------------------------
    # Queue helpers
    # ---------------------------------------------------------------------

    async def _process_queue(self, queue_id: str):
        """Sequentially processes all GenerationContext objects in the queue.

        Once the last context has been processed the queue state is reset so a
        future generation call will create a new queue (and therefore a new
        id).  The *queue_id* argument allows us to later add cancellation logic
        that can target a specific queue instance.
        """

        try:
            while True:
                async with self._queue_lock:
                    if not self._generation_queue:
                        break

                    context, chunk = self._generation_queue.popleft()

                    log.debug(
                        "tts queue dequeue",
                        queue_id=queue_id,
                        total_items=len(self._generation_queue),
                        chunk_type=chunk.type,
                    )

                # Process outside lock so other coroutines can enqueue
                await self._generate_chunk(chunk, context)
        finally:
            # Clean up queue state after finishing (or on cancellation)
            async with self._queue_lock:
                if queue_id == self._queue_id:
                    self._queue_id = None
                    self._queue_task = None
                    self._generation_queue.clear()

    # Public helper so external code (e.g. later cancellation UI) can find the current queue id
    def current_queue_id(self) -> str | None:
        return self._queue_id

    async def _generate_chunk(self, chunk: Chunk, context: GenerationContext):
        """Generate audio for a single chunk (all its sub-chunks)."""

        for _chunk in chunk.sub_chunks:
            if not _chunk.cleaned_text.strip():
                continue

            emission: VoiceGenerationEmission = VoiceGenerationEmission(
                chunk=_chunk, context=context
            )

            log.info("Generating audio", api=chunk.api, chunk=_chunk)

            if _chunk.prepare_fn:
                await async_signals.get("agent.tts.prepare.before").send(emission)
                await _chunk.prepare_fn(_chunk)
                await async_signals.get("agent.tts.prepare.after").send(emission)

            await async_signals.get("agent.tts.generate.before").send(emission)
            try:
                emission.wav_bytes = await _chunk.generate_fn(_chunk, context)
            except Exception as e:
                log.error("Error generating audio", error=e, chunk=_chunk)
                continue
            await async_signals.get("agent.tts.generate.after").send(emission)
            self.play_audio(emission.wav_bytes)
            await asyncio.sleep(0.1)

    # Deprecated: kept for backward compatibility but no longer used.
    async def generate_chunks(self, context: GenerationContext):
        for chunk in context.chunks:
            await self._generate_chunk(chunk, context)

    def play_audio(self, audio_data):
        # play audio through the websocket (browser)

        emit(
            "audio_queue",
            data={"audio_data": base64.b64encode(audio_data).decode("utf-8")},
        )

        self.playback_done_event.set()  # Signal that playback is finished

    async def stop_and_clear_queue(self):
        """Cancel any ongoing generation and clear the pending queue.

        This is triggered by UI actions that request immediate stop of TTS
        synthesis and playback.  It cancels the background task (if still
        running) and clears all queued items in a thread-safe manner.
        """
        async with self._queue_lock:
            # Clear all queued items
            self._generation_queue.clear()

            # Cancel the background task if it is still running
            if self._queue_task and not self._queue_task.done():
                self._queue_task.cancel()

            # Reset queue identifiers/state
            self._queue_id = None
            self._queue_task = None

        # Ensure downstream components know playback is finished
        self.playback_done_event.set()
