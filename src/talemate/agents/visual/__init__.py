import structlog
import asyncio
from talemate.client.base import ClientBase
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)

from .handlers import HANDLERS
from .schema import RenderSettings, RESOLUTION_MAP
from .commands import * # noqa
from .style import STYLE_MAP, combine_styles

import talemate.agents.visual.automatic1111
import talemate.agents.visual.comfyui

from talemate.agents.registry import register
from talemate.prompts.base import Prompt


__all__ = [
    "VisualAgent",
]

BACKENDS = [
    {"value": mixin_backend, "label": mixin["label"]} for mixin_backend, mixin in HANDLERS.items()
]

log = structlog.get_logger("talemate.agents.visual")


class VisualBase(Agent):
    """
    The visual agent
    """

    agent_type = "visual"
    verbose_name = "Visualizer"
    concurrent = True
    
    ACTIONS = {}
    
    def __init__(self, client: ClientBase, *kwargs):
        self.client = client
        self.is_enabled = True
        self.actions = {
            "_config": AgentAction(
                enabled=True,
                label="Configure",
                description="Visual agent configuration",
                config={
                    "backend": AgentActionConfig(
                        type="text",
                        choices=BACKENDS,
                        value="automatic1111",
                        label="Backend",
                        description="The backend to use for visual processing",
                    ),
                    "api_url": AgentActionConfig(
                        type="text",
                        value="http://localhost:7860",
                        label="API URL",
                        description="The URL of the backend API",
                    ),
                    "api_key": AgentActionConfig(
                        type="text",
                        value="",
                        label="API Key",
                        description="The API key for the backend",
                    ),
                }
            ),
            "process_in_background": AgentAction(
                enabled=False,
                label="Process in Background",
                description="Process the render in the background - make sure you have enough VRAM to load both the LLM and the stable diffusion model",
            ),                
        }
        
        for action_name, action in self.ACTIONS.items():
            self.actions[action_name] = action

    @property
    def enabled(self):
        return self.is_enabled

    @property
    def has_toggle(self):
        return True

    @property
    def experimental(self):
        return False
    
    @property
    def backend(self):
        return self.actions["_config"].config["backend"].value
    
    @property
    def backend_name(self):
        key = self.actions["_config"].config["backend"].value
        
        for backend in BACKENDS:
            if backend["value"] == key:
                return backend["label"]

    @property
    def ready(self):
        return True
    
    @property
    def api_url(self):
        return self.actions["_config"].config["api_url"].value

    @property
    def agent_details(self):
        return {
            "backend": AgentDetail(
                icon="mdi-server-outline",
                value=self.backend_name,
                description="The backend to use for visual processing",
            ).model_dump(),
            "client": AgentDetail(
                icon="mdi-network-outline",
                value=self.client.name if self.client else None,
                description="The client to use for prompt generation",
            ).model_dump(),
        }
        
    @property
    def style(self):
        return combine_styles(STYLE_MAP["concept_art"])
    
    @property
    def process_in_background(self):
        return self.actions["process_in_background"].enabled
        
    def resolution_from_format(self, format:str, model_type:str="sdxl"):
        if model_type not in RESOLUTION_MAP:
            raise ValueError(f"Model type {model_type} not found in resolution map")
        return RESOLUTION_MAP[model_type].get(format, RESOLUTION_MAP[model_type]["portrait"])
    
    @set_processing
    async def generate(self, prompt:str, format:str="portrait"):
        
        backend = self.backend
        fn = f"{backend.lower()}_generate"
        
        log.info("generate", backend=backend, prompt=prompt, format=format)
        
        if not hasattr(self, fn):
            log.error("generate", error=f"Backend {backend} does not support generate")
        
        # add the function call to the asyncio task queue
        
        if self.process_in_background:
            task = asyncio.create_task(getattr(self, fn)(prompt=prompt, format=format))
            await self.set_background_processing(task)
        else:
            await getattr(self, fn)(prompt=prompt, format=format)
        
    
    @set_processing
    async def generate_environment_prompt(self):
        
        response = await Prompt.request(
            "visual.generate-environment-prompt",
            self.client,
            "visualize",
            {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            }
        )
        
        return response.strip()
    
    @set_processing
    async def generate_character_prompt(
        self, 
        character_name:str,
        instructions:str=None
    ):
        
        character = self.scene.get_character(character_name)
        
        response = await Prompt.request(
            "visual.generate-character-prompt",
            self.client,
            "visualize",
            {
                "scene": self.scene,
                "character_name": character_name,
                "character": character,
                "max_tokens": self.client.max_token_length,
                "instructions": instructions or "",
            }
        )
        
        return response.strip()
        
        
        
    
# apply mixins to the agent (from HANDLERS dict[str, cls])

for mixin_backend, mixin in HANDLERS.items():
    mixin_cls = mixin["cls"]
    VisualBase = type("VisualAgent", (mixin_cls, VisualBase), {})
    
    extend_actions = getattr(mixin_cls, "EXTEND_ACTIONS", {})
    
    for action_name, action in extend_actions.items():
        VisualBase.ACTIONS[action_name] = action
    

@register()
class VisualAgent(VisualBase):
    pass
    