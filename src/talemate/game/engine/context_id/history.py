"""
History-specific Context ID classes
"""

from __future__ import annotations

from typing import ClassVar, TYPE_CHECKING, Literal, Generator
import structlog

from .base import (
    ContextID,
    ContextIDItem,
    ContextIDHandler,
    ContextIDMeta,
    ContextIDMetaGroup,
    register_context_id_type,
    register_context_id_handler,
    register_context_id_meta,
)
from talemate.util import iso8601_diff_to_human
from talemate.context import active_scene
from talemate.history import HistoryEntry, update_history_entry

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.context_id.history")

__all__ = [
    "HistoryEntryContextID",
    "StaticHistoryEntryContextID",
    "DynamicHistoryEntryContextID",
    "HistoryContextItem",
    "HistoryContext",
]


register_context_id_meta(
    ContextIDMetaGroup(
        description="History entries",
        context_id="history_entry",
        items=[
            ContextIDMeta(
                context_id="history_entry.static:<entry_id>",
                description="The text of a static history entry. Replace <entry_id> with the id of the history entry.",
            ),
        ],
    )
)


## History Entry Context IDs


@register_context_id_type
class HistoryEntryContextID(ContextID):
    entry_id: str
    context_type: ClassVar[str] = "history_entry"

    @property
    def context_type_label(self) -> str:
        return "History"


@register_context_id_type
class StaticHistoryEntryContextID(HistoryEntryContextID):
    context_type: ClassVar[str] = f"{HistoryEntryContextID.context_type}.static"

    @classmethod
    def make(
        cls, entry: "HistoryEntry | str", **kwargs
    ) -> "StaticHistoryEntryContextID":
        entry_id = entry if isinstance(entry, str) else entry.id
        return cls(entry_id=entry_id, path=[entry_id])


@register_context_id_type
class DynamicHistoryEntryContextID(HistoryEntryContextID):
    layer: int
    context_type: ClassVar[str] = f"{HistoryEntryContextID.context_type}.dynamic"

    @classmethod
    def make(cls, entry: "HistoryEntry", **kwargs) -> "DynamicHistoryEntryContextID":
        return cls(
            entry_id=entry.id,
            layer=entry.layer,
            path=["layer", str(entry.layer), "id", entry.id],
        )


## History Context Handler and Items


class HistoryContextItem(ContextIDItem):
    context_type: Literal["static", "dynamic"]
    entry: "HistoryEntry"
    name: str = "text"
    value: str | None = None

    @property
    def context_id(self) -> ContextID:
        if self.context_type == "static":
            return StaticHistoryEntryContextID.make(self.entry)
        return DynamicHistoryEntryContextID.make(self.entry)

    @property
    def human_id(self) -> str:
        layer = self.entry.layer
        scene: "Scene" = active_scene.get()
        human_time_diff = iso8601_diff_to_human(scene.ts, self.entry.ts)
        return f"History entry - {human_time_diff} (id `{self.entry.id}`, layer {layer}, index {self.entry.index})"

    async def get(self, scene: "Scene") -> str | None:
        # Re-resolve latest text from scene using layer/index
        try:
            if self.entry.layer == 0:
                raw = scene.archived_history[self.entry.index]
            else:
                raw = scene.layered_history[self.entry.layer - 1][self.entry.index]
            return raw.get("text")
        except Exception:
            return self.entry.text

    async def set(self, scene: "Scene", value: str | None):
        if value is None:
            return
        self.entry.text = value
        await update_history_entry(scene, self.entry)


@register_context_id_handler
class HistoryContext(ContextIDHandler):
    context_types: ClassVar[list[str]] = [
        "history_entry.static",
        "history_entry.dynamic",
    ]

    @classmethod
    def instance_from_path(cls, path: list[str], scene: "Scene") -> "HistoryContext":
        return cls()

    def _static_items(
        self, scene: "Scene"
    ) -> Generator[HistoryContextItem, None, None]:
        # Static entries are manual base-layer entries (no start/end markers)
        for index, raw in enumerate(scene.archived_history):
            if raw.get("start") is None and raw.get("end") is None:
                entry = HistoryEntry(
                    text=raw.get("text", ""),
                    ts=raw.get("ts", "PT0S"),
                    index=index,
                    layer=0,
                    id=raw.get("id"),
                    ts_start=raw.get("ts_start"),
                    ts_end=raw.get("ts_end"),
                    start=raw.get("start"),
                    end=raw.get("end"),
                )
                yield HistoryContextItem(
                    context_type="static",
                    entry=entry,
                    name="text",
                    value=entry.text,
                )

    def _dynamic_items(
        self, scene: "Scene"
    ) -> Generator[HistoryContextItem, None, None]:
        # Dynamic entries include summarized base-layer entries (with start/end)
        # and all layered-history entries
        for index, raw in enumerate(scene.archived_history):
            if raw.get("end") is not None:
                entry = HistoryEntry(
                    text=raw.get("text", ""),
                    ts=raw.get("ts", "PT0S"),
                    index=index,
                    layer=0,
                    id=raw.get("id"),
                    ts_start=raw.get("ts_start"),
                    ts_end=raw.get("ts_end"),
                    start=raw.get("start"),
                    end=raw.get("end"),
                )
                yield HistoryContextItem(
                    context_type="dynamic",
                    entry=entry,
                    name="text",
                    value=entry.text,
                )

        if not scene.layered_history:
            return

        for layer_index, layer in enumerate(scene.layered_history, start=1):
            for index, raw in enumerate(layer):
                entry = HistoryEntry(
                    text=raw.get("text", ""),
                    ts=raw.get("ts", "PT0S"),
                    index=index,
                    layer=layer_index,
                    id=raw.get("id"),
                    ts_start=raw.get("ts_start"),
                    ts_end=raw.get("ts_end"),
                    start=raw.get("start"),
                    end=raw.get("end"),
                )
                yield HistoryContextItem(
                    context_type="dynamic",
                    entry=entry,
                    name="text",
                    value=entry.text,
                )

    async def context_id_item_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> HistoryContextItem | None:
        if context_type == "history_entry.static":
            iterator = self._static_items(scene)
        elif context_type == "history_entry.dynamic":
            iterator = self._dynamic_items(scene)
        else:
            return None

        for item in iterator:
            if item.compressed_path == path_str:
                return item
        return None

    async def context_id_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> ContextID | None:
        value: HistoryContextItem | None = await self.context_id_item_from_path(
            context_type, path, path_str, scene
        )
        if value:
            return value.context_id
        return None
