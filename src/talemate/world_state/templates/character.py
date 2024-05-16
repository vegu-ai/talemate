from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union
import pydantic
from talemate.world_state.templates.base import Template, register, log
from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "Attribute",
    "Detail",
    "GeneratedAttribute",
    "GeneratedDetail"
]


class GeneratedAttribute(pydantic.BaseModel):
    attribute: str
    value: str
    character: str
    template: "Attribute"
    
@register("character_attribute")
class Attribute(Template):
    name: str
    attribute: str
    instructions: str | None = None
    description: str | None = None
    supports_spice: bool = False
    supports_style: bool = False
    template_type: str = "character_attribute"

    async def generate(
        self, 
        scene: "Scene",
        character_name: str,
        apply: bool = True,
    ) -> GeneratedAttribute:
    
        creator = get_agent("creator")
        
        character = scene.get_character(character_name)
        
        if not character:
            log.error("apply_template_character_attribute: character not found", character_name=character_name)
            return
        
        response = await creator.contextual_generate_from_args(
            context = f"character attribute:{self.attribute}",
            instructions = self.formatted("instructions", scene, character.name),
            length = 100,
            character = character.name,
            uid = "wsm.character_attribute"
        )
        
        if apply:
            await character.set_base_attribute(self.attribute, response)
        
        return GeneratedAttribute(
            attribute = self.formatted("attribute", scene, character.name),
            value = response,
            character = character.name,
            template = self
        )
    
class GeneratedDetail(pydantic.BaseModel):
    detail: str
    value: str
    character: str
    template: "Detail"
    
@register("character_detail")
class Detail(Template):
    name: str
    detail: str
    instructions: str | None = None
    description: str | None = None
    supports_spice: bool = False
    supports_style: bool = False
    template_type: str = "character_detail"
    
    async def generate(
        self, 
        scene: "Scene",
        character_name: str,
        apply: bool = True,
    ) -> GeneratedDetail:
    
        creator = get_agent("creator")
        
        character = scene.get_character(character_name)
        
        if not character:
            log.error("apply_template_character_detail: character not found", character_name=character_name)
            return
        
        response = await creator.contextual_generate_from_args(
            context = f"character detail:{self.detail}",
            instructions = self.formatted("instructions", scene, character.name),
            length = 100,
            character = character.name,
            uid = "wsm.character_detail"
        )
        
        if apply:
            await character.set_detail(self.detail, response)
        
        return GeneratedDetail(
            detail = self.formatted("detail", scene, character.name),
            value = response,
            character = character.name,
            template = self
        )
        