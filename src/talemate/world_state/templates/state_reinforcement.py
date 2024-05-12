from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union
from talemate.world_state import InsertionMode
from talemate.world_state.templates.base import Template, register
import pydantic

__all__ = [
    "StateReinforcement",
]

@register("state_reinforcement")
class StateReinforcement(Template):
    name: str
    query: str
    state_type: str = "npc"
    insert: InsertionMode = InsertionMode.sequential
    instructions: Union[str, None] = None
    description: Union[str, None] = None
    interval: int = 10
    auto_create: bool = False
    template_type: str = "state_reinforcement"
    
    @pydantic.field_serializer('insert')
    def serialize_insert(self, value: InsertionMode, _info) -> str:
        return value.value