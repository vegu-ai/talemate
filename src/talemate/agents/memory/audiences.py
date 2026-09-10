import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

import structlog
from chromadb.utils.batch_utils import create_batches

from talemate.context import scene_is_loading

from talemate.knowledge.memory import audience_documents
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.revision_browsing import defer_derived_jobs
from talemate.knowledge.reinforcements import reinforcement_source_keys
from talemate.knowledge.perspectives import PerspectiveReadContext, perspectives_changed

log = structlog.get_logger(__name__)


@dataclass
class AudienceIndexState:
    revision: int = 0
    applied: int = -1
    db: object = None
    fingerprints: dict | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    documents: dict = field(default_factory=dict)
    fact_sources: dict = field(default_factory=dict)
    dirty: set | None = None
    collection_revision: int = 0
    topics: dict = field(default_factory=dict)


class AudienceMemoryMixin:
    def init_audience_index(self):
        self._audience_states = WeakKeyDictionary()

    def connect(self, scene):
        super().connect(scene)
        perspectives_changed.connect(self._audiences_changed, sender=scene)

    def _audience_state(self, scene):
        if not hasattr(self, "_audience_states"):
            self.init_audience_index()
        return self._audience_states.setdefault(scene, AudienceIndexState())

    def _audiences_changed(self, scene, *, event):
        groups = {reference.key for reference in event.affected}
        if groups.intersection(reinforcement_source_keys(scene)):
            # Generated details/world entries select the reinforcement's view too.
            groups.add(("authored",))
        # Other signal listeners may already have pruned the live contributions.
        groups.update(
            group
            for group, sources in self._audience_state(scene).fact_sources.items()
            if groups.intersection(sources)
        )
        groups.update(
            ("fact", fact.id, 0)
            for fact in scene.world_state.facts.values()
            if any(item.source.key in groups for item in fact.contributions)
        )
        self.invalidate_audience_index(scene, groups=groups)

    def invalidate_audience_writes(self, documents, *, scene=None):
        groups = {("authored",)}
        for document in documents:
            if document.get("meta", {}).get("typ") == "fact":
                groups.add(("fact", document["id"], 0))
            elif document.get("meta", {}).get("typ") == "history":
                groups.add(("summary", document["id"], 0))
        self.invalidate_audience_index(scene, groups=groups)

    def invalidate_audience_index(self, scene=None, *, reconcile=False, groups=None):
        scene = scene or self.scene
        if not character_knowledge_enabled(scene):
            return
        state = self._audience_state(scene)
        state.revision += 1
        state.topics.clear()
        if groups is None or reconcile:
            state.dirty = None
        elif state.dirty is not None:
            state.dirty.update(groups)
        if reconcile:
            state.fingerprints = None
        if (
            self.scene is not scene
            or not self.db
            or not self._ready_to_add
            or self.readonly
            or scene_is_loading.get()
            or defer_derived_jobs.get()
        ):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if state.task is None or state.task.done():
            state.task = loop.create_task(self.ensure_audience_index(scene))
            state.task.add_done_callback(self._audience_update_done)

    @staticmethod
    def _audience_update_done(task):
        if not task.cancelled() and task.exception() is not None:
            log.warning(
                "audience index update failed; retry on next read",
                error=str(task.exception()),
            )

    async def rebuild_audience_index(self):
        if not character_knowledge_enabled(self.scene):
            return
        self.invalidate_audience_index(reconcile=True)
        await self.ensure_audience_index(self.scene)

    async def purge_audience_index(self, scene):
        if self.scene is not scene:
            return
        state = self._audience_state(scene)
        async with state.lock:
            if self.db is not None:
                operation = asyncio.create_task(
                    asyncio.to_thread(self.db.delete, where={"knowledge_index": True})
                )
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    await asyncio.shield(operation)
                    raise
                finally:
                    state.fingerprints = None
                    state.dirty = None
            self._audience_states.pop(scene, None)

    async def ensure_audience_index(self, scene):
        if not character_knowledge_enabled(scene):
            return
        state = self._audience_state(scene)
        async with state.lock:
            while True:
                if not character_knowledge_enabled(scene):
                    return
                if self.readonly or not self._ready_to_add:
                    raise RuntimeError("Audience index collection is not writable")
                if self.scene is not scene or not self.db:
                    raise RuntimeError(
                        "Audience index scene or collection was released"
                    )
                db = self.db
                if state.db is not db:
                    state.db = db
                    state.collection_revision += 1
                    state.topics.clear()
                    state.applied = -1
                    state.fingerprints = None
                    state.dirty = None
                read = PerspectiveReadContext(scene)
                if state.dirty is not None:
                    # Some callers truncate history without source notifications.
                    # Check even a clean index before returning cached rows.
                    removed = {
                        doc["group"]
                        for doc in state.documents.values()
                        if doc["group"][0] in ("message", "summary", "intro")
                        and doc["group"] not in read.sources
                    }
                    if removed:
                        state.dirty.update(removed)
                        if removed.intersection(reinforcement_source_keys(scene)):
                            state.dirty.add(("authored",))
                        state.dirty.update(
                            group
                            for group, sources in state.fact_sources.items()
                            if removed.intersection(sources)
                        )
                        state.revision += 1
                        state.topics.clear()
                if state.applied == state.revision and state.fingerprints is not None:
                    return
                revision = state.revision
                dirty = state.dirty
                updated = audience_documents(scene, groups=dirty, read=read)
                if dirty is None:
                    state.fact_sources.clear()
                else:
                    for group in dirty:
                        state.fact_sources.pop(group, None)
                state.fact_sources.update(
                    (
                        ("fact", fact.id, 0),
                        tuple(item.source.key for item in fact.contributions),
                    )
                    for fact in scene.world_state.facts.values()
                    if dirty is None or ("fact", fact.id, 0) in dirty
                )
                for document in updated.values():
                    meta = document["meta"]
                    meta.setdefault("source", "talemate")
                    meta["knowledge_fingerprint"] = hashlib.sha256(
                        json.dumps(document, sort_keys=True).encode()
                    ).hexdigest()
                    meta["session"] = scene.memory_session_id
                documents = (
                    {
                        identity: document
                        for identity, document in state.documents.items()
                        if document["group"] not in dirty
                    }
                    if dirty is not None
                    else {}
                )
                documents.update(updated)
                state.documents = documents
                state.dirty = set()
                operation = asyncio.create_task(
                    asyncio.to_thread(
                        self._sync_audience_documents, db, documents, state.fingerprints
                    )
                )
                try:
                    fingerprints = await asyncio.shield(operation)
                except asyncio.CancelledError:
                    # Executor writes keep running after cancellation; retain the lock.
                    try:
                        await asyncio.shield(operation)
                    finally:
                        state.fingerprints = None
                        state.dirty = None
                    raise
                except BaseException:
                    state.fingerprints = None
                    state.dirty = None
                    raise
                if self.scene is not scene or self.db is not db:
                    raise RuntimeError(
                        "Audience index scene or collection changed during update"
                    )
                if state.revision == revision or state.fingerprints is not None:
                    state.fingerprints = fingerprints
                state.applied = revision

    async def prepare_author_index(self):
        try:
            await self.ensure_audience_index(self.scene)
        except Exception as error:
            log.warning(
                "author memory query without audience synchronization", error=str(error)
            )

    async def audience_character_context(self, viewer, names=None):
        names = list(names if names is not None else self.scene.active_characters)
        if not names:
            return ""
        documents = await self.get_documents_by_meta(
            {"character": {"$in": names}}, viewer=viewer
        )
        return "\n".join(str(doc) for doc in documents.values())

    @staticmethod
    def _sync_audience_documents(db, documents, fingerprints):
        if fingerprints is None:
            stored = db.get(include=["metadatas"])
            fingerprints = {}
            unmarked = []
            for identity, meta in zip(stored["ids"], stored["metadatas"]):
                meta = meta or {}
                if meta.get("knowledge_index") is True:
                    fingerprints[identity] = meta.get("knowledge_fingerprint")
                elif "knowledge_index" not in meta:
                    unmarked.append(identity)
            if unmarked:
                for ids, _, metadatas, _ in create_batches(
                    db._client,
                    unmarked,
                    metadatas=[{"knowledge_index": False} for _ in unmarked],
                ):
                    db.update(ids=ids, metadatas=metadatas)
        changed = {
            identity: doc
            for identity, doc in documents.items()
            if fingerprints.get(identity) != doc["meta"]["knowledge_fingerprint"]
        }
        removed = (fingerprints.keys() - documents.keys()) | (
            fingerprints.keys() & changed.keys()
        )
        # Remove old permissions before publishing replacements; failed writes stay dirty.
        if removed:
            for ids, _, _, _ in create_batches(db._client, sorted(removed)):
                db.delete(ids=ids)
        if changed:
            docs = list(changed.values())
            for ids, _, metadatas, texts in create_batches(
                db._client,
                [d["id"] for d in docs],
                documents=[d["text"] for d in docs],
                metadatas=[d["meta"] for d in docs],
            ):
                db.upsert(ids=ids, documents=texts, metadatas=metadatas)
        return {
            identity: doc["meta"]["knowledge_fingerprint"]
            for identity, doc in documents.items()
        }

    async def audience_query(self, text, character, viewer, query):
        return await self.audience_read(
            self._get, text, character, viewer=viewer, **query
        )

    def validate_audience_viewer(self, viewer):
        if not character_knowledge_enabled(self.scene):
            raise ValueError("A memory viewer requires perception mode")
        if viewer not in self.scene.character_data:
            raise ValueError(f"Unknown memory viewer: {viewer}")

    async def audience_read(self, reader, *args, viewer, **kwargs):
        async def operation(db):
            return await asyncio.to_thread(
                reader, *args, viewer=viewer, _collection=db, **kwargs
            )

        return await self.audience_operation(viewer, operation)

    async def audience_operation(self, viewer, operation):
        scene = self.scene
        for attempt in range(2):
            self.validate_audience_viewer(viewer)
            await self.ensure_audience_index(scene)
            db = self.db
            state = self._audience_state(scene)
            revision = state.revision
            results = await operation(db)
            if self.scene is not scene or self.db is not db:
                raise RuntimeError("Memory query scene or collection was released")
            await self.ensure_audience_index(scene)
            if state.revision == revision:
                return results
            log.warning(
                "audience changed during retrieval", viewer=viewer, attempt=attempt + 1
            )
        # A repeated visibility change can revoke content used by the model.
        # Bound paid requests without returning a stale result as a fallback.
        raise RuntimeError("Memory audience kept changing during retrieval; retry")
