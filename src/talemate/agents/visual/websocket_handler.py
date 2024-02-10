from typing import Union
import pydantic
import structlog

from .context import VisualContextState, VisualContext

from talemate.server.websocket_plugin import Plugin
from talemate.instance import get_agent

__all__ = [
    "VisualWebsocketHandler",
]

log = structlog.get_logger("talemate.server.visual")

class SetCoverImagePayload(pydantic.BaseModel):
    base64: str
    context: Union[VisualContextState, None] = None

class RegeneratePayload(pydantic.BaseModel):
    context: Union[VisualContextState, None] = None

class VisualWebsocketHandler(Plugin):
    router = "visual"
    
    async def handle_regenerate(self, data: dict):
        """
        Regenerate the image based on the context.
        """   
        
        payload = RegeneratePayload(**data)
        
        context = payload.context
        
        visual = get_agent("visual")
        
        with VisualContext(**context.model_dump()):
            await visual.generate(format="")
    
    async def handle_cover_image(self, data:dict):
        
        """
        Sets the cover image for a character and the scene.
        """
        
        payload = SetCoverImagePayload(**data)
        
        context = payload.context
        scene = self.scene
        
        if context and context.character_name:
            
            character = scene.get_character(context.character_name)
            
            if not character:
                log.error("character not found", character_name=context.character_name)
                return
            
            asset = scene.assets.add_asset_from_image_data(payload.base64)
            
            log.info("setting scene cover image", character_name=context.character_name)
            scene.assets.cover_image = asset.id
            
            log.info("setting character cover image", character_name=context.character_name)
            character.cover_image = asset.id
            
            scene.emit_status()
            self.websocket_handler.request_scene_assets([asset.id])
            
            self.websocket_handler.queue_put(
                {
                    "type": "scene_asset_character_cover_image",
                    "asset_id": asset.id,
                    "asset": self.scene.assets.get_asset_bytes_as_base64(asset.id),
                    "media_type": asset.media_type,
                    "character": character.name,
                }
            )
            return