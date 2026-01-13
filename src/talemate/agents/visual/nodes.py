import asyncio
import structlog
from typing import ClassVar
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
    TYPE_CHOICES,
    Node,
    InputValueError,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode
from talemate.game.engine.nodes.run import FunctionWrapper
from talemate.agents.visual.schema import (
    PROMPT_TYPE,
    VIS_TYPE,
    VisualPrompt,
    VisualPromptPart,
    GenerationRequest,
    GenerationResponse,
    FORMAT_TYPE,
    VIS_TYPE_TO_FORMAT,
    GEN_TYPE,
    BackendBase,
    ENUM_TYPES,
    AssetAttachmentContext,
    AnalysisRequest,
)
from talemate.context import active_scene

__all__ = [
    "VisualSettings",
    "Prompt",
    "UnpackPrompt",
    "ApplyStyles",
    "ApplyStyle",
    "SelectBackend",
    "GenerationRequestNode",
    "GenerateImage",
    "UnpackGenerationRequest",
    "UnpackGenerationResponse",
    "BackendStatus",
    "PromptPart",
    "AnalyzeImages",
]

log = structlog.get_logger("talemate.game.engine.nodes.agents.visual")


TYPE_CHOICES.extend(
    [
        "visual/prompt",
        "visual/prompt_part",
        "visual/reference",
        "visual/generation_request",
        "visual/generation_response",
    ]
)


@register("agents/visual/Settings")
class VisualSettings(AgentSettingsNode):
    """
    Base node to render visual agent settings.
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Visual Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/visual/EnumValues")
class EnumValues(Node):
    """
    Returns the values of an enum
    """

    class Fields:
        enum = PropertyField(
            name="enum",
            type="str",
            description="The enum to get the values of",
            default="VIS_TYPE",
            choices=ENUM_TYPES,
        )

    def __init__(self, title="Visual Enum Values", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("enum", "VIS_TYPE")
        self.add_output("values", socket_type="list")

    async def run(self, state: GraphState):
        enum_name: str = self.normalized_input_value("enum")
        values: list[str] = []
        if enum_name == "VIS_TYPE":
            values = VIS_TYPE.choice_values()
        elif enum_name == "GEN_TYPE":
            values = GEN_TYPE.choice_values()
        elif enum_name == "FORMAT_TYPE":
            values = FORMAT_TYPE.choice_values()
        elif enum_name == "PROMPT_TYPE":
            values = PROMPT_TYPE.choice_values()

        self.set_output_values({"values": values})


@register("agents/visual/BackendStatus")
class BackendStatus(AgentNode):
    """
    Checks the status of the backend
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Backend Status", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("can_generate_images", socket_type="bool")
        self.add_output("can_edit_images", socket_type="bool")
        self.add_output("max_references", socket_type="int")

    async def run(self, state: GraphState):
        can_generate_images = self.agent.can_generate_images
        can_edit_images = self.agent.can_edit_images
        max_references = (
            self.agent.backend_image_edit.max_references
            if self.agent.backend_image_edit
            else 0
        )
        self.set_output_values(
            {
                "can_generate_images": can_generate_images,
                "can_edit_images": can_edit_images,
                "max_references": max_references,
            }
        )


