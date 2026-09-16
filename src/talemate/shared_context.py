import json
import pydantic
from typing import TYPE_CHECKING
from pathlib import Path
import structlog

from .character import Character
from .world_state import WorldState, ManualContext
from .save import SceneEncoder
from .history import (
    ArchiveEntry,
    legacy_start_ts,
    shift_scene_timeline,
    static_history as get_static_history,
)
from .util.time import migrate_entry_time
import deepdiff

if TYPE_CHECKING:
    from .tale_mate import Scene


log = structlog.get_logger("talemate.shared_context")


class SharedContext(pydantic.BaseModel):
    filepath: Path = pydantic.Field(exclude=True)
    character_data: dict[str, Character] = pydantic.Field(default_factory=dict)
    world_state: WorldState = pydantic.Field(default_factory=WorldState)
    static_history: list[ArchiveEntry] = pydantic.Field(default_factory=list)
    # the start of the scene that wrote `static_history`; None in older files
    start_ts: int | None = None

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
                id: ManualContext(
                    **manual_context.model_dump(exclude={"reinforcement"})
                )
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
            self.start_ts = scene.start_ts
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
                self.world_state.manual_context[id] = ManualContext(
                    **manual_context.model_dump(exclude={"reinforcement"})
                )

        # static history
        if self.share_static_history:
            # replace stored static history from scene
            self.static_history = [
                ArchiveEntry(**entry.model_dump())
                for entry in await get_static_history(scene)
            ]
            self.start_ts = scene.start_ts

    def _place_static_history(self, scene: "Scene") -> tuple[list[dict], set[str]]:
        """
        The shared static entries in the scene's timeline, each at the same
        distance from the scene start as from the start of the scene that
        wrote it. A file without `start_ts` was written when the newest static
        entry was the scene start. An entry older than the zero moves the
        scene's timeline forward; returns the ids of the facts that moved.
        """
        entries = [entry.model_dump(exclude_none=True) for entry in self.static_history]
        writer_start = (
            self.start_ts if self.start_ts is not None else legacy_start_ts(entries)
        )
        for entry in entries:
            entry["ts"] += scene.start_ts - writer_start
        oldest = min((entry["ts"] for entry in entries), default=0)
        if oldest >= 0:
            return entries, set()
        shifted = shift_scene_timeline(scene, -oldest)
        for entry in entries:
            entry["ts"] -= oldest
        return entries, shifted

    async def update_to_scene(self, scene: "Scene", relative: bool = True) -> bool:
        """
        Update the scene with the shared context.
        Returns True if the scene was updated, False otherwise.

        `relative=False` copies the static entries with their saved times: a
        save from an older version takes its scene start from them afterwards.
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
                scene_character = Character(name=character_data.name)
                scene.character_data[name] = scene_character
            await scene_character.apply_shared_context(character_data)
        for id, manual_context in list(self.world_state.manual_context.items()):
            if manual_context.shared:
                existing = scene.world_state.manual_context.get(id)
                scene.world_state.manual_context[id] = ManualContext(
                    **manual_context.model_dump(exclude={"reinforcement"}),
                    reinforcement=(
                        existing.reinforcement
                        if existing and existing.text == manual_context.text
                        else None
                    ),
                )

        # handle characters removed from shared context
        for character in list(scene.character_data.values()):
            if character.shared and character.name not in self.character_data:
                # We dont ever want to remove a character once its been added
                # to a scene, so we just make sure it is no longer shared
                await character.set_shared(False)

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
                if relative:
                    static_entries, shifted = self._place_static_history(scene)
                else:
                    static_entries = [
                        entry.model_dump(exclude_none=True)
                        for entry in self.static_history
                    ]
                    shifted = set()
                # replace archived_history with shared static entries first, then summarized
                scene.archived_history = static_entries + summarized_entries
                if shifted:
                    scene.refresh_fact_times(shifted)
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
        self.start_ts = data.get("start_ts")
        # Sidecar files written before scene time became integer seconds carry
        # ISO8601 durations and are never rewritten on disk, so they have to be
        # converted on every read.
        self.static_history = [
            ArchiveEntry(**migrate_entry_time(entry))
            for entry in data.get("static_history", [])
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
