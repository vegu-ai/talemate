import base64
import io
from urllib.parse import unquote

import httpx
import structlog
from openai import AsyncOpenAI
from PIL import Image

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)

from .handlers import register
from .schema import RenderSettings, Resolution
from .style import STYLE_MAP, Style

log = structlog.get_logger("talemate.agents.visual.openai_image")


@register(backend_name="openai_image", label="OpenAI")
class OpenAIImageMixin:

    openai_image_default_render_settings = RenderSettings()

    EXTEND_ACTIONS = {
        "openai_image": AgentAction(
            enabled=False,
            condition=AgentActionConditional(
                attribute="_config.config.backend", value="openai_image"
            ),
            label="OpenAI Image Generation Advanced Settings",
            description="Setting overrides for the openai backend",
            config={
                "model_type": AgentActionConfig(
                    type="text",
                    value="dall-e-3",
                    choices=[
                        {"value": "dall-e-3", "label": "DALL-E 3"},
                        {"value": "dall-e-2", "label": "DALL-E 2"},
                    ],
                    label="Model Type",
                    description="Image generation model",
                ),
                "quality": AgentActionConfig(
                    type="text",
                    value="standard",
                    choices=[
                        {"value": "standard", "label": "Standard"},
                        {"value": "hd", "label": "HD"},
                    ],
                    label="Quality",
                    description="Image generation quality",
                ),
            },
        )
    }

    @property
    def openai_api_key(self):
        return self.config.get("openai", {}).get("api_key")

    @property
    def openai_model_type(self):
        return self.actions["openai_image"].config["model_type"].value

    @property
    def openai_quality(self):
        return self.actions["openai_image"].config["quality"].value

    async def openai_image_generate(self, prompt: Style, format: str):
        """
        #
        from openai import OpenAI
        client = OpenAI()

        response = client.images.generate(
            model="dall-e-3",
            prompt="a white siamese cat",
            size="1024x1024",
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url
        """

        client = AsyncOpenAI(api_key=self.openai_api_key)

        # When using DALL·E 3, images can have a size of 1024x1024, 1024x1792 or 1792x1024 pixels.#

        if format == "portrait":
            resolution = Resolution(width=1024, height=1792)
        elif format == "landscape":
            resolution = Resolution(width=1792, height=1024)
        else:
            resolution = Resolution(width=1024, height=1024)

        log.debug("openai_image_generate", resolution=resolution)

        response = await client.images.generate(
            model=self.openai_model_type,
            prompt=prompt.positive_prompt,
            size=f"{resolution.width}x{resolution.height}",
            quality=self.openai_quality,
            n=1,
        )

        download_url = response.data[0].url

        # decode url because httpx will encode it again
        download_url = unquote(download_url)
        log.debug("openai_image_generate", download_url=download_url)

        async with httpx.AsyncClient() as client:
            response = await client.get(download_url, timeout=90)
            log.debug("openai_image_generate", status_code=response.status_code)
            if response.status_code >= 400:
                raise ValueError(f"Error downloading image: {response.content}")
            # bytes to base64encoded
            image = base64.b64encode(response.content).decode("utf-8")
            await self.emit_image(image)

    async def openai_image_ready(self) -> bool:
        """
        Will send a GET to /sdapi/v1/memory and on 200 will return True
        """

        if not self.openai_api_key:
            raise ValueError("OpenAI API Key not set")

        return True