@register("agents/visual/PromptPart")
class PromptPart(Node):
    """
    Creates a visual prompt part instance
    """

    class Fields:
        instructions = PropertyField(
            name="instructions",
            type="text",
            description="The instructions for the prompt part",
            default="",
        )
        negative_keywords_raw = PropertyField(
            name="negative_keywords_raw",
            type="list",
            description="The negative keywords for the prompt part",
            default=[],
        )
        positive_keywords_raw = PropertyField(
            name="positive_keywords_raw",
            type="list",
            description="The positive keywords for the prompt part",
            default=[],
        )
        positive_descriptive = PropertyField(
            name="positive_descriptive",
            type="text",
            description="The positive descriptive for the prompt part",
            default="",
        )
        negative_descriptive = PropertyField(
            name="negative_descriptive",
            type="text",
            description="The negative descriptive for the prompt part",
            default="",
        )

    def __init__(self, title="Visual Prompt Part", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("positive_keywords_raw", socket_type="list,str", optional=True)
        self.add_input("negative_keywords_raw", socket_type="list,str", optional=True)
        self.add_input("positive_descriptive", socket_type="str", optional=True)
        self.add_input("negative_descriptive", socket_type="str", optional=True)

        self.set_property("instructions", "")
        self.set_property("positive_keywords_raw", [])
        self.set_property("negative_keywords_raw", [])
        self.set_property("positive_descriptive", "")
        self.set_property("negative_descriptive", "")

        self.add_output("prompt_part", socket_type="visual/prompt_part")
        self.add_output("instructions", socket_type="str")
        self.add_output("positive_keywords_raw", socket_type="list")
        self.add_output("negative_keywords_raw", socket_type="list")
        self.add_output("implied_negative_keywords", socket_type="list")
        self.add_output("positive_keywords", socket_type="list")
        self.add_output("negative_keywords", socket_type="list")
        self.add_output("positive_descriptive", socket_type="str")
        self.add_output("negative_descriptive", socket_type="str")

    async def run(self, state: GraphState):
        instructions = self.normalized_input_value("instructions")
        negative_keywords_raw = (
            self.normalized_input_value("negative_keywords_raw") or []
        )
        positive_keywords_raw = (
            self.normalized_input_value("positive_keywords_raw") or []
        )
        positive_descriptive = self.normalized_input_value("positive_descriptive") or ""
        negative_descriptive = self.normalized_input_value("negative_descriptive") or ""

        if isinstance(negative_keywords_raw, str):
            negative_keywords_raw = negative_keywords_raw.split(", ")
        if isinstance(positive_keywords_raw, str):
            positive_keywords_raw = positive_keywords_raw.split(", ")

        prompt_part = VisualPromptPart(
            instructions=instructions,
            negative_keywords_raw=negative_keywords_raw,
            positive_keywords_raw=positive_keywords_raw,
            positive_descriptive=positive_descriptive,
            negative_descriptive=negative_descriptive,
        )
        self.set_output_values(
            {
                "prompt_part": prompt_part,
                "instructions": prompt_part.instructions,
                "negative_keywords_raw": prompt_part.negative_keywords_raw,
                "positive_keywords_raw": prompt_part.positive_keywords_raw,
                "positive_descriptive": prompt_part.positive_descriptive,
                "negative_descriptive": prompt_part.negative_descriptive,
                "implied_negative_keywords": prompt_part.implied_negative_keywords,
                "negative_keywords": prompt_part.negative_keywords,
                "positive_keywords": prompt_part.positive_keywords,
            }
        )


@register("agents/visual/Prompt")
class Prompt(Node):
    """
    Creates a visual prompt instance
    """

    class Fields:
        prompt_type = PropertyField(
            name="prompt_type",
            type="str",
            description="The type of prompt to create",
            default="KEYWORDS",
            choices=PROMPT_TYPE.choice_values(),
        )

    def __init__(self, title="Visual Prompt", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("prompt_type", socket_type="str", optional=True)
        self.add_input("parts", socket_type="list", optional=True)
        self.set_property("prompt_type", "KEYWORDS")
        self.add_output("prompt", socket_type="visual/prompt")

    async def run(self, state: GraphState):
        prompt_type = self.normalized_input_value("prompt_type")
        parts = self.normalized_input_value("parts")
        if not parts:
            parts = []
        prompt = VisualPrompt(prompt_type=PROMPT_TYPE(prompt_type), parts=parts)
        self.set_output_values({"prompt": prompt})


@register("agents/visual/UnpackPrompt")
class UnpackPrompt(Node):
    """
    Unpacks a visual prompt into a list of prompt parts
    """

    def __init__(self, title="Unpack Visual Prompt", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("prompt", socket_type="visual/prompt")
        self.add_output("prompt", socket_type="visual/prompt")
        self.add_output("parts", socket_type="list")
        self.add_output("prompt_type", socket_type="str")
        self.add_output("instructions", socket_type="str")
        self.add_output("positive_prompt", socket_type="str")
        self.add_output("negative_prompt", socket_type="str")
        self.add_output("positive_prompt_keywords", socket_type="str")
        self.add_output("negative_prompt_keywords", socket_type="str")
        self.add_output("positive_prompt_descriptive", socket_type="str")
        self.add_output("negative_prompt_descriptive", socket_type="str")

    async def run(self, state: GraphState):
        prompt = self.normalized_input_value("prompt")
        parts = prompt.parts
        self.set_output_values(
            {
                "prompt": prompt,
                "prompt_type": str(prompt.prompt_type),
                "instructions": prompt.instructions,
                "parts": parts,
                "positive_prompt": prompt.positive_prompt,
                "negative_prompt": prompt.negative_prompt,
                "positive_prompt_keywords": prompt.positive_prompt_keywords,
                "negative_prompt_keywords": prompt.negative_prompt_keywords,
                "positive_prompt_descriptive": prompt.positive_prompt_descriptive,
                "negative_prompt_descriptive": prompt.negative_prompt_descriptive,
            }
        )


@register("agents/visual/ApplyStyles")
class ApplyStyles(AgentNode):
    """
    Applies configured styles to a visual prompt
    """

    _agent_name: ClassVar[str] = "visual"

    class Fields:
        vis_type = PropertyField(
            name="vis_type",
            type="str",
            description="The type of visual to apply styles to",
            default="UNSPECIFIED",
            choices=VIS_TYPE.choice_values(),
        )

    def __init__(self, title="Apply Styles", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("prompt", socket_type="visual/prompt")
        self.add_input("vis_type", socket_type="str", optional=True)
        self.set_property("vis_type", "UNSPECIFIED")
        self.add_output("prompt", socket_type="visual/prompt")
        self.add_output("vis_type", socket_type="str")

    async def run(self, state: GraphState):
        prompt = self.normalized_input_value("prompt")
        vis_type = self.normalized_input_value("vis_type")
        _prompt: VisualPrompt = self.agent.apply_styles(prompt, VIS_TYPE(vis_type))
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "prompt": _prompt,
                "vis_type": vis_type,
            }
        )


@register("agents/visual/ApplyStyle")
class ApplyStyle(AgentNode):
    """
    Applies a style to a visual prompt
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Apply Style", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("prompt", socket_type="visual/prompt")
        self.add_input("template_id", socket_type="str")
        self.add_output("prompt", socket_type="visual/prompt")
        self.add_output("template_id", socket_type="str")
        self.add_output("prompt_part", socket_type="visual/prompt_part")

    async def run(self, state: GraphState):
        prompt = self.normalized_input_value("prompt")
        template_id = self.normalized_input_value("template_id")
        prompt_part: VisualPromptPart | None = self.agent.apply_style(
            prompt, template_id
        )
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "prompt": prompt,
                "template_id": template_id,
                "prompt_part": prompt_part,
            }
        )


@register("agents/visual/SelectBackend")
class SelectBackend(AgentNode):
    """
    Selects a backend based on the generation type
    """

    _agent_name: ClassVar[str] = "visual"

    class Fields:
        vis_type = PropertyField(
            name="vis_type",
            type="str",
            description="The type of visual to generate",
            default="UNSPECIFIED",
            choices=VIS_TYPE.choice_values(),
        )

    def __init__(self, title="Select Backend", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("vis_type", socket_type="str", optional=True)
        self.add_input("reference_assets", socket_type="list", optional=True)
        self.set_property("vis_type", "UNSPECIFIED")
        self.add_output("state")
        self.add_output("backend_name", socket_type="str")
        self.add_output("gen_type", socket_type="str")
        self.add_output("vis_type", socket_type="str")
        self.add_output("prompt_type", socket_type="str")
        self.add_output("format", socket_type="str")
        self.add_output("reference_assets", socket_type="list")

    async def run(self, state: GraphState):
        vis_type = self.normalized_input_value("vis_type")
        reference_assets = self.normalized_input_value("reference_assets") or []

        gen_type: GEN_TYPE = GEN_TYPE.TEXT_TO_IMAGE

        if reference_assets and self.agent.can_edit_images:
            gen_type = GEN_TYPE.IMAGE_EDIT
        elif (
            not reference_assets
            and not self.agent.can_generate_images
            and self.agent.can_edit_images
        ):
            gen_type = GEN_TYPE.IMAGE_EDIT

        if gen_type == GEN_TYPE.IMAGE_EDIT:
            backend: BackendBase = self.agent.backend_image_edit
        else:
            backend: BackendBase = self.agent.backend

        prompt_type = (
            backend.prompt_type if backend else self.agent.fallback_prompt_type
        )

        log.debug("SelectBackend", backend=backend, prompt_type=prompt_type)

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "backend_name": backend.name if backend else "",
                "gen_type": gen_type,
                "prompt_type": prompt_type,
                "format": VIS_TYPE_TO_FORMAT[VIS_TYPE(vis_type)],
                "vis_type": vis_type,
                "reference_assets": reference_assets,
            }
        )


@register("agents/visual/GenerationRequest")
class GenerationRequestNode(AgentNode):
    """
    Creates a generation request for image generation.

    Inputs:
    - prompt: visual prompt object (required)
    - vis_type: type of visual to generate (optional)
    - gen_type: type of generation (TEXT_TO_IMAGE, etc.) (optional)
    - format: image format/aspect ratio (optional)
    - instructions: additional instructions for generation (optional)
    - character_name: name of character for character-specific generation (optional)
    - reference_assets: list of reference asset IDs (optional)
    - callback: callback function to run after generation (optional)
    - save_asset: whether to save the generated asset to scene (optional)
    - extra_config: additional configuration dict (optional)
    - asset_attachment_context: controls automatic asset attachment behavior (optional)

    Outputs:
    - generation_request: the created generation request object
    - prompt: the visual prompt (passed through)
    - vis_type: visual type (passed through)
    - format: format type (passed through)
    - character_name: character name (passed through)
    - reference_assets: reference assets list (passed through)
    - gen_type: generation type (passed through)
    - save_asset: save asset flag (passed through)
    - extra_config: extra config dict (passed through)
    """

    _agent_name: ClassVar[str] = "visual"

    class Fields:
        vis_type = PropertyField(
            name="vis_type",
            type="str",
            description="The type of visual to generate",
            default="UNSPECIFIED",
            choices=VIS_TYPE.choice_values(),
        )
        gen_type = PropertyField(
            name="gen_type",
            type="str",
            description="The type of generation to perform",
            default="TEXT_TO_IMAGE",
            choices=GEN_TYPE.choice_values(),
        )
        format = PropertyField(
            name="format",
            type="str",
            description="The format of the visual to generate",
            default="LANDSCAPE",
            choices=FORMAT_TYPE.choice_values(),
        )
        character_name = PropertyField(
            name="character_name",
            type="str",
            description="The name of the character to generate",
            default="",
        )
        extra_config = PropertyField(
            name="extra_config",
            type="dict",
            description="The extra configuration for the generation request",
            default={},
        )
        instructions = PropertyField(
            name="instructions",
            type="text",
            description="The instructions for the generation request",
            default="",
        )

    def __init__(self, title="Visual Generation Request", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("prompt", socket_type="visual/prompt")
        self.add_input("vis_type", socket_type="str", optional=True)
        self.add_input("gen_type", socket_type="str", optional=True)
        self.add_input("format", socket_type="str", optional=True)
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("character_name", socket_type="str", optional=True)
        self.add_input("reference_assets", socket_type="list", optional=True)
        self.add_input("callback", socket_type="function", optional=True)
        self.add_input("extra_config", socket_type="dict", optional=True)
        self.add_input(
            "asset_attachment_context",
            socket_type="asset_attachment_context",
            optional=True,
        )
        self.set_property("vis_type", "UNSPECIFIED")
        self.set_property("gen_type", "TEXT_TO_IMAGE")
        self.set_property("format", "LANDSCAPE")
        self.set_property("character_name", "")
        self.set_property("instructions", "")
        self.set_property("extra_config", {})
        self.add_output("generation_request", socket_type="visual/generation_request")
        self.add_output("prompt", socket_type="visual/prompt")
        self.add_output("vis_type", socket_type="str")
        self.add_output("format", socket_type="str")
        self.add_output("character_name", socket_type="str")
        self.add_output("reference_assets", socket_type="list")
        self.add_output("gen_type", socket_type="str")
        self.add_output("extra_config", socket_type="dict")

    async def run(self, state: GraphState):
        prompt: VisualPrompt = self.normalized_input_value("prompt")
        vis_type = self.normalized_input_value("vis_type")
        gen_type = self.normalized_input_value("gen_type")
        format = self.normalized_input_value("format")
        character_name = self.normalized_input_value("character_name")
        reference_assets = self.normalized_input_value("reference_assets") or []
        extra_config = self.normalized_input_value("extra_config") or {}
        callback: FunctionWrapper | None = self.normalized_input_value("callback")
        instructions = self.normalized_input_value("instructions") or ""
        asset_attachment_context: AssetAttachmentContext = self.normalized_input_value(
            "asset_attachment_context"
        )
        if callback and not isinstance(callback, FunctionWrapper):
            raise InputValueError(
                self, "callback", "callback must be a FunctionWrapper instance"
            )

        async def callback_wrapper(response: GenerationResponse):
            if callback:
                await callback(response=response)

        generation_request = GenerationRequest(
            prompt=prompt.positive_prompt,
            negative_prompt=prompt.negative_prompt,
            instructions=instructions,
            vis_type=vis_type,
            gen_type=gen_type,
            format=format,
            character_name=character_name,
            reference_assets=reference_assets,
            callback=callback_wrapper,
            extra_config=extra_config,
            asset_attachment_context=asset_attachment_context
            or AssetAttachmentContext(),
        )
        self.set_output_values(
            {
                "generation_request": generation_request,
                "prompt": prompt,
                "vis_type": vis_type,
                "format": format,
                "character_name": character_name,
                "reference_assets": reference_assets,
                "gen_type": generation_request.gen_type,
                "extra_config": extra_config,
            }
        )


@register("agents/visual/GenerateImage")
class GenerateImage(AgentNode):
    """
    Generates an image
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Generate Image", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("generation_request", socket_type="visual/generation_request")
        self.add_output("state")
        self.add_output("generation_request", socket_type="visual/generation_request")
        self.add_output("generation_response", socket_type="visual/generation_response")

    async def run(self, state: GraphState):
        generation_request: GenerationRequest = self.normalized_input_value(
            "generation_request"
        )
        response = await self.agent.generate(generation_request)
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "generation_request": generation_request,
                "generation_response": response,
            }
        )


