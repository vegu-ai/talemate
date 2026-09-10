from talemate.knowledge.processing import evidence_writer, track_evidence_task
import asyncio
from weakref import WeakKeyDictionary

import structlog

from talemate.context import handle_generation_cancelled
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.facts import fact_memory_document
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.revision_browsing import defer_derived_jobs
from talemate.knowledge.evidence import extraction_evidence
from talemate.knowledge.topics import prune_topics
from talemate.knowledge.summaries import summary_entry, summary_inputs
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    perspectives_changed,
    select_character_view,
    source_reference,
)
from talemate.knowledge.supported_facts import (
    extraction_text,
    retain_current_contributions,
    replace_source_facts,
)

log = structlog.get_logger(__name__)


class SourceFactMixin:
    def init_source_facts(self):
        self._fact_extract_locks = WeakKeyDictionary()
        self._fact_memory_dirty = WeakKeyDictionary()
        self._fact_memory_locks = WeakKeyDictionary()
        self._fact_wakeup_tasks = WeakKeyDictionary()

    def connect(self, scene):
        super().connect(scene)
        perspectives_changed.connect(self._facts_invalidated, sender=scene)

    def _facts_invalidated(self, scene, *, event):
        if not character_knowledge_enabled(scene):
            return
        if event.reason == "rename":
            # Rename already rewrites audiences before this notification.
            touched = {
                fact.id
                for fact in scene.world_state.facts.values()
                if fact.contributions
            }
        else:
            touched = retain_current_contributions(scene, event.affected)
        if event.reason != "rename":
            affected = {
                ref.id
                for ref in event.affected
                if ref.kind == "summary" and ref.layer == 0
            }
            for entry in scene.archived_history:
                if entry.get("id") in affected:
                    entry.pop("facts_status", None)
        if touched:
            prune_topics(scene.world_state)
        if not touched:
            return
        self._queue_fact_work(scene, touched, self.schedule_audience_summaries)

    @staticmethod
    def _fact_wakeup_done(task):
        if not task.cancelled() and task.exception() is not None:
            log.warning("fact index scheduling failed", error=str(task.exception()))

    async def flush_fact_memory(self, scene):
        dirty = self._fact_memory_dirty.setdefault(scene, set())
        lock = self._fact_memory_locks.setdefault(scene, asyncio.Lock())
        async with lock:
            while dirty:
                if self.scene is not scene:
                    return False
                keys = dirty.copy()
                dirty.difference_update(keys)
                try:
                    documents = [
                        fact_memory_document(scene.world_state.facts[key])
                        for key in keys
                        if key in scene.world_state.facts
                    ]
                    if documents:
                        await get_agent("memory").add_many(documents)
                    if self.scene is not scene:
                        dirty.update(keys)
                        return False
                    removed = keys - scene.world_state.facts.keys()
                    if removed:
                        await get_agent("memory").delete({"ids": sorted(removed)})
                    if self.scene is not scene:
                        dirty.update(keys)
                        return False
                except BaseException:
                    dirty.update(keys)
                    raise
            return self.scene is scene

    def queue_fact_memory(self, scene, ids):
        self._queue_fact_work(scene, ids, self.flush_fact_memory)

    def _queue_fact_work(self, scene, ids, run):
        self._fact_memory_dirty.setdefault(scene, set()).update(ids)
        if self.scene is not scene or defer_derived_jobs.get():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = self._fact_wakeup_tasks.get(scene)
        if task is None or task.done():
            task = loop.create_task(run(scene))
            track_evidence_task(scene, task)
            self._fact_wakeup_tasks[scene] = task
            task.add_done_callback(self._fact_wakeup_done)

    def saved_fact_sources(self, scene):
        read = PerspectiveReadContext(scene)
        covered = set()
        summaries = []
        for key, owners in read.sources.items():
            if key[0] != "summary" or key[2] != 0 or len(owners) != 1:
                continue
            owner = owners[0]
            if owner.knowledge is None:
                continue
            reference = source_reference(scene, *key[:2], layer=key[2], read=read)
            for view in owner.knowledge.views:
                selections = [
                    select_character_view(scene, reference, name, read=read)
                    for name in view.audience
                ]
                if not selections or any(part.status != "ready" for part in selections):
                    continue
                summaries.append(selections[0].source)
                for name in view.audience:
                    for dependency in view.sources:
                        part = select_character_view(scene, dependency, name, read=read)
                        if part.status == "ready":
                            covered.add((part.source, name))
        yield from summaries
        for key, owners in read.sources.items():
            if key[0] != "message" or len(owners) != 1:
                continue
            owner = owners[0]
            if owner.knowledge is None or owner.owner.hidden:
                continue
            reference = source_reference(scene, *key[:2], layer=key[2], read=read)
            for view in owner.knowledge.views:
                selections = [
                    select_character_view(scene, reference, name, read=read)
                    for name in view.audience
                ]
                if any(part.status not in ("ready", "omitted") for part in selections):
                    continue
                if selections and not all(
                    (part.source, name) in covered
                    for part, name in zip(selections, view.audience)
                ):
                    # A partly covered shared view still supplies its entire audience.
                    yield selections[0].source
        for disclosure in scene.knowledge.disclosures if scene.knowledge else ():
            yield source_reference(scene, "disclosure", disclosure.id, read=read)

    @evidence_writer
    async def rebuild_supported_facts(self, scene, sources=None):
        if not character_knowledge_enabled(scene):
            raise ValueError("Source fact rebuilds require perception mode")
        if not self.archive_extract_facts:
            return None
        requested = list(self.saved_fact_sources(scene) if sources is None else sources)
        if not requested:
            return None
        lock = self._fact_extract_locks.setdefault(scene, asyncio.Lock())
        async with lock:
            while True:
                try:
                    if sources is None:
                        requested = list(self.saved_fact_sources(scene))
                        if not requested:
                            return None
                    if self.scene is not scene or not character_knowledge_enabled(
                        scene
                    ):
                        raise GenerationCancelled("Fact extraction scene changed")
                    batches = []
                    requests = []
                    read = PerspectiveReadContext(scene)
                    for requested_source in requested:
                        source = source_reference(
                            scene,
                            requested_source.kind,
                            requested_source.id,
                            layer=requested_source.layer,
                            read=read,
                        )
                        if source is None:
                            raise ValueError("Requested fact source was removed")
                        if source.kind == "disclosure":
                            audiences = [read.disclosures[source.id].audience]
                        else:
                            owner = read.sources[source.key][0]
                            audiences = [
                                view.audience
                                for view in owner.knowledge.views
                                if requested_source.view_id is None
                                or view.id == requested_source.view_id
                            ]
                            if not audiences:
                                raise ValueError("Requested fact view was removed")
                        for audience in audiences:
                            view = select_character_view(
                                scene, source, audience[0], read=read
                            )
                            if view.status == "omitted":
                                batches.append((view.source, audience, []))
                                continue
                            if view.status != "ready":
                                raise ValueError(
                                    "Fact sources must be ready before rebuilding"
                                )
                            text = extraction_text(
                                scene, view.source, audience[0], read=read
                            )
                            requests.append((view.source, audience, text))
                    for source, audience, text in requests:
                        _, parsed = await self.summarize(
                            text,
                            audience=audience,
                            extra_context=[],
                            return_facts=True,
                            skip_author_hooks=True,
                            fact_evidence=extraction_evidence(
                                scene, [source], audience, read=read
                            ),
                        )
                        if parsed is None:
                            raise ValueError(
                                "Fact extraction response was missing or malformed"
                            )
                        batches.append((source, audience, parsed))
                    if self.scene is not scene or not character_knowledge_enabled(
                        scene
                    ):
                        raise GenerationCancelled("Fact extraction scene changed")
                    if sources is None and set(self.saved_fact_sources(scene)) != set(
                        requested
                    ):
                        raise ValueError(
                            "Saved fact audiences changed during rebuilding"
                        )
                    await replace_source_facts(scene, batches)
                    if not await self.flush_fact_memory(scene):
                        return "failed"
                    rebuilt = {}
                    for source, audience, _ in batches:
                        if source.kind == "summary" and source.layer == 0:
                            rebuilt.setdefault(source.id, set()).update(audience)
                    read = PerspectiveReadContext(scene)
                    for identity, audience in rebuilt.items():
                        entry = summary_entry(scene, identity, 0)
                        if entry is None:
                            continue
                        inputs = summary_inputs(scene, entry, 0, read=read)
                        failures = self._summary_failure_keys(scene, entry, 0, inputs)
                        failures.difference_update(
                            (0, identity, name) for name in audience
                        )
                        self._update_summary_facts_status(scene, entry, read=read)
                    return "ok"
                except GenerationCancelled as exc:
                    handle_generation_cancelled(exc)
                    return "failed"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("source fact rebuild failed", error=str(exc))
                    action = await self.client._prompt_generation_error(
                        "Fact extraction failed; no successful rebuild was published. "
                        "Retry the requested sources, or Cancel to keep independent source contributions."
                    )
                    if action != "retry":
                        return "failed"
