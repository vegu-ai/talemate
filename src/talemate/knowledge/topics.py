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


def _topic_name(members: list[Fact], index: int) -> str:
    counts: Counter = Counter()
    first_seen: dict[str, str] = {}
    for fact in members:
        for subject in fact.subjects:
            key = subject.strip().lower()
            if not key:
                continue
            counts[key] += 1
            first_seen.setdefault(key, subject.strip())
    if counts:
        best = max(counts.items(), key=lambda item: (item[1], -len(item[0]), item[0]))
        return first_seen[best[0]]
    return f"topic {index}"


def cluster_facts(
    facts: list[Fact], vectors: dict[str, list[float]], threshold: float
) -> list[Topic]:
    """
    Greedy leader clustering in creation order, then one refinement pass
    that moves each fact to its nearest centroid. Facts without a vector are
    left out.
    """
    ordered = [f for f in sorted(facts, key=fact_order) if f.id in vectors]
    if not ordered:
        return []
    units = {f.id: _unit(vectors[f.id]) for f in ordered}

    groups: list[list[Fact]] = []
    centroids: list[np.ndarray] = []
    for fact in ordered:
        vector = units[fact.id]
        placed = False
        for i, centroid in enumerate(centroids):
            if float(np.dot(vector, centroid)) >= threshold:
                groups[i].append(fact)
                centroids[i] = _centroid([units[m.id] for m in groups[i]])
                placed = True
                break
        if not placed:
            groups.append([fact])
            centroids.append(vector.copy())

    # refinement: nearest centroid wins, then empty groups fall away
    if len(groups) > 1:
        matrix = np.stack(centroids)
        refined: list[list[Fact]] = [[] for _ in groups]
        for fact in ordered:
            scores = matrix @ units[fact.id]
            refined[int(np.argmax(scores))].append(fact)
        groups = [g for g in refined if g]

    topics: list[Topic] = []
    for i, members in enumerate(groups, start=1):
        topics.append(
            Topic(
                id=f"T{i}",
                name=_topic_name(members, i),
                fact_ids=[m.id for m in members],
            )
        )
    return topics


def _clusterable(scene: "Scene") -> list[Fact]:
    return list(scene.world_state.facts.values())


async def refresh_topics(scene: "Scene", force: bool = False) -> bool:
    """
    Recluster when enough facts arrived since the last run (or when forced).
    Returns True when the topics were rebuilt.
    """
    memory = get_agent("memory")
    if not getattr(memory, "topics_enabled", False):
        return False
    world_state = scene.world_state
    facts = _clusterable(scene)
    if not facts:
        if world_state.topics:
            world_state.topics = {}
            world_state.topics_fact_count = 0
            memory.topic_centroids = {}
        return False
    new_facts = len(facts) - world_state.topics_fact_count
    if not force and world_state.topics and new_facts < memory.topics_recluster_step:
        return False
    if not memory.ready:
        log.debug("topics: memory not ready, keeping the current topics")
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
    return True


async def topics_on_load(scene: "Scene"):
    """Centroids are not persisted: rebuild them, and cluster when nothing is stored yet."""
    memory = get_agent("memory")
    if not getattr(memory, "topics_enabled", False):
        return
    world_state = scene.world_state
    if not world_state.topics:
        if world_state.facts:
            await refresh_topics(scene, force=True)
        return
    await memory.rebuild_topic_centroids(scene)


def coverage(scene: "Scene", character: str) -> list[TopicCoverage]:
    """Per topic, how many of its facts sit in the character's bucket; largest topics first."""
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
    rows.sort(key=lambda r: (-r.total, r.id))
    return rows


def awareness_line(scene: "Scene", character: str) -> str | None:
    """
    `<name> knows all of A and B, some of C, nothing of D` over the topics
    with at least three facts, largest first, at most six.
    """
    rows = [r for r in coverage(scene, character) if r.total >= AWARENESS_MIN_FACTS]
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
