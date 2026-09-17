from typing import TYPE_CHECKING

import pydantic

from talemate.emit import emit
from talemate.knowledge.schema import EdgeKind, FactAnchor, KnowledgeEdge

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


class KnowledgeChange(pydantic.BaseModel):
    character: str
    target: str
    kind: EdgeKind = "grant"


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
        lifted = lifted_unlearns(pair)
        kinds = {e.kind for e in pair if e.id not in lifted}
        return next(
            (kind for kind in ("revoke", "unlearn", "grant") if kind in kinds), None
        )

    return state(before) != state(after)


def unlearn_lifted_by(edge: KnowledgeEdge, message_id: int | None) -> bool:
    return message_id is not None and message_id > (edge.message_id_boundary or 0)


def lifts_unlearn(
    edges: list[KnowledgeEdge], character: str, target: str, message_id: int | None
) -> bool:
    """Whether a grant from this line overrides the pair's unlearn edge."""
    return any(
        edge.kind == "unlearn"
        and edge.character == character
        and edge.target == target
        and unlearn_lifted_by(edge, message_id)
        for edge in edges
    )


def lifted_unlearns(edges: list[KnowledgeEdge]) -> set[str]:
    """
    The ids of the unlearn edges that a grant from a later line overrides. The
    lift is read from the grants each time and never stored: when the line
    that taught the fact again goes, its grant goes, and the Unlearn is in
    force again.
    """
    newest: dict[tuple[str, str], int] = {}
    for edge in edges:
        if edge.kind == "grant" and edge.message_id is not None:
            pair = (edge.character, edge.target)
            newest[pair] = max(newest.get(pair, edge.message_id), edge.message_id)
    return {
        edge.id
        for edge in edges
        if edge.kind == "unlearn"
        and unlearn_lifted_by(edge, newest.get((edge.character, edge.target)))
    }


# a grant from these sources records a line of the story; the other sources
# are the author's rules (a Learn, the director, a node)
STORY_GRANT_SOURCES = frozenset({"told", "inferred"})


def is_author_rule(edge: KnowledgeEdge) -> bool:
    return edge.kind != "grant" or edge.source not in STORY_GRANT_SOURCES


def drop_fact_edges(world_state, removed: set[str], *, keep_rules: bool) -> None:
    """
    Remove the edges of the facts in `removed`, which are still in the world
    state. With `keep_rules` (a regeneration) an author rule, and a learning
    from dialogue that no regeneration writes again, stays, anchored on the
    fact's statement and its line or entry, until a fact for the same
    statement takes it over (`facts.reattach_author_rules`).
    """
    kept = []
    for edge in world_state.knowledge:
        if edge.target in removed:
            fact = world_state.facts.get(edge.target)
            if not (
                keep_rules
                and fact is not None
                and (is_author_rule(edge) or edge.source == "inferred")
            ):
                continue
            edge.anchor = FactAnchor(
                text=fact.text, message_id=fact.message_id, archive_id=fact.archive_id
            )
        kept.append(edge)
    world_state.knowledge = kept


def lift_unlearn(world_state, character: str, target: str) -> None:
    """An explicit Learn or Never Learn replaces the pair's unlearn edge."""
    world_state.knowledge = [
        edge
        for edge in world_state.knowledge
        if not (
            edge.kind == "unlearn"
            and edge.character == character
            and edge.target == target
        )
    ]


def knowledge_label(scene: "Scene", target: str) -> str:
    for disclosure in scene.knowledge.disclosures if scene.knowledge else ():
        if disclosure.id == target:
            return disclosure.text
    fact = scene.world_state.facts.get(target)
    if fact:
        return fact.text
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
    entries = []
    for change in unique.values():
        entries.append(
            {
                **change.model_dump(),
                "label": labels[change.target],
            }
        )
    emit(
        "knowledge_changed",
        scene=scene,
        data={"scene_id": scene.id, "changes": entries},
        websocket_passthrough=True,
    )