@register("agents/visual/UnpackGenerationRequest")
class UnpackGenerationRequest(AgentNode):
    """
    Unpacks a generation request
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Unpack Visual Generation Request", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("generation_request", socket_type="visual/generation_request")
        self.add_output("generation_request", socket_type="visual/generation_request")
        self.add_output("prompt", socket_type="str")
        self.add_output("vis_type", socket_type="str")
        self.add_output("format", socket_type="str")
        self.add_output("character_name", socket_type="str")
        self.add_output("reference_assets", socket_type="list")
        self.add_output("gen_type", socket_type="str")
        self.add_output("extra_config", socket_type="dict")
        self.add_output(
            "asset_attachment_context", socket_type="asset_attachment_context"
        )

    async def run(self, state: GraphState):
        generation_request: GenerationRequest = self.require_input("generation_request")
        self.set_output_values(
            {
                "generation_request": generation_request,
                "prompt": generation_request.prompt,
                "vis_type": generation_request.vis_type,
                "format": generation_request.format,
                "character_name": generation_request.character_name,
                "reference_assets": generation_request.reference_assets,
                "gen_type": generation_request.gen_type,
                "extra_config": generation_request.extra_config,
                "asset_attachment_context": generation_request.asset_attachment_context,
            }
        )


@register("agents/visual/UnpackGenerationResponse")
class UnpackGenerationResponse(AgentNode):
    """
    Unpacks a generation response
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Unpack Visual Generation Response", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("generation_response", socket_type="visual/generation_response")
        self.add_output("generation_response", socket_type="visual/generation_response")
        self.add_output("base64", socket_type="str")
        self.add_output("image_data", socket_type="str")
        self.add_output("id", socket_type="str")
        self.add_output("backend_name", socket_type="str")
        self.add_output("request", socket_type="visual/generation_request")

    async def run(self, state: GraphState):
        generation_response: GenerationResponse = self.normalized_input_value(
            "generation_response"
        )
        self.set_output_values(
            {
                "generation_response": generation_response,
                "base64": generation_response.base64,
                "image_data": generation_response.image_data,
                "id": generation_response.id,
                "backend_name": generation_response.backend_name,
                "request": generation_response.request,
            }
        )


