"""
Scene time at a message, and the fact times that follow from it. No imports
from the history or fact modules, so both can import this one.
"""

from typing import TYPE_CHECKING

from talemate.scene_message import TimePassageMessage
from talemate.util.time import shift_optional_ts, shift_ts

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "message_times",
    "refresh_fact_times",
    "shift_fact_times",
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


def shift_fact_times(scene: "Scene", shift: int) -> set[str]:
    """
    Move every stored fact time by `shift` seconds, clamped to zero, as
    `shift_scene_timeline` moves the entries. The acquisition order stays.
    Returns the ids of the facts whose time changed.
    """

    def acquired(record):
        return record.model_copy(update={"ts": shift_ts(record.ts, shift)})

    def times(fact):
        return (
            fact.ts,
            fact.last_seen_ts,
            *(item.ts for item in fact.restated_by),
            fact.acquired.ts if fact.acquired is not None else None,
            *(item.acquired.ts for item in fact.contributions),
        )

    changed = set()
    for fact in scene.world_state.facts.values():
        before = times(fact)
        fact.ts = shift_optional_ts(fact.ts, shift)
        fact.last_seen_ts = shift_optional_ts(fact.last_seen_ts, shift)
        for item in fact.restated_by:
            item.ts = shift_optional_ts(item.ts, shift)
        if fact.acquired is not None:
            fact.acquired = acquired(fact.acquired)
        fact.contributions = tuple(
            item.model_copy(update={"acquired": acquired(item.acquired)})
            for item in fact.contributions
        )
        if times(fact) != before:
            changed.add(fact.id)
    return changed


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
    open, so only this key moves.
    """
    for entry in scene.world_state.manual_context.values():
        if "ts" in entry.meta:
            entry.meta["ts"] = shift_optional_ts(entry.meta["ts"], shift)


def refresh_fact_times(scene: "Scene", fact_ids=None) -> set[str]:
    """
    Recompute the time of every message-bound fact from its message's
    position, so an edited, inserted or deleted time passage moves the facts
    after it. Returns the ids of the facts whose time changed.
    """
    times = message_times(scene)
    changed = set()
    for fact in scene.world_state.facts.values():
        if fact_ids is not None and fact.id not in fact_ids:
            continue
        # the restating messages move too, whether or not the origin is one
        for item in fact.restated_by:
            if item.message_id in times and item.ts != times[item.message_id]:
                item.ts = times[item.message_id]
                changed.add(fact.id)
        origin = times.get(fact.message_id) if fact.message_id is not None else None
        seen = [
            times[item.message_id]
            for item in (*fact.restated_by, *fact.contributions)
            if item.message_id in times
        ]
        if origin is None and not seen:
            continue
        ts = origin if origin is not None else fact.ts
        last_seen = max(value for value in (ts, *seen) if value is not None)
        if (fact.ts, fact.last_seen_ts) == (ts, last_seen):
            continue
        fact.ts = ts
        fact.last_seen_ts = last_seen
        changed.add(fact.id)
    return changed
