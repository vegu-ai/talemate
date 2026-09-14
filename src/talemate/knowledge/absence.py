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
from talemate.knowledge.names import aliases_for, mentions
from talemate.knowledge.schema import Fact
from talemate.knowledge.chronology import ranked_facts, render_fact
from talemate.knowledge.revision_browsing import current_facts

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "absence_facts",
    "render_absence_lines",
    "ABSENCE_LIMIT",
    "ABSENCE_WINDOW",
    "fact_order",
    "concerns_character",
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


def concerns_character(
    scene: "Scene", fact: Fact, character: str, aliases=None
) -> bool:
    """
    The facts the unknown list exists for: the character is one of the
    fact's subjects, or it was recorded while they were away.
    """
    aliases = aliases if aliases is not None else aliases_for(scene, character)
    if mentions(fact, aliases, subjects_first=True):
        return True
    return fact.present is not None and character not in fact.present


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
    facts = current_facts(scene)
    index = KnowledgeIndex.from_scene(scene)

    # the whole bucket, not only the window: the near-duplicate step needs
    # every fact the character knows
    bucket_ids = [
        f.id
        for f in facts
        if index.in_bucket(
            character, KnowledgeItem(id=f.id, kind="fact", present=f.present)
        )
    ]
    bucket = set(bucket_ids)

    def candidate(fact: Fact) -> bool:
        # a fact marked false is never listed: in the bucket it is known,
        # outside it there is nothing to warn about
        return fact.source != "offscreen" and fact.id not in bucket and not fact.false

    # facts about the character, or recorded while they were away, are
    # always eligible, ahead of the creation-order window and the age cut
    aliases = aliases_for(scene, character)
    concerning = ranked_facts(
        scene,
        [
            f
            for f in facts
            if candidate(f) and concerns_character(scene, f, character, aliases)
        ],
        tiers=False,
        superseders=facts,
    )
    recent = sorted(
        (f for f in facts if f.source != "offscreen"),
        key=fact_order,
        reverse=True,
    )[: max(0, window)]
    # This warning describes current author-state facts the viewer does not know.
    recent = ranked_facts(scene, recent, superseders=facts)

    listed = {f.id for f in concerning}
    unknown = concerning + [f for f in recent if candidate(f) and f.id not in listed]

    log.debug(
        "absence_facts candidates",
        character=character,
        concerning=[f.id for f in concerning],
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

    log.debug(
        "absence_facts result", character=character, listed=[f.id for f in unknown]
    )
    return unknown[:limit]


def render_absence_lines(facts: list[Fact], scene: "Scene") -> list[str]:
    """One line per fact: a newline inside a fact's text would break the bullet."""
    return [render_fact(scene, fact, include_id=False) for fact in facts]
