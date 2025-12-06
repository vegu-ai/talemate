from typing import TYPE_CHECKING

import pydantic
from talemate.world_state.templates.base import Template, register

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["VisualStyle"]


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

    # Visual type (maps to VIS_TYPE, stored as string to avoid coupling)
    visual_type: str = "STYLE"

    template_type: str = "visual_style"

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
