from talemate.knowledge.transitions import departures

from typing import TYPE_CHECKING
from talemate.knowledge.perspectives import (
    message_sources,
    rename_perspective_audiences,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["rename_knowledge_references"]


def _swap(names: list[str] | None, old: str, new: str) -> list[str] | None:
    if not names or old not in names:
        return names
    return [new if name == old else name for name in names]


def rename_knowledge_references(scene: "Scene", old: str, new: str):
    """
    Follow a character rename through every place that names characters:
    presence lists, knowledge edges (subject and `<name>.` targets) and
    visibility lists.
    """
    if old == new:
        return
    scene.world_state.clear_snapshot_perspectives()

    for identity, fact in scene.world_state.facts.items():
        if any(old in item.audience for item in fact.contributions):
            contributions = tuple(
                item.model_copy(
                    update={
                        "audience": tuple(
                            new if name == old else name for name in item.audience
                        )
                    }
                )
                for item in fact.contributions
            )
            scene.world_state.facts[identity] = fact.model_copy(
                update={
                    "contributions": contributions,
                    "present": _swap(fact.present, old, new),
                    "known_by": {
                        new if name == old else name: kind
                        for name, kind in fact.known_by.items()
                    },
                }
            )
    rename_perspective_audiences(scene, old, new)
    if old in scene.character_data:
        scene.character_data[new] = scene.character_data.pop(old)

    scene.active_characters = _swap(scene.active_characters, old, new)
    scene.intro_present = _swap(scene.intro_present, old, new)

    pending = departures(scene)
    if old in pending:
        pending[new] = pending.pop(old)
    for message in scene.history:
        if message.typ == "character_transition":
            if message.character_name == old:
                message.character_name = new
            message.participants = _swap(message.participants, old, new)
            message.present = _swap(message.present, old, new)

    for message in message_sources(scene):
        message.present = _swap(message.present, old, new)

    for entry in scene.archived_history:
        if entry.get("present"):
            entry["present"] = _swap(entry["present"], old, new)

    prefix = f"{old}."
    for reinforcement in scene.world_state.reinforce:
        if reinforcement.character == old:
            source = reinforcement.source_for(scene)
            reinforcement.character = new
            if source is not None:
                arguments = dict(source.source_arguments)
                arguments["character"] = new
                source.set_source("world_state", "update_reinforcement", **arguments)
    for edge in scene.world_state.knowledge:
        if edge.character == old:
            edge.character = new
        if edge.target.startswith(prefix):
            edge.target = f"{new}.{edge.target[len(prefix) :]}"

    for character in scene.character_data.values():
        for visibility in character.visibility.values():
            visibility.characters = _swap(visibility.characters, old, new)

    for entry in scene.world_state.manual_context.values():
        entry.visibility.characters = _swap(entry.visibility.characters, old, new)
