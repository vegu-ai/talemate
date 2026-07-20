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
    Returns the possible values of one of the visual agent's enums
    (VIS_TYPE, GEN_TYPE, FORMAT_TYPE or PROMPT_TYPE), selected via the
    enum property.

    Properties:

    - enum: The enum to get the values of

    Outputs:

    - values: The list of the enum's values
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
    Reports the capabilities of the visual agent's currently configured
    backends.

    Outputs:

    - can_generate_images: Whether an image generation backend is available
    - can_edit_images: Whether an image editing backend is available
    - max_references: Maximum number of reference images the image-edit
      backend supports (0 if none is available)
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
    Creates a visual prompt part from instructions, keyword lists and
    descriptive text. Prompt parts are combined into a visual prompt (via the
    Prompt node), which compiles the final positive / negative prompts from
    them. Keyword inputs given as a single string are split on ", ", and
    positive keywords prefixed with "no " (e.g. "no glasses") are treated as
    implied negative keywords.

    Inputs:

    - instructions: Free-form instructions for the prompt part
    - positive_keywords_raw: Positive keywords as a list or comma-separated string
    - negative_keywords_raw: Negative keywords as a list or comma-separated string
    - positive_descriptive: Descriptive (prose) positive prompt text
    - negative_descriptive: Descriptive (prose) negative prompt text

    Outputs:

    - prompt_part: The created visual prompt part
    - instructions: The instructions (passed through)
    - positive_keywords_raw: Raw positive keywords, including any "no ..." entries
    - negative_keywords_raw: Raw negative keywords (passed through)
    - implied_negative_keywords: Keywords derived from "no ..." positive keywords
    - positive_keywords: Positive keywords with "no ..." entries removed
    - negative_keywords: Raw negative keywords plus the implied negative keywords
    - positive_descriptive: Descriptive positive text (passed through)
    - negative_descriptive: Descriptive negative text (passed through)
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
    Creates a visual prompt from a list of prompt parts. The prompt_type
    controls how the parts are compiled into the final positive / negative
    prompt strings (comma-separated keywords or descriptive prose).

    Inputs:

    - prompt_type: The type of prompt to create (KEYWORDS or DESCRIPTIVE)
    - parts: List of visual prompt parts to combine

    Outputs:

    - prompt: The created visual prompt
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
    Unpacks a visual prompt into its parts and the compiled prompt strings.
    Use this to access the final positive / negative prompts (built according
    to the prompt's prompt_type) or the keyword-only / descriptive-only
    variants regardless of the prompt type.

    Inputs:

    - prompt: The visual prompt to unpack

    Outputs:

    - prompt: The visual prompt (passed through)
    - parts: The prompt's list of prompt parts
    - prompt_type: The prompt type (KEYWORDS or DESCRIPTIVE)
    - instructions: Combined instructions from all parts
    - positive_prompt: Positive prompt compiled according to prompt_type
    - negative_prompt: Negative prompt compiled according to prompt_type
    - positive_prompt_keywords: Positive prompt compiled as comma-separated keywords
    - negative_prompt_keywords: Negative prompt compiled as comma-separated keywords
    - positive_prompt_descriptive: Positive prompt compiled as descriptive text
    - negative_prompt_descriptive: Negative prompt compiled as descriptive text
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
    Applies the configured style templates to a visual prompt: the active
    art style plus the subject style matching the given vis_type. Matching
    styles are inserted at the front of the prompt's part list, modifying
    the prompt in place.

    Inputs:

    - state: The graph state
    - prompt: The visual prompt to apply styles to
    - vis_type: The type of visual to apply styles for (optional)

    Outputs:

    - state: The graph state, passed through
    - prompt: The prompt with the styles applied
    - vis_type: The vis_type, passed through
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
        self.add_output("state")
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


@register("agents/visual/FinalizePrompt")
class FinalizePrompt(AgentNode):
    """
    Applies the visualizer's prompt finalization (post-processing actions)
    to a positive / negative prompt string pair.

    Inputs:
    - state: graph state (required — wire through any gating switch so the
      node is skipped when its output would be discarded)
    - positive_prompt: positive prompt string (required)
    - negative_prompt: negative prompt string (optional)
    - vis_type: type of visual the prompts are for (optional)
    - character_name: character the prompts involve, enables character
      level finalizers (optional)

    Outputs:
    - state: graph state (passed through)
    - positive_prompt: finalized positive prompt
    - negative_prompt: finalized negative prompt
    """

    _agent_name: ClassVar[str] = "visual"

    class Fields:
        vis_type = PropertyField(
            name="vis_type",
            type="str",
            description="The type of visual the prompts are for",
            default="UNSPECIFIED",
            choices=VIS_TYPE.choice_values(),
        )

    def __init__(self, title="Finalize Prompt", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        # state is required so an upstream gate (e.g. a prompt_only switch)
        # can deactivate this node — finalization may issue AI queries, so
        # it must not run eagerly on paths whose result is discarded
        self.add_input("state")
        self.add_input("positive_prompt", socket_type="str")
        self.add_input("negative_prompt", socket_type="str", optional=True)
        self.add_input("vis_type", socket_type="str", optional=True)
        self.add_input("character_name", socket_type="str", optional=True)
        self.set_property("vis_type", "UNSPECIFIED")
        self.add_output("state")
        self.add_output("positive_prompt", socket_type="str")
        self.add_output("negative_prompt", socket_type="str")

    async def run(self, state: GraphState):
        positive = self.normalized_input_value("positive_prompt")
        negative = self.normalized_input_value("negative_prompt")
        vis_type = self.normalized_input_value("vis_type") or "UNSPECIFIED"
        character_name = self.normalized_input_value("character_name")

        positive, negative = await self.agent.finalize_prompts(
            positive,
            negative,
            VIS_TYPE(vis_type),
            character_name or None,
        )

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "positive_prompt": positive,
                "negative_prompt": negative,
            }
        )


