import re

import pydantic

from talemate.world_state.templates.base import Template, register

__all__ = ["SceneToolShortcutTemplate"]

ICON_VALID_RE = re.compile(r"^mdi-[a-z0-9]+(-[a-z0-9]+)*$")


@register("scene_tool_shortcut")
class SceneToolShortcutTemplate(Template):
    """
    Template for scene tool shortcuts.

    Applying it adds a shortcut to the application config, no AI generation
    involved. `instructions` holds the canned instruction text the shortcut
    passes to its action.
    """

    action_id: str
    label: str
    icon: str
    template_type: str = "scene_tool_shortcut"

    @pydantic.field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Label must not be empty")
        return v

    @pydantic.field_validator("icon")
    @classmethod
    def _validate_icon(cls, v: str) -> str:
        # a yaml block scalar (`icon: |`) appends a newline - strip it so a
        # hand authored template still loads, and match the whole string so
        # what is stored is always a value the frontend accepts too (`$`
        # would let a trailing newline through, the JS regex does not)
        v = v.strip()
        if not ICON_VALID_RE.fullmatch(v):
            raise ValueError(
                f"Icon must be an mdi icon name (e.g. mdi-script-text), got: {v}"
            )
        return v
