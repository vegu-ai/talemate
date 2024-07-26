import base64
import uuid
from typing import Any, Union

import pydantic
import structlog

import talemate.world_state.templates as world_state_templates
from talemate.export import ExportOptions, export
from talemate.history import history_with_relative_time, rebuild_history
from talemate.instance import get_agent
from talemate.world_state.manager import WorldStateManager

log = structlog.get_logger("talemate.server.world_state_manager")


class UpdateCharacterAttributePayload(pydantic.BaseModel):
    name: str
    attribute: str
    value: str


class UpdateCharacterDetailPayload(pydantic.BaseModel):
    name: str
    detail: str
    value: str


class UpdateCharacterColorPayload(pydantic.BaseModel):
    name: str
    color: str


class SetCharacterDetailReinforcementPayload(pydantic.BaseModel):
    name: str
    question: str
    instructions: Union[str, None] = None
    interval: int = 10
    answer: str = ""
    update_state: bool = False
    insert: str = "sequential"


class CharacterDetailReinforcementPayload(pydantic.BaseModel):
    name: str
    question: str
    reset: bool = False


class CharacterActorPayload(pydantic.BaseModel):
    name: str
    dialogue_instructions: str
    dialogue_examples: list[str] = pydantic.Field(default_factory=list)


class SaveWorldEntryPayload(pydantic.BaseModel):
    id: str
    text: str
    meta: dict = {}


class DeleteWorldEntryPayload(pydantic.BaseModel):
    id: str


class SetWorldEntryReinforcementPayload(pydantic.BaseModel):
    question: str
    instructions: Union[str, None] = None
    interval: int = 10
    answer: str = ""
    update_state: bool = False
    insert: str = "never"


class WorldEntryReinforcementPayload(pydantic.BaseModel):
    question: str
    reset: bool = False


class QueryContextDBPayload(pydantic.BaseModel):
    query: str
    meta: dict = {}


class UpdateContextDBPayload(pydantic.BaseModel):
    text: str
    meta: dict = {}
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))


class DeleteContextDBPayload(pydantic.BaseModel):
    id: Any


class UpdatePinPayload(pydantic.BaseModel):
    entry_id: str
    condition: Union[str, None] = None
    condition_state: bool = False
    active: bool = False


class RemovePinPayload(pydantic.BaseModel):
    entry_id: str


class SaveWorldStateTemplatePayload(pydantic.BaseModel):
    template: world_state_templates.AnnotatedTemplate


class DeleteWorldStateTemplatePayload(pydantic.BaseModel):
    template: world_state_templates.AnnotatedTemplate


class ApplyWorldStateTemplatePayload(pydantic.BaseModel):
    template: world_state_templates.AnnotatedTemplate
    character_name: str | None = (None,)
    run_immediately: bool = (False,)


class ApplyWorldStateTemplatesPayload(pydantic.BaseModel):
    templates: list[world_state_templates.AnnotatedTemplate]
    character_name: str | None = (None,)
    run_immediately: bool = (False,)
    source: str | None = None
    generation_options: world_state_templates.GenerationOptions | None = None


class SaveWorldStateTemplateGroupPayload(pydantic.BaseModel):
    group: world_state_templates.Group


class DeleteWorldStateTemplateGroupPayload(pydantic.BaseModel):
    group: world_state_templates.Group


class SelectiveCharacterPayload(pydantic.BaseModel):
    name: str


class CreateCharacterPayload(pydantic.BaseModel):
    generate: bool = True
    instructions: str | None = None
    name: str | None = None
    description: str | None = None
    is_player: bool = False
    generate_attributes: bool = False
    generation_options: world_state_templates.GenerationOptions | None = None


class SceneOutlinePayload(pydantic.BaseModel):
    title: str
    description: str | None = None
    intro: str | None = None
    context: str | None = None


class SceneSettingsPayload(pydantic.BaseModel):
    experimental: bool = False
    immutable_save: bool = False


