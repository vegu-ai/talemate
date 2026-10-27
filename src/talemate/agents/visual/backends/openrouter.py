import base64
import hashlib
import io
import pydantic
import structlog
import httpx
from typing import Literal, ClassVar
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


log = structlog.get_logger("talemate.agents.visual.openrouter")


BACKEND_NAME = "openrouter"

DEFAULT_IMAGE_MODEL = "google/gemini-3-pro-image-preview"
DEFAULT_ANALYSIS_MODEL = "google/gemini-3-flash-preview"

IMAGES_URL = "https://openrouter.ai/api/v1/images"


def _choices(values) -> list[dict[str, str]]:
    return [{"label": value, "value": value} for value in values]


def _text_to_image_models() -> list[str]:
    return [
        model.id
        for model in openrouter_client.IMAGE_MODELS.values()
        if not model.svg_only and not model.needs_references
    ]


def _image_edit_models() -> list[str]:
    return [
        model.id
        for model in openrouter_client.IMAGE_MODELS.values()
        if not model.svg_only and model.takes_references
    ]


def _ratio_value(ratio: str) -> float | None:
    width, _, height = ratio.partition(":")
    try:
        return float(width) / float(height)
    except (ValueError, ZeroDivisionError):
        return None


def nearest_aspect_ratio(target: str, listed: list[str]) -> str | None:
    """The listed aspect ratio closest to `target`; None when the list holds
    no ratio (it can hold `auto`)."""
    values = {ratio: _ratio_value(ratio) for ratio in listed}
    values = {ratio: value for ratio, value in values.items() if value}
    if not values:
        return None
    wanted = _ratio_value(target)
    return min(values, key=lambda ratio: abs(values[ratio] - wanted))


