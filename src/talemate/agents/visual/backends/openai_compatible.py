import base64
from typing import ClassVar

import structlog
from openai import AsyncOpenAI

import talemate.agents.visual.backends as backends
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
)
from talemate.agents.visual.schema import (
    AnalysisRequest,
    AnalysisResponse,
)

log = structlog.get_logger("talemate.agents.visual.openai_compatible")

BACKEND_NAME = "openai_compatible"


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "OpenAI Compatible"
    image_create = False
    image_edit = False
    image_analyzation = True
    description = "Analyze images using any OpenAI-compatible vision endpoint."

    base_url: str = ""
    api_key: str = ""
    model: str = ""

    _test_conn_cache_maxage: ClassVar[int] = 10

    @property
    def instance_label(self) -> str:
        return self.model or self.base_url or "Not configured"

    @property
    def generator_label(self) -> str | None:
        if not self.model:
            return None
        return self.model

    @property
    def status_cache_key(self) -> str:
        return f"{self.name}-{self.base_url or 'none'}-{self.model or 'none'}"

    def _make_client(self) -> AsyncOpenAI:
        if not self.base_url:
            raise ValueError("Base URL is not configured")
        api_key = self.api_key or "sk-1234"
        base = self.base_url.strip().rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return AsyncOpenAI(base_url=base, api_key=api_key)

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        if not self.base_url:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message="Base URL not set",
            )

        if not self.model:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message="Model not set",
            )

        try:
            client = self._make_client()
            await client.models.list(timeout=timeout)
            return backends.BackendStatus(type=backends.BackendStatusType.OK)
        except Exception as e:
            log.debug("openai_compatible.test_connection.error", error=str(e))
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    async def analyze(
        self, request: AnalysisRequest, response: AnalysisResponse
    ) -> AnalysisResponse:
        client = self._make_client()

        refs = list(request.reference_bytes or [])
        if not refs or not refs[0]:
            raise ValueError("Image analysis requires at least one reference image")

        image_bytes = refs[0]
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        log.debug(
            "openai_compatible.analyze",
            base_url=self.base_url,
            model=self.model,
            prompt=request.prompt[:100],
        )

        try:
            result = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": request.prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                },
                            },
                        ],
                    }
                ],
            )

            if not result.choices or not result.choices[0].message.content:
                raise ValueError("Vision analysis response missing content")

            response.analysis = result.choices[0].message.content
            return response
        except Exception as e:
            log.error("openai_compatible.analyze.error", error=str(e))
            raise


class OpenAICompatibleMixin:
    """Mixin for VisualAgent to support the OpenAI Compatible analysis backend."""

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["openai_compatible_image_analyzation"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-search",
            label="OpenAI Compatible",
            subtitle="Image analysis",
            description="Analyze images using any OpenAI-compatible vision endpoint.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_analyzation",
                value=BACKEND_NAME,
            ),
            config={
                "base_url": AgentActionConfig(
                    type="text",
                    value="",
                    label="Base URL",
                    description=(
                        "The base URL for the OpenAI-compatible API endpoint "
                        "(e.g., http://localhost:8080). The /v1 path will be "
                        "appended automatically if not present."
                    ),
                    save_on_change=True,
                ),
                "api_key": AgentActionConfig(
                    type="password",
                    value="",
                    label="API Key",
                    description="Optional API key for authentication.",
                    save_on_change=True,
                ),
                "model": AgentActionConfig(
                    type="text",
                    value="",
                    label="Model",
                    description=(
                        "The model name to use for vision analysis. (May be optional depending on the API endpoint)"
                    ),
                    save_on_change=True,
                ),
            },
        )

    async def openai_compatible_backend_image_analyzation(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        backend = self.backend_image_analyzation
        backend_instance_exists = isinstance(backend, Backend)
        action_config = self.actions["openai_compatible_image_analyzation"].config
        base_url = action_config["base_url"].value or ""
        api_key = action_config["api_key"].value or ""
        model = action_config["model"].value or ""

        _reinit = force or not backend_instance_exists

        if _reinit:
            return Backend(base_url=base_url, api_key=api_key, model=model)

        backend.base_url = base_url
        backend.api_key = api_key
        backend.model = model
        return backend

    async def openai_compatible_prepare_analysis(
        self, request: AnalysisRequest
    ) -> Backend:
        return self.backend_image_analyzation

    async def openai_compatible_emit_status(self, processing: bool = None):
        pass
