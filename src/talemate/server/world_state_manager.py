import pydantic
import structlog

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
        
        print("DELETED")

        # resend character details
        await self.handle_get_character_details({"name":payload.name})
        await self.signal_operation_done()
