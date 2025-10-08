import json
import pydantic
from typing import TYPE_CHECKING
from pathlib import Path
import structlog

from .character import Character
from .world_state import WorldState, ManualContext
from .save import SceneEncoder
from .history import ArchiveEntry, static_history as get_static_history
import deepdiff

if TYPE_CHECKING:
    from .tale_mate import Scene


log = structlog.get_logger("talemate.shared_context")


class SharedContext(pydantic.BaseModel):
    filepath: Path = pydantic.Field(exclude=True)
    character_data: dict[str, Character] = pydantic.Field(default_factory=dict)
    world_state: WorldState = pydantic.Field(default_factory=WorldState)
    static_history: list[ArchiveEntry] = pydantic.Field(default_factory=list)

    share_static_history: bool = False

    @property
    def filename(self) -> str:
        return self.filepath.name

    async def init_from_scene(self, scene: "Scene", write: bool = False):
        # characters
        for name, character_data in scene.character_data.items():
            if character_data.shared:
                character = Character(name=character_data.name)
                await character.apply_shared_context(character_data)
                self.character_data[name] = character

        # world entries
        self.world_state = WorldState(
            manual_context={
                id: ManualContext(**manual_context.model_dump())
                for id, manual_context in scene.world_state.manual_context.items()
                if manual_context.shared
            },
        )

        # static history
        if self.share_static_history:
            # capture static history from scene
            self.static_history = [
                ArchiveEntry(**entry.model_dump())
                for entry in await get_static_history(scene)
            ]
        if write:
            await self.write_to_file()

    async def update_from_scene(self, scene: "Scene"):
        # characters
        for name, character_data in scene.character_data.items():
            if character_data.shared:
                character = Character(name=character_data.name)
                await character.apply_shared_context(character_data)
                self.character_data[name] = character

        # world entries
        for id, manual_context in scene.world_state.manual_context.items():
            if manual_context.shared:
                self.world_state.manual_context[id] = manual_context

        # static history
        if self.share_static_history:
            # replace stored static history from scene
            self.static_history = [
                ArchiveEntry(**entry.model_dump())
                for entry in await get_static_history(scene)
            ]

    async def update_to_scene(self, scene: "Scene") -> bool:
        """
        Update the scene with the shared context.
        Returns True if the scene was updated, False otherwise.
        """
        compare_context = SharedContext(
            filepath=self.filepath, share_static_history=self.share_static_history
        )
        await compare_context.init_from_scene(scene)

        delta = deepdiff.DeepDiff(compare_context.model_dump(), self.model_dump())

        if not delta:
            log.debug("shared context data is the same, no need to update scene")
            return False

        # import shared context into scene
        for name, character_data in list(self.character_data.items()):
            scene_character: Character | None = scene.character_data.get(name)
            if not scene_character:
                # character does not exist in scene, add it
                scene.character_data[name] = character_data
            else:
                # character exists in scene, update it
                await scene_character.apply_shared_context(character_data)
        for id, manual_context in list(self.world_state.manual_context.items()):
            if manual_context.shared:
                scene.world_state.manual_context[id] = manual_context

        # handle characters removed from shared context
        for character in list(scene.character_data.values()):
            if character.shared and character.name not in self.character_data:
                # We dont ever want to remove a character once its been added
                # to a scene, so we just make sure it is no longer shared
                await scene_character.set_shared(False)

        # handle world entries removed from shared context
        for id, world_entry in list(scene.world_state.manual_context.items()):
            if world_entry.shared and id not in self.world_state.manual_context:
                log.warning(
                    "world entry was removed from shared context, removing from scene",
                    world_entry_id=id,
                )
                del scene.world_state.manual_context[id]

        # apply static history from shared context (replace all static entries)
        log.info(
            "apply static history from shared context",
            share_static_history=self.share_static_history,
        )
        if self.share_static_history:
            try:
                # summarized entries are those with an end value
                summarized_entries = [
                    entry
                    for entry in scene.archived_history
                    if entry.get("end") is not None
                ]
                static_entries = [
                    entry.model_dump(exclude_none=True) for entry in self.static_history
                ]
                # replace archived_history with shared static entries first, then summarized
                scene.archived_history = static_entries + summarized_entries
            except Exception as e:
                log.error("apply static history failed", error=e)

        return True

    async def init_from_file(self):
        with open(self.filepath, "r") as f:
            data = json.load(f)
        self.character_data = {
            name: Character(**character_data)
            for name, character_data in data["character_data"].items()
        }
        self.world_state = WorldState(**data["world_state"])
        # optional fields for backward compatibility
        self.share_static_history = data.get("share_static_history", False)
        self.static_history = [
            ArchiveEntry(**entry) for entry in data.get("static_history", [])
        ]
        log.debug(
            "init_from_file",
            character_data=self.character_data,
            world_state=self.world_state,
            share_static_history=self.share_static_history,
            static_history=self.static_history,
        )
        return self

    async def write_to_file(self):
        with open(self.filepath, "w") as f:
            json.dump(self.model_dump(), f, indent=2, cls=SceneEncoder)

    async def clean_up_shared_context(self, scene: "Scene"):
        for id, manual_context in list(self.world_state.manual_context.items()):
            scene_manual_context = scene.world_state.manual_context.get(id)
            if (
                not manual_context.shared
                or not scene_manual_context
                or not scene_manual_context.shared
            ):
                del self.world_state.manual_context[id]
        for name, character_data in list(self.character_data.items()):
            scene_character_data = scene.character_data.get(name)
            if (
                not character_data.shared
                or not scene_character_data
                or not scene_character_data.shared
            ):
                del self.character_data[name]

    async def commit_changes(self, scene: "Scene"):
        await self.update_from_scene(scene)
        await self.clean_up_shared_context(scene)
        await self.write_to_file()
