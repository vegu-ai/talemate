"""
The knowledge step: the one place knowledge work runs, as an explicit step
before a generation, or as the user's Repair.
"""

import asyncio
from weakref import WeakKeyDictionary

import talemate.emit.async_signals as async_signals
from talemate.agents.summarize.perceptions import eligible_passage
from talemate.instance import get_agent
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.backlog import cancel_count, cancelled_since
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import message_sources
from talemate.knowledge.revision_refresh import catch_up_revisions, refresh_revision
from talemate.knowledge.revision_scope import StepEvents, step_events
from talemate.status import LoadingStatus

__all__ = ["knowledge_step", "repair_knowledge", "repair_passage"]

# One step at a time per scene. The events a step produces, config.changed
# included, are sent after it is released. Not covered: a template override
# that queries the narrator would wait on this lock, and a step queued behind
# this one can run while this one's events are still being handled.
_locks = WeakKeyDictionary()


async def knowledge_step(scene) -> None:
    """
    Before a generation: analyze the new lines and build the summary views of
    new archive entries. What an edit invalidated stays flagged for Repair.
    """
    await _run(scene, repair=False)


async def repair_knowledge(scene) -> None:
    """
    Rebuild everything that is not current, in dependency order: pending
    revisions and passages in history order, then summaries layer by layer.
    A Stop leaves the rest flagged.
    """
    await _run(scene, repair=True)


async def repair_passage(scene, message) -> None:
    """
    The per-message repair: settle and analyze one edited passage, then do
    the turn's own work. The views built on it stay flagged for Repair.
    """
    await _run(scene, repair=False, passage=message)


async def _run(scene, *, repair: bool, passage=None) -> None:
    events = StepEvents()
    token = step_events.set(events)
    cancels = cancel_count(scene)
    cancel_sequence = scene.cancel_sequence

    def stop_if_cancelled():
        # also catches a Stop during work that does not poll, such as the index
        if cancelled_since(scene, cancels) or scene.cancel_sequence != cancel_sequence:
            raise GenerationCancelled("Knowledge update was cancelled", by_user=True)

    try:
        async with _locks.setdefault(scene, asyncio.Lock()):
            stop_if_cancelled()
            if not character_knowledge_enabled(scene):
                await catch_up_revisions(scene)
                stop_if_cancelled()
                return
            await _settle_and_analyze(
                scene, stop_if_cancelled, repair=repair, passage=passage
            )
    finally:
        step_events.reset(token)
        events.closed = True
        for name, emission in events:
            await async_signals.get(name).send(emission)


async def _settle_and_analyze(
    scene, stop_if_cancelled, *, repair: bool, passage=None
) -> None:
    summarizer = get_agent("summarizer")
    # lines pushed since the last step; registered after the revisions settle,
    # so a refresh never analyzes them inside its journal. A revised one is
    # registered and analyzed by its own refresh.
    new = [
        message
        for message in message_sources(scene)
        if message.knowledge is None
        and eligible_passage(message)
        and (message.revision_state is None or message.revision_matches_baseline)
    ]
    # a passage done or ignored earlier in the step is not picked again, so an
    # Ignore is asked once
    attempted = set()
    if passage is not None and passage.revision_state is not None:
        await refresh_revision(scene, passage, attempted=attempted)
        stop_if_cancelled()
    await catch_up_revisions(
        scene, analyze=repair, past_failures=repair, attempted=attempted
    )
    stop_if_cancelled()
    summarizer.register_perception_sources(scene, new)
    progress = LoadingStatus(cancellable=True) if repair else None
    try:
        await summarizer.ensure_perceptions(
            scene, repair=repair, progress=progress, attempted=attempted
        )
    finally:
        if progress is not None:
            progress.done()
    stop_if_cancelled()
    await summarizer.repair_summary_views(scene, repair=repair)
    stop_if_cancelled()
    memory = get_agent("memory")
    if memory.audience_index_writable(scene):
        await memory.ensure_audience_index(scene)
        stop_if_cancelled()
