import structlog
from openai import AsyncOpenAI

from talemate.agents.base import (
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
)

from .handlers import register
from .schema import RenderSettings, Resolution
from .style import Style

log = structlog.get_logger("talemate.agents.visual.nanogpt_image")


@register(backend_name="nanogpt_image", label="NanoGPT")
class NanoGPTImageMixin:
    nanogpt_image_default_render_settings = RenderSettings()

    EXTEND_ACTIONS = {
        "nanogpt_image": AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value="nanogpt_image"
            ),
            label="NanoGPT",
            description="Settings for the NanoGPT image backend",
            config={
                "api_url": AgentActionConfig(
                    type="text",
                    value="https://nano-gpt.com",
                    label="API URL",
                    description="Base URL (without /v1)",
                ),
                "api_key": AgentActionConfig(
                    type="text",
                    value="",
                    label="API Key",
                    description="NanoGPT API Key (Authorization: Bearer)",
                ),
                "model_type": AgentActionConfig(
                    type="text",
                    value="hidream",
                    choices=[
                        {"value": "hidream", "label": "HiDream"},
                        {"value": "recraft-v3", "label": "Recraft v3"},
                    ],
                    label="Model Type",
                    description="Image generation model",
                ),
            },
        )
    }

    @property
    def nanogpt_api_url(self):
        url = self.actions["nanogpt_image"].config["api_url"].value
        if url.endswith("/"):
            url = url[:-1]
        return url

    @property
    def nanogpt_api_key(self):
        return self.actions["nanogpt_image"].config["api_key"].value

    @property
    def nanogpt_model_type(self):
        return self.actions["nanogpt_image"].config["model_type"].value

    async def nanogpt_image_generate(self, prompt: Style, format: str):
        if not self.nanogpt_api_key:
            raise ValueError("NanoGPT API Key not set")

        base_url = f"{self.nanogpt_api_url}/v1"
        client = AsyncOpenAI(base_url=base_url, api_key=self.nanogpt_api_key)

        if format == "portrait":
            resolution = Resolution(width=1024, height=1024)
        elif format == "landscape":
            resolution = Resolution(width=1024, height=1024)
        else:
            resolution = Resolution(width=1024, height=1024)

        log.debug("nanogpt_image_generate", resolution=resolution, base_url=base_url)

        response = await client.images.generate(
            model=self.nanogpt_model_type,
            prompt=prompt.positive_prompt,
            size=f"{resolution.width}x{resolution.height}",
            n=1,
            response_format="b64_json",
            timeout=self.generate_timeout,
        )

        await self.emit_image(response.data[0].b64_json)

    async def nanogpt_image_ready(self) -> bool:
        if not self.nanogpt_api_key:
            raise ValueError("NanoGPT API Key not set")
        return True
