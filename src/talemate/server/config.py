import pydantic
import structlog
from talemate import VERSION

from talemate.config import Config as AppConfigData, load_config, save_config

log = structlog.get_logger("talemate.server.config")

class ConfigPayload(pydantic.BaseModel):
    config: AppConfigData
    
class DefaultCharacterPayload(pydantic.BaseModel):
    name: str
    gender: str
    description: str
    color: str = "#3362bb"
    
class ConfigPlugin:
    
    router = "config"
    
    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler
    
    async def handle(self, data:dict):
        
        log.info("Config action", action=data.get("action"))
        
        fn = getattr(self, f"handle_{data.get('action')}", None)
        
        if fn is None:
            return
        
        await fn(data)
        
    async def handle_save(self, data):
        
        app_config_data = ConfigPayload(**data)
        current_config = load_config()
        
        current_config.update(app_config_data.dict().get("config"))
        
        save_config(current_config)
        
        self.websocket_handler.config = current_config
        self.websocket_handler.queue_put({
            "type": "app_config",
            "data": load_config(),
            "version": VERSION
        })
        self.websocket_handler.queue_put({
            "type": "config",
            "action": "save_complete",
        }) 
        
    async def handle_save_default_character(self, data):
        
        log.info("Saving default character", data=data["data"])
        
        payload = DefaultCharacterPayload(**data["data"])
        
        current_config = load_config()
        
        current_config["game"]["default_player_character"] = payload.model_dump()
        
        log.info("Saving default character", character=current_config["game"]["default_player_character"])
        
        save_config(current_config)
        
        self.websocket_handler.config = current_config
        self.websocket_handler.queue_put({
            "type": "app_config",
            "data": load_config(),
            "version": VERSION
        })
        self.websocket_handler.queue_put({
            "type": "config",
            "action": "save_default_character_complete",
        })
        
