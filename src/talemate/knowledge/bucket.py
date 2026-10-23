"""
The knowledge bucket predicate.

A character's bucket is never stored. It is evaluated over shared records
(messages, archive entries, memory documents) plus the explicit edges and
visibility settings the world state keeps.
"""

import hashlib
import json
import re
from typing import TYPE_CHECKING, Literal

import pydantic

from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.revision_browsing import RevisionCheck, current_edges
from talemate.knowledge.schema import EntryVisibility

if TYPE_CHECKING:
    from talemate.scene_message import SceneMessage
    from talemate.tale_mate import Scene

__all__ = [
    "KnowledgeItem",
    "KnowledgeIndex",
    "ItemKind",
    "Rejection",
    "RetrievalFilter",
    "COMMON_KINDS",
    "knowledge_digest",
    "canonical_entry_id",
]

Rejection = Literal["revoke", "visibility", "presence", "stale"]

ItemKind = Literal[
    "history", "attribute", "detail", "description", "world_entry", "static"
]

# kinds every character knows unless a visibility setting or a revoke says otherwise
COMMON_KINDS = {"attribute", "detail", "description", "world_entry"}


_DESCRIPTION_CHUNK = re.compile(r"^(?P<base>.+\.description)\.\d+$")


def canonical_entry_id(entry_id: str) -> str:
    """`<name>.description.<n>` (one document per paragraph, written by
    `Character.set_description`) is the same entry as `<name>.description`."""
    match = _DESCRIPTION_CHUNK.match(entry_id)
    return match.group("base") if match else entry_id


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
        # only a description document (one per paragraph) folds onto its
        # entry id; a world entry id is free text and is looked up as typed
        is_description = typ == "description" or (
            typ == "base_attribute" and meta.get("attr") == "description"
        )
        doc_id = canonical_entry_id(doc.id) if is_description else doc.id

        present = None
        if meta.get("presence_known"):
            try:
                present = json.loads(meta.get("present") or "[]")
            except (TypeError, ValueError):
                present = None

        if typ == "history":
            return cls(id=doc_id, kind="history", present=present)

        key = visibility_key(meta)
        if key is not None and owner:
            kind = {"base_attribute": "attribute", "details": "detail"}.get(
                typ, "description"
            )
            character = scene.get_character(owner)
            visibility = character.visibility.get(key) if character else None
            return cls(id=doc_id, kind=kind, owner=owner, visibility=visibility)

        if typ == "world_state":
            entry = scene.world_state.manual_context.get(doc_id)
            return cls(
                id=doc_id,
                kind="world_entry",
                visibility=entry.visibility if entry else None,
            )

        # anything the design does not classify stays shared
        return cls(id=doc_id, kind="world_entry", owner=owner)


def knowledge_digest(
    scene: "Scene",
    *,
    viewer: str | None = None,
    boundary_ids: set[int] | None = None,
) -> str:
    """Digest predicate inputs, optionally limited to one viewer and boundary."""
    edges = scene.world_state.knowledge
    if viewer is not None:
        edges = [
            edge
            for edge in edges
            if edge.character == viewer
            and (
                boundary_ids is None
                or edge.message_id is None
                or edge.message_id in boundary_ids
            )
        ]
    payload = {
        "intro": [getattr(scene, "intro", ""), getattr(scene, "intro_present", None)],
        "edges": sorted({(edge.character, edge.target, edge.kind) for edge in edges}),
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
        "static": {
            entry.get("id"): entry.get("present")
            for entry in scene.archived_history
            if entry.get("end") is None and entry.get("present") is not None
        },
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]


class KnowledgeIndex:
    """Per-prompt view over the scene's knowledge edges."""

    def __init__(
        self,
        grants: set[tuple[str, str]],
        revokes: set[tuple[str, str]],
    ):
        self.grants = grants
        self.revokes = revokes

    @classmethod
    def from_scene(
        cls, scene: "Scene", check: RevisionCheck | None = None
    ) -> "KnowledgeIndex":
        pairs: dict[str, set[tuple[str, str]]] = {
            "grant": set(),
            "revoke": set(),
        }
        edges = current_edges(scene, check)
        for edge in edges:
            if edge.kind != "grant" and character_knowledge_enabled(scene):
                continue
            pairs[edge.kind].add((edge.character, edge.target))
        return cls(pairs["grant"], pairs["revoke"])

    def granted(self, character: str, target: str) -> bool:
        return (character, target) in self.grants

    def revoked(self, character: str, target: str) -> bool:
        return (character, target) in self.revokes

    def rejection(self, character: str, item: KnowledgeItem) -> Rejection | None:
        """Why the item is outside the character's bucket, or None when it is inside."""
        if self.revoked(character, item.id):
            return "revoke"
        if self.granted(character, item.id):
            return None
        if item.visibility is not None and not item.visibility.allows(
            character, item.owner
        ):
            return "visibility"
        if item.owner == character:
            return None
        if item.kind in COMMON_KINDS:
            return None
        if item.present is None or character in item.present:
            return None
        return "presence"

    def in_bucket(self, character: str, item: KnowledgeItem) -> bool:
        return self.rejection(character, item) is None

    def item_for_entry(self, scene: "Scene", entry_id: str) -> KnowledgeItem:
        """Classify a memory document id without the document: world entry,
        sheet entry (`<name>.<key>`), archive entry, or unknown (shared)."""
        entry = scene.world_state.manual_context.get(entry_id)
        if entry is not None:
            return KnowledgeItem(
                id=entry_id, kind="world_entry", visibility=entry.visibility
            )
        entry_id = canonical_entry_id(entry_id)

        # the longest character name wins, so `Bob.Jr.age` is Bob.Jr's, not Bob's
        for name in sorted(scene.character_data, key=len, reverse=True):
            character = scene.character_data[name]
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

    def retrieval_filter(
        self,
        scene: "Scene",
        character: str,
        check: RevisionCheck | None = None,
    ) -> "RetrievalFilter":
        return RetrievalFilter(self, scene, character, check or RevisionCheck(scene))


class RetrievalFilter:
    """
    The knowledge filter memory retrieval applies for one character: a
    callable with the reason a document was rejected.
    """

    def __init__(
        self,
        index: KnowledgeIndex,
        scene: "Scene",
        character: str,
        check: RevisionCheck,
    ):
        self.index = index
        self.scene = scene
        self.character = character
        self.check = check

    def rejection(self, doc) -> Rejection | None:
        if not self.check(doc):
            return "stale"
        return self.index.rejection(
            self.character, KnowledgeItem.from_memory_document(doc, self.scene)
        )

    def __call__(self, doc) -> bool:
        return self.rejection(doc) is None
