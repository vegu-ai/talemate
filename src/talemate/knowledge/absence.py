"""
The absence block: what the speaking character does not know.

recent salient facts − facts in the character's bucket − near-duplicates of
those. No LLM turn.
"""

import math
from typing import TYPE_CHECKING

import structlog

from talemate.instance import get_agent
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem
from talemate.knowledge.schema import Fact

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["absence_facts", "render_absence_lines"]

log = structlog.get_logger("talemate.knowledge.absence")


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _by_recency(facts: list[Fact]) -> list[Fact]:
    return sorted(facts, key=lambda f: (f.ts if f.ts is not None else -1, f.id))


async def absence_facts(
    scene: "Scene",
    character: str,
    limit: int = 5,
    window: int = 30,
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

    recent = [
        f
        for f in _by_recency(list(world_state.facts.values()))
        if f.source != "offscreen"
    ]
    recent = recent[-window:]

    known: list[Fact] = []
    unknown: list[Fact] = []
    for fact in recent:
        if fact.false and not index.granted(character, fact.id):
            continue
        item = KnowledgeItem(id=fact.id, kind="fact", present=fact.present)
        (known if index.in_bucket(character, item) else unknown).append(fact)

    log.debug(
        "absence_facts",
        character=character,
        recent=len(recent),
        known=len(known),
        unknown=[f.id for f in unknown],
    )
    if not unknown:
        return []

    # the near-duplicate step needs the bucket beyond the window too
    bucket_ids = [
        f.id
        for f in world_state.facts.values()
        if index.in_bucket(
            character, KnowledgeItem(id=f.id, kind="fact", present=f.present)
        )
    ]
    if bucket_ids:
        memory = get_agent("memory")
        vectors = {}
        # a backend that is not ready (or has no vector store) skips the step
        if getattr(memory, "ready", False):
            try:
                vectors = await memory.get_embeddings(
                    [f.id for f in unknown] + bucket_ids
                )
            except NotImplementedError:
                vectors = {}
        if vectors:
            kept = []
            for fact in unknown:
                vector = vectors.get(fact.id)
                if vector is None:
                    kept.append(fact)
                    continue
                retold = any(
                    known_id in vectors
                    and _distance(vector, vectors[known_id]) <= dedupe_distance
                    for known_id in bucket_ids
                )
                if not retold:
                    kept.append(fact)
            unknown = kept

    unknown.sort(
        key=lambda f: (-f.restatements, -(f.ts if f.ts is not None else -1), f.id)
    )
    log.debug(
        "absence_facts", character=character, after_dedupe=[f.id for f in unknown]
    )
    return unknown[:limit]


def render_absence_lines(facts: list[Fact]) -> list[str]:
    return [fact.text for fact in facts]
