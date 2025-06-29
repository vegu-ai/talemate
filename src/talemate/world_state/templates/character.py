from typing import TYPE_CHECKING

import pydantic

from talemate.instance import get_agent
from talemate.world_state.templates.base import Template, log, register
from talemate.world_state.templates.content import (
    GenerationOptions,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["Attribute", "Detail", "GeneratedAttribute", "GeneratedDetail"]


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
        generation_options: GenerationOptions | None = None,
        **kwargs,
    ) -> GeneratedAttribute:
        creator = get_agent("creator")

        character = scene.get_character(character_name)

        if not character:
            log.error(
                "apply_template_character_attribute: character not found",
                character_name=character_name,
            )
            return

        if not generation_options:
            generation_options = GenerationOptions()

        formatted_attribute = self.formatted("attribute", scene, character.name)
        formatted_instructions = self.formatted("instructions", scene, character.name)

        response = await creator.contextual_generate_from_args(
            context=f"character attribute:{formatted_attribute}",
            instructions=formatted_instructions,
            length=192,
            character=character.name,
            uid="wsm.character_attribute",
            template=self,
            information=kwargs.get("information", ""),
            **generation_options.model_dump(),
        )

        if apply:
            await character.set_base_attribute(formatted_attribute, response)

        return GeneratedAttribute(
            attribute=formatted_attribute,
            value=response,
            character=character.name,
            template=self,
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
        generation_options: GenerationOptions | None = None,
        **kwargs,
    ) -> GeneratedDetail:
        creator = get_agent("creator")

        character = scene.get_character(character_name)

        if not character:
            log.error(
                "apply_template_character_detail: character not found",
                character_name=character_name,
            )
            return

        if not generation_options:
            generation_options = GenerationOptions()

        formatted_detail = self.formatted("detail", scene, character.name)
        formatted_instructions = self.formatted("instructions", scene, character.name)

        response = await creator.contextual_generate_from_args(
            context=f"character detail:{formatted_detail}",
            instructions=formatted_instructions,
            length=256,
            character=character.name,
            uid="wsm.character_detail",
            template=self,
            information=kwargs.get("information", ""),
            **generation_options.model_dump(),
        )

        if apply:
            await character.set_detail(formatted_detail, response)

        return GeneratedDetail(
            detail=formatted_detail,
            value=response,
            character=character.name,
            template=self,
        )
