"""
This is currently not used.

OpenAI requires biometric verification of your organization in order to use their latest
image models over the API and i am not doing that.

Someone can test and tell me if it its working or not and I'll be happy to use it.

I confirmed that dall-e-3 is working, but its terrible.
"""

import os
import tempfile
import pydantic
import structlog
from typing import Literal

from openai import AsyncOpenAI
import httpx

from talemate.instance import get_agent
from talemate.config import get_config
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentActionNote,
)
from talemate.agents.visual.schema import (
    GenerationRequest,
    GenerationResponse,
    AnalysisRequest,
    AnalysisResponse,
    GEN_TYPE,
    Resolution,
    FORMAT_TYPE,
    PROMPT_TYPE,
)
import talemate.agents.visual.backends as backends


log = structlog.get_logger("talemate.agents.visual.openai")


BACKEND_NAME = "openai"


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "OpenAI"
    image_create = True
    image_edit = True
    image_analyzation = True
    description = "OpenAI GPT-Image-1 image generation and editing."

    model: str = "gpt-image-1"
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.DESCRIPTIVE

    @property
    def instance_label(self) -> str:
        return self.model

    @property
    def generator_label(self) -> str | None:
        return self.model

    @property
    def max_references(self) -> int:
        # single base image reference for edit
        return 1

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        api_key = get_config().openai.api_key
        if not api_key:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message="OpenAI API Key not set"
            )
        try:
            client = AsyncOpenAI(api_key=api_key)
            # Cheap authenticated call
            await client.models.list(timeout=timeout)
            return backends.BackendStatus(type=backends.BackendStatusType.OK)
        except Exception as e:
            log.error("openai.test_connection.error", error=str(e))
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    def _size_string(self, resolution: Resolution) -> str:
        return f"{resolution.width}x{resolution.height}"

    async def _generate_text(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        client = AsyncOpenAI(api_key=get_config().openai.api_key)
        size = self._size_string(request.resolution)
        log.debug("openai.generate", model=self.model, size=size)
        result = await client.images.generate(
            model=self.model,
            prompt=request.prompt,
            size=size,
            n=1,
            timeout=self.generate_timeout,
        )
        url = result.data[0].url
        if not url:
            raise ValueError("OpenAI image response missing data.url")
        async with httpx.AsyncClient() as http:
            r = await http.get(url, timeout=self.generate_timeout)
            r.raise_for_status()
            response.generated = r.content
        return response

    async def _generate_edit(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        client = AsyncOpenAI(api_key=get_config().openai.api_key)
        refs = list(request.reference_bytes or [])
        if not refs or not refs[0]:
            raise ValueError("Image edit requires at least one reference image")

        if self.model == "dall-e-3":
            raise ValueError(
                "DALL·E 3 does not support image editing. Select gpt-image-1."
            )

        # reference[0] = base image
        base_bytes = refs[0]

        # Use temporary files for SDK compatibility
        base_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_img:
                f_img.write(base_bytes)
                base_path = f_img.name

            size = self._size_string(request.resolution)
            log.debug("openai.edit", model=self.model, size=size)
            kwargs = {
                "model": self.model,
                "prompt": request.prompt,
                "size": size,
                "n": 1,
                "timeout": self.generate_timeout,
            }
            with open(base_path, "rb") as img_f:
                result = await client.images.edit(image=img_f, **kwargs)
            url = result.data[0].url
            if not url:
                raise ValueError("OpenAI image edit response missing data.url")
            async with httpx.AsyncClient() as http:
                r = await http.get(url, timeout=self.generate_timeout)
                r.raise_for_status()
                response.generated = r.content
            return response
        finally:
            if base_path and os.path.exists(base_path):
                try:
                    os.unlink(base_path)
                except Exception:
                    pass

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            return await self._generate_edit(request, response)
        return await self._generate_text(request, response)

    async def analyze(
        self, request: AnalysisRequest, response: AnalysisResponse
    ) -> AnalysisResponse:
        import base64

        client = AsyncOpenAI(api_key=get_config().openai.api_key)
        refs = list(request.reference_bytes or [])
        if not refs or not refs[0]:
            raise ValueError("Image analysis requires at least one reference image")

        # Ensure model is gpt-4.1-mini for analysis
        model = self.model
        if model != "gpt-4.1-mini":
            model = "gpt-4.1-mini"

        # Use the first image for analysis
        image_bytes = refs[0]
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        log.debug("openai.analyze", model=model, prompt=request.prompt[:100])

        # Use chat completions API with vision
        result = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": request.prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                            },
                        },
                    ],
                }
            ],
            timeout=self.generate_timeout,
        )

        if not result.choices or not result.choices[0].message.content:
            raise ValueError("OpenAI analysis response missing content")

        response.analysis = result.choices[0].message.content
        return response


class OpenAIHandler(pydantic.BaseModel):
    backend: Backend
    action: AgentAction


