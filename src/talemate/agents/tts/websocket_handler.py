from __future__ import annotations

import asyncio
from pathlib import Path
import pydantic
import structlog


from typing import TYPE_CHECKING, Literal
import base64
import os
import re

from talemate.emit.signals import handlers
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

import talemate.scene_message as scene_message

from .voice_library import (
    get_instance as get_voice_library,
    save_voice_library,
)
from .schema import (
    Voice,
    GenerationContext,
    Chunk,
    APIStatus,
    VoiceMixer,
    VoiceWeight,
    TALEMATE_ROOT,
)

from .util import voice_is_scene_asset
from .providers import provider

if TYPE_CHECKING:
    from talemate.agents.tts import TTSAgent
    from talemate.tale_mate import Scene
    from talemate.character import Character

__all__ = [
    "TTSWebsocketHandler",
]

log = structlog.get_logger("talemate.server.voice_library")


class EditVoicePayload(pydantic.BaseModel):
    """Payload for editing an existing voice. Only specified fields are updated."""

    voice_id: str

    label: str
    provider: str
    provider_id: str
    provider_model: str | None = None
    tags: list[str] = pydantic.Field(default_factory=list)
    parameters: dict[str, int | float | str | bool] = pydantic.Field(
        default_factory=dict
    )


class VoiceRefPayload(pydantic.BaseModel):
    """Payload referencing an existing voice by its id (used for remove / test)."""

    voice_id: str


class TestVoicePayload(pydantic.BaseModel):
    """Payload for testing a voice."""

    provider: str
    provider_id: str
    provider_model: str | None = None
    text: str | None = None
    parameters: dict[str, int | float | str | bool] = pydantic.Field(
        default_factory=dict
    )


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


class UploadVoiceFilePayload(pydantic.BaseModel):
    """Payload for uploading a new voice file for providers that support it."""

    provider: str
    label: str
    content: str  # Base64 data URL (e.g. data:audio/wav;base64,AAAB...)
    as_scene_asset: bool = False

    @pydantic.field_validator("content")
    @classmethod
    def _validate_content(cls, v: str):
        if not v.startswith("data:") or ";base64," not in v:
            raise ValueError("Content must be a base64 data URL")
        return v


class GenerateForSceneMessagePayload(pydantic.BaseModel):
    """Payload for generating a voice for a scene message."""

    message_id: int | Literal["intro"]


