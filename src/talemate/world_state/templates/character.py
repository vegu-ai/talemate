from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union
import pydantic
from talemate.world_state.templates.base import Template, register

__all__ = [
    "Attribute",
    "Detail",
    "GeneratedAttribute",
    "GeneratedDetail"
]

@register("character_attribute")
class Attribute(Template):
    name: str
    attribute: str
    instructions: str | None = None
    description: str | None = None
    template_type: str = "character_attribute"
    
class GeneratedAttribute(pydantic.BaseModel):
    attribute: str
    character: str
    template: Attribute
    
@register("character_detail")
class Detail(Template):
    name: str
    detail: str
    instructions: str | None = None
    description: str | None = None
    template_type: str = "character_detail"
    
class GeneratedDetail(pydantic.BaseModel):
    detail: str
    character: str
    template: Detail