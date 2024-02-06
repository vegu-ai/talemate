import structlog

from talemate.client.base import ClientBase
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)

from .handlers import HANDLERS
from .schema import RenderSettings, RESOLUTION_MAP
from .commands import * # noqa
from .style import STYLE_MAP, combine_styles

import talemate.agents.visual.automatic1111

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
    
    default_render_settings = RenderSettings()
    
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
                }
            ),
            "advanced_render_settings": AgentAction(
                enabled=False,
                label="Advanced Render Settings",
                description="Advanced render settings",
                config={
                    "steps": AgentActionConfig(
                        type="number",
                        value=25,
                        label="Steps",
                        min=5,
                        max=150,
                        step=1,
                        description="number of render steps",
                    ),
                    "model_type": AgentActionConfig(
                        type="text",
                        value="sdxl",
                        choices=[
                            {"value": "sdxl", "label": "SDXL"},
                            {"value": "sd15", "label": "SD1.5"},
                        ],
                        label="Model Type",
                        description="Right now just differentiates between sdxl and sd15 - affect generation resolution",
                    ),
                }
            )
                
        }

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
    def render_settings(self):
        if self.actions["advanced_render_settings"].enabled:
            return RenderSettings(
                steps=self.actions["advanced_render_settings"].config["steps"].value,
                type_model=self.actions["advanced_render_settings"].config["model_type"].value,
            )
        else:
            return self.default_render_settings

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
    def model_type(self):
        return self.render_settings.type_model
    
    @property
    def style(self):
        return combine_styles(STYLE_MAP["concept_art"], STYLE_MAP["anime"])
        
    def resolution_from_format(self, format:str):
        if self.model_type == "sdxl":
            resmap = RESOLUTION_MAP["sdxl"]        
        elif self.model_type == "sd15":
            resmap = RESOLUTION_MAP["sd15"]
        else:
            resmap = RESOLUTION_MAP["sdxl"]
            
        return resmap.get(format, resmap["portrait"])
    
    @set_processing
    async def generate(self, prompt:str, format:str="portrait"):
        
        backend = self.backend
        fn = f"{backend.lower()}_generate"
        
        resolution = self.resolution_from_format(format)
        
        log.info("generate", backend=backend, prompt=prompt, format=format, resolution=resolution)
        
        if not hasattr(self, fn):
            log.error("generate", error=f"Backend {backend} does not support generate")
        
        await getattr(self, fn)(prompt=prompt, resolution=resolution)
        
    
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
    async def generate_character_prompt(self, character_name:str):
        
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
            }
        )
        
        return response.strip()
        
        
        
    
# apply mixins to the agent (from HANDLERS dict[str, cls])

for mixin_backend, mixin in HANDLERS.items():
    VisualBase = type("VisualAgent", (mixin["cls"], VisualBase), {})
    

@register()
class VisualAgent(VisualBase):
    pass
    