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
from talemate.knowledge.schema import (
    Fact,
    KnownFact,
    Topic,
    TopicCoverage,
    FACT_SOURCE_LABELS,
    KnownKind,
    TopicFact,
)
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.names import aliases_for, numeric_id
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.knowledge.chronology import ranked_facts, fact_time, prompt_fact_text
from talemate.knowledge.revision_browsing import current_facts, fact_current

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
    "known_bucket",
    "known_facts",
    "KNOWN_FACTS_LIMIT",
    "topic_facts",
    "topics_facts",
]

log = structlog.get_logger("talemate.knowledge.topics")

AWARENESS_MIN_FACTS = 3
AWARENESS_MAX_TOPICS = 6
AWARENESS_ALL = 0.9
KNOWN_FACTS_LIMIT = 5
# why a Standard story character does not know a recorded fact
STANDARD_UNKNOWN_REASONS = {
    "revoke": "Never Learn rule",
    "unlearn": "Unlearned",
    "presence": "Not present",
}


def _unit(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector


def _centroid(vectors: list[np.ndarray]) -> np.ndarray:
    return _unit(np.mean(np.stack(vectors), axis=0))


def _topic_subject(members: list[Fact]) -> str | None:
    """The most frequent subject among the members, as written; None without subjects."""
    counts: Counter = Counter()
    first_seen: dict[str, str] = {}
    for fact in members:
        for subject in fact.subjects:
            cleaned = subject.strip()
            key = cleaned.lower()
            if not key:
                continue
            counts[key] += 1
            first_seen.setdefault(key, cleaned)
    if not counts:
        return None
    best = max(counts.items(), key=lambda item: (item[1], -len(item[0]), item[0]))
    return first_seen[best[0]]


def _topic_names(groups: list[list[Fact]]) -> list[tuple[str, bool]]:
    """
    One name per group: the head of its subject (the part before a comma)
    when no other group claims the same head, else the whole subject, so
    the awareness line and the coverage table never show two topics with
    one name. Groups without a subject get a placeholder.
    """
    subjects = [_topic_subject(g) for g in groups]
    heads = [s.split(",")[0].strip() if s else None for s in subjects]
    head_counts = Counter(h.lower() for h in heads if h)
    names: list[tuple[str, bool]] = []
    for index, (subject, head) in enumerate(zip(subjects, heads), start=1):
        if subject is None:
            names.append((f"topic {index}", False))
        elif head_counts[head.lower()] > 1:
            names.append((subject, True))
        else:
            names.append((head, True))
    return names


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
    for i, (members, (name, named)) in enumerate(
        zip(groups, _topic_names(groups)), start=1
    ):
        topics.append(
            Topic(id=f"T{i}", name=name, named=named, fact_ids=[m.id for m in members])
        )
    return topics


LARGEST_SHARE_BLOB = 0.8
SINGLETON_SHARE_DUST = 0.9


def _report_shape(topics: list[Topic]):
    """
    Both degenerate outcomes look alike from outside: say which one it is.
    Shares are over the clustered facts (facts without a vector never reach
    the clustering), and the singleton share counts facts, not topics.
    """
    members = sum(len(t.fact_ids) for t in topics)
    if not topics or members < 2:
        return
    largest = max(len(t.fact_ids) for t in topics) / members
    singletons = sum(len(t.fact_ids) for t in topics if len(t.fact_ids) == 1) / members
    if largest >= LARGEST_SHARE_BLOB and members >= 5:
        log.warning(
            "topics: most facts sit in one topic; the similarity threshold may be too low for this embedding model",
            facts=members,
            topics=len(topics),
            largest_share=round(largest, 2),
        )
    elif singletons >= SINGLETON_SHARE_DUST and members >= 5:
        log.warning(
            "topics: nearly every fact sits in its own topic; the similarity threshold may be too high for this embedding model",
            facts=members,
            topics=len(topics),
            singleton_share=round(singletons, 2),
        )
    log.info(
        "topics",
        facts=members,
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


async def refresh_topics(
    scene: "Scene", force: bool = False, *, still_current=None
) -> bool:
    """
    Recluster when the fact count moved by the recluster step in either
    direction since the last run, or when forced (every fact mutation the
    user makes forces it). Returns True when the topics were rebuilt.
    """
    memory = get_agent("memory")
    if still_current is not None and not still_current():
        from talemate.exceptions import GenerationCancelled

        raise GenerationCancelled("The scene changed during topic refresh")
    if not memory.topics_enabled:
        return False
    world_state = scene.world_state
    facts = current_facts(scene)
    if not facts:
        if still_current is not None and not still_current():
            from talemate.exceptions import GenerationCancelled

            raise GenerationCancelled("The scene changed during topic refresh")
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
    if still_current is not None and not still_current():
        from talemate.exceptions import GenerationCancelled

        raise GenerationCancelled("The scene changed during topic refresh")
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
    _report_shape(topics)
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


def _known(scene: "Scene", character: str) -> list[tuple[Fact, KnownKind]]:
    """The character's bucket with how each fact is known, oldest first."""
    # graph -> supported_facts -> summaries -> disclosures -> entry -> topics:
    # a module-level import cycles, like character_fact's at the other sites
    from talemate.knowledge.graph import bucket

    # a viewer the scene no longer holds has no perspective to resolve
    if character_knowledge_enabled(scene) and character not in scene.character_data:
        return []
    return bucket(scene, character)


def known_bucket(scene: "Scene", character: str) -> list[Fact]:
    """Every fact the character knows, oldest first, as the character holds it."""
    return [fact for fact, _ in _known(scene, character)]


def topic_facts(
    scene: "Scene",
    character: str,
    topic_id: str,
    known: list[tuple[Fact, KnownKind]] | None = None,
    *,
    read: PerspectiveReadContext | None = None,
    cache: dict | None = None,
    index: KnowledgeIndex | None = None,
) -> list[TopicFact]:
    """
    Every fact of one topic for the character: the ones they know, as the
    character holds them, with how they know them, and the recorded ones they
    do not, in topic order. `known` is the character's bucket when the caller
    already holds it.
    """
    from talemate.knowledge.fact_reconciliation import fact_knowledge_reason

    topic = scene.world_state.topics.get(topic_id)
    if topic is None:
        return []
    if known is None:
        known = _known(scene, character)
    views = {fact.id: (fact, kind) for fact, kind in known}
    facts = scene.world_state.facts
    rows = []
    perception = character_knowledge_enabled(scene)
    if perception and read is None:
        read = PerspectiveReadContext(scene)
    if not perception and index is None:
        index = KnowledgeIndex.from_scene(scene)
    cache = {} if cache is None else cache
    for fact_id in topic.fact_ids:
        canonical = facts.get(fact_id)
        if canonical is None:
            continue
        if not fact_current(scene, canonical):
            continue
        view, kind = views.get(fact_id, (canonical, None))
        if perception:
            reason = fact_knowledge_reason(
                scene, canonical, character, read=read, cache=cache
            )
        elif kind is None:
            rejection = index.rejection(
                character,
                KnowledgeItem(id=fact_id, kind="fact", present=canonical.present),
            )
            reason = STANDARD_UNKNOWN_REASONS.get(rejection)
        else:
            reason = None
        rows.append(
            TopicFact(
                id=fact_id,
                text=view.text,
                importance=view.importance,
                subjects=list(view.subjects),
                known=kind is not None,
                how=kind,
                source=FACT_SOURCE_LABELS[canonical.source],
                source_id=view.archive_id,
                ts=view.ts,
                time=fact_time(scene, view),
                reason=reason,
            )
        )
    return rows


def topics_facts(
    scene: "Scene", character: str, topic_ids: list[str]
) -> dict[str, list[TopicFact]]:
    """The rows of several topics from one bucket pass."""
    known = _known(scene, character)
    perception = character_knowledge_enabled(scene)
    read = PerspectiveReadContext(scene) if perception else None
    index = None if perception else KnowledgeIndex.from_scene(scene)
    cache = {}
    return {
        topic_id: topic_facts(
            scene,
            character,
            topic_id,
            known=known,
            read=read,
            cache=cache,
            index=index,
        )
        for topic_id in topic_ids
    }


def _topic_of(scene: "Scene") -> dict[str, str]:
    """Fact id -> topic name, empty while the Memory agent's Topics group is off."""
    if not get_agent("memory").topics_enabled:
        return {}
    return {
        fact_id: topic.name
        for topic in scene.world_state.topics.values()
        for fact_id in topic.fact_ids
    }


def coverage(
    scene: "Scene", character: str, known: list[Fact] | None = None
) -> list[TopicCoverage]:
    """
    Per topic, how many of its facts the character knows; largest topics first.
    `known` is the character's bucket when the caller already holds it.
    """
    if not get_agent("memory").topics_enabled:
        return []
    if character_knowledge_enabled(scene) and character not in scene.character_data:
        return []
    if known is None:
        known = known_bucket(scene, character)
    known_ids = {fact.id for fact in known}
    facts = scene.world_state.facts
    rows: list[TopicCoverage] = []
    for topic in scene.world_state.topics.values():
        members = [
            facts[i]
            for i in topic.fact_ids
            if i in facts and fact_current(scene, facts[i])
        ]
        if not members:
            continue
        rows.append(
            TopicCoverage(
                id=topic.id,
                name=topic.name,
                total=len(members),
                known=sum(fact.id in known_ids for fact in members),
            )
        )
    rows.sort(key=lambda r: (-r.total, _topic_number(r.id)))
    return rows


def known_facts(
    scene: "Scene",
    character: str,
    limit: int = KNOWN_FACTS_LIMIT,
    known: list[Fact] | None = None,
    *,
    prompt: bool = True,
) -> tuple[list[KnownFact], int]:
    if known is None:
        known = known_bucket(scene, character)
    topic_of = _topic_of(scene)
    recent = ranked_facts(
        scene, known, limit=limit, character=character, prompt=prompt, superseders=known
    )
    return [
        KnownFact(
            id=fact.id,
            text=prompt_fact_text(fact),
            topic=topic_of.get(fact.id),
            ts=fact.ts,
            last_seen_ts=fact.last_seen_ts,
            time=fact_time(scene, fact),
        )
        for fact in recent
    ], len(known)


def _topic_number(topic_id: str) -> int:
    return numeric_id(topic_id)


def _awareness_rows(scene: "Scene", character: str) -> list[TopicCoverage]:
    """
    Coverage merged per name: the topics named after one character (through
    their aliases) become one row, other topics merge by name. The speaker's
    own name and placeholder names are no awareness.
    """
    topics = scene.world_state.topics
    own = aliases_for(scene, character)
    cast = {
        name: aliases_for(scene, name)
        for name in scene.character_data
        if name.strip().casefold() not in own
    }
    merged: dict[str, TopicCoverage] = {}
    for row in coverage(scene, character):
        if row.id not in topics or not topics[row.id].named:
            continue
        key = row.name.strip().casefold()
        if not key or key in own:
            continue
        name = row.name.strip()
        for cast_name, aliases in cast.items():
            if key in aliases:
                key, name = cast_name.casefold(), cast_name
                break
        current = merged.get(key)
        merged[key] = TopicCoverage(
            id=current.id if current else row.id,
            name=current.name if current else name,
            total=(current.total if current else 0) + row.total,
            known=(current.known if current else 0) + row.known,
        )
    rows = [row for row in merged.values() if row.total >= AWARENESS_MIN_FACTS]
    rows.sort(key=lambda r: (-r.total, _topic_number(r.id)))
    return rows[:AWARENESS_MAX_TOPICS]


def awareness_line(scene: "Scene", character: str) -> str | None:
    """
    `<name> knows all of A, some of B, nothing of C`: one clause per name,
    each name in exactly one bucket, largest first, at most six.
    """
    if character_knowledge_enabled(scene):
        return None
    rows = _awareness_rows(scene, character)
    if not rows:
        return None

    def bucket(row: TopicCoverage) -> str:
        if row.share >= AWARENESS_ALL:
            return "all"
        return "some" if row.share > 0 else "nothing"

    parts = [f"{bucket(row)} of {row.name}" for row in rows]
    return f"{character} knows {', '.join(parts)}"
