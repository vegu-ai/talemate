"""
Venice.ai image generation backend for Talemate's visual agent.

Modeled on openai_image.py. Text-to-image only (no edit / analysis).
Uses Venice's native POST /image/generate endpoint, which returns base64
images in JSON.

UNTESTED against a live Talemate install: verify the model name, supported
resolutions and any parameter errors against Venice's current docs/models list.
"""

import os
import base64

import httpx
import pydantic
import structlog

from talemate.instance import get_agent
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
)
from talemate.agents.visual.schema import (
    GenerationRequest,
    GenerationResponse,
    GEN_TYPE,
    Resolution,
    FORMAT_TYPE,
    PROMPT_TYPE,
)
import talemate.agents.visual.backends as backends


log = structlog.get_logger("talemate.agents.visual.venice")


BACKEND_NAME = "venice"
VENICE_BASE_URL = "https://api.venice.ai/api/v1"

# Venice validates sizes per model. Adjust if a model rejects these.
RESOLUTIONS = {
    FORMAT_TYPE.LANDSCAPE: (1216, 832),
    FORMAT_TYPE.PORTRAIT: (832, 1216),
    FORMAT_TYPE.SQUARE: (1024, 1024),
}


ASPECT_RATIOS = {
    FORMAT_TYPE.LANDSCAPE: "3:2",
    FORMAT_TYPE.PORTRAIT: "2:3",
    FORMAT_TYPE.SQUARE: "1:1",
}

# Models that rejected width/height (learned at runtime).
_ASPECT_RATIO_MODELS: set[str] = set()


def _aspect_ratio_payload(payload: dict, fmt: FORMAT_TYPE) -> dict:
    body = {k: v for k, v in payload.items() if k not in ("width", "height")}
    body["aspect_ratio"] = ASPECT_RATIOS.get(fmt, ASPECT_RATIOS[FORMAT_TYPE.SQUARE])
    return body


