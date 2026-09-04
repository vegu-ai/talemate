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


def emit_knowledge_changes(scene: "Scene", changes: list[KnowledgeChange]):
    if not changes or not scene.active:
        return
    unique = {(c.character, c.target, c.kind): c for c in changes}
    labels = {
        target.id: target.label
        for target in scene.world_state_manager.knowledge_targets()
    }
    entries = []
    for change in unique.values():
        fact = scene.world_state.facts.get(change.target)
        entries.append(
            {
                **change.model_dump(),
                "label": fact.text
                if fact
                else labels.get(change.target, change.target),
            }
        )
    emit(
        "knowledge_changed",
        scene=scene,
        data={"scene_id": scene.id, "changes": entries},
        websocket_passthrough=True,
    )
