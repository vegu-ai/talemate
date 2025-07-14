from __future__ import annotations

import asyncio
from pathlib import Path
import pydantic
import structlog


from typing import TYPE_CHECKING

from talemate.emit.signals import handlers
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

from .voice_library import (
    get_instance as get_voice_library,
    save_voice_library,
)
from .schema import Voice, GenerationContext, Chunk, APIStatus, VoiceMixer, VoiceWeight

if TYPE_CHECKING:
    from talemate.agents.tts import TTSAgent

__all__ = [
    "VoiceLibraryWebsocketHandler",
]

log = structlog.get_logger("talemate.server.voice_library")

TALEMATE_ROOT = Path(__file__).parent.parent.parent.parent.parent


class EditVoicePayload(pydantic.BaseModel):
    """Payload for editing an existing voice. Only specified fields are updated."""

    voice_id: str

    label: str | None = None
    provider: str | None = None
    provider_id: str | None = None
    provider_model: str | None = None
    tags: list[str] | None = None


class VoiceRefPayload(pydantic.BaseModel):
    """Payload referencing an existing voice by its id (used for remove / test)."""

    voice_id: str


class TestVoicePayload(pydantic.BaseModel):
    """Payload for testing a voice."""

    provider: str
    provider_id: str


class AddVoicePayload(Voice):
    """Explicit payload for adding a new voice – identical fields to Voice."""

    pass


class TestMixedVoicePayload(pydantic.BaseModel):
    """Payload for testing a mixed voice."""

    provider: str
    voices: list[VoiceWeight]


class SaveMixedVoicePayload(pydantic.BaseModel):
    """Payload for saving a mixed voice."""

    provider: str
    label: str
    voices: list[VoiceWeight]
    tags: list[str] = pydantic.Field(default_factory=list)


