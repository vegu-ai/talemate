"""
Topics: facts clustered by embedding, no LLM turn.

Greedy leader clustering over the stored fact vectors (cosine), one
refinement pass, deterministic for a fixed embedding. Coverage tells how much
of each topic a character knows; the awareness line puts that into the
conversation prompt.
"""

from collections import Counter
from typing import TYPE_CHECKING

import numpy as np
import structlog

from talemate.instance import get_agent
from talemate.knowledge.absence import fact_order
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem
from talemate.knowledge.schema import Fact, Topic, TopicCoverage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "cluster_facts",
    "refresh_topics",
    "prune_topics",
    "topics_on_load",
    "coverage",
    "awareness_line",
    "AWARENESS_MIN_FACTS",
    "AWARENESS_MAX_TOPICS",
]

log = structlog.get_logger("talemate.knowledge.topics")

AWARENESS_MIN_FACTS = 3
AWARENESS_MAX_TOPICS = 6
AWARENESS_ALL = 0.9


def _unit(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector


def _centroid(vectors: list[np.ndarray]) -> np.ndarray:
    return _unit(np.mean(np.stack(vectors), axis=0))


def _topic_name(members: list[Fact], index: int) -> tuple[str, bool]:
    """The most frequent subject among the members (named), or a placeholder."""
    counts: Counter = Counter()
    first_seen: dict[str, str] = {}
    for fact in members:
        for subject in fact.subjects:
            # a subject with a comma is a phrase; its head is the name
            cleaned = subject.split(",")[0].strip()
            key = cleaned.lower()
            if not key:
                continue
            counts[key] += 1
            first_seen.setdefault(key, cleaned)
    if counts:
        best = max(counts.items(), key=lambda item: (item[1], -len(item[0]), item[0]))
        return first_seen[best[0]], True
    return f"topic {index}", False


def cluster_facts(
    facts: list[Fact], vectors: dict[str, list[float]], threshold: float
) -> list[Topic]:
    """
    Greedy leader clustering in creation order: a fact joins the first topic
    whose leader (its first fact, held fixed) is at least `threshold` similar,
    so the threshold means the pairwise quantity it was measured on. One
    refinement pass then moves each fact to its nearest centroid. Facts
    without a vector are left out.
    """
    ordered = [f for f in sorted(facts, key=fact_order) if f.id in vectors]
    if not ordered:
        return []
    units = {f.id: _unit(vectors[f.id]) for f in ordered}

    groups: list[list[Fact]] = []
    leaders: list[np.ndarray] = []
    for fact in ordered:
        vector = units[fact.id]
        placed = False
        for i, leader in enumerate(leaders):
            if float(np.dot(vector, leader)) >= threshold:
                groups[i].append(fact)
                placed = True
                break
        if not placed:
            groups.append([fact])
            leaders.append(vector)

    # refinement: nearest centroid wins, then empty groups fall away
    if len(groups) > 1:
        matrix = np.stack([_centroid([units[m.id] for m in g]) for g in groups])
        refined: list[list[Fact]] = [[] for _ in groups]
        for fact in ordered:
            scores = matrix @ units[fact.id]
            refined[int(np.argmax(scores))].append(fact)
        groups = [g for g in refined if g]

    topics: list[Topic] = []
    for i, members in enumerate(groups, start=1):
        name, named = _topic_name(members, i)
        topics.append(
            Topic(id=f"T{i}", name=name, named=named, fact_ids=[m.id for m in members])
        )
    return topics


def _report_shape(topics: list[Topic], facts: int):
    """Both degenerate outcomes look alike from outside: say which one it is."""
    if not topics or facts < 2:
        return
    largest = max(len(t.fact_ids) for t in topics) / facts
    singletons = sum(1 for t in topics if len(t.fact_ids) == 1) / len(topics)
    if len(topics) == 1:
        log.warning(
            "topics: every fact in one topic; the similarity threshold may be too low for this embedding model",
            facts=facts,
        )
    elif singletons >= 0.9 and len(topics) >= 5:
        log.warning(
            "topics: nearly every fact in its own topic; the similarity threshold may be too high for this embedding model",
            facts=facts,
            topics=len(topics),
        )
    log.info(
        "topics",
        facts=facts,
        topics=len(topics),
        largest_share=round(largest, 2),
        singleton_share=round(singletons, 2),
    )


def prune_topics(world_state) -> bool:
    """
    Drop fact ids that no longer exist from the topics (a deletion or a
    reset while the store is not available), and empty topics with them.
    Returns True when anything changed.
    """
    changed = False
    for topic_id in list(world_state.topics):
        topic = world_state.topics[topic_id]
        kept = [i for i in topic.fact_ids if i in world_state.facts]
        if len(kept) != len(topic.fact_ids):
            changed = True
            if kept:
                topic.fact_ids = kept
            else:
                del world_state.topics[topic_id]
    if changed:
        world_state.topics_fact_count = len(world_state.facts)
    return changed


async def refresh_topics(scene: "Scene", force: bool = False) -> bool:
    """
    Recluster when the fact count moved by the recluster step in either
    direction since the last run, or when forced (every fact mutation the
    user makes forces it). Returns True when the topics were rebuilt.
    """
    memory = get_agent("memory")
    if not memory.topics_enabled:
        return False
    world_state = scene.world_state
    facts = list(world_state.facts.values())
    if not facts:
        if world_state.topics:
            world_state.topics = {}
            world_state.topics_fact_count = 0
            memory.topic_centroids = {}
        return False
    moved = abs(len(facts) - world_state.topics_fact_count)
    if not force and world_state.topics and moved < memory.topics_recluster_step:
        return False
    if not memory.ready:
        log.debug("topics: memory not ready, keeping the current topics")
        prune_topics(world_state)
        return False

    vectors = await memory.get_embeddings([f.id for f in facts])
    if not vectors:
        log.debug("topics: no fact vectors stored yet")
        return False

    topics = cluster_facts(facts, vectors, memory.topics_similarity_threshold)
    world_state.topics = {topic.id: topic for topic in topics}
    world_state.topics_fact_count = len(facts)
    memory.topic_centroids = {
        topic.id: _centroid([_unit(vectors[i]) for i in topic.fact_ids if i in vectors])
        for topic in topics
    }
    log.debug(
        "topics rebuilt",
        topics=[(t.id, t.name, len(t.fact_ids)) for t in topics],
        facts=len(facts),
    )
    _report_shape(topics, len(facts))
    return True


async def topics_on_load(scene: "Scene"):
    """Centroids are not persisted: rebuild them, and cluster when nothing is stored yet."""
    memory = get_agent("memory")
    if not memory.topics_enabled:
        return
    world_state = scene.world_state
    if not world_state.topics:
        if world_state.facts:
            await refresh_topics(scene, force=True)
        return
    await memory.rebuild_topic_centroids(scene)


def coverage(scene: "Scene", character: str) -> list[TopicCoverage]:
    """Per topic, how many of its facts sit in the character's bucket; largest topics first."""
    if not get_agent("memory").topics_enabled:
        return []
    index = KnowledgeIndex.from_scene(scene)
    facts = scene.world_state.facts
    rows: list[TopicCoverage] = []
    for topic in scene.world_state.topics.values():
        members = [facts[i] for i in topic.fact_ids if i in facts]
        if not members:
            continue
        known = sum(
            1
            for f in members
            if index.in_bucket(
                character, KnowledgeItem(id=f.id, kind="fact", present=f.present)
            )
        )
        rows.append(
            TopicCoverage(id=topic.id, name=topic.name, total=len(members), known=known)
        )
    rows.sort(key=lambda r: (-r.total, _topic_number(r.id)))
    return rows


def _topic_number(topic_id: str) -> int:
    digits = "".join(ch for ch in topic_id if ch.isdigit())
    return int(digits) if digits else 0


def awareness_line(scene: "Scene", character: str) -> str | None:
    """
    `<name> knows all of A and B, some of C, nothing of D` over the topics
    with at least three facts, largest first, at most six.
    """
    topics = scene.world_state.topics
    rows = [
        r
        for r in coverage(scene, character)
        if r.total >= AWARENESS_MIN_FACTS
        # a placeholder name the model cannot resolve, or the speaker's own
        # name ("Edwin knows nothing of Edwin"), is no awareness
        and r.id in topics
        and topics[r.id].named
        and r.name.strip().lower() != character.strip().lower()
    ]
    rows = rows[:AWARENESS_MAX_TOPICS]
    if not rows:
        return None
    groups: dict[str, list[str]] = {"all": [], "some": [], "nothing": []}
    for row in rows:
        if row.share >= AWARENESS_ALL:
            groups["all"].append(row.name)
        elif row.share > 0:
            groups["some"].append(row.name)
        else:
            groups["nothing"].append(row.name)

    def join(names: list[str]) -> str:
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " and " + names[-1]

    parts = [f"{kind} of {join(names)}" for kind, names in groups.items() if names]
    return f"{character} knows {', '.join(parts)}"
