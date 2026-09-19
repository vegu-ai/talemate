from talemate.knowledge.processing import evidence_writer, track_evidence_task
import asyncio
import weakref
from typing import Literal

import structlog

from talemate.context import handle_generation_cancelled
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import PerspectiveOutput
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    perspectives_changed,
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.knowledge.summaries import (
    SummaryInput,
    summary_entry,
    summary_inputs,
)
from talemate.status import background_task

log = structlog.get_logger(__name__)
MAX_SUMMARY_REPAIR_PASSES = 8


class AudienceSummaryMixin:
    def init_audience_summaries(self):
        self._audience_summary_locks = weakref.WeakKeyDictionary()
        self._summary_rebuild_tasks = weakref.WeakKeyDictionary()
        self._summary_dirty = weakref.WeakKeyDictionary()
        self._summary_waiting = weakref.WeakKeyDictionary()
        self._summary_generation_options = weakref.WeakKeyDictionary()

    def connect(self, scene):
        super().connect(scene)
        perspectives_changed.connect(self._summary_invalidated, sender=scene)

    def _summary_invalidated(self, scene, *, event):
        dirty = self._summary_dirty.setdefault(scene, set())
        for reference in event.affected:
            if reference.kind != "summary" or (
                reference.key == event.source.key and event.reason == "views"
            ):
                continue
            entry = summary_entry(scene, reference.id, reference.layer)
            if entry is None:
                continue
            dirty.update(
                (reference.layer, reference.id, name)
                for view in (entry.get("knowledge") or {}).get("views", [])
                if reference.view_id is None or reference.view_id == view["id"]
                for name in view["audience"]
            )

    def _publish_summary_group(
        self,
        scene,
        identity,
        layer,
        audience,
        status: Literal["ready", "pending", "failed", "omitted"],
        *,
        text=None,
        sources=(),
    ):
        entry = summary_entry(scene, identity, layer)
        if entry is None:
            return
        read = PerspectiveReadContext(scene)
        reference = source_reference(scene, "summary", identity, layer=layer, read=read)
        outputs = []
        for view in (entry.get("knowledge") or {}).get("views", []):
            remaining = tuple(name for name in view["audience"] if name not in audience)
            if not remaining:
                continue
            values = {key: value for key, value in view.items() if key != "revision"}
            values["audience"] = remaining
            if view["status"] != "failed" and any(
                select_character_view(scene, reference, name, read=read).status
                not in ("ready", "omitted")
                for name in remaining
            ):
                values.update(
                    status="pending", text=None, sources=(), passage_provenance=()
                )
            outputs.append(PerspectiveOutput(**values))
        outputs.append(
            PerspectiveOutput(
                audience=audience, status=status, text=text, sources=sources
            )
        )
        set_source_perspectives(scene, "summary", identity, outputs, layer=layer)

    @evidence_writer
    async def ensure_summary_views(
        self, scene, identity, layer=0, *, generation_options=None, audiences=None
    ):
        if not character_knowledge_enabled(scene):
            return
        lock = self._audience_summary_locks.setdefault(scene, asyncio.Lock())
        async with lock:
            entry = summary_entry(scene, identity, layer)
            if entry is None:
                return
            read = PerspectiveReadContext(scene)
            inputs = summary_inputs(scene, entry, layer, read=read)
            reference = source_reference(
                scene, "summary", identity, layer=layer, read=read
            )
            groups = {}
            names = set(inputs) if audiences is None else set(audiences)
            for name in sorted(names):
                if name not in scene.character_data:
                    continue
                if reference and select_character_view(
                    scene, reference, name, read=read
                ).status in ("ready", "omitted"):
                    continue
                groups.setdefault(inputs.get(name, SummaryInput("pending")), []).append(
                    name
                )
            for summary_input, names in groups.items():
                await self._generate_summary_group(
                    scene,
                    entry,
                    layer,
                    tuple(names),
                    summary_input,
                    generation_options=generation_options,
                )

    async def _generate_summary_group(
        self, scene, entry, layer, audience, summary_input, *, generation_options=None
    ):
        identity = entry["id"]
        keys = {(layer, identity, name) for name in audience}
        dirty = self._summary_dirty.setdefault(scene, set())
        waiting = self._summary_waiting.setdefault(scene, set())
        dirty.difference_update(keys)
        waiting.difference_update(keys)
        self._publish_summary_group(scene, identity, layer, audience, "pending")
        if summary_input.status == "pending":
            waiting.update(keys)
            return
        if summary_input.status == "omitted":
            self._publish_summary_group(
                scene,
                identity,
                layer,
                audience,
                "omitted",
                sources=summary_input.sources,
            )
            return True
        stamp = (entry["text"], entry.get("start"), entry.get("end"))

        def current():
            if self.scene is not scene or not character_knowledge_enabled(scene):
                return False
            stored = summary_entry(scene, identity, layer)
            if (
                stored is None
                or (stored["text"], stored.get("start"), stored.get("end")) != stamp
            ):
                return False
            inputs = summary_inputs(scene, stored, layer)
            return all(inputs.get(name) == summary_input for name in audience)

        def requeue():
            if summary_entry(scene, identity, layer) is not None:
                dirty.update(keys)

        if not current():
            requeue()
            return

        while True:
            try:
                if layer == 0:
                    result = await self.summarize(
                        "\n\n".join(summary_input.texts),
                        extra_context=[],
                        generation_options=generation_options,
                        audience=audience,
                        skip_author_hooks=True,
                    )
                else:
                    summaries = await self._lh_split_and_summarize_chunks(
                        [{"text": part} for part in summary_input.texts],
                        "",
                        generation_options=generation_options,
                        audience=audience,
                        skip_author_hooks=True,
                    )
                    result = "\n\n".join(summaries)
                if not result.strip():
                    raise ValueError("Summary response was empty")
                if not current():
                    requeue()
                    return False
                self._publish_summary_group(
                    scene,
                    identity,
                    layer,
                    audience,
                    "ready",
                    text=result.strip(),
                    sources=summary_input.sources,
                )
                return True
            except asyncio.CancelledError:
                requeue()
                raise
            except GenerationCancelled as exc:
                handle_generation_cancelled(exc)
                if current():
                    self._publish_summary_group(
                        scene,
                        identity,
                        layer,
                        audience,
                        "failed",
                        sources=summary_input.sources,
                    )
                    dirty.difference_update(keys)
                else:
                    requeue()
                return
            except Exception as exc:
                if not current():
                    requeue()
                    return
                self._publish_summary_group(
                    scene,
                    identity,
                    layer,
                    audience,
                    "failed",
                    sources=summary_input.sources,
                )
                log.warning(
                    "audience summary failed",
                    source_id=identity,
                    layer=layer,
                    error=str(exc),
                )
                action = await self.client._prompt_generation_error(
                    f"Audience summary {identity} failed. Retry to rebuild it. "
                    "Cancel or Ignore keeps it unavailable; character history uses only safe source views."
                )
                if not current():
                    requeue()
                    return
                if action != "retry":
                    dirty.difference_update(keys)
                    return
                continue

    def _wake_summary_waiters(self, scene):
        waiting = self._summary_waiting.setdefault(scene, set())
        dirty = self._summary_dirty.setdefault(scene, set())
        inputs = {}
        read = PerspectiveReadContext(scene)
        for layer, identity, name in waiting.copy():
            key = (layer, identity, name)
            entry = summary_entry(scene, identity, layer)
            if entry is None or name not in scene.character_data:
                waiting.discard(key)
                continue
            if (layer, identity) not in inputs:
                inputs[layer, identity] = summary_inputs(scene, entry, layer, read=read)
            summary_input = inputs[layer, identity].get(name)
            if summary_input and summary_input.status != "pending":
                waiting.discard(key)
                dirty.add(key)

    async def repair_summary_views(self, scene):
        if not character_knowledge_enabled(scene):
            return
        dirty = self._summary_dirty.setdefault(scene, set())
        for _ in range(MAX_SUMMARY_REPAIR_PASSES):
            self._wake_summary_waiters(scene)
            if not dirty:
                break
            groups = {}
            for layer, identity, name in sorted(dirty):
                groups.setdefault((layer, identity), []).append(name)
            for (layer, identity), names in groups.items():
                keys = {(layer, identity, name) for name in names}
                dirty.difference_update(keys)
                try:
                    await self.ensure_summary_views(
                        scene,
                        identity,
                        layer,
                        audiences=names,
                        generation_options=self._summary_generation_options.get(
                            scene, {}
                        ).get((layer, identity)),
                    )
                except asyncio.CancelledError:
                    dirty.update(keys)
                    raise
        self._wake_summary_waiters(scene)
        if dirty:
            await self.schedule_audience_summaries(scene)

    async def queue_summary_views(
        self, scene, identity, layer=0, *, generation_options=None
    ):
        if not character_knowledge_enabled(scene):
            return
        entry = summary_entry(scene, identity, layer)
        if entry is None:
            return
        if generation_options is not None:
            self._summary_generation_options.setdefault(scene, {})[layer, identity] = (
                generation_options
            )
        names = set(summary_inputs(scene, entry, layer))
        self._summary_dirty.setdefault(scene, set()).update(
            (layer, identity, name) for name in names
        )
        await self.schedule_audience_summaries(scene)

    async def schedule_audience_summaries(self, scene):
        if not character_knowledge_enabled(scene):
            return
        self._wake_summary_waiters(scene)
        if not self._summary_dirty.get(scene):
            return
        task = self._summary_rebuild_tasks.get(scene)
        if task is not None and not task.done():
            return
        task = await self.rebuild_audience_summaries(scene)
        self._summary_rebuild_tasks[scene] = task
        track_evidence_task(scene, task)

    @evidence_writer
    @background_task("Updating character summaries")
    async def rebuild_audience_summaries(self, scene):
        while True:
            if self.scene is not scene:
                return
            await self.repair_summary_views(scene)
            if not self._summary_dirty.get(scene) and self.scene is scene:
                await scene.attempt_auto_save()
            self._wake_summary_waiters(scene)
            if not self._summary_dirty.get(scene):
                break
            await asyncio.sleep(0)
