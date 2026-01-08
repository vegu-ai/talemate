import asyncio
from typing import Literal
import structlog

# import talemate.agents.visual.automatic1111  # noqa: F401
# import talemate.agents.visual.comfyui  # noqa: F401
# import talemate.agents.visual.openai_image  # noqa: F401
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    AgentDetail,
)
from talemate.agents.registry import register
from talemate.client.base import ClientBase

from .backends import BACKENDS, NONE_BACKEND, Backend, BackendStatus
from .commands import *  # noqa
from .websocket_handler import VisualWebsocketHandler
from .schema import ReadyCheckResult, BackendStatusType, PROMPT_TYPE
import talemate.agents.visual.nodes  # noqa: F401

from .style import StyleMixin
from .generation import GenerationMixin
from .analyze import AnalysisMixin
from .backends.comfyui import ComfyUIMixin
from .backends.automatic1111 import Automatic1111Mixin
from .backends.google_image import GoogleImageMixin
from .backends.sdnext import SDNextMixin
from .backends.openai_image import OpenAIMixin
from .backends.openrouter import OpenRouterMixin

__all__ = [
    "VisualAgent",
]

PROMPT_OUTPUT_FORMAT = """
### Positive
{positive_prompt}

### Negative
{negative_prompt}
"""

VERBOSE_LOGGING = False

log = structlog.get_logger("talemate.agents.visual")


