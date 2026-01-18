"""
Story configuration-specific Context ID handler and item

- Story Title
- Story Description
- Story Introduction
- Story Content Classification
- Story Intention
- Scene Intention
- Scene Type
"""

from __future__ import annotations

from typing import ClassVar, TYPE_CHECKING, Literal
import structlog
import json
import pydantic

from .base import (
    ContextID,
    ContextIDItem,
    ContextIDHandler,
    ContextIDHandlerError,
    ContextIDMeta,
    ContextIDMetaGroup,
    ContextIDItemReadOnly,
    register_context_id_type,
    register_context_id_handler,
    register_context_id_meta,
)
from talemate.character import list_characters

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.context_id.story_configuration")

__all__ = [
    "StoryConfigurationContextID",
    "StoryTitleContextID",
    "StoryDescriptionContextID",
    "StoryIntroductionContextID",
    "StoryContentClassificationContextID",
    "StoryIntentionContextID",
    "SceneIntentionContextID",
    "DirectorInstructionsContextID",
    "SceneTypeContextID",
    "StoryConfigurationContextItem",
    "StoryConfigurationContext",
    # scene types inspector
    "SceneTypesContextID",
    "SceneTypesContextItem",
    "SceneTypesContext",
]

## Story Configuration Context IDs

register_context_id_meta(
    ContextIDMetaGroup(
        description="Story and scene setup information",
        context_id="story_configuration",
        items=[
            ContextIDMeta(
                context_id="story_configuration:title",
                description="The story's title (think movie, film or game title)",
                permanent=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:description",
                description="A short description of the story premise.",
                permanent=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:introduction",
                description="The introductory text shown the user at the beginning of the interactive story. Generally the turn will be yielded to the user at the end of the introduction, so leaving it open ended is recommended.",
                permanent=True,
                creative=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:content_classification",
                description="Describes the expectations of genre and adult themes, or lack thereof.",
                permanent=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:story_intention",
                description="The overall intention of the story. Lays out expectations for the experience, the general direction and any special rules or constraints.",
                permanent=True,
                creative=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:scene_intention",
                description="The intention of the current scene. Describes the expectations for the scene, the general direction and goals.",
                permanent=True,
                creative=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:director_instructions",
                description="Omnipresent instructions available to the director during automated scene direction and director chat.",
                permanent=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:scene_type",
                description="The type of scene that is currently being played. This allows to differentiate between, for example `roleplay` or `combat` scenes.",
                permanent=True,
            ),
            ContextIDMeta(
                context_id="story_configuration:character_list",
                description="A list of all characters in the story, including inactive characters. Active characters are the ones that are currently enabled to act in the scene.",
                permanent=True,
                readonly=True,
            ),
        ],
    )
)


register_context_id_meta(
    ContextIDMetaGroup(
        description="Available Scene Types",
        context_id="story_configuration.scene_types",
        items=[
            ContextIDMeta(
                context_id="story_configuration.scene_types:list",
                description="All scene types in this story",
                permanent=True,
                readonly=True,
            ),
            ContextIDMeta(
                context_id="story_configuration.scene_types:<scene_type_id>.description",
                description="The description of the scene type. Replace <scene_type_id> with the id of the scene type.",
                permanent=True,
            ),
            ContextIDMeta(
                context_id="story_configuration.scene_types:<scene_type_id>.instructions",
                description="The instructions of the scene type. Replace <scene_type_id> with the id of the scene type.",
                permanent=True,
            ),
        ],
    )
)


@register_context_id_type
class StoryConfigurationContextID(ContextID):
    context_type: ClassVar[str] = "story_configuration"
    key: ClassVar[str] = ""

    @classmethod
    def make(cls, key: str | None = None, **kwargs) -> "StoryConfigurationContextID":
        k = key or getattr(cls, "key", "")
        return cls(path=[k])

    @property
    def context_type_label(self) -> str:
        return self.key.replace(".", " ").replace("_", " ").title()


class StoryTitleContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "title"


class StoryDescriptionContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "description"


class StoryIntroductionContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "introduction"


class StoryContentClassificationContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "content_classification"


class StoryIntentionContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "story_intention"


class SceneIntentionContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "scene_intention"


class SceneTypeContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "scene_type"


class DirectorInstructionsContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "director_instructions"


class CharacterListContextID(StoryConfigurationContextID):
    key: ClassVar[str] = "character_list"


## Story Configuration Context Handler and Item


