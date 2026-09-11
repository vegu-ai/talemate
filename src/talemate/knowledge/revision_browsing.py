from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from talemate.knowledge.perspective_models import content_digest

if TYPE_CHECKING:
    from talemate.knowledge.schema import Fact, KnowledgeEdge
    from talemate.tale_mate import Scene


defer_derived_jobs = ContextVar("defer_derived_jobs", default=False)


@contextmanager
def defer_revision_work():
    """Select a revision without destroying evidence from the committed baseline."""
    token = defer_derived_jobs.set(True)
    try:
        yield
    finally:
        defer_derived_jobs.reset(token)


def revision_source_current(
    scene: "Scene", message_id: int | None, digest: str | None = None
) -> bool:
    if message_id is None:
        return True
    message = scene.get_message(message_id)
    if message is None:
        return False
    if digest is not None:
        return digest == content_digest(message.perception_text)
    state = getattr(message, "revision_state", None)
    return state is None or message.revision_matches_baseline


def affected_archive_ids(scene: "Scene", message) -> set[str]:
    """Return the persisted summary closure whose source range contains message."""
    try:
        message_index = next(
            index
            for index, candidate in enumerate(scene.history)
            if candidate is message
        )
    except StopIteration:
        return set()
    affected_indexes = {
        index
        for index, entry in enumerate(scene.archived_history)
        if entry.get("start") is not None
        and entry.get("end") is not None
        and entry["start"] <= message_index <= entry["end"]
    }
    affected = {
        entry["id"]
        for index, entry in enumerate(scene.archived_history)
        if index in affected_indexes and entry.get("id")
    }
    source_indexes = affected_indexes
    for entries in scene.layered_history:
        source_indexes = {
            index
            for index, entry in enumerate(entries)
            if entry.get("start") is not None
            and entry.get("end") is not None
            and any(entry["start"] <= item <= entry["end"] for item in source_indexes)
        }
        affected.update(
            entry["id"]
            for index, entry in enumerate(entries)
            if index in source_indexes and entry.get("id")
        )
    return affected


def stale_archive_ids(scene: "Scene") -> set[str]:
    affected = set()
    for message in scene.history:
        state = getattr(message, "revision_state", None)
        if state is not None and not message.revision_matches_baseline:
            affected.update(affected_archive_ids(scene, message))
            journal = state.refresh_journal or {}
            affected.update(journal.get("affected_archive_ids", ()))
    return affected


def fact_current(scene: "Scene", fact: "Fact") -> bool:
    independent = (
        fact.text_edited
        or fact.link_edited
        or any(
            edge.target == fact.id and edge.source == "manual"
            for edge in scene.world_state.knowledge
        )
    )
    if independent:
        return True
    stale = stale_archive_ids(scene)
    summary_sources = {
        item.source.id for item in fact.contributions if item.source.kind == "summary"
    }
    summary_sources.update(source.archive_id for source in fact.archive_sources)
    if fact.archive_id:
        summary_sources.add(fact.archive_id)
    dialogue_current = bool(fact.dialogue_sources) and any(
        revision_source_current(scene, source.message_id, source.message_digest)
        for source in fact.dialogue_sources
    )
    summary_current = bool(summary_sources - stale)
    if fact.dialogue_sources or summary_sources:
        return dialogue_current or summary_current
    return revision_source_current(scene, fact.message_id, fact.message_digest)


def current_facts(scene: "Scene") -> list["Fact"]:
    return [
        fact for fact in scene.world_state.facts.values() if fact_current(scene, fact)
    ]


def edge_current(scene: "Scene", edge: "KnowledgeEdge") -> bool:
    return revision_source_current(scene, edge.message_id)


def current_edges(scene: "Scene") -> list["KnowledgeEdge"]:
    return [edge for edge in scene.world_state.knowledge if edge_current(scene, edge)]


def has_stale_revisions(scene: "Scene") -> bool:
    return any(
        message.revision_state is not None and not message.revision_matches_baseline
        for message in scene.history
    )


def memory_document_current(scene: "Scene", document) -> bool:
    meta = getattr(document, "meta", {}) or {}
    if meta.get("typ") == "fact":
        identity = meta.get("knowledge_id", getattr(document, "id", None))
        fact = scene.world_state.facts.get(identity)
        return fact is not None and fact_current(scene, fact)
    if meta.get("knowledge_kind") == "message":
        try:
            identity = int(meta.get("knowledge_id"))
        except (TypeError, ValueError):
            return False
        return revision_source_current(scene, identity)
    if meta.get("typ") == "history":
        identity = str(getattr(document, "id", ""))
        if identity in stale_archive_ids(scene):
            return False
    return True