class OpenAIMixin:
    @classmethod
    def openai_shared_config(cls) -> dict[str, AgentActionConfig]:
        # OpenAI uses config-managed API key; only expose model selection.
        return {
            "api_key": AgentActionConfig(
                type="unified_api_key",
                value="openai.api_key",
                label="OpenAI API Key",
            ),
            "model": AgentActionConfig(
                type="text",
                value="dall-e-3",
                choices=[
                    {"label": "gpt-image-1", "value": "gpt-image-1"},
                    {"label": "gpt-image-1-mini", "value": "gpt-image-1-mini"},
                    {"label": "dall-e-3", "value": "dall-e-3"},
                ],
                label="Model",
                description="OpenAI image model",
                save_on_change=True,
                note_on_value={
                    "gpt-image-1": AgentActionNote(
                        color="warning",
                        text="This model may require your OpenAI organization to be verified.",
                    ),
                    "gpt-image-1-mini": AgentActionNote(
                        color="warning",
                        text="This model may require your OpenAI organization to be verified.",
                    ),
                },
            ),
        }

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        config_create = cls.openai_shared_config()
        actions["openai_image_create"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image",
            label="OpenAI",
            subtitle="Text to image",
            description="Basic text to image generation.",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value=BACKEND_NAME
            ),
            config=config_create,
        )

        # Image edit: restrict model choices to gpt-image-1 only
        config_edit = cls.openai_shared_config()
        config_edit["model"].choices = [
            {"label": "gpt-image-1", "value": "gpt-image-1"},
            {"label": "gpt-image-1-mini", "value": "gpt-image-1-mini"},
        ]
        config_edit["model"].value = "gpt-image-1"
        actions["openai_image_edit"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-edit",
            label="OpenAI",
            subtitle="Image editing",
            description="Image generation with contextual references.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_edit", value=BACKEND_NAME
            ),
            config=config_edit,
        )

        # Image analysis: restrict model choices to gpt-4.1-mini only
        config_analysis = cls.openai_shared_config()
        config_analysis["model"].choices = [
            {"label": "gpt-4.1-mini", "value": "gpt-4.1-mini"},
            {"label": "gpt-4o-mini", "value": "gpt-4o-mini"},
        ]
        config_analysis["model"].value = "gpt-4.1-mini"
        actions["openai_image_analyzation"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-search",
            label="OpenAI",
            subtitle="Image analysis",
            description="Analyze images using OpenAI vision API.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_analyzation", value=BACKEND_NAME
            ),
            config=config_analysis,
        )

        return actions

    def _openai_handler(
        self,
        backend_type: Literal[
            "backend", "backend_image_edit", "backend_image_analyzation"
        ],
    ) -> OpenAIHandler | None:
        if (
            backend_type == "backend"
            and self.backend
            and isinstance(self.backend, Backend)
        ):
            return OpenAIHandler(
                backend=self.backend, action=self.actions["openai_image_create"]
            )
        if (
            backend_type == "backend_image_edit"
            and self.backend_image_edit
            and isinstance(self.backend_image_edit, Backend)
        ):
            return OpenAIHandler(
                backend=self.backend_image_edit,
                action=self.actions["openai_image_edit"],
            )
        if (
            backend_type == "backend_image_analyzation"
            and self.backend_image_analyzation
            and isinstance(self.backend_image_analyzation, Backend)
        ):
            return OpenAIHandler(
                backend=self.backend_image_analyzation,
                action=self.actions["openai_image_analyzation"],
            )
        return None

    async def _openai_backend(
        self,
        backend: Backend | None,
        action_name: str,
        old_config: dict | None = None,
        force: bool = False,
    ) -> Backend | None:
        backend_instance_exists = isinstance(backend, Backend)
        model = self.actions[action_name].config["model"].value
        gen_type = (
            GEN_TYPE.TEXT_TO_IMAGE
            if action_name == "openai_image_create"
            else GEN_TYPE.IMAGE_EDIT
        )

        try:
            _model_changed = old_config[action_name].config["model"].value != model
        except Exception:
            _model_changed = False

        _reinit = force or not backend_instance_exists

        if _reinit:
            log.debug("reinitializing openai backend", action_name=action_name)
            return Backend(model=model, gen_type=gen_type)

        backend.model = model
        return backend

    async def openai_backend_image_analyzation(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._openai_backend(
            self.backend_image_analyzation,
            "openai_image_analyzation",
            old_config,
            force,
        )

    async def openai_prepare_analysis(self, request: AnalysisRequest) -> Backend:
        backend = self.backend_image_analyzation
        return backend

    async def openai_backend(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._openai_backend(
            self.backend, "openai_image_create", old_config, force
        )

    async def openai_backend_image_edit(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._openai_backend(
            self.backend_image_edit, "openai_image_edit", old_config, force
        )

    async def openai_prepare_generation(self, request: GenerationRequest) -> Backend:
        backend = (
            self.backend
            if request.gen_type == GEN_TYPE.TEXT_TO_IMAGE
            else self.backend_image_edit
        )
        # Supported sizes:
        # - gpt-image-1: 1024x1024, 1536x1024, 1024x1536
        # - dall-e-3:   1024x1024, 1792x1024, 1024x1792
        model = backend.model
        if model == "dall-e-3":
            if request.format == FORMAT_TYPE.LANDSCAPE:
                request.resolution = Resolution(width=1792, height=1024)
            elif request.format == FORMAT_TYPE.PORTRAIT:
                request.resolution = Resolution(width=1024, height=1792)
            else:
                request.resolution = Resolution(width=1024, height=1024)
        else:
            if request.format == FORMAT_TYPE.LANDSCAPE:
                request.resolution = Resolution(width=1536, height=1024)
            elif request.format == FORMAT_TYPE.PORTRAIT:
                request.resolution = Resolution(width=1024, height=1536)
            else:
                request.resolution = Resolution(width=1024, height=1024)
        return backend
