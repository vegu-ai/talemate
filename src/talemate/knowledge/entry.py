"""
Who knows one entry: its visibility, the presence it was recorded with, and
the grant and revoke edges that point at it.
"""

from typing import TYPE_CHECKING, Iterable, Literal

import pydantic

from talemate.knowledge.bucket import (
    ItemKind,
    KnowledgeIndex,
    KnowledgeItem,
    canonical_entry_id,
)
from talemate.knowledge.presence import layer_entry_presence
from talemate.knowledge.changes import edge_change, emit_knowledge_changes
from talemate.knowledge.schema import EdgeKind, EntryVisibility, KnowledgeEdge
from talemate.knowledge.topics import awareness_line, coverage

if TYPE_CHECKING:
    from talemate.game.engine.context_id import ContextIDItem
    from talemate.tale_mate import Scene

__all__ = [
    "EntryKnowledge",
    "SHEET_KINDS",
    "VISIBILITY_KINDS",
    "entry_knowledge",
    "known_by_line",
    "known_by_lines",
    "set_edge",
    "sheet_visibility_key",
    "character_knowledge_report",
]

SHEET_KINDS = {"description", "attribute", "detail"}
VISIBILITY_KINDS = SHEET_KINDS | {"world_entry"}
PRESENCE_KINDS = {"history", "fact"}


def _edge_detail(edge: KnowledgeEdge) -> str:
    if edge.note:
        return f'{edge.source}, "{edge.note}"'
    return edge.source


def _edge_text(edge: KnowledgeEdge) -> str:
    return f"{edge.character} ({_edge_detail(edge)})"


class EntryKnowledge(pydantic.BaseModel):
    id: str
    kind: ItemKind | Literal["unknown"]
    owner: str | None = None
    visibility: EntryVisibility | None = None
    present: list[str] | None = None
    grants: list[KnowledgeEdge] = pydantic.Field(default_factory=list)
    revokes: list[KnowledgeEdge] = pydantic.Field(default_factory=list)

    @property
    def has_visibility(self) -> bool:
        return self.kind in VISIBILITY_KINDS

    @property
    def known_by(self) -> str:
        if self.kind == "unknown":
            return "unknown (no such entry)"
        if self.kind in PRESENCE_KINDS:
            if self.present is None:
                return "everyone"
            if not self.present:
                return "nobody (present)"
            return ", ".join(self.present) + " (present)"
        if not self.has_visibility or self.visibility is None:
            return "everyone"
        mode = self.visibility.mode
        if mode == "everyone":
            return "everyone"
        if mode == "owner":
            return f"only {self.owner} (owner)" if self.owner else "nobody"
        names = [f"{self.owner} (owner)"] if self.owner else []
        names += [c for c in self.visibility.characters if c != self.owner]
        return ", ".join(names) if names else "nobody"

    @property
    def line(self) -> str:
        parts = [f"Known by: {self.known_by}"]
        if self.grants:
            parts.append("grants: " + ", ".join(_edge_text(e) for e in self.grants))
        if self.revokes:
            parts.append("revokes: " + ", ".join(_edge_text(e) for e in self.revokes))
        return "; ".join(parts)


def _sheet_item(character, key: str) -> KnowledgeItem:
    if key == "description":
        kind = "description"
    elif key.startswith("detail."):
        kind = "detail"
    else:
        kind = "attribute"
    return KnowledgeItem(
        id=f"{character.name}.{key}",
        kind=kind,
        owner=character.name,
        visibility=character.visibility.get(key),
    )


def _sheet_key(character, key: str) -> str:
    """A key that names a real attribute or detail is taken literally; only
    then does a `description.<n>` suffix count as a description paragraph."""
    if (
        key == "description"
        or key in character.base_attributes
        or (key.startswith("detail.") and key[len("detail.") :] in character.details)
    ):
        return key
    return canonical_entry_id(f"{character.name}.{key}")[len(character.name) + 1 :]


