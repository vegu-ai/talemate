import base64
import io
import pydantic
import structlog
import httpx
from typing import Literal
from PIL import Image

from openai import AsyncOpenAI

from talemate.instance import get_agent
from talemate.config import get_config
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
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
from talemate.client import openrouter as openrouter_client

AVAILABLE_PROVIDERS = openrouter_client.AVAILABLE_PROVIDERS


log = structlog.get_logger("talemate.agents.visual.openrouter")


BACKEND_NAME = "openrouter"

DEFAULT_IMAGE_MODEL = "google/gemini-3-pro-image-preview"
DEFAULT_ANALYSIS_MODEL = "google/gemini-3-flash-preview"


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "OpenRouter"
    image_create = True
    image_edit = True
    image_analyzation = True
    description = "OpenRouter image generation, editing, and analysis."

    model: str = DEFAULT_IMAGE_MODEL
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.DESCRIPTIVE
    max_references_config: int = 1  # Configurable max references (1-3)
    image_create_enabled: bool = False  # Instance-level config flag
    image_edit_enabled: bool = False  # Instance-level config flag
    provider_only: list[str] = pydantic.Field(default_factory=list)
    provider_ignore: list[str] = pydantic.Field(default_factory=list)

    _test_conn_cache_maxage: int = 60

    @property
    def instance_label(self) -> str:
        return self.model

    @property
    def generator_label(self) -> str | None:
        return self.model

    @property
    def max_references(self) -> int:
        return self.max_references_config

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    @property
    def status_cache_key(self) -> str:
        config = get_config()
        return (
            f"{self.name}-{config.openrouter.api_key[:10]}"
            if config.openrouter.api_key
            else self.name
        )

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        api_key = get_config().openrouter.api_key
        if not api_key:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message="OpenRouter API Key not set",
            )
        try:
            # Test with /api/v1/key endpoint - lightweight auth check
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/key",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=timeout,
                )
                if response.status_code == 200:
                    return backends.BackendStatus(type=backends.BackendStatusType.OK)
                else:
                    return backends.BackendStatus(
                        type=backends.BackendStatusType.ERROR,
                        message=f"API returned status {response.status_code}",
                    )
        except Exception as e:
            log.error("openrouter.test_connection.error", error=str(e))
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    def _make_client(self) -> AsyncOpenAI:
        api_key = get_config().openrouter.api_key
        if not api_key:
            raise ValueError("OpenRouter API Key not set")
        return AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    def _aspect_ratio(self, fmt: FORMAT_TYPE) -> str:
        if fmt == FORMAT_TYPE.LANDSCAPE:
            return "16:9"
        if fmt == FORMAT_TYPE.PORTRAIT:
            return "9:16"
        return "1:1"

    def _add_provider_config(self, extra_body: dict) -> None:
        """Add provider routing config to extra_body if configured."""
        provider = {}
        if self.provider_only:
            provider["only"] = self.provider_only
        if self.provider_ignore:
            provider["ignore"] = self.provider_ignore
        if provider:
            extra_body["provider"] = provider

    async def _extract_image_from_message(self, message) -> bytes:
        """Extract image data from OpenRouter API response message.

        Args:
            message: The message object from the API response

        Returns:
            bytes: The image data as bytes

        Raises:
            ValueError: If no image data is found in the message
        """
        if not hasattr(message, "images") or not message.images:
            raise ValueError("OpenRouter response missing images")

        # Get first image - structure is: images[0].image_url.url
        image_data = message.images[0]

        if isinstance(image_data, dict):
            # Check for image_url.url structure (base64 data URL)
            if "image_url" in image_data and isinstance(image_data["image_url"], dict):
                url = image_data["image_url"].get("url", "")
                if url.startswith("data:image"):
                    # Extract base64 data from data URL
                    # Format: data:image/png;base64,<base64_data>
                    base64_data = url.split(",", 1)[1]
                    return base64.b64decode(base64_data)
                elif url.startswith("http"):
                    # Fetch image from HTTP URL
                    async with httpx.AsyncClient() as http_client:
                        img_response = await http_client.get(
                            url, timeout=self.generate_timeout
                        )
                        img_response.raise_for_status()
                        return img_response.content
            elif "url" in image_data:
                # Direct URL (fallback)
                async with httpx.AsyncClient() as http_client:
                    img_response = await http_client.get(
                        image_data["url"], timeout=self.generate_timeout
                    )
                    img_response.raise_for_status()
                    return img_response.content
            elif "b64_json" in image_data:
                # Decode base64 image
                return base64.b64decode(image_data["b64_json"])
        elif isinstance(image_data, str):
            # Assume base64 string
            return base64.b64decode(image_data)

        raise ValueError("OpenRouter response image data format not recognized")

    async def _generate_text(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        client = self._make_client()
        aspect_ratio = self._aspect_ratio(request.format)

        log.debug(
            "openrouter.generate_text",
            model=self.model,
            format=request.format,
            aspect_ratio=aspect_ratio,
            prompt=request.prompt[:100] if request.prompt else None,
            extra_body_aspect_ratio=aspect_ratio,
        )

        # OpenRouter uses chat completions with modalities=["image", "text"]
        # for image generation. Use extra_body to pass custom parameters.
        # Aspect ratio must be nested under image_config according to OpenRouter docs
        extra_body = {
            "modalities": ["image", "text"],
            "image_config": {
                "aspect_ratio": aspect_ratio,
            },
        }
        self._add_provider_config(extra_body)
        log.debug(
            "openrouter.generate_text.api_call",
            extra_body=extra_body,
        )
        result = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": request.prompt or "Generate an image",
                }
            ],
            extra_body=extra_body,
            timeout=self.generate_timeout,
        )

        # Extract image from response
        # OpenRouter returns images in the assistant message
        if not result.choices or not result.choices[0].message:
            raise ValueError("OpenRouter generation response missing content")

        message = result.choices[0].message

        try:
            response.generated = await self._extract_image_from_message(message)
        except ValueError as e:
            log.error(
                "openrouter._generate_text.no_image",
                error=str(e),
                message_attrs=dir(message),
                message_dict=message.model_dump()
                if hasattr(message, "model_dump")
                else str(message),
            )
            raise ValueError("OpenRouter generation response missing image data") from e

        # Post-process: record actual image resolution
        self._set_request_resolution_from_image(request, response)
        return response

    async def _generate_edit(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        client = self._make_client()
        refs = [rb for rb in (request.reference_bytes or []) if rb]
        if not refs:
            raise ValueError("Image edit requires at least one reference image")

        # Limit to configured max references
        refs = refs[: self.max_references_config]

        aspect_ratio = self._aspect_ratio(request.format)
        log.debug(
            "openrouter.generate_edit",
            model=self.model,
            format=request.format,
            aspect_ratio=aspect_ratio,
            num_refs=len(refs),
        )

        # Build content with text prompt and reference images
        content = [
            {
                "type": "text",
                "text": request.prompt or "Edit this image",
            }
        ]

        # Add reference images
        for ref_bytes in refs:
            ref_base64 = base64.b64encode(ref_bytes).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{ref_base64}",
                    },
                }
            )

        # Aspect ratio must be nested under image_config according to OpenRouter docs
        extra_body = {
            "modalities": ["image", "text"],
            "image_config": {
                "aspect_ratio": aspect_ratio,
            },
        }
        self._add_provider_config(extra_body)

        log.debug(
            "openrouter.generate_edit.api_call",
            extra_body=extra_body,
        )
        result = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            extra_body=extra_body,
            timeout=self.generate_timeout,
        )

        # Extract image from response (same as _generate_text)
        if not result.choices or not result.choices[0].message:
            raise ValueError("OpenRouter edit response missing content")

        message = result.choices[0].message

        try:
            response.generated = await self._extract_image_from_message(message)
        except ValueError as e:
            raise ValueError("OpenRouter edit response missing image data") from e

        # Post-process: record actual image resolution
        self._set_request_resolution_from_image(request, response)
        return response

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            return await self._generate_edit(request, response)
        return await self._generate_text(request, response)

    def _set_request_resolution_from_image(
        self, request: GenerationRequest, response: GenerationResponse
    ):
        """Extract and set the actual resolution from the generated image."""
        if not response.generated:
            return
        try:
            with Image.open(io.BytesIO(response.generated)) as im:
                request.resolution = Resolution(width=im.width, height=im.height)
        except Exception as e:
            log.error("openrouter.read_size_failed", error=str(e))

    async def analyze(
        self, request: AnalysisRequest, response: AnalysisResponse
    ) -> AnalysisResponse:
        client = self._make_client()

        refs = list(request.reference_bytes or [])
        if not refs or not refs[0]:
            raise ValueError("Image analysis requires at least one reference image")

        # Use the first image for analysis
        image_bytes = refs[0]
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        log.debug(
            "openrouter.analyze",
            model=self.model,
            prompt=request.prompt[:100],
        )

        try:
            # Build extra_body with provider routing if configured
            extra_body = {}
            self._add_provider_config(extra_body)

            result = await client.chat.completions.create(
                model=self.model,
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
                **({"extra_body": extra_body} if extra_body else {}),
                timeout=self.generate_timeout,
            )

            if not result.choices or not result.choices[0].message.content:
                raise ValueError("OpenRouter analysis response missing content")

            response.analysis = result.choices[0].message.content
            return response

        except Exception as e:
            log.error("openrouter.analyze.error", error=str(e))
            raise