class SaveScenePayload(pydantic.BaseModel):
    save_as: str | None = None


class RegenerateHistoryPayload(pydantic.BaseModel):
    generation_options: world_state_templates.GenerationOptions | None = None


class WorldStateManagerPlugin:
    router = "world_state_manager"

    @property
    def scene(self):
        return self.websocket_handler.scene

    @property
    def world_state_manager(self):
        return WorldStateManager(self.scene)

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    async def handle(self, data: dict):
        log.info("World state manager action", action=data.get("action"))

        fn = getattr(self, f"handle_{data.get('action')}", None)

        if fn is None:
            return

        await fn(data)

    async def signal_operation_done(self):
        self.websocket_handler.queue_put(
            {"type": "world_state_manager", "action": "operation_done", "data": {}}
        )

        if self.scene.auto_save:
            await self.scene.save(auto=True)
        else:
            self.scene.saved = False
            self.scene.emit_status()

    async def handle_get_character_list(self, data):
        character_list = await self.world_state_manager.get_character_list()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_list",
                "data": character_list.model_dump(),
            }
        )

    async def handle_get_character_details(self, data):
        character_details = await self.world_state_manager.get_character_details(
            data["name"]
        )

        if not character_details:
            log.error("Character not found", name=data["name"])
            return

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_details",
                "data": character_details.model_dump(),
            }
        )

    async def handle_get_world(self, data):
        world = await self.world_state_manager.get_world()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "world",
                "data": world.model_dump(),
            }
        )

    async def handle_get_pins(self, data):
        context_pins = await self.world_state_manager.get_pins()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "pins",
                "data": context_pins.model_dump(),
            }
        )

    async def handle_get_templates(self, data):
        templates = await self.world_state_manager.get_templates()
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "templates",
                "data": {
                    "by_type": templates.model_dump()["templates"],
                    "managed": self.world_state_manager.template_collection.model_dump(),
                },
            }
        )

    async def handle_update_character_color(self, data):
        payload = UpdateCharacterColorPayload(**data)

        await self.world_state_manager.update_character_color(
            payload.name, payload.color
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_color_updated",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_update_character_attribute(self, data):
        payload = UpdateCharacterAttributePayload(**data)

        await self.world_state_manager.update_character_attribute(
            payload.name, payload.attribute, payload.value
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_attribute_updated",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})

        await self.signal_operation_done()

    async def handle_update_character_description(self, data):
        payload = UpdateCharacterAttributePayload(**data)

        await self.world_state_manager.update_character_description(
            payload.name, payload.value
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_description_updated",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_update_character_detail(self, data):
        payload = UpdateCharacterDetailPayload(**data)

        await self.world_state_manager.update_character_detail(
            payload.name, payload.detail, payload.value
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_detail_updated",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_set_character_detail_reinforcement(self, data):
        payload = SetCharacterDetailReinforcementPayload(**data)

        await self.world_state_manager.add_detail_reinforcement(
            payload.name,
            payload.question,
            payload.instructions,
            payload.interval,
            payload.answer,
            payload.insert,
            payload.update_state,
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_detail_reinforcement_set",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_run_character_detail_reinforcement(self, data):
        payload = CharacterDetailReinforcementPayload(**data)

        log.debug(
            "Run character detail reinforcement",
            name=payload.name,
            question=payload.question,
            reset=payload.reset,
        )

        await self.world_state_manager.run_detail_reinforcement(
            payload.name, payload.question, reset=payload.reset
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_detail_reinforcement_run",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_delete_character_detail_reinforcement(self, data):
        payload = CharacterDetailReinforcementPayload(**data)

        await self.world_state_manager.delete_detail_reinforcement(
            payload.name, payload.question
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_detail_reinforcement_deleted",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_update_character_actor(self, data):
        payload = CharacterActorPayload(**data)

        await self.world_state_manager.update_character_actor(
            payload.name,
            payload.dialogue_instructions,
            payload.dialogue_examples,
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_actor_updated",
                "data": payload.model_dump(),
            }
        )

        # resend character details
        await self.handle_get_character_details({"name": payload.name})
        await self.signal_operation_done()

    async def handle_save_world_entry(self, data):
        payload = SaveWorldEntryPayload(**data)

        log.debug(
            "Save world entry", id=payload.id, text=payload.text, meta=payload.meta
        )

        await self.world_state_manager.save_world_entry(
            payload.id, payload.text, payload.meta
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "world_entry_saved",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_world({})
        await self.signal_operation_done()

        self.scene.world_state.emit()

    async def handle_delete_world_entry(self, data):
        payload = DeleteWorldEntryPayload(**data)

        log.debug("Delete world entry", id=payload.id)

        await self.world_state_manager.delete_context_db_entry(payload.id)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "world_entry_deleted",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_world({})
        await self.signal_operation_done()

        self.scene.world_state.emit()
        self.scene.emit_status()

    async def handle_set_world_state_reinforcement(self, data):
        payload = SetWorldEntryReinforcementPayload(**data)

        log.debug(
            "Set world state reinforcement",
            question=payload.question,
            instructions=payload.instructions,
            interval=payload.interval,
            answer=payload.answer,
            insert=payload.insert,
            update_state=payload.update_state,
        )

        reinforcement = await self.world_state_manager.add_detail_reinforcement(
            None,
            payload.question,
            payload.instructions,
            payload.interval,
            payload.answer,
            payload.insert,
            payload.update_state,
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "world_state_reinforcement_set",
                "data": reinforcement.model_dump(),
            }
        )

        # resend world
        await self.handle_get_world({})
        await self.signal_operation_done()

    async def handle_run_world_state_reinforcement(self, data):
        payload = WorldEntryReinforcementPayload(**data)

        await self.world_state_manager.run_detail_reinforcement(
            None, payload.question, payload.reset
        )

        _, reinforcement = (
            await self.world_state_manager.world_state.find_reinforcement(
                payload.question, None
            )
        )

        if not reinforcement:
            log.error("Reinforcement not found", question=payload.question)
            await self.signal_operation_done()
            return

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "world_state_reinforcement_ran",
                "data": reinforcement.model_dump(),
            }
        )

        # resend world
        await self.handle_get_world({})
        await self.signal_operation_done()

    async def handle_delete_world_state_reinforcement(self, data):
        payload = WorldEntryReinforcementPayload(**data)

        await self.world_state_manager.delete_detail_reinforcement(
            None, payload.question
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "world_state_reinforcement_deleted",
                "data": payload.model_dump(),
            }
        )

        # resend world
        await self.handle_get_world({})
        await self.signal_operation_done()

    async def handle_query_context_db(self, data):
        payload = QueryContextDBPayload(**data)

        log.debug("Query context db", query=payload.query, meta=payload.meta)

        context_db = await self.world_state_manager.get_context_db_entries(
            payload.query, **payload.meta
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "context_db_result",
                "data": context_db.model_dump(),
            }
        )

        await self.signal_operation_done()

    async def handle_update_context_db(self, data):
        payload = UpdateContextDBPayload(**data)

        log.debug(
            "Update context db", text=payload.text, meta=payload.meta, id=payload.id
        )

        await self.world_state_manager.update_context_db_entry(
            payload.id, payload.text, payload.meta
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "context_db_updated",
                "data": payload.model_dump(),
            }
        )

        await self.signal_operation_done()

    async def handle_delete_context_db(self, data):
        payload = DeleteContextDBPayload(**data)

        log.debug("Delete context db", id=payload.id)

        await self.world_state_manager.delete_context_db_entry(payload.id)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "context_db_deleted",
                "data": payload.model_dump(),
            }
        )

        await self.signal_operation_done()

    async def handle_set_pin(self, data):
        payload = UpdatePinPayload(**data)

        log.debug(
            "Set pin",
            entry_id=payload.entry_id,
            condition=payload.condition,
            condition_state=payload.condition_state,
            active=payload.active,
        )

        await self.world_state_manager.set_pin(
            payload.entry_id, payload.condition, payload.condition_state, payload.active
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "pin_set",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_pins({})
        await self.signal_operation_done()
        await self.scene.load_active_pins()
        self.scene.emit_status()

    async def handle_remove_pin(self, data):
        payload = RemovePinPayload(**data)

        log.debug("Remove pin", entry_id=payload.entry_id)

        await self.world_state_manager.remove_pin(payload.entry_id)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "pin_removed",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_pins({})
        await self.signal_operation_done()
        await self.scene.load_active_pins()
        self.scene.emit_status()

    async def handle_apply_template(self, data):
        payload = ApplyWorldStateTemplatePayload(**data)

        log.debug("Apply world state template", payload=payload)

        result = await self.world_state_manager.apply_template(
            template=payload.template,
            character_name=payload.character_name or "",
            run_immediately=payload.run_immediately,
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "template_applied",
                "status": "done",
                "data": payload.model_dump(),
                "result": result.model_dump() if result else None,
            }
        )

        await self.handle_get_world({})
        await self.handle_get_templates({})
        await self.signal_operation_done()

    async def handle_save_template(self, data):
        payload = SaveWorldStateTemplatePayload(**data)

        log.debug("Save world state template", template=payload.template)

        await self.world_state_manager.save_template(payload.template)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "template_saved",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_templates({})
        await self.signal_operation_done()

    async def handle_delete_template(self, data):
        payload = DeleteWorldStateTemplatePayload(**data)
        template = payload.template

        log.debug(
            "Delete world state template",
            template=template.name,
            template_type=template.template_type,
        )

        await self.world_state_manager.remove_template(template)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "template_deleted",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_templates({})
        await self.signal_operation_done()

    async def handle_apply_templates(self, data):
        payload = ApplyWorldStateTemplatesPayload(**data)

        log.debug("Applying world state templates", templates=payload.templates)

        def callback_done(template, result, last_template: bool):
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "template_applied",
                    "status": "done" if last_template else "running",
                    "source": payload.source,
                    "data": template.model_dump(),
                    "result": result.model_dump() if result else None,
                }
            )

        def callback_start(template, last_template: bool):
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "template_applying",
                    "source": payload.source,
                    "data": template.model_dump(),
                }
            )

        await self.world_state_manager.apply_templates(
            payload.templates,
            callback_start=callback_start,
            callback_done=callback_done,
            character_name=payload.character_name,
            run_immediately=payload.run_immediately,
            generation_options=payload.generation_options,
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "templates_applied",
                "source": payload.source,
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_world({})
        await self.handle_get_templates({})
        await self.signal_operation_done()

    async def handle_save_template_group(self, data):
        payload = SaveWorldStateTemplateGroupPayload(**data)
        group = payload.group
        log.debug("Save template group", group=group)

        await self.world_state_manager.save_template_group(group)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "template_group_saved",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_templates({})
        await self.signal_operation_done()

    async def handle_delete_template_group(self, data):

        payload = DeleteWorldStateTemplateGroupPayload(**data)
        group = payload.group

        log.debug("Remove template group", group=group)

        await self.world_state_manager.remove_template_group(group)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "template_group_deleted",
                "data": payload.model_dump(),
            }
        )

        await self.handle_get_templates({})
        await self.signal_operation_done()

    async def handle_generate_character_dialogue_instructions(self, data):
        payload = SelectiveCharacterPayload(**data)

        log.debug("Generate character dialogue instructions", name=payload.name)

        character = self.scene.get_character(payload.name)

        if not character:
            log.error("Character not found", name=payload.name)
            return

        creator = get_agent("creator")

        instructions = await creator.determine_character_dialogue_instructions(
            character
        )

        character.dialogue_instructions = instructions

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_dialogue_instructions_generated",
                "data": {
                    "name": payload.name,
                    "instructions": instructions,
                },
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_delete_character(self, data):
        payload = SelectiveCharacterPayload(**data)
        character = self.scene.get_character(payload.name)

        if not character:
            log.error("Character not found", name=payload.name)
            return

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_deleted",
                "data": {
                    "name": payload.name,
                },
            }
        )

        await self.scene.remove_actor(character.actor)
        await self.signal_operation_done()
        await self.handle_get_character_list({})
        self.scene.emit_status()

    async def handle_activate_character(self, data):
        payload = SelectiveCharacterPayload(**data)
        character = self.scene.get_character(payload.name)

        if not character:
            log.error("Character not found", name=payload.name)
            return

        await self.world_state_manager.activate_character(character.name)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_activated",
                "data": {
                    "name": payload.name,
                },
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_deactivate_character(self, data):
        payload = SelectiveCharacterPayload(**data)
        character = self.scene.get_character(payload.name)

        if not character:
            log.error("Character not found", name=payload.name)
            return

        await self.world_state_manager.deactivate_character(character.name)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_deactivated",
                "data": {
                    "name": payload.name,
                },
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_create_character(self, data):
        payload = CreateCharacterPayload(**data)

        character = await self.world_state_manager.create_character(
            generate=payload.generate,
            instructions=payload.instructions,
            name=payload.name,
            description=payload.description,
            is_player=payload.is_player,
            generate_attributes=payload.generate_attributes,
            generation_options=payload.generation_options,
            active=payload.is_player or not self.scene.has_active_npcs,
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "character_created",
                "data": {
                    "name": character.name,
                    "description": character.description,
                },
            }
        )

        await self.handle_get_character_list({})
        await self.handle_get_character_details({"name": character.name})
        await self.signal_operation_done()

        self.scene.emit_status()

    async def handle_update_scene_outline(self, data):
        payload = SceneOutlinePayload(**data)

        await self.world_state_manager.update_scene_outline(**payload.model_dump())

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "scene_outline_updated",
                "data": payload.model_dump(),
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()
        await self.scene.emit_history()

    async def handle_update_scene_settings(self, data):
        payload = SceneSettingsPayload(**data)

        await self.world_state_manager.update_scene_settings(**payload.model_dump())

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "scene_settings_updated",
                "data": payload.model_dump(),
            }
        )

        await self.signal_operation_done()
        self.scene.emit_status()

    async def handle_export_scene(self, data):
        payload = ExportOptions(**data)
        scene_data = await export(self.scene, payload)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "scene_exported",
                "data": scene_data,
            }
        )
        await self.signal_operation_done()

    async def handle_save_scene(self, data):
        payload = SaveScenePayload(**data)

        log.debug("Save scene", copy=payload.save_as)

        await self.scene.save(auto=False, force=True, copy_name=payload.save_as)
        self.scene.emit_status()

    async def handle_request_scene_history(self, data):
        history = history_with_relative_time(self.scene.archived_history, self.scene.ts)

        self.websocket_handler.queue_put(
            {"type": "world_state_manager", "action": "scene_history", "data": history}
        )

    async def handle_regenerate_history(self, data):

        payload = RegenerateHistoryPayload(**data)

        def callback():
            self.websocket_handler.queue_put(
                {
                    "type": "world_state_manager",
                    "action": "history_entry_added",
                    "data": history_with_relative_time(
                        self.scene.archived_history, self.scene.ts
                    ),
                }
            )

        await rebuild_history(
            self.scene, callback=callback, generation_options=payload.generation_options
        )

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "history_regenerated",
                "data": payload.model_dump(),
            }
        )

        await self.signal_operation_done()
        await self.handle_request_scene_history(data)