class TTSWebsocketHandler(Plugin):
    """Websocket plugin to manage the TTS voice library."""

    router = "tts"

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

        # sort by label
        voices.sort(key=lambda x: x["label"])

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

        voice.is_scene_asset = voice_is_scene_asset(voice, provider(voice.provider))

        voice_library.voices[voice.id] = voice
        await save_voice_library(voice_library)
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
            delete_method(voice)

        await save_voice_library(voice_library)
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

        # all fields are always provided
        voice.label = payload.label
        voice.provider = payload.provider
        voice.provider_id = payload.provider_id
        voice.provider_model = payload.provider_model
        voice.tags = payload.tags
        voice.parameters = payload.parameters
        voice.is_scene_asset = voice_is_scene_asset(voice, provider(voice.provider))

        # If provider or provider_id changed, id changes -> reinsert
        new_id = voice.id
        if new_id != payload.voice_id:
            # Remove old key, insert new
            del voice_library.voices[payload.voice_id]
            voice_library.voices[new_id] = voice

        await save_voice_library(voice_library)
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
            provider_model=payload.provider_model,
            parameters=payload.parameters,
        )

        if not tts_agent or not tts_agent.api_ready(voice.provider):
            await self.signal_operation_failed(f"API '{voice.provider}' not ready")
            return

        generate_fn = getattr(tts_agent, f"{voice.provider}_generate", None)
        if not generate_fn:
            await self.signal_operation_failed("Provider not supported by TTS agent")
            return

        # Use provided text or default
        test_text = payload.text or "This is a test of the selected voice."

        # Build minimal generation context
        context = GenerationContext()
        chunk = Chunk(
            text=[test_text],
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
            await save_voice_library(voice_library)
            self._broadcast_update(new_voice.id)
            await self.signal_operation_done()

        except Exception as e:
            log.error("Failed to save mixed voice", error=e)
            await self.signal_operation_failed(f"Failed to save mixed voice: {str(e)}")

    async def handle_generate_for_scene_message(self, data: dict):
        """Handle a request to generate a voice for a scene message."""

        tts_agent: "TTSAgent" = get_agent("tts")
        scene: "Scene" = self.scene

        log.debug("Generating TTS for scene message", data=data)

        try:
            payload = GenerateForSceneMessagePayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        log.debug("Payload", payload=payload)

        character: "Character | None" = None
        text: str = ""

        if payload.message_id == "intro":
            text = scene.get_intro()
        else:
            message = scene.get_message(payload.message_id)

            if not message:
                await self.signal_operation_failed("Message not found")
                return

            if message.typ not in ["character", "narrator"]:
                await self.signal_operation_failed(
                    "Message is not a character or narrator message"
                )
                return

            log.debug("Message type", message_type=message.typ)

            if isinstance(message, scene_message.CharacterMessage):
                character = scene.get_character(message.character_name)

                if not character:
                    await self.signal_operation_failed("Character not found")
                    return

                text = message.without_name
            else:
                text = message.message

        if not text:
            await self.signal_operation_failed("No text to generate speech for.")
            return

        await tts_agent.generate(text, character)

        await self.signal_operation_done()

    async def handle_stop_and_clear(self, data: dict):
        """Handle a request from the frontend to stop and clear the current TTS queue."""

        tts_agent: "TTSAgent" = get_agent("tts")

        if not tts_agent:
            await self.signal_operation_failed("TTS agent not available")
            return

        try:
            await tts_agent.stop_and_clear_queue()
            await self.signal_operation_done()
        except Exception as e:
            log.error("Failed to stop and clear TTS queue", error=e)
            await self.signal_operation_failed(str(e))

    # ------------------------------------------------------------------
    # File upload handler
    # ------------------------------------------------------------------

    async def handle_upload_voice_file(self, data: dict):
        """Handle uploading a new audio file for a voice.

        The *provider* defines which MIME types it accepts via
        ``VoiceProvider.upload_file_types``.  This method therefore:

        1. Parses the data-URL to obtain the raw bytes **and** MIME type.
        2. Verifies the MIME type against the provider's allowed list
           (if the provider restricts uploads).
        3. Stores the file under

           ``tts/voice/<provider>/<slug(label)>.<extension>``

           where *extension* is derived from the MIME type (e.g. ``audio/wav`` → ``wav``).
        4. Returns the relative path ("provider_id") back to the frontend so
           it can populate the voice's ``provider_id`` field.
        """

        try:
            payload = UploadVoiceFilePayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        # Check provider allows file uploads
        from .providers import provider as get_provider

        P = get_provider(payload.provider)
        if not P.allow_file_upload:
            await self.signal_operation_failed(
                f"Provider '{payload.provider}' does not support file uploads"
            )
            return

        # Build filename from label
        def slugify(text: str) -> str:
            text = text.lower().strip()
            text = re.sub(r"[^a-z0-9]+", "-", text)
            return text.strip("-")

        filename_no_ext = slugify(payload.label or "voice") or "voice"

        # Determine media type and validate against provider
        try:
            header, b64data = payload.content.split(",", 1)
            media_type = header.split(":", 1)[1].split(";", 1)[0]
        except Exception:
            await self.signal_operation_failed("Invalid data URL format")
            return

        if P.upload_file_types and media_type not in P.upload_file_types:
            await self.signal_operation_failed(
                f"File type '{media_type}' not allowed for provider '{payload.provider}'"
            )
            return

        extension = media_type.split("/")[1]
        filename = f"{filename_no_ext}.{extension}"

        # Determine target directory and path
        if not payload.as_scene_asset:
            target_dir = P.default_voice_dir
        else:
            target_dir = Path(self.scene.assets.asset_directory) / "tts"

        os.makedirs(target_dir, exist_ok=True)
        target_path = target_dir / filename

        log.debug(
            "Target path",
            target_path=target_path,
            as_scene_asset=payload.as_scene_asset,
        )

        # Decode base64 data URL
        try:
            file_bytes = base64.b64decode(b64data)
        except Exception as e:
            await self.signal_operation_failed(f"Invalid base64 data: {e}")
            return

        try:
            with open(target_path, "wb") as f:
                f.write(file_bytes)
        except Exception as e:
            await self.signal_operation_failed(f"Failed to save file: {e}")
            return

        provider_id = str(target_path.relative_to(TALEMATE_ROOT))

        # Send response back to frontend so it can set provider_id
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "voice_file_uploaded",
                "provider_id": provider_id,
            }
        )
        await self.signal_operation_done(signal_only=True)
