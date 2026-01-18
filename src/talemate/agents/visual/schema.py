from typing import Any, ClassVar, TYPE_CHECKING, Callable
import pydantic
import enum
import base64
import uuid
import re
from talemate.context import active_scene
import time

if TYPE_CHECKING:
    from talemate import Scene

__all__ = [
    "GenerationRequest",
    "GenerationResponse",
    "AnalysisRequest",
    "AnalysisResponse",
    "ReadyCheckResult",
    "BackendStatus",
    "BackendStatusType",
    "VisualPrompt",
    "VisualPromptPart",
    "SamplerSettings",
    "Resolution",
    "RESOLUTION_MAP",
    "VIS_TYPE",
    "GEN_TYPE",
    "PROMPT_TYPE",
    "FORMAT_TYPE",
    "VIS_TYPE_TO_FORMAT",
    "ENUM_TYPES",
]

ENUM_TYPES = [
    "VIS_TYPE",
    "GEN_TYPE",
    "FORMAT_TYPE",
    "PROMPT_TYPE",
]


class ChoiceMixin:
    @classmethod
    def choices(cls) -> list[dict[str, str]]:
        return [{"label": v.value.title(), "value": v.value} for v in cls]

    @classmethod
    def choice_values(cls) -> list[str]:
        return [v.value for v in cls]


class VIS_TYPE(ChoiceMixin, enum.StrEnum):
    UNSPECIFIED = "UNSPECIFIED"

    CHARACTER_CARD = "CHARACTER_CARD"
    CHARACTER_PORTRAIT = "CHARACTER_PORTRAIT"
    # CHARACTER_SPRITE = "CHARACTER_SPRITE"

    SCENE_CARD = "SCENE_CARD"
    SCENE_BACKGROUND = "SCENE_BACKGROUND"
    SCENE_ILLUSTRATION = "SCENE_ILLUSTRATION"

    # ITEM_CARD = "ITEM_CARD"


class GEN_TYPE(ChoiceMixin, enum.StrEnum):
    TEXT_TO_IMAGE = "TEXT_TO_IMAGE"
    IMAGE_EDIT = "IMAGE_EDIT"
    UPLOAD = "UPLOAD"


class PROMPT_TYPE(ChoiceMixin, enum.StrEnum):
    KEYWORDS = "KEYWORDS"
    DESCRIPTIVE = "DESCRIPTIVE"


class FORMAT_TYPE(ChoiceMixin, enum.StrEnum):
    LANDSCAPE = "LANDSCAPE"
    PORTRAIT = "PORTRAIT"
    SQUARE = "SQUARE"


class BackendStatusType(enum.Enum):
    OK = "ok"
    ERROR = "error"
    WARNING = "warning"
    DISCONNECTED = "disconnected"


VIS_TYPE_TO_FORMAT: dict[VIS_TYPE, FORMAT_TYPE] = {
    VIS_TYPE.CHARACTER_CARD: FORMAT_TYPE.PORTRAIT,
    VIS_TYPE.CHARACTER_PORTRAIT: FORMAT_TYPE.SQUARE,
    VIS_TYPE.SCENE_CARD: FORMAT_TYPE.PORTRAIT,
    VIS_TYPE.SCENE_BACKGROUND: FORMAT_TYPE.LANDSCAPE,
    VIS_TYPE.SCENE_ILLUSTRATION: FORMAT_TYPE.LANDSCAPE,
    VIS_TYPE.UNSPECIFIED: FORMAT_TYPE.PORTRAIT,
}


class VisualPromptPart(pydantic.BaseModel):
    negative_keywords_raw: list[str] = pydantic.Field(default_factory=list)
    positive_keywords_raw: list[str] = pydantic.Field(default_factory=list)
    positive_descriptive: str | None = None
    negative_descriptive: str | None = None
    instructions: str | None = None

    @pydantic.computed_field
    @property
    def implied_negative_keywords(self) -> list[str]:
        return [kw[3:] for kw in self.positive_keywords_raw if kw.startswith("no ")]

    @pydantic.computed_field
    @property
    def negative_keywords(self) -> list[str]:
        return self.negative_keywords_raw + self.implied_negative_keywords

    @pydantic.computed_field
    @property
    def positive_keywords(self) -> list[str]:
        return [kw for kw in self.positive_keywords_raw if not kw.startswith("no ")]


