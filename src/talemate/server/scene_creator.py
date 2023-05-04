import os
import pydantic
import asyncio
import structlog
import json

from talemate.load import load_character_into_scene

log = structlog.get_logger("talemate.server.character_importer")
    
class ListScenesData(pydantic.BaseModel):
    scene_path: str
    
class CreateSceneData(pydantic.BaseModel):
    name: str = None
    description: str = None
    intro: str = None 
    content_context: str = None
    prompt: str = None

class SceneCreatorServerPlugin:
    
    router = "scene_creator"
    
    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler
    
    @property
    def scene(self):
        return self.websocket_handler.scene
    
    async def handle(self, data:dict):
        
        log.info("Scene importer action", action=data.get("action"))
        
        fn = getattr(self, f"handle_{data.get('action')}", None)
        
        if fn is None:
            return
        
        await fn(data)
        
    async def handle_generate_description(self, data):
        create_scene_data = CreateSceneData(**data)
        
        scene = self.websocket_handler.scene
        
        creator = scene.get_helper("creator").agent
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating",
        })
    
        description = await creator.create_scene_description(
            create_scene_data.prompt,
            create_scene_data.content_context,
        )
        
        log.info("Generated scene description", description=description)
    
        scene.description = description
        
        self.send_scene_update()
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating_done",
        })
        
    async def handle_generate_name(self, data):
        
        create_scene_data = CreateSceneData(**data)
        
        scene = self.websocket_handler.scene
        
        creator = scene.get_helper("creator").agent
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating",
        })
    
        name = await creator.create_scene_name(
            create_scene_data.prompt,
            create_scene_data.content_context,
            scene.description,
        )
        
        log.info("Generated scene name", name=name)
        
        scene.name = name
        
        self.send_scene_update()
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating_done",
        })
    
    async def handle_generate_intro(self, data):
        
        create_scene_data = CreateSceneData(**data)
        
        scene = self.websocket_handler.scene
        
        creator = scene.get_helper("creator").agent
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating",
        })
    
        intro = await creator.create_scene_intro(
            create_scene_data.prompt,
            create_scene_data.content_context,
            scene.description,
            scene.name,
        )
        
        log.info("Generated scene intro", intro=intro)
        
        scene.intro = intro
        
        self.send_scene_update()
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating_done",
        })
        
    async def handle_generate(self, data):
        create_scene_data = CreateSceneData(**data)
        
        scene = self.websocket_handler.scene
        
        creator = scene.get_helper("creator").agent
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating",
        })
    
        description = await creator.create_scene_description(
            create_scene_data.prompt,
            create_scene_data.content_context,
        )
        
        log.info("Generated scene description", description=description)

        name = await creator.create_scene_name(
            create_scene_data.prompt,
            create_scene_data.content_context,
            description,
        )
        
        log.info("Generated scene name", name=name)
        
        intro = await creator.create_scene_intro(
            create_scene_data.prompt,
            create_scene_data.content_context,
            description,
            name,
        )
        
        log.info("Generated scene intro", intro=intro)
        
        scene.name = name
        scene.description = description
        scene.intro = intro
        scene.scenario_context = create_scene_data.content_context
        
        self.send_scene_update()
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "set_generating_done",
        })
        
    async def handle_edit(self, data):
        scene = self.websocket_handler.scene
        create_scene_data = CreateSceneData(**data)
        
        scene.description = create_scene_data.description
        scene.name = create_scene_data.name
        scene.intro = create_scene_data.intro
        scene.scenario_context = create_scene_data.content_context
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "scene_saved",
        })
        
    async def handle_load(self, data):
        self.send_scene_update()
        await asyncio.sleep(0)
        
    def send_scene_update(self):
        scene = self.websocket_handler.scene
        
        self.websocket_handler.queue_put({
            "type": "scene_creator",
            "action": "scene_update",
            "description": scene.description,
            "name": scene.name,
            "intro": scene.intro,
        })