@register()
class VisualAgent(
    StyleMixin,
    GenerationMixin,
    AnalysisMixin,
    ComfyUIMixin,
    Automatic1111Mixin,
    SDNextMixin,
    GoogleImageMixin,
    OpenAIMixin,
    OpenRouterMixin,
    Agent,
):
    """
    The visual agent
    """

    agent_type = "visual"
    verbose_name = "Visualizer"
    essential = False
    websocket_handler = VisualWebsocketHandler

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "_config": AgentAction(
                enabled=True,
                label="Configure",
                description="Visual agent configuration",
                config={
                    "backend": AgentActionConfig(
                        type="text",
                        choices=[
                            backend.as_choice()
                            for backend in BACKENDS.values()
                            if backend.image_create
                        ]
                        + [NONE_BACKEND],
                        value="",
                        label="Backend (text to image)",
                        description="The backend to use for basic text to image generation",
                        save_on_change=True,
                    ),
                    "backend_image_edit": AgentActionConfig(
                        type="text",
                        choices=[
                            backend.as_choice()
                            for backend in BACKENDS.values()
                            if backend.image_edit
                        ]
                        + [NONE_BACKEND],
                        value="",
                        label="Backend (image editing)",
                        description="The backend to use for contextual image editing",
                        save_on_change=True,
                    ),
                    "backend_image_analyzation": AgentActionConfig(
                        type="text",
                        choices=[
                            backend.as_choice()
                            for backend in BACKENDS.values()
                            if backend.image_analyzation
                        ]
                        + [NONE_BACKEND],
                        value="",
                        label="Backend (image analysis)",
                        description="The backend to use for image analysis",
                        save_on_change=True,
                    ),
                    "timeout": AgentActionConfig(
                        type="number",
                        value=300,
                        label="Image generation timeout",
                        min=1,
                        max=900,
                        step=10,
                        description="Timeout in seconds. If the backend does not generate an image within this time, it will be considered failed.",
                    ),
                    "automatic_setup": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Automatic Setup",
                        description="Automatically setup the visual agent if the selected client has an implementation of the selected backend. (Like the KoboldCpp Automatic1111 api)",
                    ),
                    "automatic_generation": AgentActionConfig(
                        type="bool",
                        value=False,
                        label="Automatic Generation",
                        description="Allow automatic generation of visual content",
                    ),
                },
            ),
            "prompt_generation": AgentAction(
                enabled=True,
                container=True,
                label="Prompt Generation",
                description="Prompt generation configuration",
                icon="mdi-text-box-search-outline",
                config={
                    "fallback_prompt_type": AgentActionConfig(
                        type="text",
                        value=PROMPT_TYPE.KEYWORDS,
                        label="Fallback Prompt Type",
                        description="The prompt type to use for prompt only generation (if backends are not configured)",
                        note="This will be used for `prompt only` generation if no backends are configured",
                        choices=PROMPT_TYPE.choices(),
                    ),
                    "max_length": AgentActionConfig(
                        type="number",
                        value=1024,
                        label="Max. Prompt Generation Length",
                        description="Maximum token length for generated prompts. This must allocate room for both keyword and descriptive prompt types, because both are always generated.",
                        min=512,
                        max=4096,
                        step=256,
                    ),
                    "automatic_analysis": AgentActionConfig(
                        type="bool",
                        value=False,
                        label="Automatic analysis of references",
                        description="When enabled, reference images lacking analysis data will be automatically analyzed before being used in prompt generation.",
                        note_on_value={
                            True: AgentActionNote(
                                color="warning",
                                text="Reference images will be analyzed on-the-fly when missing analysis data, adding one AI query per unanalyzed reference. Requires image analysis backend to be configured.",
                            ),
                        },
                    ),
                    "revise_edit_prompts": AgentActionConfig(
                        type="bool",
                        value=True,
                        label="Perform extra revision of editing prompts",
                        description="Uses AI to refine and simplify image editing prompts based on provided references, potentially improving generation results.",
                        note_on_value={
                            True: AgentActionNote(
                                color="warning",
                                title="Additional AI Query Required",
                                text="This will add an extra AI query to the prompt generation process when references are provided, but may improve results by better aligning the prompt with the provided references.",
                            ),
                        },
                    ),
                },
            ),
        }

        ComfyUIMixin.add_actions(actions)
        Automatic1111Mixin.add_actions(actions)
        SDNextMixin.add_actions(actions)
        GoogleImageMixin.add_actions(actions)
        OpenAIMixin.add_actions(actions)
        OpenRouterMixin.add_actions(actions)
        StyleMixin.add_actions(actions)

        return actions

    def __init__(self, client: ClientBase | None = None, **kwargs):
        self.client = client
        self.is_enabled = False
        self.initialized = False
        self.backend = None
        self.backend_image_edit = None
        self.backend_image_analyzation = None
        self.ready_check_result = ReadyCheckResult()

        self.actions = VisualAgent.init_actions()

    ## Helpers

    @property
    def enabled(self) -> bool:
        return True

    @property
    def has_toggle(self) -> bool:
        return False

    @property
    def experimental(self) -> bool:
        return False

    @property
    def any_backend_configured(self) -> bool:
        return self.backend or self.backend_image_edit or self.backend_image_analyzation

    @property
    def create_backend_ok(self) -> bool:
        return not self.backend or self.backend.status.type == BackendStatusType.OK

    @property
    def image_edit_backend_ok(self) -> bool:
        return (
            not self.backend_image_edit
            or self.backend_image_edit.status.type == BackendStatusType.OK
        )

    @property
    def image_analyzation_backend_ok(self) -> bool:
        return (
            not self.backend_image_analyzation
            or self.backend_image_analyzation.status.type == BackendStatusType.OK
        )

    @property
    def ready(self) -> bool:
        if not self.create_backend_ok:
            return False
        if not self.image_edit_backend_ok:
            return False
        if not self.image_analyzation_backend_ok:
            return False
        return super().ready

    @property
    def meta(self):
        meta: dict = super().meta

        if self.backend:
            meta["image_create"] = {
                "status": str(self.backend.status.type),
            }
            generator_label = self.backend.generator_label
            if generator_label:
                meta["image_create"]["generator_label"] = generator_label
        if self.backend_image_edit:
            meta["image_edit"] = {
                "status": str(self.backend_image_edit.status.type),
                "max_references": self.backend_image_edit.max_references,
            }
            generator_label = self.backend_image_edit.generator_label
            if generator_label:
                meta["image_edit"]["generator_label"] = generator_label
        if self.backend_image_analyzation:
            meta["image_analyzation"] = {
                "status": str(self.backend_image_analyzation.status.type),
            }
            generator_label = self.backend_image_analyzation.generator_label
            if generator_label:
                meta["image_analyzation"]["generator_label"] = generator_label

        # Add current art style name and source
        art_style_name = self._get_current_art_style_name()
        if art_style_name:
            meta["current_art_style"] = art_style_name
            meta["current_art_style_source"] = self._get_current_art_style_source()

        return meta

    @property
    def generate_timeout(self) -> int:
        return self.actions["_config"].config["timeout"].value

    @property
    def agent_details(self) -> dict[str, AgentDetail]:
        details = {
            "client": AgentDetail(
                icon="mdi-network-outline",
                value=self.client.name if self.client else None,
                description="The client to use for prompt generation",
            ).model_dump(),
        }

        if not self.enabled:
            return details

        if not self.any_backend_configured:
            details["status"] = AgentDetail(
                icon="mdi-alert",
                value="No backend configured",
                color="muted",
                description="Image generation is disabled - No backend configured. Please configure a backend to use for visual processing",
            ).model_dump()
            return details

        if self.backend:
            details["backend"] = AgentDetail(
                icon="mdi-image",
                value=self.backend.label,
                color=self.backend.status_color,
                description=self.backend.status_description,
            ).model_dump()
        if self.backend_image_edit:
            max_references = self.backend_image_edit.max_references
            details["backend_image_edit"] = AgentDetail(
                icon="mdi-pencil",
                color=self.backend_image_edit.status_color,
                value=self.backend_image_edit.label,
                description=f"Image Editing: {self.backend_image_edit.status_description}",
            ).model_dump()
            if max_references > 0:
                details["max_references"] = AgentDetail(
                    icon="mdi-image-multiple",
                    value=f"References {max_references}",
                    description="The maximum number of references that can be used for image editing",
                ).model_dump()
        if self.backend_image_analyzation:
            details["backend_image_analyzation"] = AgentDetail(
                icon="mdi-image-search",
                color=self.backend_image_analyzation.status_color,
                value=self.backend_image_analyzation.label,
                description=f"Image Analysis: {self.backend_image_analyzation.status_description}",
            ).model_dump()
        return details

    @property
    def allow_automatic_generation(self) -> bool:
        return self.actions["_config"].config["automatic_generation"].value

    @property
    def automatic_setup(self) -> bool:
        return self.actions["_config"].config["automatic_setup"].value

    @property
    def fallback_prompt_type(self) -> PROMPT_TYPE:
        value = self.actions["prompt_generation"].config["fallback_prompt_type"].value
        return PROMPT_TYPE(value) if value else PROMPT_TYPE.KEYWORDS

    @property
    def prompt_generation_length(self) -> int:
        return self.actions["prompt_generation"].config["max_length"].value

    @property
    def automatic_analysis(self) -> bool:
        return self.actions["prompt_generation"].config["automatic_analysis"].value

    @property
    def revise_edit_prompts(self) -> bool:
        return self.actions["prompt_generation"].config["revise_edit_prompts"].value

    @property
    def backend_name(self) -> str:
        return self.actions["_config"].config["backend"].value

    @property
    def backend_image_edit_name(self) -> str:
        return self.actions["_config"].config["backend_image_edit"].value

    @property
    def backend_image_analyzation_name(self) -> str:
        return self.actions["_config"].config["backend_image_analyzation"].value

    ## Backend instantiation / swapping

    async def setup_check(self):
        """
        Automatically setup backends if the client has implementations available.
        For example, KoboldCpp provides an Automatic1111 API.
        """
        if not self.automatic_setup or not self.client:
            return

        # Try to setup each backend if client has the capability
        for backend_name in BACKENDS.keys():
            setup_method = f"visual_{backend_name.lower()}_setup"
            setup_fn = getattr(self.client, setup_method, None)
            if setup_fn:
                completed = await setup_fn(self)
                if completed:
                    # Actually instantiate the backend after setup
                    await self.evaluate_backend(
                        backend_type="backend",
                        backend_name=self.backend_name,
                        force=True,
                    )
                    await self.emit_status()
                    return True
        return False

    async def apply_config(
        self, actions: dict | None = None, enabled: bool | None = None, **kwargs
    ):
        # track relevant states before applying config
        _old_action_config = {
            key: AgentAction(**action.model_dump())
            for key, action in self.actions.items()
        }
        _old_enabled = self.enabled
        _old_backend_name = self.backend_name
        _old_backend_image_edit_name = self.backend_image_edit_name
        _old_backend_image_analyzation_name = self.backend_image_analyzation_name

        # apply config
        await super().apply_config(actions=actions, enabled=enabled, **kwargs)

        # check if relevant states have changed
        _handle_enable = self.enabled and not _old_enabled
        _handle_disable = not self.enabled and _old_enabled
        _backend_changed = self.backend_name != _old_backend_name
        _backend_image_edit_changed = (
            self.backend_image_edit_name != _old_backend_image_edit_name
        )
        _backend_image_analyzation_changed = (
            self.backend_image_analyzation_name != _old_backend_image_analyzation_name
        )

        await self.evaluate_backend(
            backend_type="backend",
            backend_name=self.backend_name,
            force=(_backend_changed or _handle_enable),
            old_config=_old_action_config,
        )
        await self.evaluate_backend(
            backend_type="backend_image_edit",
            backend_name=self.backend_image_edit_name,
            force=(_backend_image_edit_changed or _handle_enable),
            old_config=_old_action_config,
        )
        await self.evaluate_backend(
            backend_type="backend_image_analyzation",
            backend_name=self.backend_image_analyzation_name,
            force=(_backend_image_analyzation_changed or _handle_enable),
            old_config=_old_action_config,
        )

    async def evaluate_backend(
        self,
        backend_type: Literal[
            "backend", "backend_image_edit", "backend_image_analyzation"
        ],
        backend_name: str | None,
        force: bool = False,
        old_config: dict | None = None,
    ) -> Backend | None:
        if not backend_name:
            setattr(self, f"{backend_type}", None)
            return None
        backend = BACKENDS.get(backend_name)
        if not backend:
            raise ValueError(f"Backend {backend_name} not found")

        if backend_type not in [
            "backend",
            "backend_image_edit",
            "backend_image_analyzation",
        ]:
            raise ValueError(f"Invalid backend type: {backend_type}")

        fn = getattr(self, f"{backend_name}_{backend_type}", None)

        if not fn:
            raise ValueError(f"Backend {backend_name} does not support {backend_type}")

        backend = await fn(old_config=old_config, force=force)
        setattr(self, f"{backend_type}", backend)
        return backend

    ## Ready check

    async def check_backends(self, result: ReadyCheckResult):
        if VERBOSE_LOGGING:
            log.debug(
                "checking backends",
                agent=self.agent_type,
                backend=self.backend,
                backend_image_edit=self.backend_image_edit,
                backend_image_analyzation=self.backend_image_analyzation,
            )
        if self.backend:
            backend_ready: BackendStatus = await self.backend.ready()
            result.backend = backend_ready
        if self.backend_image_edit:
            backend_image_edit_ready: BackendStatus = (
                await self.backend_image_edit.ready()
            )
            result.backend_image_edit = backend_image_edit_ready
        if self.backend_image_analyzation:
            backend_image_analyzation_ready: BackendStatus = (
                await self.backend_image_analyzation.ready()
            )
            result.backend_image_analyzation = backend_image_analyzation_ready
        return result

    async def ready_check(self) -> ReadyCheckResult:
        if not self.enabled:
            return
        result = ReadyCheckResult()
        if VERBOSE_LOGGING:
            log.debug("ready check", agent=self.agent_type)
        task = asyncio.create_task(self.check_backends(result))
        await super().ready_check(task)
        return result

    async def on_ready_check_success(self, result: ReadyCheckResult):
        if result != self.ready_check_result:
            await self.emit_status()
            self.ready_check_result = result

    async def on_ready_check_failure(self, error):
        if self.ready_check_result.error != error:
            await self.emit_status()
            self.ready_check_result.error = error

    ## Status

    async def emit_status(self, processing: bool = None):
        if self.enabled:
            if self.backend_name:
                fn = getattr(self, f"{self.backend_name}_emit_status", None)
                if fn:
                    await fn(processing)
            if (
                self.backend_image_edit_name
                and self.backend_image_edit_name != self.backend_name
            ):
                fn = getattr(self, f"{self.backend_image_edit_name}_emit_status", None)
                if fn:
                    await fn(processing)
            if (
                self.backend_image_analyzation_name
                and self.backend_image_analyzation_name != self.backend_name
                and self.backend_image_analyzation_name != self.backend_image_edit_name
            ):
                fn = getattr(
                    self, f"{self.backend_image_analyzation_name}_emit_status", None
                )
                if fn:
                    await fn(processing)
        await super().emit_status(processing)