def _history_item(scene: "Scene", layer: int, raw: dict) -> KnowledgeItem:
    """`layer` counts as `HistoryEntry.layer`: 0 is the archive, 1 the first
    layered history layer."""
    if layer == 0:
        return KnowledgeItem.from_archive_entry(raw)
    return KnowledgeItem(
        id=raw.get("id", ""),
        kind="history",
        present=layer_entry_presence(scene, layer - 1, raw),
    )


def _item_from_context_item(
    scene: "Scene", item: "ContextIDItem"
) -> KnowledgeItem | None:
    """Classify a resolved Context ID item by what it already knows about itself."""
    from talemate.game.engine.context_id.character import CharacterContextItem
    from talemate.game.engine.context_id.history import HistoryContextItem
    from talemate.game.engine.context_id.world_entry import WorldEntryContextItem

    if isinstance(item, WorldEntryContextItem):
        entry = scene.world_state.manual_context.get(item.entry.id)
        if entry is None:
            return None
        return KnowledgeItem(
            id=entry.id, kind="world_entry", visibility=entry.visibility
        )
    if isinstance(item, CharacterContextItem):
        if item.context_type not in SHEET_KINDS:
            return None
        key = item.knowledge_id[len(item.character.name) + 1 :]
        return _sheet_item(item.character, key)
    if isinstance(item, HistoryContextItem):
        entry = item.entry
        try:
            if entry.layer == 0:
                raw = scene.archived_history[entry.index]
            else:
                raw = scene.layered_history[entry.layer - 1][entry.index]
        except IndexError:
            return None
        if raw.get("id") != entry.id:
            return None
        return _history_item(scene, entry.layer, raw)
    return None


def _sheet_item_from_id(scene: "Scene", entry_id: str) -> KnowledgeItem | None:
    # the longest character name wins, so `Bob.Jr.age` is Bob.Jr's, not Bob's
    for name in sorted(scene.character_data, key=len, reverse=True):
        prefix = f"{name}."
        if entry_id.startswith(prefix):
            character = scene.character_data[name]
            return _sheet_item(
                character, _sheet_key(character, entry_id[len(prefix) :])
            )
    return None


def _item_from_id(scene: "Scene", entry_id: str) -> KnowledgeItem | None:
    """Classify a bare memory document id; None when nothing carries it. A
    world entry title and a sheet entry that exists are taken literally;
    only a character description paragraph id folds onto its entry."""
    entry = scene.world_state.manual_context.get(entry_id)
    if entry is not None:
        return KnowledgeItem(
            id=entry_id, kind="world_entry", visibility=entry.visibility
        )
    sheet = _sheet_item_from_id(scene, entry_id)
    if sheet is not None:
        return sheet

    for raw in scene.archived_history:
        if raw.get("id") == entry_id:
            return _history_item(scene, 0, raw)
    for layer_index, layer in enumerate(scene.layered_history or []):
        for raw in layer:
            if raw.get("id") == entry_id:
                return _history_item(scene, layer_index + 1, raw)

    fact = scene.world_state.facts.get(entry_id)
    if fact is not None:
        return KnowledgeItem(id=fact.id, kind="fact", present=fact.present)
    return None


def entry_knowledge(scene: "Scene", entry: "str | ContextIDItem") -> EntryKnowledge:
    """
    The knowledge record of one entry: a resolved Context ID item keeps the
    kind it resolved with; a bare id is looked up in every store, and an id
    nothing carries comes back with kind `unknown`.
    """
    if isinstance(entry, str):
        item = _item_from_id(scene, entry)
        entry_id = entry
    else:
        item = _item_from_context_item(scene, entry)
        entry_id = entry.knowledge_id or ""
    if item is None:
        return EntryKnowledge(id=entry_id, kind="unknown")
    edges = [e for e in scene.world_state.knowledge if e.target == item.id]
    return EntryKnowledge(
        id=item.id,
        kind=item.kind,
        owner=item.owner,
        visibility=item.visibility,
        present=item.present,
        grants=[e for e in edges if e.kind == "grant"],
        revokes=[e for e in edges if e.kind == "revoke"],
    )


