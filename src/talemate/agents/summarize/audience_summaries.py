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
    set_source_perspectives,
    source_reference,
    view_staleness,
)
from talemate.status import LoadingStatus
from talemate.knowledge.summaries import (
    SummaryInput,
    summary_entry,
    summary_inputs,
    summary_repair_work,
)

log = structlog.get_logger(__name__)


class AudienceSummaryMixin:
    def init_audience_summaries(self):
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
                view_staleness(scene, reference, name, read=read) is not None
                for name in remaining
            ):
                if view["status"] in ("ready", "omitted"):
                    values["stale"] = True
                else:
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

    async def ensure_summary_views(
        self, scene, identity, layer=0, *, generation_options=None, audiences=None
    ) -> int:
        """Build the missing views of an entry; returns how many requested a summary."""
        if not character_knowledge_enabled(scene):
            return 0
        dirty = self._summary_dirty.setdefault(scene, set())
        entry = summary_entry(scene, identity, layer)
        if entry is None:
            dirty.difference_update((layer, identity, name) for name in audiences or ())
            return 0
        read = PerspectiveReadContext(scene)
        inputs = summary_inputs(scene, entry, layer, read=read)
        reference = source_reference(scene, "summary", identity, layer=layer, read=read)
        groups = {}
        names = set(inputs) if audiences is None else set(audiences)
        for name in sorted(names):
            if name not in scene.character_data or (
                reference and view_staleness(scene, reference, name, read=read) is None
            ):
                dirty.discard((layer, identity, name))
                continue
            groups.setdefault(
                inputs.get(name, SummaryInput(status="pending")), []
            ).append(name)
        requested = 0
        for summary_input, names in groups.items():
            requested += await self._generate_summary_group(
                scene,
                entry,
                layer,
                tuple(names),
                summary_input,
                generation_options=generation_options,
            )
        return requested

    @staticmethod
    def _without_stored_text(entry, audience) -> tuple[str, ...]:
        """The names in `audience` with no stored ready or omitted view."""
        stored = {
            name: view
            for view in (entry.get("knowledge") or {}).get("views", [])
            for name in view["audience"]
        }
        return tuple(
            name
            for name in audience
            if name not in stored or stored[name]["status"] not in ("ready", "omitted")
        )

    async def _generate_summary_group(
        self, scene, entry, layer, audience, summary_input, *, generation_options=None
    ) -> bool:
        """Build one audience group's view; returns whether it sent a request."""
        identity = entry["id"]
        keys = {(layer, identity, name) for name in audience}
        dirty = self._summary_dirty.setdefault(scene, set())
        waiting = self._summary_waiting.setdefault(scene, set())
        dirty.difference_update(keys)
        waiting.difference_update(keys)
        # stored text stays readable, flagged, until a new summary replaces it
        empty = self._without_stored_text(entry, audience)
        if empty:
            self._publish_summary_group(scene, identity, layer, empty, "pending")
        if summary_input.status == "pending":
            waiting.update(keys)
            return False
        if summary_input.status == "omitted":
            self._publish_summary_group(
                scene,
                identity,
                layer,
                audience,
                "omitted",
                sources=summary_input.sources,
            )
            return False
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
            return False

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
                    return True
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
                if exc.by_user:
                    requeue()
                    raise
                if current():
                    if empty:
                        self._publish_summary_group(
                            scene,
                            identity,
                            layer,
                            empty,
                            "failed",
                            sources=summary_input.sources,
                        )
                    dirty.difference_update(keys)
                else:
                    requeue()
                return True
            except Exception as exc:
                if not current():
                    requeue()
                    return True
                if empty:
                    self._publish_summary_group(
                        scene,
                        identity,
                        layer,
                        empty,
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
                    + (
                        "Cancel or Ignore keeps its last text, out of sync until a Repair."
                        if not empty
                        else "Cancel or Ignore keeps it unavailable; character history uses only safe source views."
                    )
                )
                if not current():
                    requeue()
                    return True
                if action != "retry":
                    dirty.difference_update(keys)
                    return True
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

    async def repair_summary_views(self, scene, *, repair: bool = False):
        """
        Build the summary views that were never built (new archive entries),
        one entry at a time, including the layers they queue in turn. With
        `repair`, rebuild every summary view that is not current, layer by
        layer; a view stays flagged until its rebuild succeeds.
        """
        if not character_knowledge_enabled(scene):
            return
        progress = LoadingStatus(cancellable=True)
        try:
            if repair:
                await self._repair_all_summary_views(scene, progress)
            else:
                await self._build_new_summary_views(scene, progress)
        finally:
            progress.done()
        self._wake_summary_waiters(scene)

    async def _build_new_summary_views(self, scene, progress):
        dirty = self._summary_dirty.setdefault(scene, set())
        while True:
            self._wake_summary_waiters(scene)
            # a view with stored text, or one that failed, waits for a repair
            dirty.difference_update(
                key for key in list(dirty) if not self._never_built(scene, *key)
            )
            if not dirty:
                break
            queued = set(dirty)
            groups = {}
            for layer, identity, name in sorted(queued):
                groups.setdefault((layer, identity), []).append(name)
            requested = 0
            for (layer, identity), names in groups.items():
                progress.max_steps = progress.current_step + len(
                    {(layer, identity) for layer, identity, _ in dirty}
                )
                progress("Updating character summaries")
                # each group takes its keys off the queue as it starts, so
                # a cancel leaves the groups that have not started queued
                requested += await self.ensure_summary_views(
                    scene,
                    identity,
                    layer,
                    audiences=names,
                    generation_options=self._summary_options(scene, layer, identity),
                )
            if not requested and dirty >= queued:
                # every entry went back on the queue before its request
                # (the scene was released, or its inputs did not hold); a
                # later step retries them
                break

    async def _repair_all_summary_views(self, scene, progress):
        attempted = set()
        progress.max_steps = len(summary_repair_work(scene))
        while True:
            work = summary_repair_work(scene, skip=attempted)
            if not work:
                break
            layer, identity, names = work[0]
            attempted.update((layer, identity, name) for name in names)
            progress.max_steps = progress.current_step + len(work)
            progress("Repairing character summaries")
            await self.ensure_summary_views(
                scene,
                identity,
                layer,
                audiences=names,
                generation_options=self._summary_options(scene, layer, identity),
            )

    def _summary_options(self, scene, layer, identity):
        return self._summary_generation_options.get(scene, {}).get((layer, identity))

    @staticmethod
    def _never_built(scene, layer, identity, name) -> bool:
        entry = summary_entry(scene, identity, layer)
        if entry is None:
            return True
        return all(
            view["status"] == "pending"
            for view in (entry.get("knowledge") or {}).get("views", [])
            if name in view["audience"]
        )

    async def queue_summary_views(
        self, scene, identity, layer=0, *, generation_options=None
    ):
        self.queue_summary_entry(
            scene, identity, layer, generation_options=generation_options
        )

    def queue_summary_entry(self, scene, identity, layer=0, *, generation_options=None):
        """Queue an entry's views; its generation options also serve a later Repair."""
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
