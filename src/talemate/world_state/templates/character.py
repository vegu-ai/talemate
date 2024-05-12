from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union
from talemate.world_state.templates.base import Template, register

__all__ = [
    "Attribute",
    "Detail",
]

@register("character_attribute")
class Attribute(Template):
    name: str
    attribute: str
    instructions: str
    template_type: str = "character_attribute"
    
@register("character_detail")
class Detail(Template):
    name: str
    detail: str
    instructions: str
    template_type: str = "character_detail"
    