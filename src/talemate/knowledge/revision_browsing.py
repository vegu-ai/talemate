import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from talemate.knowledge.mode import character_knowledge_enabled

if TYPE_CHECKING:
    from talemate.knowledge.schema import KnowledgeEdge
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


class RevisionCurrency(BaseModel):
    """Which history messages and archive entries are current, read in one
    pass over the history. It is true for the history it was read from; a
    check across awaits uses RevisionCheck.
    """

    model_config = ConfigDict(frozen=True)

    sources: dict[int, bool] = {}
    stale_archive_ids: frozenset[str] = frozenset()
    stale: bool = False

    @classmethod
    def from_scene(cls, scene: "Scene") -> "RevisionCurrency":
        sources: dict[int, bool] = {}
        stale_archive_ids: set[str] = set()
        stale = False
        # with character perspectives an edit only flags what it affects, and
        # retrieval keeps the last stored knowledge until a repair
        flagged_only = character_knowledge_enabled(scene)
        for message in scene.history:
            state = getattr(message, "revision_state", None)
            current = flagged_only or state is None or message.revision_matches_baseline
            # a later message with the same id wins, as in Scene.get_message
            sources[message.id] = current
            if not current:
                stale = True
                stale_archive_ids.update(affected_archive_ids(scene, message))
                journal = state.refresh_journal or {}
                stale_archive_ids.update(journal.get("affected_archive_ids", ()))
        return cls(
            sources=sources,
            stale_archive_ids=frozenset(stale_archive_ids),
            stale=stale,
        )

    def source_current(self, message_id: int | None) -> bool:
        if message_id is None:
            return True
        return self.sources.get(message_id, False)

    def edge_current(self, edge: "KnowledgeEdge") -> bool:
        return self.source_current(edge.message_id)

    def document_current(self, document) -> bool:
        meta = getattr(document, "meta", {}) or {}
        if meta.get("knowledge_kind") == "message":
            try:
                identity = int(meta.get("knowledge_id"))
            except (TypeError, ValueError):
                return False
            return self.source_current(identity)
        if meta.get("typ") == "history":
            return str(getattr(document, "id", "")) not in self.stale_archive_ids
        return True


class RevisionCheck:
    """Tells if a memory document is current for the history as it is at the
    check.

    Another task can select a version, edit or delete a message while a
    retrieval awaits a query or an LLM call, so the history is read again
    once the event loop has run. Checks with no await between them share
    one read; a caller must not change the history between two such checks.
    """

    def __init__(self, scene: "Scene"):
        self.scene = scene
        self._revisions: RevisionCurrency | None = None

    @property
    def revisions(self) -> RevisionCurrency:
        if self._revisions is not None:
            return self._revisions
        revisions = RevisionCurrency.from_scene(self.scene)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # no loop: the read cannot be tied to one, so it is not kept
            return revisions
        self._revisions = revisions
        loop.call_soon(self._expire)
        return revisions

    def _expire(self) -> None:
        self._revisions = None

    def __call__(self, document) -> bool:
        return self.revisions.document_current(document)


def current_edges(
    scene: "Scene", check: RevisionCheck | None = None
) -> list["KnowledgeEdge"]:
    edges = scene.world_state.knowledge
    if not edges:
        return []
    revisions = (check or RevisionCheck(scene)).revisions
    return [edge for edge in edges if revisions.edge_current(edge)]
