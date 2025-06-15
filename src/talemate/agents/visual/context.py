import contextvars
import enum
from typing import Union

import pydantic

__all__ = [
    "VIS_TYPES",
    "visual_context",
    "VisualContext",
]


class VIS_TYPES(str, enum.Enum):
    UNSPECIFIED = "UNSPECIFIED"
    ENVIRONMENT = "ENVIRONMENT"
    CHARACTER = "CHARACTER"
    ITEM = "ITEM"


visual_context = contextvars.ContextVar("visual_context", default=None)


class VisualContextState(pydantic.BaseModel):
    character_name: Union[str, None] = None
    instructions: Union[str, None] = None
    vis_type: VIS_TYPES = VIS_TYPES.ENVIRONMENT
    prompt: Union[str, None] = None
    prepared_prompt: Union[str, None] = None
    format: Union[str, None] = None
    replace: bool = False
    prompt_only: bool = False
    
    @property
    def title(self) -> str:
        if self.vis_type == VIS_TYPES.ENVIRONMENT:
            return "Environment"
        elif self.vis_type == VIS_TYPES.CHARACTER:
            return f"Character: {self.character_name}"
        return "Visual Context"


class VisualContext:
    def __init__(
        self,
        character_name: Union[str, None] = None,
        instructions: Union[str, None] = None,
        vis_type: VIS_TYPES = VIS_TYPES.ENVIRONMENT,
        prompt: Union[str, None] = None,
        **kwargs,
    ):
        self.state = VisualContextState(
            character_name=character_name,
            instructions=instructions,
            vis_type=vis_type,
            prompt=prompt,
            **kwargs,
        )

    def __enter__(self):
        self.token = visual_context.set(self.state)

    def __exit__(self, *args, **kwargs):
        visual_context.reset(self.token)
        return False
