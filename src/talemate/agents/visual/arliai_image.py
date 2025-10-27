import httpx
import structlog

from talemate.agents.base import (
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
)

from .handlers import register
from .schema import RenderSettings, Resolution
from .style import Style

log = structlog.get_logger("talemate.agents.visual.arliai_image")


@register(backend_name="arliai_image", label="Arli AI")
class ArliAIImageMixin:
    arliai_image_default_render_settings = RenderSettings()

    EXTEND_ACTIONS = {
        "arliai_image": AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value="arliai_image"
            ),
            label="Arli AI",
            description="Settings for the Arli AI image backend",
            config={
                "api_url": AgentActionConfig(
                    type="text",
                    value="https://api.arliai.com",
                    label="API URL",
                    description="Base URL (without /v1)",
                ),
                "api_key": AgentActionConfig(
                    type="text",
                    value="",
                    label="API Key",
                    description="Arli AI API Key (Authorization: Bearer)",
                ),
                "model_type": AgentActionConfig(
                    type="text",
                    value="sdxl",
                    choices=[
                        {"value": "sdxl", "label": "SDXL"},
                        {"value": "sd15", "label": "SD1.5"},
                    ],
                    label="Model Type",
                    description="Determines default resolution presets",
                ),
                "sd_model_checkpoint": AgentActionConfig(
                    type="text",
                    value="",
                    label="Image Model",
                    description="Model checkpoint name for txt2img (sd_model_checkpoint)",
                ),
                "steps": AgentActionConfig(
                    type="number",
                    value=30,
                    label="Steps",
                    min=1,
                    max=40,
                    step=1,
                    description="Number of render steps (max 40)",
                ),
                "sampler_name": AgentActionConfig(
                    type="text",
                    value="DPM++ 2M Karras",
                    label="Sampler",
                    description="Sampler name",
                ),
                "cfg_scale": AgentActionConfig(
                    type="number",
                    value=7,
                    label="CFG Scale",
                    min=1,
                    max=30,
                    step=0.5,
                    description="CFG scale",
                ),
            },
        )
    }

    @property
    def arliai_api_url(self):
        url = self.actions["arliai_image"].config["api_url"].value
        if url.endswith("/"):
            url = url[:-1]
        return url

    @property
    def arliai_api_key(self):
        return self.actions["arliai_image"].config["api_key"].value

    @property
    def arliai_image_model(self):
        return self.actions["arliai_image"].config["sd_model_checkpoint"].value

    @property
    def arliai_model_type(self):
        return self.actions["arliai_image"].config["model_type"].value

    @property
    def arliai_steps(self):
        return self.actions["arliai_image"].config["steps"].value

    @property
    def arliai_sampler(self):
        return self.actions["arliai_image"].config["sampler_name"].value

    @property
    def arliai_cfg_scale(self):
        return self.actions["arliai_image"].config["cfg_scale"].value

    async def arliai_image_generate(self, prompt: Style, format: str):
        if not self.arliai_api_key:
            raise ValueError("Arli AI API Key not set")
        if not self.arliai_image_model:
            raise ValueError("Arli AI image model (sd_model_checkpoint) not set")

        # Use shared resolution presets based on model type (sdxl/sd15)
        resolution = self.resolution_from_format(format, self.arliai_model_type)

        payload = {
            "prompt": prompt.positive_prompt,
            "negative_prompt": prompt.negative_prompt,
            "steps": self.arliai_steps,
            "sampler_name": self.arliai_sampler,
            "width": resolution.width,
            "height": resolution.height,
            "sd_model_checkpoint": self.arliai_image_model,
            "seed": -1,
            "cfg_scale": self.arliai_cfg_scale,
        }

        url = f"{self.arliai_api_url}/sdapi/v1/txt2img"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.arliai_api_key}",
        }

        log.debug("arliai_image_generate", url=url, payload=payload)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=url, json=payload, headers=headers, timeout=self.generate_timeout
            )

        data = response.json()
        images = data.get("images", []) if isinstance(data, dict) else []

        if not images:
            raise ValueError(f"No images returned: {data}")

        for image in images:
            await self.emit_image(image)

    async def arliai_image_ready(self) -> bool:
        if not self.arliai_api_key:
            raise ValueError("Arli AI API Key not set")
        # Check models endpoint quickly
        url = f"{self.arliai_api_url}/sdapi/v1/sd-models"
        headers = {
            "Authorization": f"Bearer {self.arliai_api_key}",
        }
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, timeout=2)
            return r.status_code == 200