class StoryConfigurationContextItem(ContextIDItem):
    context_type: Literal[
        "title",
        "description",
        "introduction",
        "content_classification",
        "story_intention",
        "scene_intention",
        "director_instructions",
        "scene_type",
        "character_list",
    ]
    name: str

    @property
    def context_id(
        self,
    ) -> (
        StoryTitleContextID
        | StoryDescriptionContextID
        | StoryIntroductionContextID
        | StoryContentClassificationContextID
        | StoryIntentionContextID
        | SceneIntentionContextID
        | DirectorInstructionsContextID
        | SceneTypeContextID
        | CharacterListContextID
    ):
        if self.context_type == "title":
            return StoryTitleContextID.make()
        if self.context_type == "description":
            return StoryDescriptionContextID.make()
        if self.context_type == "introduction":
            return StoryIntroductionContextID.make()
        if self.context_type == "content_classification":
            return StoryContentClassificationContextID.make()
        if self.context_type == "story_intention":
            return StoryIntentionContextID.make()
        if self.context_type == "scene_intention":
            return SceneIntentionContextID.make()
        if self.context_type == "director_instructions":
            return DirectorInstructionsContextID.make()
        if self.context_type == "scene_type":
            return SceneTypeContextID.make()
        if self.context_type == "character_list":
            return CharacterListContextID.make()

    @property
    def human_id(self) -> str:
        mapping = {
            "title": "Story Title",
            "description": "Story Description",
            "introduction": "Story Introduction",
            "content_classification": "Story Content Classification",
            "story_intention": "Overarching Story Intention",
            "scene_intention": "Current Scene Intention",
            "director_instructions": "Director Instructions",
            "scene_type": "Current Scene Type",
            "character_list": "List of All Characters (active and inactive)",
        }
        return mapping.get(self.context_type, self.name)

    async def get(self, scene: "Scene") -> str | None:
        if self.context_type == "title":
            return scene.title or scene.name or ""
        if self.context_type == "description":
            return scene.description
        if self.context_type == "introduction":
            return scene.get_intro()
        if self.context_type == "content_classification":
            return scene.context
        if self.context_type == "story_intention":
            return scene.intent_state.intent
        if self.context_type == "scene_intention":
            return scene.intent_state.phase.intent if scene.intent_state.phase else None
        if self.context_type == "director_instructions":
            return scene.intent_state.instructions
        if self.context_type == "scene_type":
            if not scene.intent_state or not scene.intent_state.phase:
                return None
            try:
                return scene.intent_state.current_scene_type.id
            except Exception:
                return None
        if self.context_type == "character_list":
            characters = await list_characters(scene)
            return json.dumps([item.model_dump() for item in characters])

    async def set(self, scene: "Scene", value: str | None):
        from talemate.scene.schema import ScenePhase

        intent_changed = False
        if self.context_type == "title":
            scene.title = value or ""
        elif self.context_type == "description":
            scene.description = value or ""
        elif self.context_type == "introduction":
            scene.set_intro(value or "")
        elif self.context_type == "content_classification":
            scene.context = value or ""
        elif self.context_type == "story_intention":
            scene.intent_state.intent = value or None
            intent_changed = True
        elif self.context_type == "scene_intention":
            if scene.intent_state.phase is None:
                # Ensure a phase object exists
                first_type_id = next(iter(scene.intent_state.scene_types.keys()))
                scene.intent_state.phase = ScenePhase(scene_type=first_type_id)
            scene.intent_state.phase.intent = value or None
            intent_changed = True
        elif self.context_type == "director_instructions":
            scene.intent_state.instructions = value or None
            intent_changed = True
        elif self.context_type == "scene_type":
            if value is None:
                raise ContextIDHandlerError("Scene type id cannot be None")
            scene_type_id = str(value)
            if scene_type_id not in scene.intent_state.scene_types:
                raise ContextIDHandlerError(f"Invalid scene type id: {scene_type_id}")
            # Only switch the type; do not alter phase start or other metadata here
            if scene.intent_state.phase is None:
                scene.intent_state.phase = ScenePhase(scene_type=scene_type_id)
            else:
                scene.intent_state.phase.scene_type = scene_type_id
            intent_changed = True

        elif self.context_type == "character_list":
            raise ContextIDItemReadOnly(self.context_id.path_to_str)

        if intent_changed:
            scene.emit_scene_intent()


class SceneTypeListItem(pydantic.BaseModel):
    id: str
    name: str
    description: str | None = None
    instructions: str | None = None

    @pydantic.field_validator("description", "instructions")
    @classmethod
    def _cap_100(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) <= 100:
            return value
        return value[:97] + "..."


@register_context_id_type
class SceneTypesContextID(ContextID):
    context_type: ClassVar[str] = "story_configuration.scene_types"


