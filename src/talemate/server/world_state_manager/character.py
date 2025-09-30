import pydantic
import structlog

log = structlog.get_logger("talemate.server.world_state_manager.character")


class UpdateCharacterVoicePayload(pydantic.BaseModel):
    """Payload for updating a character voice."""

    name: str
    voice_id: str | None = None


class UpdateCharacterSharedPayload(pydantic.BaseModel):
    """Payload for updating a character shared."""

    name: str
    shared: bool


class CharacterMixin:
    """Mixin adding websocket handlers for character voice assignment."""

    async def handle_update_character_voice(self, data: dict):
        """Assign or clear a voice for a character.

        Expected payload
        -----------------
        {
            "type": "world_state_manager",
            "action": "update_character_voice",
            "name": "<character name>",
            "voice_id": "<provider:id>" | null
        }
        """
        try:
            payload = UpdateCharacterVoicePayload(**data)
        except pydantic.ValidationError as e:
            log.error("Invalid payload for update_character_voice", error=e)
            await self.signal_operation_failed(str(e))
            return

        # Persist change via world state manager helper
        try:
            await self.world_state_manager.update_character_voice(
                payload.name, payload.voice_id
            )
        except Exception as e:
            log.error(
                "Failed to update character voice", character=payload.name, error=e
            )
            await self.signal_operation_failed("Failed to update character voice")
            return

        # Notify frontend
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_voice_updated",
                "data": payload.model_dump(),
            }
        )

        # Re-emit updated character details so UI stays in sync
        if hasattr(self, "handle_get_character_details"):
            await self.handle_get_character_details({"name": payload.name})

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_update_character_shared(self, data: dict):
        """Update a character shared.
        If enabling shared and no shared context is configured, ensure one exists following selection rules.
        """
        payload = UpdateCharacterSharedPayload(**data)
        character = self.scene.get_character(payload.name)
        character.shared = payload.shared

        if payload.shared and not self.scene.shared_context:
            await self._ensure_shared_context_exists()

        await self.signal_operation_done()
        self.scene.emit_status()
