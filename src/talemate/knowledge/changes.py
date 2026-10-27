from typing import TYPE_CHECKING, Literal

import pydantic

import talemate.emit.async_signals as async_signals
from talemate.emit import emit
from talemate.events import Event
from talemate.knowledge.schema import EdgeKind, EntryVisibility, KnowledgeEdge

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


async_signals.register(
    "knowledge.changed",
    "knowledge.visibility_changed",
    "knowledge.edge_removed",
    "knowledge.disclosure_added",
)


class KnowledgeChange(pydantic.BaseModel):
    character: str
    target: str
    kind: EdgeKind = "grant"


class LabeledKnowledgeChange(KnowledgeChange):
    label: str


class KnowledgeChangedEvent(Event):
    """What a character now knows (grant) or no longer knows (revoke)."""

    changes: list[LabeledKnowledgeChange]


VisibilityKind = Literal["world_entry", "sheet"]


class KnowledgeVisibilityChangedEvent(Event):
    """The Known by setting of a world entry or a character sheet entry changed."""

    entry_id: str
    kind: VisibilityKind
    owner: str | None = None
    key: str | None = None
    previous: EntryVisibility | None = None
    visibility: EntryVisibility


class KnowledgeEdgeRemovedEvent(Event):
    """A Learn or Never Learn rule was removed."""

    edge: KnowledgeEdge
    changed: bool


class DisclosureAddedEvent(Event):
    """Information was shared with characters as a disclosure."""

    disclosure_id: str
    text: str
    audience: list[str]
    origin: str | None = None


def edge_change(edge: KnowledgeEdge) -> KnowledgeChange:
    return KnowledgeChange(character=edge.character, target=edge.target, kind=edge.kind)


def edge_changes_knowledge(
    edge: KnowledgeEdge, before: list[KnowledgeEdge], after: list[KnowledgeEdge]
) -> bool:
    def state(edges):
        pair = [
            e
            for e in edges
            if e.character == edge.character and e.target == edge.target
        ]
        kinds = {e.kind for e in pair}
        return next((kind for kind in ("revoke", "grant") if kind in kinds), None)

    return state(before) != state(after)


def knowledge_label(scene: "Scene", target: str) -> str:
    for disclosure in scene.knowledge.disclosures if scene.knowledge else ():
        if disclosure.id == target:
            return disclosure.text
    if target in scene.world_state.manual_context:
        return target
    for character in scene.character_data.values():
        prefix = f"{character.name}."
        if not target.startswith(prefix):
            continue
        key = target[len(prefix) :]
        if key == "description" or key in character.base_attributes:
            return f"{character.name}: {key}"
        if key.startswith("detail.") and key[7:] in character.details:
            return f"{character.name}: {key[7:]}"
    for entry in scene.archived_history:
        if entry.get("id") == target:
            kind = "static history" if entry.get("end") is None else "history"
            return f"{kind}: {entry.get('text', '')[:60]}"
    for layer_index, layer in enumerate(scene.layered_history or [], start=1):
        for entry in layer:
            if entry.get("id") == target:
                return f"history (layer {layer_index}): {entry.get('text', '')[:60]}"
    return target


def emit_knowledge_changes(
    scene: "Scene", changes: list[KnowledgeChange], *, labels=None
):
    if not changes or not scene.active:
        return
    unique = {(c.character, c.target, c.kind): c for c in changes}
    labels = {
        target: labels[target]
        if labels and target in labels
        else knowledge_label(scene, target)
        for target in {c.target for c in unique.values()}
    }
    entries = [
        LabeledKnowledgeChange(**change.model_dump(), label=labels[change.target])
        for change in unique.values()
    ]
    emit(
        "knowledge_changed",
        scene=scene,
        data={
            "scene_id": scene.id,
            "changes": [entry.model_dump() for entry in entries],
        },
        websocket_passthrough=True,
    )
    async_signals.send_soon(
        "knowledge.changed",
        KnowledgeChangedEvent(
            scene=scene, event_type="knowledge.changed", changes=entries
        ),
    )


def detach_missing_message_edges(scene: "Scene") -> None:
    """Retain authored access rules after their source message is removed."""
    sources = {message.id for message in scene.history}
    for edge in scene.world_state.knowledge:
        if edge.message_id is not None and edge.message_id not in sources:
            edge.message_id = None