class VoiceLibraryWebsocketHandler(Plugin):
    """Websocket plugin to manage the TTS voice library."""

    router = "voice_library"

    def __init__(self, websocket_handler):
        super().__init__(websocket_handler)
        # Immediately send current voice list to the frontend
        asyncio.create_task(self._send_voice_list())

    # ---------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------

    def connect(self):
        # needs to be after config is saved so the TTS agent has already
        # refreshed to the latest config
        handlers.get("config_saved_after").connect(self.on_app_config_saved)

    def on_app_config_saved(self, event):
        self._send_api_status()

    # ---------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------

    async def _send_voice_list(self, select_voice_id: str | None = None):
        voice_library = get_voice_library()
        voices = [v.model_dump() for v in voice_library.voices.values()]

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "voices",
                "voices": voices,
                "select_voice_id": select_voice_id,
            }
        )

    def _voice_exists(self, voice_id: str) -> bool:
        return voice_id in get_voice_library().voices

    def _broadcast_update(self, select_voice_id: str | None = None):
        # After any mutation we broadcast the full list for simplicity
        asyncio.create_task(self._send_voice_list(select_voice_id))

    def _send_api_status(self):
        tts_agent: "TTSAgent" = get_agent("tts")
        api_status: list[APIStatus] = tts_agent.api_status
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "api_status",
                "api_status": [s.model_dump() for s in api_status],
            }
        )

    # ---------------------------------------------------------------------
    # Handlers
    # ---------------------------------------------------------------------

    async def handle_list(self, data: dict):
        await self._send_voice_list()

    async def handle_api_status(self, data: dict):
        self._send_api_status()

    async def handle_add(self, data: dict):
        try:
            voice = AddVoicePayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        voice_library = get_voice_library()
        if self._voice_exists(voice.id):
            await self.signal_operation_failed("Voice already exists")
            return

        voice_library.voices[voice.id] = voice
        save_voice_library(voice_library)
        self._broadcast_update()
        await self.signal_operation_done()

    async def handle_remove(self, data: dict):
        try:
            payload = VoiceRefPayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        tts_agent: "TTSAgent" = get_agent("tts")

        voice_library = get_voice_library()

        try:
            voice = voice_library.voices[payload.voice_id]
        except KeyError:
            await self.signal_operation_failed("Voice not found")
            return

        provider = voice.provider

        try:
            del voice_library.voices[payload.voice_id]
        except KeyError:
            await self.signal_operation_failed("Voice not found")
            return

        # check if porivder has a delete method
        delete_method = getattr(tts_agent, f"{provider}_delete_voice", None)
        if delete_method:
            delete_method(voice.provider_id)

        save_voice_library(voice_library)
        self._broadcast_update()
        await self.signal_operation_done()

    async def handle_edit(self, data: dict):
        try:
            payload = EditVoicePayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        voice_library = get_voice_library()
        voice = voice_library.voices.get(payload.voice_id)
        if not voice:
            await self.signal_operation_failed("Voice not found")
            return

        # Update provided fields
        if payload.label is not None:
            voice.label = payload.label
        if payload.provider is not None:
            voice.provider = payload.provider
        if payload.provider_id is not None:
            voice.provider_id = payload.provider_id
        if payload.provider_model is not None:
            voice.provider_model = payload.provider_model

        if payload.tags is not None:
            voice.tags = payload.tags

        # If provider or provider_id changed, id changes -> reinsert
        new_id = voice.id
        if new_id != payload.voice_id:
            # Remove old key, insert new
            del voice_library.voices[payload.voice_id]
            voice_library.voices[new_id] = voice

        save_voice_library(voice_library)
        self._broadcast_update()
        await self.signal_operation_done()

    async def handle_test(self, data: dict):
        """Handle a request to test a voice.

        Supports two payload formats:

        1. Existing voice – identified by ``voice_id`` (legacy behaviour)
        2. Unsaved voice – identified by at least ``provider`` and ``provider_id``.
        """

        tts_agent: "TTSAgent" = get_agent("tts")

        try:
            payload = TestVoicePayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        voice = Voice(
            label=f"{payload.provider_id} (test)",
            provider=payload.provider,
            provider_id=payload.provider_id,
        )

        if not tts_agent or not tts_agent.api_ready(voice.provider):
            await self.signal_operation_failed(f"API '{voice.provider}' not ready")
            return

        generate_fn = getattr(tts_agent, f"{voice.provider}_generate", None)
        if not generate_fn:
            await self.signal_operation_failed("Provider not supported by TTS agent")
            return

        # Build minimal generation context
        context = GenerationContext()
        chunk = Chunk(
            text=["This is a test of the selected voice."],
            type="dialogue",
            api=voice.provider,
            voice=voice,
            model=voice.provider_model,
            generate_fn=generate_fn,
            character_name=None,
        )
        context.chunks.append(chunk)

        # Run generation in background so we don't block the event loop
        async def _run_test():
            try:
                await tts_agent.generate_chunks(context)
            finally:
                await self.signal_operation_done(signal_only=True)

        asyncio.create_task(_run_test())

    async def handle_test_mixed(self, data: dict):
        """Handle a request to test a mixed voice."""

        tts_agent: "TTSAgent" = get_agent("tts")

        try:
            payload = TestMixedVoicePayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        # Validate that weights sum to 1.0
        total_weight = sum(v.weight for v in payload.voices)
        if abs(total_weight - 1.0) > 0.001:
            await self.signal_operation_failed(
                f"Weights must sum to 1.0, got {total_weight}"
            )
            return

        if not tts_agent or not tts_agent.api_ready(payload.provider):
            await self.signal_operation_failed(f"{payload.provider} API not ready")
            return

        # Build mixer
        mixer = VoiceMixer(voices=payload.voices)

        # Run test in background using the appropriate provider's test method
        test_method = getattr(tts_agent, f"{payload.provider}_test_mix", None)
        if not test_method:
            await self.signal_operation_failed(
                f"{payload.provider} does not implement voice mixing"
            )
            return

        async def _run_test():
            try:
                await test_method(mixer)
            finally:
                await self.signal_operation_done(signal_only=True)

        asyncio.create_task(_run_test())

    async def handle_save_mixed(self, data: dict):
        """Handle a request to save a mixed voice."""

        tts_agent: "TTSAgent" = get_agent("tts")

        try:
            payload = SaveMixedVoicePayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        # Validate that weights sum to 1.0
        total_weight = sum(v.weight for v in payload.voices)
        if abs(total_weight - 1.0) > 0.001:
            await self.signal_operation_failed(
                f"Weights must sum to 1.0, got {total_weight}"
            )
            return

        if not tts_agent or not tts_agent.api_ready(payload.provider):
            await self.signal_operation_failed(f"{payload.provider} API not ready")
            return

        # Build mixer
        mixer = VoiceMixer(voices=payload.voices)

        # Create a unique voice id for the mixed voice
        voice_id = f"{payload.label.lower().replace(' ', '-')}"

        # Mix and save the voice using the appropriate provider's methods
        save_method = getattr(tts_agent, f"{payload.provider}_save_mix", None)

        if not save_method:
            await self.signal_operation_failed(
                f"{payload.provider} does not implement voice mixing"
            )
            return

        try:
            saved_path = await save_method(voice_id, mixer)

            # voice id is Path relative to talemate root
            voice_id = str(saved_path.relative_to(TALEMATE_ROOT))

            # Add the voice to the library
            new_voice = Voice(
                label=payload.label,
                provider=payload.provider,
                provider_id=voice_id,
                tags=payload.tags,
                mix=mixer,
            )

            voice_library = get_voice_library()
            voice_library.voices[new_voice.id] = new_voice
            save_voice_library(voice_library)
            self._broadcast_update(new_voice.id)
            await self.signal_operation_done()

        except Exception as e:
            log.error("Failed to save mixed voice", error=e)
            await self.signal_operation_failed(f"Failed to save mixed voice: {str(e)}")
