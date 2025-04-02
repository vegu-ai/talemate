import pydantic
import structlog

from talemate.scene.schema import SceneIntent

log = structlog.get_logger("talemate.server.world_state_manager.scene_intent")

class SceneIntentMixin:
    
    async def handle_get_scene_intent(self, data:dict):
        
        scene_intent:SceneIntent = self.scene.intent_state
        
        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "get_scene_intent",
                "data": scene_intent.model_dump()
            }
        )
        
    async def handle_set_scene_intent(self, data:dict):
        
        scene_intent:SceneIntent = SceneIntent(**data)
        
        self.scene.intent_state = scene_intent
        
        log.debug("Scene intent set", scene_intent=scene_intent)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "set_scene_intent",
                "data": scene_intent.model_dump()
            }
        )

        await self.signal_operation_done()
        