def as_png(image_bytes: bytes, media_type: str | None = None) -> bytes:
    """Talemate stores generated images as PNG; OpenRouter models also return
    JPEG and WebP."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format == "PNG":
                return image_bytes
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
    except OSError as e:
        raise ValueError(
            f"OpenRouter returned an image Talemate cannot read ({media_type or 'unknown format'})"
        ) from e


def _image_url_part(image_bytes: bytes) -> dict:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{encoded}"},
    }


def _error_message(result: httpx.Response) -> str:
    try:
        return result.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return result.text


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

    _test_conn_cache_maxage: ClassVar[int] = 60

    @property
    def instance_label(self) -> str:
        return self.model

    @property
    def generator_label(self) -> str | None:
        return self.model

    @property
    def max_references(self) -> int:
        # an Image API model takes no more than its listed maximum; 0 reads as
        # "no limit" to consumers, so a model that takes none keeps the setting
        image_model = openrouter_client.IMAGE_MODELS.get(self.model)
        if image_model and not image_model.outputs_text and image_model.max_references:
            return min(self.max_references_config, image_model.max_references)
        return self.max_references_config

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    @property
    def status_cache_key(self) -> str:
        config = get_config()
        api_key = config.openrouter.api_key
        if not api_key:
            return self.name
        # full-key digest: openrouter keys share the fixed sk-or-v1- prefix,
        # so a raw prefix would collide across distinct keys and reuse a
        # stale cached status after a key change
        digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"{self.name}-{digest}"

    async def ready(self) -> backends.BackendStatus:
        # not part of the connection test: its cached result is shared by
        # the three openrouter backends, which each have their own model
        if not self.model:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message="No model set"
            )
            return self.status
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 5) -> backends.BackendStatus:
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
        except Exception as e:
            message = backends.describe_error(e)
            log.error("openrouter.test_connection.error", error=message)
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=message
            )

        if response.status_code != 200:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message=f"API returned status {response.status_code}",
            )

        # retries an image model list that failed to load; returns at once
        # when the list is loaded
        await openrouter_client.fetch_available_image_models()
        return backends.BackendStatus(type=backends.BackendStatusType.OK)

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
            image_bytes = await self._extract_image_from_message(message)
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

        response.generated = as_png(image_bytes)

        # Post-process: record actual image resolution
        self._set_request_resolution_from_image(request, response)
        return response

    def _edit_references(self, request: GenerationRequest) -> list[bytes]:
        refs = [rb for rb in (request.reference_bytes or []) if rb]
        if not refs:
            raise ValueError("Image edit requires at least one reference image")
        return refs[: self.max_references_config]

    async def _generate_edit(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        client = self._make_client()
        refs = self._edit_references(request)

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
        content.extend(_image_url_part(ref_bytes) for ref_bytes in refs)

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
            image_bytes = await self._extract_image_from_message(message)
        except ValueError as e:
            raise ValueError("OpenRouter edit response missing image data") from e

        response.generated = as_png(image_bytes)

        # Post-process: record actual image resolution
        self._set_request_resolution_from_image(request, response)
        return response

    async def _image_api_model(self) -> openrouter_client.ImageModel | None:
        """The model's Image API entry when it outputs images only: such a
        model refuses chat completions."""
        image_model = openrouter_client.IMAGE_MODELS.get(self.model)
        if image_model is None:
            # released after the list loaded, or the list failed to load
            image_models = await openrouter_client.fetch_available_image_models(
                refresh=True
            )
            image_model = image_models.get(self.model)
        if image_model and not image_model.outputs_text:
            return image_model
        return None

    async def _generate_image_api(
        self,
        request: GenerationRequest,
        response: GenerationResponse,
        image_model: openrouter_client.ImageModel,
    ) -> GenerationResponse:
        api_key = get_config().openrouter.api_key
        if not api_key:
            raise ValueError("OpenRouter API Key not set")
        if image_model.svg_only:
            raise ValueError(
                f"{self.model} only makes SVG images, and Talemate stores images as PNG"
            )

        is_edit = request.gen_type == GEN_TYPE.IMAGE_EDIT
        references = []
        if is_edit:
            if not image_model.takes_references:
                raise ValueError(
                    f"{self.model} does not accept reference images, so it cannot edit images"
                )
            references = self._edit_references(request)[: image_model.max_references]
        if len(references) < (image_model.min_references or 0):
            raise ValueError(
                f"{self.model} needs at least {image_model.min_references} reference image(s)"
            )

        payload = {
            "model": self.model,
            "prompt": request.prompt
            or ("Edit this image" if is_edit else "Generate an image"),
        }
        # the Image API refuses a parameter that the model does not honor
        aspect_ratio = nearest_aspect_ratio(
            self._aspect_ratio(request.format), image_model.aspect_ratios
        )
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if "png" in image_model.output_formats:
            payload["output_format"] = "png"
        if references:
            payload["input_references"] = [_image_url_part(ref) for ref in references]
        self._add_provider_config(payload)

        log.debug(
            "openrouter.generate_image_api",
            model=self.model,
            format=request.format,
            aspect_ratio=aspect_ratio,
            output_format=payload.get("output_format"),
            num_refs=len(payload.get("input_references", [])),
        )
        try:
            async with httpx.AsyncClient() as client:
                result = await client.post(
                    IMAGES_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=self.generate_timeout,
                )
        except httpx.HTTPError as e:
            raise ValueError(
                f"OpenRouter image request failed: {backends.describe_error(e)}"
            ) from e

        if result.status_code != 200:
            raise ValueError(
                f"OpenRouter image request failed (HTTP {result.status_code}): {_error_message(result)}"
            )

        images = result.json().get("data") or []
        if not images or not images[0].get("b64_json"):
            raise ValueError("OpenRouter image response missing image data")

        response.generated = as_png(
            base64.b64decode(images[0]["b64_json"]), images[0].get("media_type")
        )
        self._set_request_resolution_from_image(request, response)
        return response

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        image_model = await self._image_api_model()
        if image_model:
            return await self._generate_image_api(request, response, image_model)
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
        cls, default_model: str, models: list[str]
    ) -> dict[str, AgentActionConfig]:
        provider_choices = _choices(openrouter_client.AVAILABLE_PROVIDERS)

        config = {
            "api_key": AgentActionConfig(
                type="unified_api_key",
                value="openrouter.api_key",
                label="OpenRouter API Key",
            ),
            "model": AgentActionConfig(
                type="combobox",
                value=default_model,
                choices=_choices(models),
                label="Model",
                description="OpenRouter model id. Pick one from the list or type one.",
                required=True,
                scene_overridable=False,
            ),
            "provider_only": AgentActionConfig(
                type="flags",
                value=[],
                choices=provider_choices,
                label="Only use these providers",
                description="Manually limit the providers to use for the selected model. This will override the default provider selection for this model.",
                scene_overridable=False,
            ),
            "provider_ignore": AgentActionConfig(
                type="flags",
                value=[],
                choices=provider_choices,
                label="Ignore these providers",
                description="Ignore these providers for the selected model. This will override the default provider selection for this model.",
                scene_overridable=False,
            ),
        }

        return config

    @classmethod
    def openrouter_create_config(
        cls, default_model: str = DEFAULT_IMAGE_MODEL
    ) -> dict[str, AgentActionConfig]:
        """Config for image generation backend."""
        return cls.openrouter_shared_config(default_model, _text_to_image_models())

    @classmethod
    def openrouter_edit_config(
        cls, default_model: str = DEFAULT_IMAGE_MODEL
    ) -> dict[str, AgentActionConfig]:
        """Config for image editing backend."""
        config = cls.openrouter_shared_config(default_model, _image_edit_models())

        # Add max_references config for edit backend
        config["max_references"] = AgentActionConfig(
            type="number",
            value=1,
            min=1,
            max=3,
            step=1,
            label="Max References",
            description="Maximum number of reference images for editing (1-3)",
            scene_overridable=False,
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
        ].note = "The list holds OpenRouter's image generation models. You can also type the id of a model that is not in the list."
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
        ].note = "Image editing sends 1 or more reference images with the prompt, so the list holds OpenRouter's image generation models that accept reference images. You can also type the id of a model that is not in the list."
        # Image analysis backend
        config_analysis = cls.openrouter_shared_config(
            DEFAULT_ANALYSIS_MODEL, openrouter_client.AVAILABLE_MODELS
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
        ].note = "There is no good way for us to determine which models support image analysis, so this is an unfiltered list. Please consult the openrouter documentation for more information. Image analysis requires a text generation model to be multi-modal and support vision. You can also type the id of a model that is not in the list."
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
        # a cleared model field saves null
        model = action_config["model"].value or ""

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
        return await self._openrouter_backend(
            self.backend, "openrouter_image_create", old_config, force
        )

    async def openrouter_backend_image_edit(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._openrouter_backend(
            self.backend_image_edit, "openrouter_image_edit", old_config, force
        )

    async def openrouter_backend_image_analyzation(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._openrouter_backend(
            self.backend_image_analyzation,
            "openrouter_image_analyzation",
            old_config,
            force,
        )

    def openrouter_update_choices(self):
        """Offer the fetched OpenRouter lists as choices on the three openrouter
        actions: image models to generate and edit, text models to analyze."""
        providers = _choices(openrouter_client.AVAILABLE_PROVIDERS)
        for action_name, models in (
            ("openrouter_image_create", _choices(_text_to_image_models())),
            ("openrouter_image_edit", _choices(_image_edit_models())),
            (
                "openrouter_image_analyzation",
                _choices(openrouter_client.AVAILABLE_MODELS),
            ),
        ):
            config = self.actions[action_name].config
            config["model"].choices = models
            config["provider_only"].choices = providers
            config["provider_ignore"].choices = providers

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
