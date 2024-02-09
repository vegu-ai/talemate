import io
import base64
from PIL import Image
import httpx
import structlog

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)

from .handlers import register
from .schema import Resolution, RenderSettings
from .style import STYLE_MAP

log = structlog.get_logger("talemate.agents.visual.automatic1111")



@register(backend_name="automatic1111", label="AUTOMATIC1111")
class Automatic1111Mixin:
    
    automatic1111_default_render_settings = RenderSettings()
    
    EXTEND_ACTIONS = {
        "automatic1111": AgentAction(
            enabled=False,
            condition=AgentActionConditional(
                attribute="_config.config.backend",
                value="automatic1111"
            ),
            label="Automatic1111 Advanced Settings",
            description="Setting overrides for the automatic1111 backend",
            config={
                "steps": AgentActionConfig(
                    type="number",
                    value=40,
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
    def automatic1111_render_settings(self):
        if self.actions["automatic1111"].enabled:
            return RenderSettings(
                steps=self.actions["automatic1111"].config["steps"].value,
                type_model=self.actions["automatic1111"].config["model_type"].value,
            )
        else:
            return self.automatic1111_default_render_settings
    
    async def automatic1111_generate(self, prompt:str, resolution:Resolution):
        url = self.api_url
        render_settings = self.automatic1111_render_settings
        style = self.style
        prompt = f"{style}, {prompt}"
        payload = {
            "prompt": prompt,
            "negative_prompt": str(STYLE_MAP["negative_prompt_1"]),
            "steps": render_settings.steps,
            "width": resolution.width,
            "height": resolution.height,
        }
        
        
        log.info("automatic1111_generate", payload=payload, url=url)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url=f'{url}/sdapi/v1/txt2img', json=payload, timeout=90)
            
        r = response.json()
        
        image = Image.open(io.BytesIO(base64.b64decode(r['images'][0])))
        image.save('a1111-test.png')
        
        log.info("automatic1111_generate", saved_to="a1111-test.png")
            