def _api_key(action_config_key: str | None = None) -> str | None:
    """Key from the agent setting, falling back to VENICE_API_KEY."""
    return action_config_key or os.environ.get("VENICE_API_KEY")


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "Venice"
    image_create = True
    image_edit = True
    image_analyzation = False
    description = "Venice.ai image generation and editing."

    model: str = "venice-sd35"
    api_key: str | None = None
    moderation: str = "auto"
    base_url: str = VENICE_BASE_URL
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.DESCRIPTIVE

    @property
    def instance_label(self) -> str:
        return self.model

    @property
    def generator_label(self) -> str | None:
        return self.model

    @property
    def max_references(self) -> int:
        return 0

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {_api_key(self.api_key)}"}

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 5) -> backends.BackendStatus:
        if not _api_key(self.api_key):
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message="Venice API key not set",
            )
        url = f"{self.base_url}/models"
        try:
            async with httpx.AsyncClient() as http:
                r = await http.get(url, headers=self._headers(), timeout=timeout)
                r.raise_for_status()
            return backends.BackendStatus(type=backends.BackendStatusType.OK)
        except Exception as e:
            log.error("venice.test_connection.error", url=url, error=str(e))
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            return await self._generate_edit(request, response)
        if request.gen_type != GEN_TYPE.TEXT_TO_IMAGE:
            raise ValueError("Venice backend only supports text to image and edit")

        url = f"{self.base_url}/image/generate"
        payload = {
            "model": self.model,
            "prompt": request.prompt,
            "width": request.resolution.width,
            "height": request.resolution.height,
            "format": "png",
            # /image/generate has no `moderation`; its equivalent is `safe_mode`
            # (auto = blur adult content, low = unblurred).
            "safe_mode": self.moderation != "low",
        }
        log.debug(
            "venice.generate",
            url=url,
            model=self.model,
            size=f"{payload['width']}x{payload['height']}",
        )

        async def _post(body: dict) -> httpx.Response:
            async with httpx.AsyncClient() as http:
                return await http.post(
                    url,
                    headers=self._headers(),
                    json=body,
                    timeout=self.generate_timeout,
                )

        if self.model in _ASPECT_RATIO_MODELS:
            payload = _aspect_ratio_payload(payload, request.format)
        r = await _post(payload)

        # Newer models reject width/height; remember and retry with aspect_ratio.
        if (
            r.status_code == 400
            and "aspect_ratio" in r.text
            and "width" in payload
        ):
            _ASPECT_RATIO_MODELS.add(self.model)
            log.debug("venice.generate.retry_aspect_ratio", model=self.model)
            r = await _post(_aspect_ratio_payload(payload, request.format))

        if r.status_code >= 400:
            # Surface the URL and body; Venice's error text names bad params.
            log.error(
                "venice.generate.error",
                url=url,
                status=r.status_code,
                body=r.text[:500],
            )
            raise ValueError(f"Venice returned {r.status_code} for {url}: {r.text[:300]}")

        images = r.json().get("images") or []
        if not images:
            raise ValueError("Venice image response contained no images")

        response.generated = base64.b64decode(images[0])
        return response

    async def _generate_edit(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        refs = list(request.reference_bytes or [])
        if not refs or not refs[0]:
            raise ValueError("Image edit requires at least one reference image")

        url = f"{self.base_url}/image/edit"
        # /image/edit takes a single image and returns binary image data.
        # aspect_ratio is left out so Venice infers it from the input image.
        data = {
            "model": self.model,
            "prompt": request.prompt,
            "safe_mode": "true" if self.moderation != "low" else "false",
        }
        log.debug("venice.edit", url=url, model=self.model)

        async with httpx.AsyncClient() as http:
            r = await http.post(
                url,
                headers=self._headers(),
                data=data,
                files={"image": ("image.png", refs[0], "image/png")},
                timeout=self.generate_timeout,
            )

        if r.status_code >= 400:
            log.error(
                "venice.edit.error", url=url, status=r.status_code, body=r.text[:500]
            )
            raise ValueError(f"Venice returned {r.status_code} for {url}: {r.text[:300]}")

        response.generated = r.content
        return response


class VeniceHandler(pydantic.BaseModel):
    backend: Backend
    action: AgentAction


class VeniceMixin:
    @classmethod
    def venice_shared_config(cls, model: str) -> dict[str, AgentActionConfig]:
        return {
            "api_key": AgentActionConfig(
                type="password",
                value="",
                label="Venice API Key",
                description="Falls back to the VENICE_API_KEY environment variable if empty.",
                save_on_change=True,
                scene_overridable=False,
            ),
            "model": AgentActionConfig(
                type="text",
                value=model,
                label="Model",
                description="Venice image model ID (see Venice's models list).",
                save_on_change=True,
                scene_overridable=False,
            ),
            "moderation": AgentActionConfig(
                type="text",
                value="auto",
                choices=[
                    {"label": "Auto (blur adult content)", "value": "auto"},
                    {"label": "Low (no blurring)", "value": "low"},
                ],
                label="Moderation",
                description="Controls blurring of images classified as adult content.",
                save_on_change=True,
                scene_overridable=False,
            ),
        }

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["venice_image_create"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image",
            label="Venice",
            subtitle="Text to image",
            description="Text to image generation via Venice.ai.",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value=BACKEND_NAME
            ),
            config=cls.venice_shared_config("venice-sd35"),
        )
        actions["venice_image_edit"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-edit",
            label="Venice",
            subtitle="Image editing",
            description="Image editing via Venice.ai.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_edit", value=BACKEND_NAME
            ),
            config=cls.venice_shared_config("firered-image-edit"),
        )
        return actions

    def _venice_handler(self, backend_type: str) -> VeniceHandler | None:
        if (
            backend_type == "backend"
            and self.backend
            and isinstance(self.backend, Backend)
        ):
            return VeniceHandler(
                backend=self.backend, action=self.actions["venice_image_create"]
            )
        if (
            backend_type == "backend_image_edit"
            and self.backend_image_edit
            and isinstance(self.backend_image_edit, Backend)
        ):
            return VeniceHandler(
                backend=self.backend_image_edit,
                action=self.actions["venice_image_edit"],
            )
        return None

    async def _venice_backend(
        self, backend: Backend | None, action_name: str, force: bool = False
    ) -> Backend:
        config = self.actions[action_name].config
        model = config["model"].value
        api_key = config["api_key"].value or None
        moderation = config["moderation"].value or "auto"

        if force or not isinstance(backend, Backend):
            log.debug("reinitializing venice backend", action_name=action_name)
            return Backend(
                model=model,
                api_key=api_key,
                moderation=moderation,
                gen_type=(
                    GEN_TYPE.TEXT_TO_IMAGE
                    if action_name == "venice_image_create"
                    else GEN_TYPE.IMAGE_EDIT
                ),
            )

        backend.model = model
        backend.api_key = api_key
        backend.moderation = moderation
        return backend

    async def venice_backend(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._venice_backend(self.backend, "venice_image_create", force)

    async def venice_backend_image_edit(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._venice_backend(
            self.backend_image_edit, "venice_image_edit", force
        )

    async def venice_prepare_generation(self, request: GenerationRequest) -> Backend:
        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            return self.backend_image_edit
        width, height = RESOLUTIONS.get(request.format, RESOLUTIONS[FORMAT_TYPE.SQUARE])
        request.resolution = Resolution(width=width, height=height)
        return self.backend
