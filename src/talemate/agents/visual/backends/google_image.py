import asyncio
import io
import pydantic
import structlog
from typing import Literal, ClassVar
import time
from google import genai
from google.genai import types as genai_types
from PIL import Image

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


log = structlog.get_logger("talemate.agents.visual.google_image")


BACKEND_NAME = "google"

DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"
DEFAULT_ANALYSIS_MODEL = "gemini-3-flash-preview"


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "Google"
    image_create = True
    image_edit = True
    image_analyzation = True
    description = "Google image generation and editing."

    model: str = DEFAULT_IMAGE_MODEL
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.DESCRIPTIVE
    max_references_config: int = 3  # Configurable max references (1-3)

    _test_conn_cache_maxage: ClassVar[int] = 60

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
            f"{self.name}-{config.google.api_key[:10]}"
            if config.google.api_key
            else self.name
        )

    def _size_string(self, resolution: Resolution) -> str:
        return f"{resolution.width}x{resolution.height}"

    def _aspect_ratio(self, fmt: FORMAT_TYPE) -> str:
        if fmt == FORMAT_TYPE.LANDSCAPE:
            return "16:9"
        if fmt == FORMAT_TYPE.PORTRAIT:
            return "9:16"
        return "1:1"

    # (no helper: use SDK's explicit image and content APIs directly)

    def _make_client(self) -> genai.Client:
        # Uses developer API key from Talemate config
        api_key = get_config().google.api_key
        return genai.Client(api_key=api_key or None)

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        api_key = get_config().google.api_key
        if not api_key:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message="Google API Key not set"
            )
        try:
            client = self._make_client()
            # Cheap authenticated call: list models (errors indicate bad auth/config)
            # Fall back to get on the configured model if listing is unavailable
            try:
                _ = await asyncio.wait_for(client.aio.models.list(), timeout=timeout)
            except Exception:
                _ = await asyncio.wait_for(
                    client.aio.models.get(model=self.model), timeout=timeout
                )
            return backends.BackendStatus(type=backends.BackendStatusType.OK)
        except Exception as e:
            log.error("google.test_connection.error", error=str(e))
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    async def _generate_text(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        client = self._make_client()
        aspect_ratio = self._aspect_ratio(request.format)
        log.debug(
            "google.generate_content.image", model=self.model, aspect_ratio=aspect_ratio
        )
        gen_config = genai_types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=getattr(genai_types, "ImageConfig")(aspect_ratio=aspect_ratio),
            http_options=genai_types.HttpOptions(timeout=self.generate_timeout * 1000),
        )
        result = await client.aio.models.generate_content(
            model=self.model,
            contents=request.prompt,
            config=gen_config,
        )

        try:
            parts = result.candidates[0].content.parts
            for p in parts:
                inline = getattr(p, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    response.generated = inline.data
                    break
        except Exception as e:
            log.error("google.generate_content.parse_error", error=str(e))
            raise
        # Post-process: record actual image resolution (do not modify bytes)
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
            "google.edit_image",
            model=self.model,
            aspect_ratio=aspect_ratio,
            num_refs=len(refs),
            generate_timeout=self.generate_timeout,
        )

        # Add reference images
        image_parts = [
            genai_types.Part.from_bytes(mime_type="image/png", data=rb) for rb in refs
        ]
        contents = [
            genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part.from_text(
                        text=request.prompt or "Edit this image"
                    ),
                    *image_parts,
                ],
            )
        ]

        gen_config = genai_types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=getattr(genai_types, "ImageConfig")(aspect_ratio=aspect_ratio),
            http_options=genai_types.HttpOptions(timeout=self.generate_timeout * 1000),
        )

        start_t = time.time()
        result = await client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=gen_config,
        )
        log.debug("google.edit_image.returned", duration=time.time() - start_t)

        try:
            parts = result.candidates[0].content.parts
            for p in parts:
                inline = getattr(p, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    response.generated = inline.data
                    break
        except Exception as e:
            log.error("google.edit_image.parse_error", error=str(e), result=result)
            raise
        # Post-process: record actual image resolution (do not modify bytes)
        self._set_request_resolution_from_image(request, response)
        return response

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            return await self._generate_edit(request, response)
        return await self._generate_text(request, response)

    async def analyze(
        self, request: AnalysisRequest, response: AnalysisResponse
    ) -> AnalysisResponse:
        client = self._make_client()
        refs = list(request.reference_bytes or [])
        if not refs or not refs[0]:
            raise ValueError("Image analysis requires at least one reference image")

        # Use the configured model (defaults to gemini-3-flash-preview)
        # This is a text model that supports vision, not the image generation model
        analysis_model = self.model

        # Use the first image for analysis
        image_bytes = refs[0]

        # Detect MIME type from image bytes
        mime_type = "image/png"  # default
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                format_lower = img.format.lower() if img.format else ""
                if format_lower == "jpeg" or format_lower == "jpg":
                    mime_type = "image/jpeg"
                elif format_lower == "png":
                    mime_type = "image/png"
                elif format_lower == "webp":
                    mime_type = "image/webp"
                elif format_lower == "heic":
                    mime_type = "image/heic"
                elif format_lower == "heif":
                    mime_type = "image/heif"
        except Exception as e:
            log.warning(
                "google.analyze.mime_detection_failed",
                error=str(e),
                defaulting_to="image/png",
            )

        log.debug(
            "google.analyze",
            model=analysis_model,
            mime_type=mime_type,
            prompt=request.prompt[:100],
        )

        # Create content with image and text prompt
        # According to Gemini docs, place text prompt after image part
        contents = [
            genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part.from_bytes(mime_type=mime_type, data=image_bytes),
                    genai_types.Part.from_text(text=request.prompt),
                ],
            )
        ]

        result = await client.aio.models.generate_content(
            model=analysis_model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                http_options=genai_types.HttpOptions(
                    timeout=self.generate_timeout * 1000
                )
            ),
        )

        try:
            # Extract text response from the result
            parts = result.candidates[0].content.parts
            for p in parts:
                if hasattr(p, "text") and p.text:
                    response.analysis = p.text
                    break
        except Exception as e:
            log.error("google.analyze.parse_error", error=str(e))
            raise ValueError(f"Failed to parse analysis response: {e}")

        if not response.analysis:
            raise ValueError("Google analysis response missing text content")

        return response

    # helpers
    def _set_request_resolution_from_image(
        self, request: GenerationRequest, response: GenerationResponse
    ):
        if not response.generated:
            return
        try:
            with Image.open(io.BytesIO(response.generated)) as im:
                request.resolution = Resolution(width=im.width, height=im.height)
        except Exception as e:
            log.error("google.read_size_failed", error=str(e))