class VisualPrompt(pydantic.BaseModel):
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.KEYWORDS
    parts: list[VisualPromptPart] = pydantic.Field(default_factory=list)

    @pydantic.computed_field
    @property
    def instructions(self) -> str:
        return "\n\n".join(
            [part.instructions for part in self.parts if part.instructions]
        )

    @pydantic.computed_field
    @property
    def positive_prompt(self) -> str:
        return self._build_prompt(self.prompt_type, True)

    @pydantic.computed_field
    @property
    def negative_prompt(self) -> str:
        return self._build_prompt(self.prompt_type, False)

    @property
    def positive_prompt_keywords(self) -> str:
        return self._build_prompt(PROMPT_TYPE.KEYWORDS, True)

    @property
    def negative_prompt_keywords(self) -> str:
        return self._build_prompt(PROMPT_TYPE.KEYWORDS, False)

    @property
    def positive_prompt_descriptive(self) -> str:
        return self._build_prompt(PROMPT_TYPE.DESCRIPTIVE, True)

    @property
    def negative_prompt_descriptive(self) -> str:
        return self._build_prompt(PROMPT_TYPE.DESCRIPTIVE, False)

    def _build_prompt(self, prompt_type: PROMPT_TYPE, positive: bool) -> str:
        prompt: list[str] = []
        if prompt_type == PROMPT_TYPE.KEYWORDS:
            for part in self.parts:
                prompt.extend(
                    part.positive_keywords if positive else part.negative_keywords
                )
            return ", ".join(dict.fromkeys(prompt))
        elif prompt_type == PROMPT_TYPE.DESCRIPTIVE:
            for part in self.parts:
                if part.positive_descriptive if positive else part.negative_descriptive:
                    prompt.append(
                        part.positive_descriptive
                        if positive
                        else part.negative_descriptive
                    )
            return "\n\n".join(prompt)
        return ""


class BackendStatus(pydantic.BaseModel):
    type: BackendStatusType
    message: str | None = None
    timestamp: float = pydantic.Field(default_factory=time.time)

    def __eq__(self, other: "BackendStatus | None") -> bool:
        if not isinstance(other, BackendStatus):
            return False
        return self.type == other.type and self.message == other.message

    def __ne__(self, other: "BackendStatus") -> bool:
        return not self == other


class BackendBase(pydantic.BaseModel):
    # internal name
    name: ClassVar[str]
    # display label
    label: ClassVar[str]
    # whether the backend can create images
    image_create: ClassVar[bool]
    # whether the backend can do contextual image editing (with references, Qwen-image-edit, nano banana etc.)
    image_edit: ClassVar[bool]
    # whether the backend can analyze images
    image_analyzation: ClassVar[bool]
    # description of the backend
    description: ClassVar[str]

    status: BackendStatus = pydantic.Field(
        default=BackendStatus(type=BackendStatusType.DISCONNECTED)
    )

    gen_type: GEN_TYPE = GEN_TYPE.TEXT_TO_IMAGE
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.KEYWORDS


class Resolution(pydantic.BaseModel):
    width: int
    height: int


RESOLUTION_MAP = {}


RESOLUTION_MAP["sdxl"] = {
    "portrait": Resolution(width=832, height=1216),
    "landscape": Resolution(width=1216, height=832),
    "square": Resolution(width=1024, height=1024),
}

RESOLUTION_MAP["sd15"] = {
    "portrait": Resolution(width=512, height=768),
    "landscape": Resolution(width=768, height=512),
    "square": Resolution(width=768, height=768),
}


class SamplerSettings(pydantic.BaseModel):
    steps: int = 40


class AssetAttachmentContext(pydantic.BaseModel):
    # message attachment
    message_ids: list[int] = pydantic.Field(default_factory=list)
    allow_auto_attach: bool = False
    allow_override: bool = False
    delete_old: bool = False

    # cover image (scene and character)
    scene_cover: bool = False
    override_scene_cover: bool = False
    character_cover: bool = False
    override_character_cover: bool = False

    # character avatar / portrait
    default_avatar: bool = False
    override_default_avatar: bool = False
    current_avatar: bool = False
    override_current_avatar: bool = False

    # asset meta
    asset_name: str | None = None
    tags: list[str] = pydantic.Field(default_factory=list)

    @pydantic.computed_field(description="Whether to save the asset")
    @property
    def save_asset(self) -> bool:
        if self.scene_cover or self.character_cover:
            return True

        if self.allow_auto_attach or self.allow_override:
            return True

        if self.default_avatar or self.current_avatar:
            return True

        return False


