import pydantic
import asyncio
import structlog
from typing import TYPE_CHECKING, Literal

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin
from .chat.websocket_handler import DirectorChatWebsocketMixin
import talemate.util as util
from .action_core.gating import (
    get_all_callback_choices,
    extract_all_callback_descriptors,
)
from talemate.context import interaction, handle_generation_cancelled
from talemate.status import set_loading
from talemate.exceptions import GenerationCancelled

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "DirectorWebsocketHandler",
]

log = structlog.get_logger("talemate.server.director")


class InstructionPayload(pydantic.BaseModel):
    instructions: str = ""


class SelectChoicePayload(pydantic.BaseModel):
    choice: str
    character: str = ""


class CharacterPayload(InstructionPayload):
    character: str = ""


class PersistCharacterPayload(pydantic.BaseModel):
    name: str
    templates: list[str] | None = None
    narrate_entry: bool = True
    narrate_entry_direction: str = ""

    active: bool = True
    determine_name: bool = True
    augment_attributes: str = ""
    generate_attributes: bool = True

    content: str = ""
    description: str = ""

    is_player: bool = False


class AssignVoiceToCharacterPayload(pydantic.BaseModel):
    character_name: str


class UpdatePersonaPayload(pydantic.BaseModel):
    persona: str | None


class GetDisabledSubActionsPayload(pydantic.BaseModel):
    mode: Literal["chat", "scene_direction"]


class GetSubActionChoicesPayload(pydantic.BaseModel):
    mode: Literal["chat", "scene_direction"] | None = None


class SetDisabledSubActionsPayload(pydantic.BaseModel):
    mode: Literal["chat", "scene_direction"]
    disabled_action_ids: list[str]


