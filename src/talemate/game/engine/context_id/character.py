"""
Character-specific Context ID classes
"""

from __future__ import annotations

from typing import ClassVar, TYPE_CHECKING, Literal, Generator
import structlog

from .base import (
    ContextID,
    ContextIDItem,
    ContextIDHandler,
    ContextIDHandlerError,
    ContextIDItemReadOnly,
    ContextIDMeta,
    ContextIDMetaGroup,
    compress_name,
    register_context_id_type,
    register_context_id_handler,
    register_context_id_meta,
    _parts,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.character import Character

log = structlog.get_logger("talemate.game.engine.context_id.character")

__all__ = [
    "CharacterContextID",
    "CharacterDescriptionContextID",
    "CharacterAttributeContextID",
    "CharacterDetailContextID",
    "CharacterActingInstructionsContextID",
    "CharacterVisualRulesContextID",
    "CharacterExampleDialogueContextID",
    "CharacterContextItem",
    "CharacterContext",
]


register_context_id_meta(
    ContextIDMetaGroup(
        description="Character information",
        context_id="character",
        items=[
            ContextIDMeta(
                context_id="character.description:<character_name>",
                description="The description of a character. Replace <character_name> with the name of the character.",
                creative=True,
            ),
            ContextIDMeta(
                context_id="character.acting_instructions:<character_name>",
                description="Generalized acting instructions for a character, giving a guideline on their speech and mannerisms. Replace <character_name> with the name of the character.",
                creative=True,
            ),
            ContextIDMeta(
                context_id="character.visual_rules:<character_name>",
                description="Static visual rules for a character that never change. Used for rendering images of the character. Replace <character_name> with the name of the character.",
                creative=True,
            ),
            ContextIDMeta(
                context_id="character.example_dialogue:<character_name>",
                description="List of example dialogue lines for a character. Use .<idx> to access a specific example or .new to add a new example.",
                creative=True,
            ),
            ContextIDMeta(
                context_id="character.attribute:<character_name>.<attribute_hash>",
                description="The attribute of a character. Replace <character_name> with the name of the character. You cannot know the attribute hash, so query for the attribute name.",
                creative=True,
            ),
            ContextIDMeta(
                context_id="character.detail:<character_name>.<detail_hash>",
                description="The detail of a character. Replace <character_name> with the name of the character. You cannot know the detail hash, so query for the detail name.",
                creative=True,
            ),
        ],
    )
)

## Character Context IDs


class CharacterContextID(ContextID):
    character: str
    context_type: ClassVar[str] = "character"

    @classmethod
    def from_str(cls, context_id_str: str, scene: "Scene") -> "CharacterContextID":
        context_type, path = _parts(context_id_str)
        character_name: str = path[0]

        return cls.make(character=character_name, context_type=context_type)


@register_context_id_type
class CharacterDescriptionContextID(CharacterContextID):
    context_type: ClassVar[str] = f"{CharacterContextID.context_type}.description"

    @classmethod
    def make(
        cls, object: "Character | str", **kwargs
    ) -> "CharacterDescriptionContextID":
        character = object.name if hasattr(object, "name") else object
        return cls(
            character=character,
            path=[character, "description"],
        )

    @property
    def context_type_label(self) -> str:
        return "Description"


@register_context_id_type
class CharacterActingInstructionsContextID(CharacterContextID):
    context_type: ClassVar[str] = (
        f"{CharacterContextID.context_type}.acting_instructions"
    )

    @classmethod
    def make(
        cls, object: "Character | str", **kwargs
    ) -> "CharacterActingInstructionsContextID":
        character = object.name if hasattr(object, "name") else object
        return cls(
            character=character,
            path=[character, "acting_instructions"],
        )

    @property
    def context_type_label(self) -> str:
        return "Acting Instructions"


@register_context_id_type
class CharacterVisualRulesContextID(CharacterContextID):
    context_type: ClassVar[str] = f"{CharacterContextID.context_type}.visual_rules"

    @classmethod
    def make(
        cls, object: "Character | str", **kwargs
    ) -> "CharacterVisualRulesContextID":
        character = object.name if hasattr(object, "name") else object
        return cls(
            character=character,
            path=[character, "visual_rules"],
        )

    @property
    def context_type_label(self) -> str:
        return "Visual Rules"


@register_context_id_type
class CharacterExampleDialogueContextID(CharacterContextID):
    index: int | None = None
    action: Literal["new"] | None = None
    context_type: ClassVar[str] = f"{CharacterContextID.context_type}.example_dialogue"

    @classmethod
    def make(
        cls,
        object: "Character | str",
        index: int | None = None,
        action: Literal["new"] | None = None,
        **kwargs,
    ) -> "CharacterExampleDialogueContextID":
        character = object.name if hasattr(object, "name") else object
        path: list[str] = [character]
        if index is not None:
            path = [character, str(index)]
        elif action is not None:
            path = [character, str(action)]
        return cls(
            character=character,
            index=index,
            action=action,
            path=path,
        )

    @property
    def context_type_label(self) -> str:
        if self.action is None:
            return "Example Dialogue"
        elif self.action == "new":
            return "New Example Dialogue"
        else:
            return f"Example Dialogue [{self.index}]"


@register_context_id_type
class CharacterAttributeContextID(CharacterContextID):
    attribute: str
    context_type: ClassVar[str] = f"{CharacterContextID.context_type}.attribute"

    @classmethod
    def make(
        cls, object: "Character | str", attribute: str, **kwargs
    ) -> "CharacterAttributeContextID":
        character = object.name if hasattr(object, "name") else object
        compressed_attribute = compress_name(attribute)
        return cls(
            character=character,
            attribute=attribute,
            path=[character, compressed_attribute],
        )

    @property
    def context_type_label(self) -> str:
        return "Attribute"


@register_context_id_type
class CharacterDetailContextID(CharacterContextID):
    detail: str
    context_type: ClassVar[str] = f"{CharacterContextID.context_type}.detail"

    @classmethod
    def make(
        cls, object: "Character | str", detail: str, **kwargs
    ) -> "CharacterDetailContextID":
        character = object.name if hasattr(object, "name") else object
        compressed_detail = compress_name(detail)
        return cls(
            character=character,
            detail=detail,
            path=[character, compressed_detail],
        )

    @property
    def context_type_label(self) -> str:
        return "Detail"


## Character Context Handler and Items


class CharacterContextItem(ContextIDItem):
    context_type: Literal[
        "description",
        "acting_instructions",
        "visual_rules",
        "example_dialogue",
        "attribute",
        "detail",
    ]
    character: "Character"
    name: str
    value: str | int | float | bool | list | dict | None

    @property
    def context_id(
        self,
    ) -> (
        CharacterDescriptionContextID
        | CharacterActingInstructionsContextID
        | CharacterVisualRulesContextID
        | CharacterExampleDialogueContextID
        | CharacterAttributeContextID
        | CharacterDetailContextID
    ):
        if self.context_type == "description":
            return CharacterDescriptionContextID.make(self.character)
        elif self.context_type == "acting_instructions":
            return CharacterActingInstructionsContextID.make(self.character)
        elif self.context_type == "visual_rules":
            return CharacterVisualRulesContextID.make(self.character)
        elif self.context_type == "example_dialogue":
            # name can be 'list' (all), a numeric index, or 'new'
            if self.name == "list":
                return CharacterExampleDialogueContextID.make(self.character)
            if self.name == "new":
                return CharacterExampleDialogueContextID.make(
                    self.character, action="new"
                )
            if self.name.isdigit():
                return CharacterExampleDialogueContextID.make(
                    self.character, index=int(self.name)
                )
            # fallback to all
            return CharacterExampleDialogueContextID.make(self.character)
        elif self.context_type == "attribute":
            return CharacterAttributeContextID.make(self.character, self.name)
        elif self.context_type == "detail":
            return CharacterDetailContextID.make(self.character, self.name)

    @property
    def human_id(self) -> str:
        return f"Information about {self.character.name} - '{self.name}'"

    @property
    def memory_id(self) -> str | None:
        if self.context_type == "attribute":
            return f"{self.character.name}.{self.name}"
        elif self.context_type == "detail":
            return f"{self.character.name}.detail.{self.name}"
        return None

    async def get(self, scene: "Scene") -> str | int | float | bool | list[str] | None:
        if self.context_type == "description":
            return self.character.description
        elif self.context_type == "acting_instructions":
            return self.character.acting_instructions
        elif self.context_type == "visual_rules":
            return self.character.visual_rules
        elif self.context_type == "example_dialogue":
            if self.name == "list":
                return self.character.example_dialogue
            if self.name == "new":
                return None
            if self.name.isdigit():
                idx = int(self.name)
                if 0 <= idx < len(self.character.example_dialogue):
                    return self.character.example_dialogue[idx]
                return None
        elif self.context_type == "attribute":
            return self.character.base_attributes.get(self.name)
        elif self.context_type == "detail":
            return self.character.details.get(self.name)

    async def set(self, scene: "Scene", value: str | int | float | bool | None):
        if self.context_type == "description":
            await self.character.set_description(value)
        elif self.context_type == "acting_instructions":
            await self.character.set_acting_instructions(
                value if isinstance(value, str) else None
            )
        elif self.context_type == "visual_rules":
            self.character.visual_rules = value if isinstance(value, str) else None
            self.character.memory_dirty = True
        elif self.context_type == "example_dialogue":
            # Manage individual examples only; full list is read-only
            if self.name == "list":
                raise ContextIDItemReadOnly(self.context_id.path_to_str)
            elif self.name == "new":
                if isinstance(value, str) and value.strip():
                    await self.character.add_example_dialogue(value.strip())
            elif self.name.isdigit():
                idx = int(self.name)
                if not isinstance(value, str) or not value.strip():
                    await self.character.remove_example_dialogue(idx)
                else:
                    await self.character.set_example_dialogue_item(idx, value.strip())
        elif self.context_type == "attribute":
            await self.character.set_base_attribute(self.name, value)
        elif self.context_type == "detail":
            await self.character.set_detail(self.name, value)


@register_context_id_handler
class CharacterContext(ContextIDHandler):
    context_types: ClassVar[list[str]] = [
        "character.description",
        "character.acting_instructions",
        "character.visual_rules",
        "character.example_dialogue",
        "character.attribute",
        "character.detail",
    ]
    character: "Character"

    @classmethod
    def instance_from_path(cls, path: list[str], scene: "Scene") -> "CharacterContext":
        character: "Character | None" = scene.get_character(path[0])
        if not character:
            raise ContextIDHandlerError(f"Character '{path[0]}' not found in scene")
        return cls(character=character)

    @property
    def attributes(self) -> Generator[CharacterContextItem, None, None]:
        for name, value in self.character.base_attributes.items():
            yield CharacterContextItem(
                context_type="attribute",
                character=self.character,
                name=name,
                value=value,
            )

    @property
    def details(self) -> Generator[CharacterContextItem, None, None]:
        for name, value in self.character.details.items():
            yield CharacterContextItem(
                context_type="detail", character=self.character, name=name, value=value
            )

    @property
    def description(self) -> CharacterContextItem:
        return CharacterContextItem(
            context_type="description",
            character=self.character,
            name="description",
            value=self.character.description,
        )

    @property
    def acting_instructions(self) -> CharacterContextItem:
        return CharacterContextItem(
            context_type="acting_instructions",
            character=self.character,
            name="acting_instructions",
            value=self.character.acting_instructions,
        )

    @property
    def visual_rules(self) -> CharacterContextItem:
        return CharacterContextItem(
            context_type="visual_rules",
            character=self.character,
            name="visual_rules",
            value=self.character.visual_rules,
        )

    @property
    def example_dialogue(self) -> CharacterContextItem:
        # Represents the entire list
        return CharacterContextItem(
            context_type="example_dialogue",
            character=self.character,
            name="list",
            value=self.character.example_dialogue,
        )

    @property
    def example_dialogue_items(self) -> Generator[CharacterContextItem, None, None]:
        for idx, example in enumerate(self.character.example_dialogue):
            yield CharacterContextItem(
                context_type="example_dialogue",
                character=self.character,
                name=str(idx),
                value=example,
            )

    def get_attribute(self, name: str) -> CharacterContextItem | None:
        for attribute in self.attributes:
            if attribute.name == name:
                return attribute
        return None

    def get_detail(self, name: str) -> CharacterContextItem | None:
        for detail in self.details:
            if detail.name == name:
                return detail
        return None

    async def context_id_item_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> CharacterContextItem | None:
        if context_type == "character.description":
            return self.description
        if context_type == "character.acting_instructions":
            return self.acting_instructions
        if context_type == "character.visual_rules":
            return self.visual_rules
        if context_type == "character.example_dialogue":
            # path is [<character>] or [<character>, <idx|new>]
            if len(path) <= 1:
                return self.example_dialogue
            second = path[1]
            name = second if second in {"new"} or second.isdigit() else "list"
            value = None
            if name == "list":
                value = self.character.example_dialogue
            elif name == "new":
                value = None
            elif name.isdigit():
                idx = int(name)
                if 0 <= idx < len(self.character.example_dialogue):
                    value = self.character.example_dialogue[idx]
            return CharacterContextItem(
                context_type="example_dialogue",
                character=self.character,
                name=name,
                value=value,
            )
        if context_type == "character.attribute":
            iterator = self.attributes
        elif context_type == "character.detail":
            iterator = self.details
        else:
            log.debug(
                "context_type not valid for this handler", context_type=context_type
            )
            return None

        for item in iterator:
            if item.compressed_path == path_str:
                return item

        log.debug("context_id not found", path_str=path_str)
        return None

    async def context_id_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> ContextID | None:
        log.debug(
            "context_id_from_path",
            context_type=context_type,
            path=path,
            path_str=path_str,
            scene=scene,
        )

        value: CharacterContextItem | None = await self.context_id_item_from_path(
            context_type, path, path_str, scene
        )

        if value:
            return value.context_id

        log.debug("context_id not found", path_str=path_str)
        return None
