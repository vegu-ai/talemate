from typing import TYPE_CHECKING

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

    scene.active_characters = _swap(scene.active_characters, old, new)

    for message in scene.history:
        message.present = _swap(message.present, old, new)

    for entry in scene.archived_history:
        if entry.get("present"):
            entry["present"] = _swap(entry["present"], old, new)

    prefix = f"{old}."
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
