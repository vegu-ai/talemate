import os
import pydantic
import asyncio


import structlog

from talemate.prompts import Prompt
from talemate.tale_mate import Character, Actor, Player

log = structlog.get_logger("talemate.server.character_creator")

    
class StepData(pydantic.BaseModel):
    template: str
    is_player_character: bool
    use_spice: float
    character_prompt: str
    dialogue_guide: str
    dialogue_examples: list[str]
    base_attributes: dict[str, str] = {}
    custom_attributes: dict[str, str] = {}
    details: dict[str, str] = {}
    description: str = None
    questions: list[str] = []
    scenario_context: str = None
    
class CharacterCreationData(pydantic.BaseModel):
    base_attributes: dict[str, str] = {}
    is_player_character: bool = False
    character: object = None
    initial_prompt: str = None
    scenario_context: str = None
    

class CharacterCreatorServerPlugin:
    
    router = "character_creator"
    
    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler
        self.character_creation_data = None
    
    @property
    def scene(self):
        return self.websocket_handler.scene
    
    async def handle(self, data:dict):
        
        action = data.get("action")
        
        log.info("Character creator action", action=action)
        
        if action == "submit":
            
            step = data.get("step")
        
            fn = getattr(self, f"handle_submit_step{step}", None)
            
            if fn is None:
                raise NotImplementedError(f"Unknown step {step}")
            
            return await fn(data)
        
        elif action == "request_templates":
            return await self.handle_request_templates(data)
        
    
    async def handle_request_templates(self, data:dict):
        choices = Prompt.get("creator.character-human",{}).list_templates("character-attributes-*.jinja2")
        
        # each choice is a filename, we want to remove the extension and the directory
        choices = [os.path.splitext(os.path.basename(c))[0] for c in choices]
        
        # finally also strip the 'character-' prefix
        choices = [c.replace("character-attributes-", "") for c in choices]
        
        self.websocket_handler.queue_put({
            "type": "character_creator",
            "action": "send_templates",
            "templates": sorted(choices),
            "content_context": self.websocket_handler.config["creator"]["content_context"],
        })
        
        await asyncio.sleep(0.01)

    
    
    def apply_step_data(self, data:dict):
        step_data = StepData(**data)
        if not self.character_creation_data:
            self.character_creation_data = CharacterCreationData(
                initial_prompt=step_data.character_prompt,
                scenario_context=step_data.scenario_context,
                is_player_character=step_data.is_player_character,
            )

        character=Character(
            name="",
            description="",
            greeting_text="",
            color="red",
            is_player=step_data.is_player_character,
        )
        character.base_attributes = step_data.base_attributes
        character.name = step_data.base_attributes.get("name")
        character.description = step_data.description
        character.details = step_data.details
        character.gender = step_data.base_attributes.get("gender")
        character.color = "red"
        character.example_dialogue = step_data.dialogue_examples
        
        return character, step_data
    
    async def handle_submit_step2(self, data:dict):
        creator = self.scene.get_helper("creator").agent
        character, step_data = self.apply_step_data(data)
                
        self.emit_step_start(2)
        def emit_attribute(name, value):
            self.websocket_handler.queue_put({
                "type": "character_creator",
                "action": "base_attribute",
                "name": name,
                "value": value,
            })
        
        base_attributes = await creator.create_character_attributes(
            step_data.character_prompt,
            step_data.template,
            use_spice=step_data.use_spice,
            attribute_callback=emit_attribute,
            content_context=step_data.scenario_context,
            custom_attributes=step_data.custom_attributes,
            predefined_attributes=step_data.base_attributes,
        )
        
        base_attributes["scenario_context"] = step_data.scenario_context
        
        character.base_attributes = base_attributes
        character.gender = base_attributes["gender"]
        character.name = base_attributes["name"]
        
        log.info("Created character", name=base_attributes.get("name"))
        
        self.emit_step_done(2)
        
    async def handle_submit_step3(self, data:dict):
        
        creator = self.scene.get_helper("creator").agent
        character, _ = self.apply_step_data(data)
        
        self.emit_step_start(3)
        
        description = await creator.create_character_description(
            character,
            content_context=self.character_creation_data.scenario_context,
        )
        
        character.description = description
    
        self.websocket_handler.queue_put({
            "type": "character_creator",
            "action": "description",
            "description": description,
        })
        
        self.emit_step_done(3)

        
    async def handle_submit_step4(self, data:dict):
        
        creator = self.scene.get_helper("creator").agent
        character, step_data = self.apply_step_data(data)

        def emit_detail(question, answer):
            self.websocket_handler.queue_put({
                "type": "character_creator",
                "action": "detail",
                "question": question,
                "answer": answer,
            })
        
        self.emit_step_start(4)

        character_details = await creator.create_character_details(
            character,
            step_data.template,
            detail_callback=emit_detail,
            questions=step_data.questions,
            content_context=self.character_creation_data.scenario_context,
        )
        character.details = list(character_details.values())
        
        self.emit_step_done(4)

    
    async def handle_submit_step5(self, data:dict):
            
        creator = self.scene.get_helper("creator").agent
        character, step_data = self.apply_step_data(data)
        
        self.websocket_handler.queue_put({
            "type": "character_creator",
            "action": "set_generating_step",
            "step": 5,
        }) 
        
        def emit_example(key, example):
            self.websocket_handler.queue_put({
                "type": "character_creator",
                "action": "example_dialogue",
                "example": example,
            })
        
        dialogue_guide = await creator.create_character_example_dialogue(
            character,
            step_data.template,
            step_data.dialogue_guide,
            examples=step_data.dialogue_examples,
            content_context=self.character_creation_data.scenario_context,
            example_callback=emit_example,
        )
        
        character.dialogue_guide = dialogue_guide
        self.emit_step_done(5)
        
        
    async def handle_submit_step6(self, data:dict):
        character, step_data = self.apply_step_data(data)
        
        # check if acter with character name already exists
        
        for actor in self.scene.actors:
            if actor.character.name == character.name:
                
                if character.is_player and not actor.character.is_player:
                    log.info("Character already exists, but is not a player", name=character.name)
                    
                    await self.scene.remove_actor(actor)
                    break
                
                log.info("Character already exists", name=character.name)
                actor.character = character
                self.scene.emit_status()
                self.emit_step_done(6)
                return
         
        if character.is_player:
            actor = Player(character, self.scene.get_helper("conversation").agent)
        else:
            actor = Actor(character, self.scene.get_helper("conversation").agent)
        
        log.info("Adding actor", name=character.name, actor=actor)
        
        character.base_attributes["scenario_context"] = step_data.scenario_context
        character.base_attributes["_template"] = step_data.template
        character.base_attributes["_prompt"] = step_data.character_prompt
        
        
        await self.scene.add_actor(actor)
        self.scene.emit_status()
        self.emit_step_done(6)
        
    def emit_step_start(self, step):
        
        self.websocket_handler.queue_put({
            "type": "character_creator",
            "action": "set_generating_step",
            "step": step,
        }) 

        
    def emit_step_done(self, step):
        
        self.websocket_handler.queue_put({
            "type": "character_creator",
            "action": "set_generating_step_done",
            "step": step,
        })
        

        