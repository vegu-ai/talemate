import json
from typing import TYPE_CHECKING

from talemate.scene_message import SceneMessage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "span_presence",
    "presence_differs",
    "layer_entry_presence",
    "presence_metadata",
]


def span_presence(messages: list[SceneMessage]) -> list[str] | None:
    """
    Presence of a span of messages.

    Unknown presence on any message makes the whole span unknown: a span is
    never narrower than one of its messages.
    """
    names: set[str] = set()
    for message in messages:
        if message.present is None:
            return None
        names.update(message.present)
    return sorted(names)


def presence_differs(a: list[str] | None, b: list[str] | None) -> bool:
    return a is not None and b is not None and set(a) != set(b)


def layer_entry_presence(
    scene: "Scene", layer_index: int, entry: dict
) -> list[str] | None:
    """
    Union of presence over a layered history entry's sources.

    ``layer_index`` indexes ``scene.layered_history``; layer 0 sources from
    ``scene.archived_history``. Unknown presence on any source makes the
    result unknown.
    """
    start = entry.get("start")
    end = entry.get("end")
    if start is None or end is None:
        return None

    if layer_index == 0:
        sources = scene.archived_history
    else:
        sources = scene.layered_history[layer_index - 1]

    names: set[str] = set()
    for source in sources[start : end + 1]:
        if layer_index == 0:
            present = source.get("present")
        else:
            present = layer_entry_presence(scene, layer_index - 1, source)
        if present is None:
            return None
        names.update(present)
    return sorted(names)


def presence_metadata(present: list[str] | None) -> dict:
    """Flat metadata for a memory document (ChromaDB accepts scalars only)."""
    if present is None:
        return {"presence_known": False}
    return {"presence_known": True, "present": json.dumps(list(present))}