@register("agents/visual/AnalyzeImages")
class AnalyzeImages(AgentNode):
    """
    Analyzes images in batches using asyncio.Semaphore to limit concurrent requests.

    Inputs:
    - state: graph state (required)
    - asset_ids: list of asset IDs to analyze (required)
    - missing_only: only analyze assets without existing analysis (optional, default True)
    - prompt: analysis prompt to use (optional, default "Describe this image in detail.")
    - save: whether to save analysis to asset meta (optional, default True)

    Outputs:
    - state: graph state (passed through)
    - asset_ids: original list of asset IDs (passed through)
    - missing_only: missing_only flag (passed through)
    - prompt: analysis prompt used (passed through)
    - save: save flag (passed through)
    - analyzed_ids: list of successfully analyzed asset IDs
    - skipped_ids: list of skipped asset IDs (missing assets or already analyzed)
    - failed_ids: list of asset IDs that failed to analyze
    """

    _agent_name: ClassVar[str] = "visual"

    class Fields:
        missing_only = PropertyField(
            name="missing_only",
            type="bool",
            description="Only analyze assets that don't have an existing analysis",
            default=True,
        )
        prompt = PropertyField(
            name="prompt",
            type="text",
            description="The prompt to use for image analysis",
            default="Describe this image in detail. (3 paragraphs max.)",
        )
        save = PropertyField(
            name="save",
            type="bool",
            description="Whether to save the analysis to asset meta",
            default=True,
        )

    def __init__(self, title="Analyze Images", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("asset_ids", socket_type="list")
        self.add_input("missing_only", socket_type="bool", optional=True)
        self.add_input("prompt", socket_type="str", optional=True)
        self.add_input("save", socket_type="bool", optional=True)

        self.set_property("missing_only", True)
        self.set_property(
            "prompt", "Describe this image in detail. (3 paragraphs max.)"
        )
        self.set_property("save", True)

        self.add_output("state")
        self.add_output("asset_ids", socket_type="list")
        self.add_output("missing_only", socket_type="bool")
        self.add_output("prompt", socket_type="str")
        self.add_output("save", socket_type="bool")
        self.add_output("analyzed_ids", socket_type="list")
        self.add_output("skipped_ids", socket_type="list")
        self.add_output("failed_ids", socket_type="list")

    async def run(self, state: GraphState):
        # Check if agent can analyze images, bail early if not
        if not self.agent.can_analyze_images:
            return

        asset_ids = self.normalized_input_value("asset_ids") or []
        missing_only = self.normalized_input_value("missing_only")
        prompt = self.normalized_input_value("prompt")
        save = self.normalized_input_value("save")

        scene = active_scene.get()

        # Filter assets if missing_only is True
        assets_to_analyze = []
        skipped_ids = []

        for asset_id in asset_ids:
            if asset_id not in scene.assets.assets:
                log.warning("analyze_images_asset_not_found", asset_id=asset_id)
                skipped_ids.append(asset_id)
                continue

            asset = scene.assets.get_asset(asset_id)
            if missing_only and asset.meta.analysis:
                log.debug("analyze_images_skipping_analyzed", asset_id=asset_id)
                skipped_ids.append(asset_id)
            else:
                assets_to_analyze.append(asset_id)

        # Analyze in batches using semaphore (max 3 concurrent)
        semaphore = asyncio.Semaphore(3)
        analyzed_ids = []
        failed_ids = []

        async def analyze_asset(asset_id: str):
            async with semaphore:
                try:
                    log.debug("analyze_images_analyzing", asset_id=asset_id)
                    request = AnalysisRequest(
                        prompt=prompt,
                        asset_id=asset_id,
                        save=save,
                    )
                    await self.agent.analyze(request)
                    analyzed_ids.append(asset_id)
                    log.info("analyze_images_success", asset_id=asset_id)
                except Exception as e:
                    log.error("analyze_images_failed", asset_id=asset_id, error=str(e))
                    failed_ids.append(asset_id)

        # Create tasks for all assets
        tasks = [analyze_asset(asset_id) for asset_id in assets_to_analyze]

        # Wait for all tasks to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        log.info(
            "analyze_images_complete",
            total=len(asset_ids),
            analyzed=len(analyzed_ids),
            skipped=len(skipped_ids),
            failed=len(failed_ids),
        )

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "asset_ids": asset_ids,
                "missing_only": missing_only,
                "prompt": prompt,
                "save": save,
                "analyzed_ids": analyzed_ids,
                "skipped_ids": skipped_ids,
                "failed_ids": failed_ids,
            }
        )
