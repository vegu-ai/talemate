from typing import TYPE_CHECKING

import pydantic

from talemate.emit import emit
from talemate.knowledge.schema import EdgeKind, KnowledgeEdge

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
        kinds = {
            e.kind
            for e in edges
            if e.character == edge.character and e.target == edge.target
        }
        return "revoke" if "revoke" in kinds else "grant" if "grant" in kinds else None

    return state(before) != state(after)


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


def emit_knowledge_changes(scene: "Scene", changes: list[KnowledgeChange]):
    if not changes or not scene.active:
        return
    unique = {(c.character, c.target, c.kind): c for c in changes}
    labels = {
        target: knowledge_label(scene, target)
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
