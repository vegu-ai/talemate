"""
The knowledge bucket predicate.

A character's bucket is never stored. It is evaluated over shared records
(messages, archive entries, memory documents) plus the explicit edges and
visibility settings the world state keeps.
"""

import hashlib
import json
from typing import TYPE_CHECKING, Callable, Literal

import pydantic

from talemate.knowledge.schema import EntryVisibility

if TYPE_CHECKING:
    from talemate.scene_message import SceneMessage
    from talemate.tale_mate import Scene

__all__ = [
    "KnowledgeItem",
    "KnowledgeIndex",
    "ItemKind",
    "COMMON_KINDS",
    "knowledge_digest",
]

ItemKind = Literal[
    "history", "fact", "attribute", "detail", "description", "world_entry", "static"
]

# kinds every character knows unless a visibility setting or a revoke says otherwise
COMMON_KINDS = {"attribute", "detail", "description", "world_entry", "static"}


def visibility_key(meta: dict) -> str | None:
    """Storage key of a character sheet entry, matching Character.visibility."""
    typ = meta.get("typ")
    if typ == "base_attribute":
        return meta.get("attr")
    if typ == "details":
        return f"detail.{meta.get('detail')}"
    if typ == "description":
        return "description"
    return None


class KnowledgeItem(pydantic.BaseModel):
    id: str
    kind: ItemKind
    owner: str | None = None
    present: list[str] | None = None
    visibility: EntryVisibility | None = None

    @classmethod
    def from_message(cls, message: "SceneMessage") -> "KnowledgeItem":
        return cls(id=str(message.id), kind="history", present=message.present)

    @classmethod
    def from_archive_entry(cls, entry: dict) -> "KnowledgeItem":
        static = entry.get("end") is None
        return cls(
            id=entry.get("id", ""),
            kind="static" if static else "history",
            present=entry.get("present"),
        )

    @classmethod
    def from_memory_document(cls, doc, scene: "Scene") -> "KnowledgeItem":
        meta = getattr(doc, "meta", None) or {}
        typ = meta.get("typ")
        owner = meta.get("character")
        if owner == "__narrator__":
            owner = None

        present = None
        if meta.get("presence_known"):
            try:
                present = json.loads(meta.get("present") or "[]")
            except (TypeError, ValueError):
                present = None

        if typ == "history":
            return cls(id=doc.id, kind="history", present=present)
        if typ == "fact":
            return cls(id=doc.id, kind="fact", owner=owner, present=present)

        key = visibility_key(meta)
        if key is not None and owner:
            kind = {"base_attribute": "attribute", "details": "detail"}.get(
                typ, "description"
            )
            character = scene.get_character(owner)
            visibility = character.visibility.get(key) if character else None
            return cls(id=doc.id, kind=kind, owner=owner, visibility=visibility)

        if typ == "world_state":
            entry = scene.world_state.manual_context.get(doc.id)
            return cls(
                id=doc.id,
                kind="world_entry",
                visibility=entry.visibility if entry else None,
            )

        # anything the design does not classify stays shared
        return cls(id=doc.id, kind="world_entry", owner=owner)


def knowledge_digest(scene: "Scene") -> str:
    """Short digest of every stored input to the predicate: edges and visibility."""
    payload = {
        "edges": sorted(
            (e.character, e.target, e.kind) for e in scene.world_state.knowledge
        ),
        "sheets": {
            name: {k: v.model_dump() for k, v in sorted(c.visibility.items())}
            for name, c in sorted(scene.character_data.items())
            if c.visibility
        },
        "entries": {
            k: v.visibility.model_dump()
            for k, v in sorted(scene.world_state.manual_context.items())
            if v.visibility.mode != "everyone"
        },
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]


class KnowledgeIndex:
    """Per-prompt view over the scene's knowledge edges."""

    def __init__(self, grants: set[tuple[str, str]], revokes: set[tuple[str, str]]):
        self.grants = grants
        self.revokes = revokes

    @classmethod
    def from_scene(cls, scene: "Scene") -> "KnowledgeIndex":
        grants: set[tuple[str, str]] = set()
        revokes: set[tuple[str, str]] = set()
        for edge in scene.world_state.knowledge:
            bucket = grants if edge.kind == "grant" else revokes
            bucket.add((edge.character, edge.target))
        return cls(grants, revokes)

    def granted(self, character: str, target: str) -> bool:
        return (character, target) in self.grants

    def revoked(self, character: str, target: str) -> bool:
        return (character, target) in self.revokes

    def in_bucket(self, character: str, item: KnowledgeItem) -> bool:
        if self.revoked(character, item.id):
            return False
        if self.granted(character, item.id):
            return True
        if item.visibility is not None and not item.visibility.allows(
            character, item.owner
        ):
            return False
        if item.owner == character:
            return True
        if item.kind in COMMON_KINDS:
            return True
        return item.present is None or character in item.present

    def item_for_entry(self, scene: "Scene", entry_id: str) -> KnowledgeItem:
        """Classify a memory document id without the document: world entry,
        sheet entry (`<name>.<key>`), archive entry, or unknown (shared)."""
        entry = scene.world_state.manual_context.get(entry_id)
        if entry is not None:
            return KnowledgeItem(
                id=entry_id, kind="world_entry", visibility=entry.visibility
            )

        for name, character in scene.character_data.items():
            prefix = f"{name}."
            if not entry_id.startswith(prefix):
                continue
            key = entry_id[len(prefix) :]
            if key == "description":
                kind = "description"
            elif key.startswith("detail."):
                kind = "detail"
            else:
                kind = "attribute"
            return KnowledgeItem(
                id=entry_id,
                kind=kind,
                owner=name,
                visibility=character.visibility.get(key),
            )

        for archived in scene.archived_history:
            if archived.get("id") == entry_id:
                return KnowledgeItem.from_archive_entry(archived)

        return KnowledgeItem(id=entry_id, kind="world_entry")

    def knows_entry(self, scene: "Scene", character: str | None, entry_id: str) -> bool:
        if not character:
            return True
        return self.in_bucket(character, self.item_for_entry(scene, entry_id))

    def sheet(
        self, scene: "Scene", character, viewer: str | None, *exclude: str
    ) -> str:
        """`Character.sheet_filtered` as the viewer knows it."""
        sheet = character.base_attributes or {
            "name": character.name,
            "gender": character.gender,
            "description": character.description,
        }
        exclude_lower = {e.lower() for e in exclude}
        lines = []
        for key, value in sheet.items():
            if key.lower() in exclude_lower:
                continue
            if key.lower() == "name" or self.knows_entry(
                scene, viewer, f"{character.name}.{key}"
            ):
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def description(self, scene: "Scene", character, viewer: str | None) -> str:
        if self.knows_entry(scene, viewer, f"{character.name}.description"):
            return character.description
        return ""

    def retrieval_filter(self, scene: "Scene", character: str) -> Callable:
        def _filter(doc) -> bool:
            return self.in_bucket(
                character, KnowledgeItem.from_memory_document(doc, scene)
            )

        return _filter
