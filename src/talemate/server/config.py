import pydantic
import structlog
from talemate import VERSION

from talemate.config import Config as AppConfigData, load_config, save_config
from talemate.client.model_prompts import model_prompt

log = structlog.get_logger("talemate.server.config")

class ConfigPayload(pydantic.BaseModel):
    config: AppConfigData
    
class DefaultCharacterPayload(pydantic.BaseModel):
    name: str
    gender: str
    description: str
    color: str = "#3362bb"
    

class SetLLMTemplatePayload(pydantic.BaseModel):
    template_file: str
    model_name: str
    
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
    
    async def handle_request_std_llm_templates(self, data):
            
        log.info("Requesting std llm templates")
        
        self.websocket_handler.queue_put({
            "type": "config",
            "action": "std_llm_templates",
            "data": {
                "templates": model_prompt.std_templates,
            }
        })
    
    async def handle_set_llm_template(self, data):
        
        print(data)
        
        payload = SetLLMTemplatePayload(**data["data"])
        
        copied_to = model_prompt.create_user_override(payload.template_file, payload.model_name)
        
        log.info("Copied template", copied_to=copied_to, template=payload.template_file, model_name=payload.model_name)
        
        prompt_template_example, prompt_template_file = model_prompt(payload.model_name, "sysmsg", "prompt<|BOT|>{LLM coercion}")
        
        self.websocket_handler.queue_put({
            "type": "config",
            "action": "set_llm_template_complete",
            "data": {
                "prompt_template_example": prompt_template_example,
                "has_prompt_template": True if prompt_template_example else False,
                "template_file": prompt_template_file,
            }
        })