def known_by_line(scene: "Scene", entry: "str | ContextIDItem") -> str:
    return entry_knowledge(scene, entry).line


def known_by_lines(scene: "Scene", items: Iterable["ContextIDItem"]) -> dict[str, str]:
    lines: dict[str, str] = {}
    for item in items:
        if item.knowledge_id:
            lines[str(item.context_id)] = known_by_line(scene, item)
    return lines


def set_edge(
    scene: "Scene",
    edge: KnowledgeEdge,
    replace: bool = False,
    item: "ContextIDItem | None" = None,
) -> KnowledgeEdge:
    """
    Store an edge. With `replace`, the pair (character, target) keeps one edge:
    the new one wins, so a revoke after a grant removes the grant. A resolved
    Context ID item is stored under its own id; a bare target is stored as
    given, except that a character description paragraph id folds onto the
    description entry.
    """
    if item is not None:
        edge.target = item.knowledge_id
    else:
        classified = _item_from_id(scene, edge.target)
        if classified is not None:
            edge.target = classified.id
    if edge.ts is None:
        edge.ts = scene.ts
    previous = [
        e
        for e in scene.world_state.knowledge
        if e.character == edge.character and e.target == edge.target
    ]
    already_recorded = (
        replace
        and len(previous) == 1
        and previous[0].kind == edge.kind
        and previous[0].source == edge.source
    )
    if replace:
        scene.world_state.knowledge = [
            e
            for e in scene.world_state.knowledge
            if not (e.character == edge.character and e.target == edge.target)
        ]
    scene.world_state.knowledge.append(edge)
    if not already_recorded:
        emit_knowledge_changes(scene, [edge_change(edge)])
    return edge


def sheet_visibility_key(entry: EntryKnowledge) -> str:
    """The `Character.visibility` key of a sheet entry: `description`, the
    attribute name, or `detail.<name>`."""
    return entry.id[len(entry.owner) + 1 :]


def character_knowledge_report(scene: "Scene", name: str) -> str:
    """
    Prompt text for one character: their grants and revokes with entry labels,
    the restricted entries they can see, the topic coverage and the awareness
    line.
    """
    targets = scene.world_state_manager.knowledge_targets()
    labels = {t.id: t.label for t in targets}
    index = KnowledgeIndex.from_scene(scene)
    edges = [e for e in scene.world_state.knowledge if e.character == name]

    def edge_lines(kind: EdgeKind) -> list[str]:
        return [
            f"- {labels.get(e.target, e.target)}: {_edge_detail(e)}"
            for e in edges
            if e.kind == kind
        ]

    restricted = []
    for target in targets:
        if target.kind not in VISIBILITY_KINDS:
            continue
        entry = entry_knowledge(scene, target.id)
        if entry.owner == name:
            continue
        if entry.visibility is None or entry.visibility.mode == "everyone":
            continue
        if index.knows_entry(scene, name, target.id):
            restricted.append(f"- {target.label} ({entry.line})")

    lines = [f"### What {name} knows"]
    grants = edge_lines("grant")
    revokes = edge_lines("revoke")
    lines.append("Grants:" if grants else "Grants: none")
    lines += grants
    lines.append("Revokes:" if revokes else "Revokes: none")
    lines += revokes
    lines.append(
        f"Restricted entries {name} can see:"
        if restricted
        else f"Restricted entries {name} can see: none"
    )
    lines += restricted
    rows = coverage(scene, name)
    if rows:
        lines.append("Topic coverage (known / total facts):")
        lines += [f"- {row.name}: {row.known} / {row.total}" for row in rows]
    awareness = awareness_line(scene, name)
    if awareness:
        lines.append(f"Awareness: {awareness}")
    return "\n".join(lines)
