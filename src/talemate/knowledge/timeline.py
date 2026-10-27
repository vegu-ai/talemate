"""
Scene time at a message and timestamps on authored knowledge.
"""

from typing import TYPE_CHECKING

from talemate.scene_message import TimePassageMessage
from talemate.util.time import shift_optional_ts, duration_to_human

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "message_times",
    "shift_knowledge_edge_times",
    "shift_world_entry_times",
]


def message_times(scene: "Scene") -> dict[int, int]:
    """
    Scene time at every message: the scene start plus the time passages up
    to the message, the rule `Scene.fix_time` applies to the archive entries.
    """
    ts = scene.start_ts
    times = {}
    for message in scene.history:
        if isinstance(message, TimePassageMessage):
            ts += message.ts
        times[message.id] = ts
    return times


def shift_knowledge_edge_times(scene: "Scene", shift: int) -> None:
    """
    Move the recorded time of every knowledge edge by `shift` seconds,
    clamped to zero, as `shift_scene_timeline` moves the entries.
    """
    for edge in scene.world_state.knowledge:
        edge.ts = shift_optional_ts(edge.ts, shift)


def shift_world_entry_times(scene: "Scene", shift: int) -> None:
    """
    Move the scene time a world entry records in `meta["ts"]` (a pin made
    from the chat stores one) by `shift` seconds, clamped to zero. `meta` is
    open, so only this key moves. Tracked-state update times live in the same
    saved world state and must also follow a shift applied before it is loaded.
    """
    for entry in scene.world_state.manual_context.values():
        if "ts" in entry.meta:
            entry.meta["ts"] = shift_optional_ts(entry.meta["ts"], shift)
    for reinforcement in scene.world_state.reinforce:
        reinforcement.updated_ts = shift_optional_ts(reinforcement.updated_ts, shift)


def record_time(scene: "Scene", timestamp: int | None) -> str:
    return (
        duration_to_human(max(0, scene.ts - timestamp))
        if timestamp is not None
        else "Time unknown"
    )