class GoogleHandler(pydantic.BaseModel):
    backend: Backend
    action: AgentAction


class GoogleImageMixin:
    @classmethod
    def google_shared_config(cls) -> dict[str, AgentActionConfig]:
        return {
            "api_key": AgentActionConfig(
                type="unified_api_key",
                value="google.api_key",
                label="Google API Key",
            ),
            "model": AgentActionConfig(
                type="text",
                value=DEFAULT_IMAGE_MODEL,
                choices=[
                    {
                        "label": "gemini-2.5-flash-image",
                        "value": "gemini-2.5-flash-image",
                    },
                    {
                        "label": "gemini-3-pro-image-preview",
                        "value": "gemini-3-pro-image-preview",
                    },
                ],
                label="Model",
                description="Google image model",
                save_on_change=True,
            ),
        }

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        config_create = cls.google_shared_config()
        actions["google_image_create"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image",
            label="Google",
            subtitle="Text to image",
            description="Text to image generation via Google.",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value=BACKEND_NAME
            ),
            config=config_create,
        )

        config_edit = cls.google_shared_config()
        # Add max_references config for edit backend
        config_edit["max_references"] = AgentActionConfig(
            type="number",
            value=3,
            min=1,
            max=3,
            step=1,
            label="Max References",
            description="Maximum number of reference images for editing (1-3)",
            save_on_change=True,
        )
        actions["google_image_edit"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-edit",
            label="Google",
            subtitle="Image editing",
            description="Image editing via Google (single reference).",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_edit", value=BACKEND_NAME
            ),
            config=config_edit,
        )

        # Image analysis: use Gemini text models that support vision
        config_analysis = cls.google_shared_config()
        config_analysis["model"].choices = [
            {"label": "gemini-2.5-flash", "value": "gemini-2.5-flash"},
            {"label": "gemini-2.5-pro", "value": "gemini-2.5-pro"},
            {"label": "gemini-3-pro-preview", "value": "gemini-3-pro-preview"},
            {"label": "gemini-3-flash-preview", "value": "gemini-3-flash-preview"},
        ]
        config_analysis["model"].value = DEFAULT_ANALYSIS_MODEL
        actions["google_image_analyzation"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-search",
            label="Google",
            subtitle="Image analysis",
            description="Analyze images using Google Gemini vision API.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_analyzation", value=BACKEND_NAME
            ),
            config=config_analysis,
        )

        return actions

    def _google_handler(
        self,
        backend_type: Literal[
            "backend", "backend_image_edit", "backend_image_analyzation"
        ],
    ) -> GoogleHandler | None:
        if (
            backend_type == "backend"
            and self.backend
            and isinstance(self.backend, Backend)
        ):
            return GoogleHandler(
                backend=self.backend, action=self.actions["google_image_create"]
            )
        if (
            backend_type == "backend_image_edit"
            and self.backend_image_edit
            and isinstance(self.backend_image_edit, Backend)
        ):
            return GoogleHandler(
                backend=self.backend_image_edit,
                action=self.actions["google_image_edit"],
            )
        if (
            backend_type == "backend_image_analyzation"
            and self.backend_image_analyzation
            and isinstance(self.backend_image_analyzation, Backend)
        ):
            return GoogleHandler(
                backend=self.backend_image_analyzation,
                action=self.actions["google_image_analyzation"],
            )
        return None

    async def _google_backend(
        self,
        backend: Backend | None,
        action_name: str,
        old_config: dict | None = None,
        force: bool = False,
    ) -> Backend | None:
        backend_instance_exists = isinstance(backend, Backend)
        action_config = self.actions[action_name].config
        model = action_config["model"].value
        gen_type = (
            GEN_TYPE.TEXT_TO_IMAGE
            if action_name == "google_image_create"
            else GEN_TYPE.IMAGE_EDIT
        )

        # Get max_references config for edit backend
        max_references = 3
        if action_name == "google_image_edit" and "max_references" in action_config:
            max_references = action_config["max_references"].value

        try:
            _model_changed = old_config[action_name].config["model"].value != model
        except Exception:
            _model_changed = False

        _reinit = force or not backend_instance_exists

        if _reinit:
            log.debug("reinitializing google backend", action_name=action_name)
            backend = Backend(model=model, gen_type=gen_type)
            if action_name == "google_image_edit":
                backend.max_references_config = max_references
            return backend

        backend.model = model
        if action_name == "google_image_edit":
            backend.max_references_config = max_references
        return backend

    async def google_backend(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._google_backend(
            self.backend, "google_image_create", old_config, force
        )

    async def google_backend_image_edit(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._google_backend(
            self.backend_image_edit, "google_image_edit", old_config, force
        )

    async def google_backend_image_analyzation(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._google_backend(
            self.backend_image_analyzation,
            "google_image_analyzation",
            old_config,
            force,
        )

    async def google_prepare_analysis(self, request: AnalysisRequest) -> Backend:
        backend = self.backend_image_analyzation
        # Analysis uses the configured model from the action config
        # The model is set via the google_image_analyzation action config
        return backend