@register("agents/visual/ApplyStyle")
class ApplyStyle(AgentNode):
    """
    Applies a specific style template (by template id) to a visual prompt,
    inserting it at the front of the prompt's part list and modifying the
    prompt in place.

    Inputs:

    - state: The graph state
    - prompt: The visual prompt to apply the style to
    - template_id: The id of the style template to apply

    Outputs:

    - state: The graph state, passed through
    - prompt: The prompt with the style applied
    - template_id: The template id, passed through
    - prompt_part: The prompt part created from the style template (None
      if the template was not found)
    """

    _agent_name: ClassVar[str] = "visual"

    def __init__(self, title="Apply Style", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("prompt", socket_type="visual/prompt")
        self.add_input("template_id", socket_type="str")
        self.add_output("state")
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
    Determines which visual backend and generation type to use for a request.
    Selects the image-edit backend (gen_type IMAGE_EDIT) when reference assets
    are provided and image editing is available, or when image generation is
    unavailable but editing is; otherwise selects the image generation backend
    (gen_type TEXT_TO_IMAGE). Also resolves the prompt type the selected
    backend expects and the image format implied by the visual type.

    Inputs:

    - state: Graph state
    - vis_type: The type of visual to generate
    - reference_assets: List of reference asset IDs; when set, steers
      selection toward the image-edit backend

    Outputs:

    - state: Graph state (passed through)
    - backend_name: Name of the selected backend (empty if none is available)
    - gen_type: The selected generation type (TEXT_TO_IMAGE or IMAGE_EDIT)
    - vis_type: The visual type (passed through)
    - prompt_type: Prompt type the selected backend expects (falls back to
      the agent's fallback prompt type when no backend is available)
    - format: Image format derived from the visual type (e.g. PORTRAIT)
    - reference_assets: The reference assets list (passed through)
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
    Generates an image by submitting a generation request to the visual
    agent, which routes it to the appropriate backend. The request's
    callback (if any) is invoked with the response, and depending on the
    request's asset attachment context the resulting image may be saved
    to the scene's assets.

    Inputs:

    - state: The graph state
    - generation_request: The generation request to execute

    Outputs:

    - state: The state input, passed through
    - generation_request: The generation request, passed through
    - generation_response: The generation response containing the image
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
    Unpacks a visual generation request into its individual fields.

    Inputs:

    - generation_request: The generation request to unpack

    Outputs:

    - generation_request: The generation request, passed through
    - prompt: The positive prompt string
    - vis_type: The visual type
    - format: The image format
    - character_name: The character name
    - reference_assets: The list of reference asset IDs
    - gen_type: The generation type
    - extra_config: The extra configuration dict
    - asset_attachment_context: The asset attachment context
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
    Unpacks a visual generation response into its individual fields.

    Inputs:

    - generation_response: The generation response to unpack

    Outputs:

    - generation_response: The generation response, passed through
    - base64: The generated image as base64 encoded data
    - image_data: The generated image as a data URI
    - id: The generation's ID
    - backend_name: The name of the backend that generated the image
    - request: The generation request that produced this response
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