class SceneTypesContextItem(ContextIDItem):
    context_type: Literal["story_configuration.scene_types"] = (
        "story_configuration.scene_types"
    )
    name: str
    path: list[str]

    @property
    def context_id(self) -> SceneTypesContextID:
        return SceneTypesContextID.make(path=self.path)

    @property
    def human_id(self) -> str:
        if self.path == ["list"]:
            return "All Scene Types"
        if len(self.path) == 1:
            return f"Scene Type: {self.path[0]}"
        if len(self.path) >= 2:
            return f"Scene Type: {self.path[0]} · {self.path[1]}"
        return self.name

    async def get(self, scene: "Scene") -> str | None:
        scene_intent = scene.intent_state
        if not scene_intent or not scene_intent.scene_types:
            return None
        types = scene_intent.scene_types

        # list all scene types
        if self.path == ["list"]:
            items = [
                SceneTypeListItem(
                    id=t.id,
                    name=t.name,
                    description=t.description,
                    instructions=t.instructions,
                ).model_dump()
                for t in types.values()
            ]
            return json.dumps(items)

        type_id = self.path[0] if self.path else None
        st = types.get(type_id) if type_id else None
        if st is None:
            return None

        # whole type object
        if len(self.path) == 1:
            return json.dumps(st.model_dump())

        # specific field
        field = self.path[1]
        if field in {"id", "name", "description", "instructions"}:
            return getattr(st, field)
        return None

    async def set(self, scene: "Scene", value: str | None):
        raise ContextIDItemReadOnly(self.context_id.path_to_str)


@register_context_id_handler
class SceneTypesContext(ContextIDHandler):
    context_types: ClassVar[list[str]] = [
        "story_configuration.scene_types",
    ]

    @classmethod
    def instance_from_path(cls, path: list[str], scene: "Scene") -> "SceneTypesContext":
        return cls()

    async def context_id_item_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> SceneTypesContextItem | None:
        if context_type != "story_configuration.scene_types":
            return None

        if not path:
            return None

        # Explicit list
        if path == ["list"]:
            types = scene.intent_state.scene_types if scene.intent_state else {}
            value = (
                json.dumps(
                    [
                        SceneTypeListItem(
                            id=t.id,
                            name=t.name,
                            description=t.description,
                            instructions=t.instructions,
                        ).model_dump()
                        for t in types.values()
                    ]
                )
                if types
                else None
            )
            return SceneTypesContextItem(
                context_type="story_configuration.scene_types",
                name="list",
                path=path,
                value=value,
            )

        # type-specific
        type_id = path[0]
        scene_intent = scene.intent_state
        if not scene_intent or not scene_intent.scene_types:
            return None
        st = scene_intent.scene_types.get(type_id)
        if st is None:
            return None

        if len(path) == 1:
            value = json.dumps(st.model_dump())
        else:
            field = path[1]
            value = (
                getattr(st, field, None)
                if field in {"id", "name", "description", "instructions"}
                else None
            )

        return SceneTypesContextItem(
            context_type="story_configuration.scene_types",
            name="scene_types",
            path=path,
            value=value,
        )

    async def context_id_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> ContextID | None:
        item = await self.context_id_item_from_path(context_type, path, path_str, scene)
        if item:
            return item.context_id
        return None


@register_context_id_handler
class StoryConfigurationContext(ContextIDHandler):
    context_types: ClassVar[list[str]] = [
        "story_configuration",
    ]

    @classmethod
    def instance_from_path(
        cls, path: list[str], scene: "Scene"
    ) -> "StoryConfigurationContext":
        return cls()

    async def context_id_item_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> StoryConfigurationContextItem | None:
        if context_type != "story_configuration":
            return None
        key = path[0] if path else ""
        if key == "title":
            return StoryConfigurationContextItem(
                context_type="title",
                name="title",
                value=scene.title or scene.name or "",
            )
        if key == "description":
            return StoryConfigurationContextItem(
                context_type="description", name="description", value=scene.description
            )
        if key == "introduction":
            return StoryConfigurationContextItem(
                context_type="introduction",
                name="introduction",
                value=scene.get_intro(),
            )
        if key == "content_classification":
            return StoryConfigurationContextItem(
                context_type="content_classification",
                name="content_classification",
                value=scene.context,
            )
        if key == "story_intention":
            return StoryConfigurationContextItem(
                context_type="story_intention",
                name="story_intention",
                value=scene.intent_state.intent,
            )
        if key == "scene_intention":
            return StoryConfigurationContextItem(
                context_type="scene_intention",
                name="scene_intention",
                value=scene.intent_state.phase.intent
                if scene.intent_state.phase
                else None,
            )
        if key == "director_instructions":
            return StoryConfigurationContextItem(
                context_type="director_instructions",
                name="director_instructions",
                value=scene.intent_state.instructions,
            )
        if key == "scene_type":
            return StoryConfigurationContextItem(
                context_type="scene_type",
                name="scene_type",
                value=(
                    scene.intent_state.current_scene_type.id
                    if scene.intent_state and scene.intent_state.phase
                    else None
                ),
            )
        if key == "character_list":
            return StoryConfigurationContextItem(
                context_type="character_list",
                name="character_list",
                value=await list_characters(scene),
            )
        return None

    async def context_id_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> ContextID | None:
        item = await self.context_id_item_from_path(context_type, path, path_str, scene)
        if item:
            return item.context_id
        return None
