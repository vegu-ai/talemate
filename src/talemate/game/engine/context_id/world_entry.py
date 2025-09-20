"""
World entry-specific Context ID handler and item (ManualContext)
"""

from __future__ import annotations

from typing import ClassVar, TYPE_CHECKING, Literal, Generator
import structlog

from talemate.world_state import ManualContext

from .base import (
    ContextID,
    ContextIDItem,
    ContextIDHandler,
    ContextIDMeta,
    ContextIDMetaGroup,
    register_context_id_handler,
    register_context_id_type,
    register_context_id_meta,
    compress_name,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


log = structlog.get_logger("talemate.game.engine.context_id.world_entry")

__all__ = [
    "WorldEntryContextItem",
    "WorldEntryContext",
    "WorldEntryManualContextID",
    "WorldEntryContextID",
]


register_context_id_meta(
    ContextIDMetaGroup(
        description="World entry information",
        context_id="world_entry",
        items=[
            ContextIDMeta(
                context_id="world_entry.manual:<title_hash>",
                description="The context of a world entry. You cannot know the title hash, so query for the title.",
                creative=True,
            ),
        ],
    )
)


class WorldEntryContextID(ContextID):
    entry_id: str
    context_type: ClassVar[str] = "world_entry"


@register_context_id_type
class WorldEntryManualContextID(WorldEntryContextID):
    context_type: ClassVar[str] = f"{WorldEntryContextID.context_type}.manual"

    @classmethod
    def make(cls, entry_id: "str | ManualContext", **kwargs) -> "WorldEntryContextID":
        entry_id_str = entry_id if isinstance(entry_id, str) else entry_id.id
        compressed_entry_id = compress_name(entry_id_str)
        return cls(entry_id=entry_id_str, path=[compressed_entry_id])


class WorldEntryContextItem(ContextIDItem):
    context_type: Literal["manual"]
    entry: ManualContext
    name: str = "text"
    value: str | None = None

    @property
    def context_id(self) -> ContextID:
        return WorldEntryManualContextID.make(self.entry)

    @property
    def human_id(self) -> str:
        return f"World entry - '{self.entry.id}'"

    async def get(self, scene: "Scene") -> str | None:
        latest = scene.world_state.manual_context.get(self.entry.id)
        if latest:
            return latest.text
        return self.entry.text

    async def set(self, scene: "Scene", value: str | None):
        if value is None:
            return
        self.entry.text = value
        await scene.world_state_manager.update_context_db_entry(
            self.entry.id, value, self.entry.meta
        )


@register_context_id_handler
class WorldEntryContext(ContextIDHandler):
    context_types: ClassVar[list[str]] = [
        "world_entry.manual",
    ]

    @classmethod
    def instance_from_path(cls, path: list[str], scene: "Scene") -> "WorldEntryContext":
        return cls()

    def _items(self, scene: "Scene") -> Generator[WorldEntryContextItem, None, None]:
        for entry in scene.world_state.manual_context_for_world().values():
            yield WorldEntryContextItem(
                context_type="manual",
                entry=entry,
                name=entry.id,
                value=entry.text,
            )

    async def context_id_item_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> WorldEntryContextItem | None:
        if context_type != "world_entry.manual":
            return None
        for item in self._items(scene):
            if item.compressed_path == path_str:
                return item
        return None

    async def context_id_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> ContextID | None:
        item = await self.context_id_item_from_path(context_type, path, path_str, scene)
        if item:
            return item.context_id
        return None
