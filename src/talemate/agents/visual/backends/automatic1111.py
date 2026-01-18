import base64
import httpx
import structlog

from talemate.instance import get_agent
from talemate.agents.base import AgentAction, AgentActionConfig, AgentActionConditional
import talemate.agents.visual.backends as backends
from talemate.agents.visual.backends.utils import (
    normalize_api_url,
    get_resolution_choices,
)
from talemate.agents.visual.schema import (
    GenerationRequest,
    GenerationResponse,
    GEN_TYPE,
    PROMPT_TYPE,
)


log = structlog.get_logger("talemate.agents.visual.automatic1111")


BACKEND_NAME = "automatic1111"


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


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "AUTOMATIC1111"
    image_create = True
    image_edit = False
    image_analyzation = False
    description = "Stable Diffusion WebUI text-to-image backend via AUTOMATIC1111 API."

    api_url: str

    @property
    def instance_label(self) -> str:
        return self.api_url

    @property
    def generator_label(self) -> str | None:
        # Automatic1111 doesn't have model selection in config,
        # it uses whatever model is currently loaded in the instance
        return None

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    async def ready(self) -> backends.BackendStatus:
        try:
            # Ensure one non-blocking connection probe, with status updated via callback
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url=f"{normalize_api_url(self.api_url)}/sdapi/v1/samplers",
                    timeout=timeout,
                )
                ready = response.status_code == 200
                return backends.BackendStatus(
                    type=backends.BackendStatusType.OK
                    if ready
                    else backends.BackendStatusType.ERROR,
                    message=response.text if not ready else None,
                )
        except httpx.RequestError as e:
            log.error(
                "Failed to test connection to AUTOMATIC1111",
                error=str(e),
                api_url=self.api_url,
                timeout=timeout,
            )
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        steps = request.agent_config.get("steps") or request.sampler_settings.steps
        cfg_scale = request.agent_config.get("cfg_scale") or 7
        sampler_name = request.agent_config.get("sampler_name") or "DPM++ 2M"
        scheduler = request.agent_config.get("scheduler") or "Automatic"

        payload = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or "",
            "steps": steps,
            "width": request.resolution.width,
            "height": request.resolution.height,
            "cfg_scale": cfg_scale,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
        }

        log.info(
            "automatic1111.Backend.generate",
            payload=payload,
            api_url=self.api_url,
            request=request,
        )

        async with httpx.AsyncClient() as client:
            _response = await client.post(
                url=f"{normalize_api_url(self.api_url)}/sdapi/v1/txt2img",
                json=payload,
                timeout=self.generate_timeout,
            )
            _response.raise_for_status()

        r = _response.json()
        images = r.get("images", [])
        if images:
            # AUTOMATIC1111 returns base64-encoded images
            b64_data = images[0]
            try:
                response.generated = base64.b64decode(b64_data)
            except Exception:
                # Some deployments return data URLs; strip prefix if present
                if "," in b64_data:
                    response.generated = base64.b64decode(b64_data.split(",", 1)[1])
        return response

    async def cancel_request(self):
        """
        Cancel the current generation request by calling AUTOMATIC1111's /interrupt endpoint.
        """
        log.info("automatic1111.Backend.cancel_request", api_url=self.api_url)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url=f"{normalize_api_url(self.api_url)}/sdapi/v1/interrupt"
                )
                response.raise_for_status()
                log.info("automatic1111.Backend.cancel_request", response=response.text)
        except Exception as e:
            log.error(
                "automatic1111.Backend.cancel_request",
                error=str(e),
                api_url=self.api_url,
            )
            raise


class Automatic1111Mixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["automatic1111_image_create"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image",
            label="AUTOMATIC1111",
            subtitle="Text to image",
            description="Basic text to image generation configuration for AUTOMATIC1111.",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value=BACKEND_NAME
            ),
            config={
                "api_url": AgentActionConfig(
                    type="text",
                    value="http://localhost:7860",
                    label="API URL",
                    description="The URL of the AUTOMATIC1111 API",
                    save_on_change=True,
                ),
                "steps": AgentActionConfig(
                    title="Sampler Settings",
                    type="number",
                    value=40,
                    label="Steps",
                    min=5,
                    max=150,
                    step=1,
                    description="Number of render steps",
                ),
                "sampling_method": AgentActionConfig(
                    type="text",
                    choices=SAMPLING_METHODS,
                    value="DPM++ 2M",
                    label="Sampling Method",
                    description="The sampling method to use",
                ),
                "schedule_type": AgentActionConfig(
                    type="text",
                    value="Automatic",
                    choices=SAMPLING_SCHEDULES,
                    label="Schedule Type",
                    description="The sampling schedule to use",
                ),
                "cfg": AgentActionConfig(
                    type="number",
                    value=7,
                    label="CFG Scale",
                    description="Classifier-free guidance scale",
                    min=1,
                    max=30,
                    step=0.5,
                ),
                "prompt_type": AgentActionConfig(
                    type="text",
                    title="Prompt generation",
                    value=PROMPT_TYPE.KEYWORDS,
                    label="Prompting Type",
                    choices=PROMPT_TYPE.choices(),
                    description="Semantic style of the generated prompt.",
                ),
                "resolution_square": AgentActionConfig(
                    type="vector2",
                    title="Resolutions",
                    value=[1024, 1024],
                    label="Square",
                    description="The resolution to use for square images.",
                    choices=get_resolution_choices("square"),
                ),
                "resolution_portrait": AgentActionConfig(
                    type="vector2",
                    value=[832, 1216],
                    label="Portrait",
                    description="The resolution to use for portrait images.",
                    choices=get_resolution_choices("portrait"),
                ),
                "resolution_landscape": AgentActionConfig(
                    type="vector2",
                    value=[1216, 832],
                    label="Landscape",
                    description="The resolution to use for landscape images.",
                    choices=get_resolution_choices("landscape"),
                ),
            },
        )
        return actions

    async def automatic1111_backend(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend | None:
        backend = self.backend
        backend_instance_exists = isinstance(backend, Backend)
        api_url = self.actions["automatic1111_image_create"].config["api_url"].value

        gen_type = GEN_TYPE.TEXT_TO_IMAGE
        prompt_type = (
            self.actions["automatic1111_image_create"].config["prompt_type"].value
        )

        try:
            _api_url_changed = (
                old_config["automatic1111_image_create"].config["api_url"].value
                != api_url
            )
        except Exception:
            _api_url_changed = False

        _reinit = force or _api_url_changed or not backend_instance_exists

        if _reinit:
            log.debug(
                "reinitializing automatic1111 backend",
                api_url=api_url,
            )
            return Backend(api_url=api_url, gen_type=gen_type, prompt_type=prompt_type)

        backend.api_url = api_url
        return backend

    async def automatic1111_prepare_generation(
        self, request: GenerationRequest
    ) -> Backend:
        if not self.backend or not isinstance(self.backend, Backend):
            raise ValueError("AUTOMATIC1111 backend not available")
        action = self.actions["automatic1111_image_create"]
        request.agent_config["steps"] = action.config["steps"].value
        request.agent_config["sampler_name"] = action.config["sampling_method"].value
        request.agent_config["scheduler"] = action.config["schedule_type"].value
        request.agent_config["cfg_scale"] = action.config["cfg"].value
        request.resolution = self.resolution(request.format, action)
        return self.backend
