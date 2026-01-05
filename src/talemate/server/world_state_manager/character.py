import pydantic
import structlog

log = structlog.get_logger("talemate.server.world_state_manager.character")


class UpdateCharacterVoicePayload(pydantic.BaseModel):
    """Payload for updating a character voice."""

    name: str
    voice_id: str | None = None


class UpdateCharacterVisualRulesPayload(pydantic.BaseModel):
    """Payload for updating a character visual rules."""

    name: str
    visual_rules: str | None = None


class UpdateCharacterSharedPayload(pydantic.BaseModel):
    """Payload for updating a character shared."""

    name: str
    shared: bool


class UpdateCharacterSharedAttributePayload(pydantic.BaseModel):
    """Payload for updating a character shared attribute."""

    name: str
    attribute: str
    shared: bool


class UpdateCharacterSharedDetailPayload(pydantic.BaseModel):
    """Payload for updating a character shared detail."""

    name: str
    detail: str
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
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_update_character_visual_rules(self, data: dict):
        """Update a character visual rules."""
        try:
            payload = UpdateCharacterVisualRulesPayload(**data)
        except pydantic.ValidationError as e:
            log.error("Invalid payload for update_character_visual_rules", error=e)
            await self.signal_operation_failed(str(e))
            return

        try:
            await self.world_state_manager.update_character_visual_rules(
                payload.name, payload.visual_rules
            )
        except Exception as e:
            log.error(
                "Failed to update character visual rules",
                character=payload.name,
                error=e,
            )
            await self.signal_operation_failed(
                "Failed to update character visual rules"
            )
            return

        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_update_character_shared(self, data: dict):
        """Update a character shared.
        If enabling shared and no shared context is configured, ensure one exists following selection rules.
        """
        payload = UpdateCharacterSharedPayload(**data)
        character = self.scene.get_character(payload.name)

        if not character:
            await self.signal_operation_failed("Character not found")
            return

        await character.set_shared(payload.shared)

        if payload.shared and not self.scene.shared_context:
            await self._ensure_shared_context_exists()

        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_update_character_shared_attribute(self, data: dict):
        payload = UpdateCharacterSharedAttributePayload(**data)
        character = self.scene.get_character(payload.name)

        if not character:
            await self.signal_operation_failed("Character not found")
            return

        await character.set_shared_attribute(payload.attribute, payload.shared)
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_update_character_shared_detail(self, data: dict):
        payload = UpdateCharacterSharedDetailPayload(**data)
        character = self.scene.get_character(payload.name)

        log.debug(
            "Update character shared detail",
            name=payload.name,
            detail=payload.detail,
            shared=payload.shared,
        )

        if not character:
            await self.signal_operation_failed("Character not found")
            return
        await character.set_shared_detail(payload.detail, payload.shared)
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_share_all_characters(self, data: dict):
        """Share all characters in the scene."""
        if not self.scene.shared_context:
            await self._ensure_shared_context_exists()

        shared_count = 0
        for name, character in self.scene.character_data.items():
            if not character.shared:
                await character.set_shared(True)
                shared_count += 1

        log.debug("Share all characters", shared_count=shared_count)

        # Refresh character list and shared context counts
        await self.handle_get_character_list({})
        await self.handle_list_shared_contexts({})
        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_unshare_all_characters(self, data: dict):
        """Unshare all characters in the scene."""
        unshared_count = 0
        for name, character in self.scene.character_data.items():
            if character.shared:
                await character.set_shared(False)
                unshared_count += 1

        log.debug("Unshare all characters", unshared_count=unshared_count)

        # Refresh character list and shared context counts
        await self.handle_get_character_list({})
        await self.handle_list_shared_contexts({})
        await self.signal_operation_done()
        self.scene.emit_status()
