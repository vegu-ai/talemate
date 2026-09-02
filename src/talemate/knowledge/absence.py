"""
The absence block: what the speaking character does not know.

recent salient facts − facts in the character's bucket − near-duplicates of
those. No LLM turn.
"""

import re
from typing import TYPE_CHECKING

import structlog

from talemate.instance import get_agent
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem
from talemate.knowledge.schema import Fact

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "absence_facts",
    "render_absence_lines",
    "ABSENCE_LIMIT",
    "ABSENCE_WINDOW",
    "fact_order",
]

log = structlog.get_logger("talemate.knowledge.absence")

# the conversation agent's settings default to these; the signature below
# shares them so the two cannot drift
ABSENCE_LIMIT = 5
ABSENCE_WINDOW = 30


def _fact_number(fact: Fact) -> int:
    match = re.search(r"\d+", fact.id)
    return int(match.group()) if match else 0


def fact_order(fact: Fact) -> tuple[int, int]:
    """Creation order: scene time, then the numeric part of the id (F10 after F2)."""
    return (fact.ts if fact.ts is not None else -1, _fact_number(fact))


_fact_order = fact_order


async def absence_facts(
    scene: "Scene",
    character: str,
    limit: int = ABSENCE_LIMIT,
    window: int = ABSENCE_WINDOW,
    dedupe_distance: float = 0.15,
) -> list[Fact]:
    """
    The most salient recent facts the character does not know.

    A fact the character does not know is dropped when a fact they do know
    sits within `dedupe_distance` of it: someone told them later, and the
    retold fact sits next to the original.
    """
    world_state = scene.world_state
    index = KnowledgeIndex.from_scene(scene)

    # the whole bucket, not only the window: the near-duplicate step needs
    # every fact the character knows
    bucket_ids = [
        f.id
        for f in world_state.facts.values()
        if index.in_bucket(
            character, KnowledgeItem(id=f.id, kind="fact", present=f.present)
        )
    ]
    bucket = set(bucket_ids)

    recent = sorted(
        (f for f in world_state.facts.values() if f.source != "offscreen"),
        key=_fact_order,
    )[-window:]

    # a fact marked false is never listed: in the bucket it is known, outside
    # it there is nothing to warn about
    unknown = [f for f in recent if f.id not in bucket and not f.false]

    log.debug(
        "absence_facts candidates",
        character=character,
        recent=len(recent),
        bucket=len(bucket),
        unknown=[f.id for f in unknown],
    )
    if not unknown:
        return []

    if bucket_ids:
        memory = get_agent("memory")
        if memory.ready:
            retold = await memory.near_duplicates(
                [f.id for f in unknown], bucket_ids, dedupe_distance
            )
            unknown = [f for f in unknown if f.id not in retold]

    unknown.sort(key=lambda f: (-f.restatements, *(-n for n in _fact_order(f))))
    log.debug(
        "absence_facts result", character=character, listed=[f.id for f in unknown]
    )
    return unknown[:limit]


def render_absence_lines(facts: list[Fact]) -> list[str]:
    """One line per fact: a newline inside a fact's text would break the bullet."""
    return [" ".join(fact.text.split()) for fact in facts]