class OpenRouterHandler(pydantic.BaseModel):
    backend: Backend
    action: AgentAction


class OpenRouterMixin:
    @classmethod
    def openrouter_shared_config(
        cls, default_model: str = DEFAULT_IMAGE_MODEL
    ) -> dict[str, AgentActionConfig]:
        # Use all available models - let user pick the correct one
        # AVAILABLE_MODELS may be empty at import time, so handle gracefully
        try:
            # Access AVAILABLE_MODELS through the module to get the current value
            models = (
                list(openrouter_client.AVAILABLE_MODELS)
                if openrouter_client.AVAILABLE_MODELS
                else []
            )
        except (AttributeError, NameError):
            models = []

        choices = [{"label": model, "value": model} for model in models]

        # Create provider choices from AVAILABLE_PROVIDERS
        provider_choices = [
            {"label": provider, "value": provider} for provider in AVAILABLE_PROVIDERS
        ]

        config = {
            "api_key": AgentActionConfig(
                type="unified_api_key",
                value="openrouter.api_key",
                label="OpenRouter API Key",
            ),
            "model": AgentActionConfig(
                type="autocomplete",
                value=default_model,
                choices=choices,
                label="Model",
                description="OpenRouter model (select appropriate model for the task)",
                save_on_change=True,
            ),
            "provider_only": AgentActionConfig(
                type="flags",
                value=[],
                choices=provider_choices,
                label="Only use these providers",
                description="Manually limit the providers to use for the selected model. This will override the default provider selection for this model.",
                save_on_change=True,
            ),
            "provider_ignore": AgentActionConfig(
                type="flags",
                value=[],
                choices=provider_choices,
                label="Ignore these providers",
                description="Ignore these providers for the selected model. This will override the default provider selection for this model.",
                save_on_change=True,
            ),
        }

        return config

    @classmethod
    def openrouter_create_config(
        cls, default_model: str = DEFAULT_IMAGE_MODEL
    ) -> dict[str, AgentActionConfig]:
        """Config for image generation backend."""
        return cls.openrouter_shared_config(default_model=default_model)

    @classmethod
    def openrouter_edit_config(
        cls, default_model: str = DEFAULT_IMAGE_MODEL
    ) -> dict[str, AgentActionConfig]:
        """Config for image editing backend."""
        config = cls.openrouter_shared_config(default_model=default_model)

        # Add max_references config for edit backend
        config["max_references"] = AgentActionConfig(
            type="number",
            value=1,
            min=1,
            max=3,
            step=1,
            label="Max References",
            description="Maximum number of reference images for editing (1-3)",
            save_on_change=True,
        )

        return config

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        # Image generation backend
        config_create = cls.openrouter_create_config(default_model=DEFAULT_IMAGE_MODEL)
        actions["openrouter_image_create"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image",
            label="OpenRouter",
            subtitle="Text to image",
            description="Text to image generation via OpenRouter.",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value=BACKEND_NAME
            ),
            config=config_create,
        )
        actions["openrouter_image_create"].config[
            "model"
        ].note = "There is no good way for us to determine which models support basic text to image generation, so this is an unfiltered list. Please consult the openrouter documentation for more information."
        # Image editing backend
        config_edit = cls.openrouter_edit_config(default_model=DEFAULT_IMAGE_MODEL)
        actions["openrouter_image_edit"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-edit",
            label="OpenRouter",
            subtitle="Image editing",
            description="Image editing via OpenRouter.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_edit", value=BACKEND_NAME
            ),
            config=config_edit,
        )
        actions["openrouter_image_edit"].config[
            "model"
        ].note = "There is no good way for us to determine which models support image editing, so this is an unfiltered list. Please consult the openrouter documentation for more information. Image editing refers to image generation with support for 1 or more contextual references."
        # Image analysis backend
        config_analysis = cls.openrouter_shared_config(
            default_model=DEFAULT_ANALYSIS_MODEL
        )
        actions["openrouter_image_analyzation"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-search",
            label="OpenRouter",
            subtitle="Image analysis",
            description="Analyze images using OpenRouter vision models.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_analyzation", value=BACKEND_NAME
            ),
            config=config_analysis,
        )
        actions["openrouter_image_analyzation"].config[
            "model"
        ].note = "There is no good way for us to determine which models support image analysis, so this is an unfiltered list. Please consult the openrouter documentation for more information. Image analysis requires a text generation model to be multi-modal and support vision."
        return actions

    def _openrouter_handler(
        self,
        backend_type: Literal[
            "backend", "backend_image_edit", "backend_image_analyzation"
        ],
    ) -> OpenRouterHandler | None:
        if (
            backend_type == "backend"
            and self.backend
            and isinstance(self.backend, Backend)
        ):
            return OpenRouterHandler(
                backend=self.backend, action=self.actions["openrouter_image_create"]
            )
        if (
            backend_type == "backend_image_edit"
            and self.backend_image_edit
            and isinstance(self.backend_image_edit, Backend)
        ):
            return OpenRouterHandler(
                backend=self.backend_image_edit,
                action=self.actions["openrouter_image_edit"],
            )
        if (
            backend_type == "backend_image_analyzation"
            and self.backend_image_analyzation
            and isinstance(self.backend_image_analyzation, Backend)
        ):
            return OpenRouterHandler(
                backend=self.backend_image_analyzation,
                action=self.actions["openrouter_image_analyzation"],
            )
        return None

    async def _openrouter_backend(
        self,
        backend: Backend | None,
        action_name: str,
        old_config: dict | None = None,
        force: bool = False,
    ) -> Backend | None:
        backend_instance_exists = isinstance(backend, Backend)
        action_config = self.actions[action_name].config
        model = action_config["model"].value

        # Determine capabilities based on backend type
        image_create_enabled = action_name == "openrouter_image_create"
        image_edit_enabled = action_name == "openrouter_image_edit"
        max_references = 1

        # Get max_references config for edit backend
        if image_edit_enabled and "max_references" in action_config:
            max_references = action_config["max_references"].value

        # Get provider configs
        provider_only = []
        provider_ignore = []
        if "provider_only" in action_config:
            provider_only = action_config["provider_only"].value or []
        if "provider_ignore" in action_config:
            provider_ignore = action_config["provider_ignore"].value or []

        try:
            _model_changed = (
                old_config[action_name].config["model"].value != model
                if old_config and action_name in old_config
                else False
            )
        except Exception:
            _model_changed = False

        _reinit = force or not backend_instance_exists

        if _reinit:
            log.debug("reinitializing openrouter backend", action_name=action_name)
            backend = Backend(
                model=model,
                image_create_enabled=image_create_enabled,
                image_edit_enabled=image_edit_enabled,
                max_references_config=max_references,
                provider_only=provider_only,
                provider_ignore=provider_ignore,
            )
            return backend

        backend.model = model
        backend.image_create_enabled = image_create_enabled
        backend.image_edit_enabled = image_edit_enabled
        backend.max_references_config = max_references
        backend.provider_only = provider_only
        backend.provider_ignore = provider_ignore
        return backend

    async def openrouter_backend(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        backend = await self._openrouter_backend(
            self.backend, "openrouter_image_create", old_config, force
        )
        # Update model choices if AVAILABLE_MODELS has been populated
        await self._update_openrouter_model_choices("openrouter_image_create")
        return backend

    async def openrouter_backend_image_edit(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        backend = await self._openrouter_backend(
            self.backend_image_edit, "openrouter_image_edit", old_config, force
        )
        # Update model choices if AVAILABLE_MODELS has been populated
        await self._update_openrouter_model_choices("openrouter_image_edit")
        return backend

    async def openrouter_backend_image_analyzation(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        backend = await self._openrouter_backend(
            self.backend_image_analyzation,
            "openrouter_image_analyzation",
            old_config,
            force,
        )
        # Update model choices if AVAILABLE_MODELS has been populated
        await self._update_openrouter_model_choices("openrouter_image_analyzation")
        return backend

    async def _update_openrouter_model_choices(self, action_name: str):
        """Update model choices from AVAILABLE_MODELS if it has been populated."""
        # Access AVAILABLE_MODELS through the module to get the current value
        available_models = openrouter_client.AVAILABLE_MODELS

        if not available_models:
            return

        action = self.actions.get(action_name)
        if not action or "model" not in action.config:
            return

        choices = [{"label": model, "value": model} for model in available_models]
        action.config["model"].choices = choices

    async def openrouter_emit_status(self, processing: bool = None):
        """Update model choices when status is emitted."""
        # Update choices for all openrouter actions if models are available
        for action_name in [
            "openrouter_image_create",
            "openrouter_image_edit",
            "openrouter_image_analyzation",
        ]:
            await self._update_openrouter_model_choices(action_name)

    async def openrouter_prepare_generation(
        self, request: GenerationRequest
    ) -> Backend:
        backend = (
            self.backend
            if request.gen_type == GEN_TYPE.TEXT_TO_IMAGE
            else self.backend_image_edit
        )
        return backend

    async def openrouter_prepare_analysis(self, request: AnalysisRequest) -> Backend:
        backend = self.backend_image_analyzation
        return backend
