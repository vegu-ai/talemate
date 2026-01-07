import structlog
from typing import ClassVar, TYPE_CHECKING
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
)
from talemate.context import active_scene

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

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
        save_asset = PropertyField(
            name="save_asset",
            type="bool",
            description="Whether to save the asset to the scene",
            default=False,
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
        self.add_input("save_asset", socket_type="bool", optional=True)
        self.add_input("extra_config", socket_type="dict", optional=True)
        self.add_input("asset_attachment_context", socket_type="asset_attachment_context", optional=True)
        self.set_property("vis_type", "UNSPECIFIED")
        self.set_property("gen_type", "TEXT_TO_IMAGE")
        self.set_property("format", "LANDSCAPE")
        self.set_property("character_name", "")
        self.set_property("instructions", "")
        self.set_property("extra_config", {})
        self.set_property("save_asset", False)
        self.add_output("generation_request", socket_type="visual/generation_request")
        self.add_output("prompt", socket_type="visual/prompt")
        self.add_output("vis_type", socket_type="str")
        self.add_output("format", socket_type="str")
        self.add_output("character_name", socket_type="str")
        self.add_output("reference_assets", socket_type="list")
        self.add_output("gen_type", socket_type="str")
        self.add_output("save_asset", socket_type="bool")
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
        save_asset = self.normalized_input_value("save_asset") or False
        asset_attachment_context = self.normalized_input_value("asset_attachment_context")
        if callback and not isinstance(callback, FunctionWrapper):
            raise InputValueError(
                self, "callback", "callback must be a FunctionWrapper instance"
            )

        callback_wrapper = None
        if callback:

            async def callback_wrapper(response: GenerationResponse):
                await callback(response=response)
                if save_asset:
                    scene: "Scene" = active_scene.get()
                    scene.assets.add_asset_from_generation_response(response)

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
            asset_attachment_context=asset_attachment_context or AssetAttachmentContext(),
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
