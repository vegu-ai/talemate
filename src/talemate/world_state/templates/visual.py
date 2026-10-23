from typing import TYPE_CHECKING, Literal, get_args

import pydantic
import structlog

from talemate.agents.visual.schema import PromptFinalizer
from talemate.world_state.templates.base import (
    Template,
    register,
    repairs_unknown_choices,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["VisualStyle", "VisualFinalizer", "VisualType", "VISUAL_TYPES"]

log = structlog.get_logger("world-state.templates.visual")

# the values the visualizer's style settings filter on (`agents/visual/style.py`).
# STYLE is the general art style and is not a VIS_TYPE member - a style template
# is picked for a slot, it does not name one
VisualType = Literal[
    "STYLE",
    "CHARACTER_CARD",
    "CHARACTER_PORTRAIT",
    "SCENE_CARD",
    "SCENE_BACKGROUND",
    "SCENE_ILLUSTRATION",
    "OBJECT_ILLUSTRATION",
]

VISUAL_TYPES = get_args(VisualType)

DEFAULT_VISUAL_TYPE = "STYLE"


@register("visual_style")
class VisualStyle(Template):
    """
    Visual prompt style configuration.

    Use this template to define both keyword-style and descriptive-style
    prompt building for image generation backends.
    """

    description: str | None = None

    # Keyword-based prompting
    positive_keywords: list[str] = pydantic.Field(default_factory=list)
    negative_keywords: list[str] = pydantic.Field(default_factory=list)

    # Descriptive prompting
    positive_descriptive: str | None = None
    negative_descriptive: str | None = None

    visual_type: VisualType = DEFAULT_VISUAL_TYPE

    template_type: str = "visual_style"

    @pydantic.field_validator("visual_type", mode="before")
    @classmethod
    def _coerce_visual_type(cls, v, info: pydantic.ValidationInfo) -> str:
        if isinstance(v, str):
            v = v.strip()

        if v in VISUAL_TYPES:
            return v

        # only a template read off disk falls back: `Group.sanitize_data` drops
        # one that fails to validate, so raising there would take the rest of
        # the template with it. Everywhere else an unknown visual type is an
        # error.
        if not repairs_unknown_choices(info):
            raise ValueError(
                f"Unknown visual type: {v}. Valid visual types: "
                f"{', '.join(VISUAL_TYPES)}"
            )

        log.warning(
            "unknown visual type, falling back",
            visual_type=v,
            template=info.data.get("name"),
            fallback=DEFAULT_VISUAL_TYPE,
        )
        return DEFAULT_VISUAL_TYPE

    def render(
        self, scene: "Scene", character_name: str | None = None
    ) -> dict[str, str | list[str] | bool | None]:
        """
        Render all string fields with scene-aware formatting.
        """
        return {
            "positive_keywords": list(self.positive_keywords),
            "negative_keywords": list(self.negative_keywords),
            "positive_descriptive": self.formatted(
                "positive_descriptive", scene, character_name
            ),
            "negative_descriptive": self.formatted(
                "negative_descriptive", scene, character_name
            ),
            "visual_type": self.visual_type,
        }


@register("visual_finalizer")
class VisualFinalizer(Template):
    """
    A reusable set of visual prompt post-processing actions, applied to
    image generation prompts by the visualizer agent's prompt
    finalization step.
    """

    description: str | None = None

    finalizers: list[PromptFinalizer] = pydantic.Field(default_factory=list)

    template_type: str = "visual_finalizer"