class DirectorWebsocketHandler(DirectorChatWebsocketMixin, Plugin):
    """
    Handles director actions
    """

    router = "director"

    @property
    def director(self):
        return get_agent("director")

    @set_loading("Generating dynamic actions", cancellable=True, as_async=True)
    async def handle_request_dynamic_choices(self, data: dict):
        """
        Generate clickable actions for the user
        """
        payload = CharacterPayload(**data)
        await self.director.generate_choices(**payload.model_dump())

    async def handle_select_choice(self, data: dict):
        payload = SelectChoicePayload(**data)

        log.debug("selecting choice", payload=payload)

        if payload.character:
            character = self.scene.get_character(payload.character)
        else:
            character = self.scene.get_player_character()

        if not character:
            log.error("handle_select_choice: could not find character", payload=payload)
            return

        # hijack the interaction state
        try:
            interaction_state = interaction.get()
        except LookupError:
            # no interaction state
            log.error("handle_select_choice: no interaction state", payload=payload)
            return

        interaction_state.from_choice = payload.choice
        interaction_state.act_as = character.name if not character.is_player else None
        interaction_state.input = f"@{payload.choice}"

    async def handle_persist_character(self, data: dict):
        payload = PersistCharacterPayload(**data)
        scene: "Scene" = self.scene

        if not payload.content:
            payload.content = scene.snapshot(lines=15)

        # add as asyncio task
        task = asyncio.create_task(
            self.director.persist_character(**payload.model_dump())
        )

        async def handle_task_done(task):
            if task.exception():
                exc = task.exception()
                log.error("Error persisting character", error=exc)

                # Handle GenerationCancelled properly to reset cancel_requested flag
                if isinstance(exc, GenerationCancelled):
                    handle_generation_cancelled(exc)

                await self.signal_operation_failed(f"Error persisting character: {exc}")
            else:
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": "character_persisted",
                        "character": task.result(),
                    }
                )
                await self.signal_operation_done()

        task.add_done_callback(lambda task: asyncio.create_task(handle_task_done(task)))

    async def handle_assign_voice_to_character(self, data: dict):
        """
        Assign a voice to a character using the director agent
        """
        try:
            payload = AssignVoiceToCharacterPayload(**data)
        except pydantic.ValidationError as e:
            await self.signal_operation_failed(str(e))
            return

        scene: "Scene" = self.scene
        if not scene:
            await self.signal_operation_failed("No scene active")
            return

        character = scene.get_character(payload.character_name)
        if not character:
            await self.signal_operation_failed(
                f"Character '{payload.character_name}' not found"
            )
            return

        character.voice = None

        # Add as asyncio task
        task = asyncio.create_task(self.director.assign_voice_to_character(character))

        async def handle_task_done(task):
            if task.exception():
                exc = task.exception()
                log.error("Error assigning voice to character", error=exc)

                # Handle GenerationCancelled properly to reset cancel_requested flag
                if isinstance(exc, GenerationCancelled):
                    handle_generation_cancelled(exc)

                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": "assign_voice_to_character_failed",
                        "character_name": payload.character_name,
                        "error": str(exc),
                    }
                )
                await self.signal_operation_failed(
                    f"Error assigning voice to character: {exc}"
                )
            else:
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": "assign_voice_to_character_done",
                        "character_name": payload.character_name,
                    }
                )
                await self.signal_operation_done()
                self.scene.emit_status()

        task.add_done_callback(lambda task: asyncio.create_task(handle_task_done(task)))

    async def handle_update_persona(self, data: dict):
        """
        Update the director's persona
        """
        try:
            payload = UpdatePersonaPayload(**data)
        except pydantic.ValidationError as e:
            log.error("director.update_persona.validation_error", error=e)
            return

        scene = self.scene
        if not scene:
            log.error("director.update_persona.no_scene")
            return

        # Update the scene's agent persona templates
        if (
            not hasattr(scene, "agent_persona_templates")
            or scene.agent_persona_templates is None
        ):
            scene.agent_persona_templates = {}

        scene.agent_persona_templates["director"] = payload.persona

        log.info("director.persona_updated", persona=payload.persona)
        scene.emit_status()

    async def handle_get_sub_action_choices(self, data: dict):
        """
        Get all available sub-action choices, optionally filtered by mode
        """
        try:
            payload = GetSubActionChoicesPayload(**data)
        except pydantic.ValidationError:
            # Backward compatibility: if no mode provided, use None
            payload = GetSubActionChoicesPayload(mode=None)

        choices = await get_all_callback_choices(
            mode=payload.mode,
            director=self.director if payload.mode else None,
            evaulate_conditions=False,
        )

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "sub_action_choices",
                "choices": choices,
                "mode": payload.mode,
            }
        )

    async def handle_get_disabled_sub_actions(self, data: dict):
        """
        Get the current list of disabled sub-actions for a specific mode
        """
        try:
            payload = GetDisabledSubActionsPayload(**data)
        except pydantic.ValidationError as e:
            log.error("director.get_disabled_sub_actions.validation_error", error=e)
            return

        if not self.director:
            log.error("director.get_disabled_sub_actions.no_director")
            return

        # Read from scene state
        disabled_sub_actions = self.director.get_scene_state(
            "disabled_sub_actions", default={}
        )

        if not isinstance(disabled_sub_actions, dict):
            disabled_sub_actions = {}

        mode_disabled = disabled_sub_actions.get(payload.mode, [])

        if not isinstance(mode_disabled, list):
            mode_disabled = []

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "disabled_sub_actions",
                "mode": payload.mode,
                "disabled_action_ids": mode_disabled,
            }
        )

    async def handle_set_disabled_sub_actions(self, data: dict):
        """
        Update the list of disabled sub-actions for a specific mode
        """
        try:
            payload = SetDisabledSubActionsPayload(**data)
        except pydantic.ValidationError as e:
            log.error("director.set_disabled_sub_actions.validation_error", error=e)
            return

        if not self.director:
            log.error("director.set_disabled_sub_actions.no_director")
            return

        # Get all descriptors to check for force_enabled actions
        all_descriptors = await extract_all_callback_descriptors()
        force_enabled_ids: set[str] = set()

        for descriptors in all_descriptors.values():
            for desc in descriptors:
                # Check if this action is force-enabled and available in this mode
                if desc.force_enabled:
                    if desc.availability == "both" or desc.availability == payload.mode:
                        force_enabled_ids.add(desc.action_id)

        # Filter out force-enabled actions from the disabled list
        filtered_disabled = [
            action_id
            for action_id in payload.disabled_action_ids
            if action_id not in force_enabled_ids
        ]

        # Read current state
        disabled_sub_actions = self.director.get_scene_state(
            "disabled_sub_actions", default={}
        )

        if not isinstance(disabled_sub_actions, dict):
            disabled_sub_actions = {}

        # Update the specific mode
        disabled_sub_actions[payload.mode] = filtered_disabled

        # Save back to scene state
        self.director.set_scene_states(disabled_sub_actions=disabled_sub_actions)

        log.info(
            "director.disabled_sub_actions_updated",
            mode=payload.mode,
            count=len(payload.disabled_action_ids),
        )

        # Echo back the update (with filtered list)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "disabled_sub_actions",
                "mode": payload.mode,
                "disabled_action_ids": filtered_disabled,
            }
        )

    async def handle_scene_direction_history(self, data: dict):
        """
        Return the current scene direction history for the active scene.

        Frontend sends:
            { type: 'director', action: 'scene_direction_history' }
        """
        if not self.director:
            return

        # Ensure direction state exists so we always have a direction_id
        direction = self.director.direction_create()
        messages = direction.messages or []

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "scene_direction_history",
                "direction_id": direction.id,
                "messages": [m.model_dump() for m in messages],
                "token_total": sum(util.count_tokens(str(m)) for m in messages),
            }
        )

    async def handle_scene_direction_clear(self, data: dict):
        """
        Clear the scene direction timeline.
        """
        if not self.director:
            return

        self.director.direction_clear()

        # Get fresh empty direction state
        direction = self.director.direction_create()
        messages = direction.messages or []

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "scene_direction_history",
                "direction_id": direction.id,
                "messages": [m.model_dump() for m in messages],
                "token_total": sum(util.count_tokens(str(m)) for m in messages),
            }
        )