class GenerationRequest(pydantic.BaseModel):
    prompt: str | None = None
    negative_prompt: str | None = None
    gen_type: GEN_TYPE = GEN_TYPE.TEXT_TO_IMAGE
    vis_type: VIS_TYPE = VIS_TYPE.UNSPECIFIED
    format: FORMAT_TYPE = FORMAT_TYPE.LANDSCAPE
    character_name: str | None = None
    instructions: str | None = None
    resolution: Resolution = pydantic.Field(default=RESOLUTION_MAP["sdxl"]["portrait"])
    sampler_settings: SamplerSettings = pydantic.Field(default=SamplerSettings())
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))

    agent_config: dict[str, Any] = pydantic.Field(default={})

    extra_config: dict[str, int | float | str | bool] = pydantic.Field(
        default_factory=dict
    )

    reference_assets: list[str] = pydantic.Field(default_factory=list)

    inline_reference: str | None = pydantic.Field(default=None, exclude=False)

    callback: Callable | None = pydantic.Field(default=None, exclude=True)

    asset_attachment_context: AssetAttachmentContext = pydantic.Field(
        default=AssetAttachmentContext()
    )

    @property
    def reference_bytes(self) -> list[bytes]:
        scene: "Scene" = active_scene.get()
        if not scene:
            return []
        asset_bytes: list[bytes] = scene.assets.get_asset_bytes_many(
            self.reference_assets
        )
        if self.inline_reference:
            asset_bytes.insert(
                0, scene.assets.bytes_from_image_data(self.inline_reference)
            )
        return asset_bytes

    @pydantic.model_validator(mode="after")
    def extract_tags_from_prompt(self) -> "GenerationRequest":
        """
        Extract tags from the prompt by finding {word} patterns.
        Removes the fencing from the prompt and adds extracted words as tags.
        """
        if self.prompt:
            tag_pattern = re.compile(r"\{([^}]+)\}")
            extracted_tags = tag_pattern.findall(self.prompt)

            if extracted_tags:
                # Remove the fencing from the prompt but keep the words
                self.prompt = tag_pattern.sub(r"\1", self.prompt)

                # Add extracted tags to asset_attachment_context.tags
                existing_tags = set(self.asset_attachment_context.tags)
                existing_tags.update(extracted_tags)
                self.asset_attachment_context.tags = list(existing_tags)

        return self


class GenerationResponse(pydantic.BaseModel):
    generated: bytes | None = pydantic.Field(default=None, exclude=True)
    request: GenerationRequest | None = None
    id: str | None = None
    backend_name: str | None = None
    saved: bool = False

    @pydantic.computed_field
    @property
    def base64(self) -> str | None:
        if not self.generated:
            return None
        return base64.b64encode(self.generated).decode("utf-8")

    @property
    def image_data(self) -> str | None:
        if not self.generated:
            return None
        return f"data:image/png;base64,{self.base64}"


class AnalysisRequest(pydantic.BaseModel):
    prompt: str
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    asset_id: str
    save: bool = False

    @property
    def reference_bytes(self) -> list[bytes]:
        scene: "Scene" = active_scene.get()
        if not scene:
            return []
        asset_bytes = scene.assets.get_asset_bytes(self.asset_id)
        return [asset_bytes] if asset_bytes else []


class AnalysisResponse(pydantic.BaseModel):
    analysis: str | None = None
    request: AnalysisRequest | None = None
    id: str | None = None
    backend_name: str | None = None


class ReadyCheckResult(pydantic.BaseModel):
    backend: BackendStatus | None = None
    backend_image_edit: BackendStatus | None = None
    backend_image_analyzation: BackendStatus | None = None
    error: str | None = None

    def __eq__(self, other: "ReadyCheckResult") -> bool:
        return (
            self.backend == other.backend
            and self.backend_image_edit == other.backend_image_edit
            and self.backend_image_analyzation == other.backend_image_analyzation
        )

    def __ne__(self, other: "ReadyCheckResult") -> bool:
        return not self == other
