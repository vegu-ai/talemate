import asyncio
import traceback

import structlog

import talemate.agents.visual.automatic1111
import talemate.agents.visual.comfyui
import talemate.agents.visual.openai_image
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)
from talemate.agents.registry import register
from talemate.client.base import ClientBase
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers as signal_handlers
from talemate.prompts.base import Prompt

from .commands import *  # noqa
from .context import VIS_TYPES, VisualContext, visual_context
from .handlers import HANDLERS
from .schema import RESOLUTION_MAP, RenderSettings
from .style import MAJOR_STYLES, STYLE_MAP, Style, combine_styles
from .websocket_handler import VisualWebsocketHandler

__all__ = [
    "VisualAgent",
]

BACKENDS = [
    {"value": mixin_backend, "label": mixin["label"]}
    for mixin_backend, mixin in HANDLERS.items()
]

log = structlog.get_logger("talemate.agents.visual")


class VisualBase(Agent):
    """
    The visual agent
    """

    agent_type = "visual"
    verbose_name = "Visualizer"
    essential = False
    websocket_handler = VisualWebsocketHandler

    ACTIONS = {}

    def __init__(self, client: ClientBase, *kwargs):
        self.client = client
        self.is_enabled = False
        self.backend_ready = False
        self.initialized = False
        self.config = load_config()
        self.actions = {
            "_config": AgentAction(
                enabled=True,
                label="Configure",
                description="Visual agent configuration",
                config={
                    "backend": AgentActionConfig(
                        type="text",
                        choices=BACKENDS,
                        value="automatic1111",
                        label="Backend",
                        description="The backend to use for visual processing",
                    ),
                    "default_style": AgentActionConfig(
                        type="text",
                        value="ink_illustration",
                        choices=MAJOR_STYLES,
                        label="Default Style",
                        description="The default style to use for visual processing",
                    ),
                },
            ),
            "automatic_generation": AgentAction(
                enabled=False,
                label="Automatic Generation",
                description="Allow automatic generation of visual content",
            ),
            "process_in_background": AgentAction(
                enabled=True,
                label="Process in Background",
                description="Process renders in the background",
            ),
        }

        for action_name, action in self.ACTIONS.items():
            self.actions[action_name] = action

        signal_handlers["config_saved"].connect(self.on_config_saved)

    @property
    def enabled(self):
        return self.is_enabled

    @property
    def has_toggle(self):
        return True

    @property
    def experimental(self):
        return False

    @property
    def backend(self):
        return self.actions["_config"].config["backend"].value

    @property
    def backend_name(self):
        key = self.actions["_config"].config["backend"].value

        for backend in BACKENDS:
            if backend["value"] == key:
                return backend["label"]

    @property
    def default_style(self):
        return STYLE_MAP.get(
            self.actions["_config"].config["default_style"].value, Style()
        )

    @property
    def ready(self):
        return self.backend_ready

    @property
    def api_url(self):
        try:
            return self.actions[self.backend].config["api_url"].value
        except KeyError:
            return None

    @property
    def agent_details(self):
        details = {
            "backend": AgentDetail(
                icon="mdi-server-outline",
                value=self.backend_name,
                description="The backend to use for visual processing",
            ).model_dump(),
            "client": AgentDetail(
                icon="mdi-network-outline",
                value=self.client.name if self.client else None,
                description="The client to use for prompt generation",
            ).model_dump(),
        }

        if not self.ready and self.enabled:
            details["status"] = AgentDetail(
                icon="mdi-alert",
                value=f"{self.backend_name} not ready",
                color="error",
                description=self.ready_check_error
                or f"{self.backend_name} is not ready for processing",
            ).model_dump()

        return details

    @property
    def process_in_background(self):
        return self.actions["process_in_background"].enabled

    @property
    def allow_automatic_generation(self):
        return self.actions["automatic_generation"].enabled

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        asyncio.create_task(self.emit_status())

    async def on_ready_check_success(self):
        prev_ready = self.backend_ready
        self.backend_ready = True
        if not prev_ready:
            await self.emit_status()

    async def on_ready_check_failure(self, error):
        prev_ready = self.backend_ready
        self.backend_ready = False
        self.ready_check_error = str(error)
        if prev_ready:
            await self.emit_status()

    async def ready_check(self):
        if not self.enabled:
            return
        backend = self.backend
        fn = getattr(self, f"{backend.lower()}_ready", None)
        task = asyncio.create_task(fn())
        await super().ready_check(task)

    async def apply_config(self, *args, **kwargs):

        try:
            backend = kwargs["actions"]["_config"]["config"]["backend"]["value"]
        except KeyError:
            backend = self.backend

        backend_changed = backend != self.backend

        if backend_changed:
            self.backend_ready = False

        log.info(
            "apply_config",
            backend=backend,
            backend_changed=backend_changed,
            old_backend=self.backend,
        )

        await super().apply_config(*args, **kwargs)
        backend_fn = getattr(self, f"{self.backend.lower()}_apply_config", None)
        if backend_fn:
            task = asyncio.create_task(
                backend_fn(backend_changed=backend_changed, *args, **kwargs)
            )
            await self.set_background_processing(task)

        if not self.backend_ready:
            await self.ready_check()

        self.initialized = True

    def resolution_from_format(self, format: str, model_type: str = "sdxl"):
        if model_type not in RESOLUTION_MAP:
            raise ValueError(f"Model type {model_type} not found in resolution map")
        return RESOLUTION_MAP[model_type].get(
            format, RESOLUTION_MAP[model_type]["portrait"]
        )

    def prepare_prompt(self, prompt: str, styles: list[Style] = None) -> Style:

        prompt_style = Style()
        prompt_style.load(prompt)

        if styles:
            prompt_style.prepend(*styles)

        return prompt_style

    def vis_type_styles(self, vis_type: str):
        if vis_type == VIS_TYPES.CHARACTER:
            portrait_style = STYLE_MAP["character_portrait"].copy()
            return portrait_style
        elif vis_type == VIS_TYPES.ENVIRONMENT:
            environment_style = STYLE_MAP["environment"].copy()
            return environment_style
        return Style()

    async def apply_image(self, image: str):
        context = visual_context.get()

        log.debug("apply_image", image=image[:100], context=context)

        if context.vis_type == VIS_TYPES.CHARACTER:
            await self.apply_image_character(image, context.character_name)

    async def apply_image_character(self, image: str, character_name: str):
        character = self.scene.get_character(character_name)

        if not character:
            log.error("character not found", character_name=character_name)
            return

        if character.cover_image:
            log.info("character cover image already set", character_name=character_name)
            return

        asset = self.scene.assets.add_asset_from_image_data(
            f"data:image/png;base64,{image}"
        )
        character.cover_image = asset.id
        self.scene.assets.cover_image = asset.id
        self.scene.emit_status()

    async def emit_image(self, image: str):
        context = visual_context.get()
        await self.apply_image(image)
        emit(
            "image_generated",
            websocket_passthrough=True,
            data={
                "base64": image,
                "context": context.model_dump() if context else None,
            },
        )

    @set_processing
    async def generate(
        self, format: str = "portrait", prompt: str = None, automatic: bool = False
    ):

        context = visual_context.get()

        if not self.enabled:
            log.warning("generate", skipped="Visual agent not enabled")
            return

        if automatic and not self.allow_automatic_generation:
            log.warning(
                "generate",
                skipped="Automatic generation disabled",
                prompt=prompt,
                format=format,
                context=context,
            )
            return

        if not context and not prompt:
            log.error("generate", error="No context or prompt provided")
            return

        # Handle prompt generation based on context

        if not prompt and context.prompt:
            prompt = context.prompt

        if context.vis_type == VIS_TYPES.ENVIRONMENT and not prompt:
            prompt = await self.generate_environment_prompt(
                instructions=context.instructions
            )
        elif context.vis_type == VIS_TYPES.CHARACTER and not prompt:
            prompt = await self.generate_character_prompt(
                context.character_name, instructions=context.instructions
            )
        else:
            prompt = prompt or context.prompt

        initial_prompt = prompt

        # Augment the prompt with styles based on context

        thematic_style = self.default_style
        vis_type_styles = self.vis_type_styles(context.vis_type)
        prompt = self.prepare_prompt(prompt, [vis_type_styles, thematic_style])

        if not prompt:
            log.error(
                "generate", error="No prompt provided and no context to generate from"
            )
            return

        context.prompt = initial_prompt
        context.prepared_prompt = str(prompt)

        # Handle format (can either come from context or be passed in)

        if not format and context.format:
            format = context.format
        elif not format:
            format = "portrait"

        context.format = format

        # Call the backend specific generate function

        backend = self.backend
        fn = f"{backend.lower()}_generate"

        log.info(
            "generate", backend=backend, prompt=prompt, format=format, context=context
        )

        if not hasattr(self, fn):
            log.error("generate", error=f"Backend {backend} does not support generate")

        # add the function call to the asyncio task queue

        if self.process_in_background:
            task = asyncio.create_task(getattr(self, fn)(prompt=prompt, format=format))
            await self.set_background_processing(task)
        else:
            await getattr(self, fn)(prompt=prompt, format=format)

    @set_processing
    async def generate_environment_prompt(self, instructions: str = None):

        response = await Prompt.request(
            "visual.generate-environment-prompt",
            self.client,
            "visualize",
            {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            },
        )

        return response.strip()

    @set_processing
    async def generate_character_prompt(
        self, character_name: str, instructions: str = None
    ):

        character = self.scene.get_character(character_name)

        response = await Prompt.request(
            "visual.generate-character-prompt",
            self.client,
            "visualize",
            {
                "scene": self.scene,
                "character_name": character_name,
                "character": character,
                "max_tokens": self.client.max_token_length,
                "instructions": instructions or "",
            },
        )

        return response.strip()

    async def generate_environment_background(self, instructions: str = None):
        with VisualContext(vis_type=VIS_TYPES.ENVIRONMENT, instructions=instructions):
            await self.generate(format="landscape")

    async def generate_character_portrait(
        self,
        character_name: str,
        instructions: str = None,
    ):
        with VisualContext(
            vis_type=VIS_TYPES.CHARACTER,
            character_name=character_name,
            instructions=instructions,
        ):
            await self.generate(format="portrait")


# apply mixins to the agent (from HANDLERS dict[str, cls])

for mixin_backend, mixin in HANDLERS.items():
    mixin_cls = mixin["cls"]
    VisualBase = type("VisualAgent", (mixin_cls, VisualBase), {})

    extend_actions = getattr(mixin_cls, "EXTEND_ACTIONS", {})

    for action_name, action in extend_actions.items():
        VisualBase.ACTIONS[action_name] = action


@register()
class VisualAgent(VisualBase):
    pass
