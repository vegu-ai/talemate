import pydantic
import structlog
from typing import Union, Any
import uuid

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

class SetCharacterDetailReinforcementPayload(pydantic.BaseModel):
    name: str
    question: str
    instructions: str = None
    interval: int = 10
    answer: str = ""
    update_state: bool = False
    
class CharacterDetailReinforcementPayload(pydantic.BaseModel):
    name: str
    question: str
    
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
        
    async def handle(self, data:dict):
        
        log.info("World state manager action", action=data.get("action"))
        
        fn = getattr(self, f"handle_{data.get('action')}", None)
        
        if fn is None:
            return
        
        await fn(data)
        
    async def signal_operation_done(self):
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "operation_done",
            "data": {}
        })
        
    async def handle_get_character_list(self, data):
        character_list = await self.world_state_manager.get_character_list()
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_list",
            "data": character_list.model_dump()
        })
        
    async def handle_get_character_details(self, data):
        character_details = await self.world_state_manager.get_character_details(data["name"])
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_details",
            "data": character_details.model_dump()
        })
        
    async def handle_get_pins(self, data):
        context_pins = await self.world_state_manager.get_pins()
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "pins",
            "data": context_pins.model_dump()
        })
        
    async def handle_update_character_attribute(self, data):

        payload = UpdateCharacterAttributePayload(**data)
        
        await self.world_state_manager.update_character_attribute(payload.name, payload.attribute, payload.value)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_attribute_updated",
            "data": payload.model_dump()
        })
        
        # resend character details
        await self.handle_get_character_details({"name":payload.name})
        
        await self.signal_operation_done()
        
    async def handle_update_character_description(self, data):
        
        payload = UpdateCharacterAttributePayload(**data)
        
        await self.world_state_manager.update_character_description(payload.name, payload.value)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_description_updated",
            "data": payload.model_dump()
        })
        
        # resend character details
        await self.handle_get_character_details({"name":payload.name})
        await self.signal_operation_done()
        
    async def handle_update_character_detail(self, data):
        
        payload = UpdateCharacterDetailPayload(**data)
        
        await self.world_state_manager.update_character_detail(payload.name, payload.detail, payload.value)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_detail_updated",
            "data": payload.model_dump()
        })

        # resend character details
        await self.handle_get_character_details({"name":payload.name})
        await self.signal_operation_done()
        
    async def handle_set_character_detail_reinforcement(self, data):
        
        payload = SetCharacterDetailReinforcementPayload(**data)
        
        await self.world_state_manager.add_detail_reinforcement(
            payload.name, 
            payload.question, 
            payload.instructions, 
            payload.interval, 
            payload.answer,
            payload.update_state
        )
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_detail_reinforcement_set",
            "data": payload.model_dump()
        })

        # resend character details
        await self.handle_get_character_details({"name":payload.name})
        await self.signal_operation_done()
        
    async def handle_run_character_detail_reinforcement(self, data):
        
        payload = CharacterDetailReinforcementPayload(**data)
        
        await self.world_state_manager.run_detail_reinforcement(payload.name, payload.question)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_detail_reinforcement_run",
            "data": payload.model_dump()
        })

        # resend character details
        await self.handle_get_character_details({"name":payload.name})
        await self.signal_operation_done()
        
    async def handle_delete_character_detail_reinforcement(self, data):
        
        payload = CharacterDetailReinforcementPayload(**data)
        
        await self.world_state_manager.delete_detail_reinforcement(payload.name, payload.question)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "character_detail_reinforcement_deleted",
            "data": payload.model_dump()
        })
        
        # resend character details
        await self.handle_get_character_details({"name":payload.name})
        await self.signal_operation_done()


    async def handle_query_context_db(self, data):
        
        payload = QueryContextDBPayload(**data)
        
        log.debug("Query context db", query=payload.query, meta=payload.meta)
        
        context_db = await self.world_state_manager.get_context_db_entries(payload.query, **payload.meta)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "context_db_result",
            "data": context_db.model_dump()
        })
        
        await self.signal_operation_done()
        
    async def handle_update_context_db(self, data):
        
        payload = UpdateContextDBPayload(**data)
        
        log.debug("Update context db", text=payload.text, meta=payload.meta, id=payload.id)
        
        await self.world_state_manager.update_context_db_entry(payload.id, payload.text, payload.meta)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "context_db_updated",
            "data": payload.model_dump()
        })
        
        await self.signal_operation_done()
        
    async def handle_delete_context_db(self, data):
        
        payload = DeleteContextDBPayload(**data)
        
        log.debug("Delete context db", id=payload.id)
        
        await self.world_state_manager.delete_context_db_entry(payload.id)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "context_db_deleted",
            "data": payload.model_dump()
        })
        
        await self.signal_operation_done()
        
    async def handle_set_pin(self, data):
        
        payload = UpdatePinPayload(**data)
        
        log.debug("Set pin", entry_id=payload.entry_id, condition=payload.condition, condition_state=payload.condition_state, active=payload.active)
        
        await self.world_state_manager.set_pin(payload.entry_id, payload.condition, payload.condition_state, payload.active)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "pin_set",
            "data": payload.model_dump()
        })
        
        await self.handle_get_pins({})
        await self.signal_operation_done()
        await self.scene.load_active_pins()
        self.scene.emit_status()
        
    async def handle_remove_pin(self, data):
        
        payload = RemovePinPayload(**data)
        
        log.debug("Remove pin", entry_id=payload.entry_id)
        
        await self.world_state_manager.remove_pin(payload.entry_id)
        
        self.websocket_handler.queue_put({
            "type": "world_state_manager",
            "action": "pin_removed",
            "data": payload.model_dump()
        })
        
        await self.handle_get_pins({})
        await self.signal_operation_done()
        await self.scene.load_active_pins()
        self.scene.emit_status()
        