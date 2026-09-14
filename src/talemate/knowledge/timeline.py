"""
Scene time at a message, and the fact times that follow from it. No imports
from the history or fact modules, so both can import this one.
"""

from typing import TYPE_CHECKING

from talemate.scene_message import TimePassageMessage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["message_times", "refresh_fact_times"]


def message_times(scene: "Scene") -> dict[int, int]:
    """
    Scene time at every message: the static history's base time plus the
    time passages before the message, the rule `Scene.fix_time` applies to
    the archive entries.
    """
    ts = 0
    for entry in scene.archived_history:
        if entry.get("ts") is not None and "end" not in entry:
            ts = entry["ts"]
        elif "end" in entry:
            break
    times = {}
    for message in scene.history:
        if isinstance(message, TimePassageMessage):
            ts += message.ts
        times[message.id] = ts
    return times


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
