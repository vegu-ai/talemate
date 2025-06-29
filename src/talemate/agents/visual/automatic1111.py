import httpx
import structlog

from talemate.agents.base import (
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
)

from .handlers import register
from .schema import RenderSettings
from .style import Style

log = structlog.get_logger("talemate.agents.visual.automatic1111")


SAMPLING_METHODS = [
    {"value": "DPM++ 2M", "label": "DPM++ 2M"},
    {"value": "DPM++ SDE", "label": "DPM++ SDE"},
    {"value": "DPM++ 2M SDE", "label": "DPM++ 2M SDE"},
    {"value": "DPM++ 2M SDE Heun", "label": "DPM++ 2M SDE Heun"},
    {"value": "DPM++ 2S a", "label": "DPM++ 2S a"},
    {"value": "DPM++ 3M SDE", "label": "DPM++ 3M SDE"},
    {"value": "Euler a", "label": "Euler a"},
    {"value": "Euler", "label": "Euler"},
    {"value": "LMS", "label": "LMS"},
    {"value": "Heun", "label": "Heun"},
    {"value": "DPM2", "label": "DPM2"},
    {"value": "DPM2 a", "label": "DPM2 a"},
    {"value": "DPM fast", "label": "DPM fast"},
    {"value": "DPM adaptive", "label": "DPM adaptive"},
    {"value": "Restart", "label": "Restart"},
]
SAMPLING_METHODS = sorted(SAMPLING_METHODS, key=lambda x: x["label"])


SAMPLING_SCHEDULES = [
    {"value": "Automatic", "label": "Automatic"},
    {"value": "Uniform", "label": "Uniform"},
    {"value": "Karras", "label": "Karras"},
    {"value": "Exponential", "label": "Exponential"},
    {"value": "polyPolyexponentialexponential", "label": "Polyexponential"},
    {"value": "SGM Uniform", "label": "SGM Uniform"},
    {"value": "KL Optimal", "label": "KL Optimal"},
    {"value": "Align Your Steps", "label": "Align Your Steps"},
    {"value": "Simple", "label": "Simple"},
    {"value": "Normal", "label": "Normal"},
    {"value": "DDIM", "label": "DDIM"},
    {"value": "Beta", "label": "Beta"},
]

SAMPLING_SCHEDULES = sorted(SAMPLING_SCHEDULES, key=lambda x: x["label"])


@register(backend_name="automatic1111", label="AUTOMATIC1111")
class Automatic1111Mixin:
    automatic1111_default_render_settings = RenderSettings()

    EXTEND_ACTIONS = {
        "automatic1111": AgentAction(
            enabled=True,
            container=True,
            condition=AgentActionConditional(
                attribute="_config.config.backend", value="automatic1111"
            ),
            icon="mdi-server-outline",
            label="AUTOMATIC1111",
            description="Settings for the currently selected AUTOMATIC1111 backend.",
            config={
                "api_url": AgentActionConfig(
                    type="text",
                    value="http://localhost:7860",
                    label="API URL",
                    description="The URL of the backend API",
                ),
                "steps": AgentActionConfig(
                    type="number",
                    value=40,
                    label="Steps",
                    min=5,
                    max=150,
                    step=1,
                    description="number of render steps",
                ),
                "sampling_method": AgentActionConfig(
                    type="text",
                    choices=SAMPLING_METHODS,
                    label="Sampling Method",
                    description="The sampling method to use",
                    value="DPM++ 2M",
                ),
                "schedule_type": AgentActionConfig(
                    type="text",
                    value="automatic",
                    choices=SAMPLING_SCHEDULES,
                    label="Schedule Type",
                    description="The sampling schedule to use",
                ),
                "cfg": AgentActionConfig(
                    type="number",
                    value=7,
                    label="CFG Scale",
                    description="CFG scale",
                    min=1,
                    max=30,
                    step=0.5,
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
            },
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

    @property
    def automatic1111_sampling_method(self):
        return self.actions["automatic1111"].config["sampling_method"].value

    @property
    def automatic1111_schedule_type(self):
        return self.actions["automatic1111"].config["schedule_type"].value

    @property
    def automatic1111_cfg(self):
        return self.actions["automatic1111"].config["cfg"].value

    async def automatic1111_generate(self, prompt: Style, format: str):
        url = self.api_url
        resolution = self.resolution_from_format(
            format, self.automatic1111_render_settings.type_model
        )
        render_settings = self.automatic1111_render_settings
        payload = {
            "prompt": prompt.positive_prompt,
            "negative_prompt": prompt.negative_prompt,
            "steps": render_settings.steps,
            "width": resolution.width,
            "height": resolution.height,
            "cfg_scale": self.automatic1111_cfg,
            "sampler_name": self.automatic1111_sampling_method,
            "scheduler": self.automatic1111_schedule_type,
        }

        log.info("automatic1111_generate", payload=payload, url=url)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=f"{url}/sdapi/v1/txt2img",
                json=payload,
                timeout=self.generate_timeout,
            )

        r = response.json()

        # image = Image.open(io.BytesIO(base64.b64decode(r['images'][0])))
        # image.save('a1111-test.png')

        #'log.info("automatic1111_generate", saved_to="a1111-test.png")

        for image in r["images"]:
            await self.emit_image(image)

    async def automatic1111_ready(self) -> bool:
        """
        Will send a GET to /sdapi/v1/memory and on 200 will return True
        """

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=f"{self.api_url}/sdapi/v1/memory", timeout=2
            )
            return response.status_code == 200
