"""
The knowledge step: the one place knowledge work runs, as an explicit step
before a generation or on the user's request.
"""

import asyncio
from weakref import WeakKeyDictionary

import talemate.emit.async_signals as async_signals
from talemate.agents.summarize.perceptions import eligible_passage
from talemate.instance import get_agent
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.backlog import (
    cancelled_since,
    cancels_at_start,
    counting_new_lines,
)
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import message_sources
from talemate.knowledge.revision_refresh import catch_up_revisions
from talemate.knowledge.revision_scope import StepEvents, step_events

__all__ = ["knowledge_step"]

# One step at a time per scene. The events a step produces, config.changed
# included, are sent after it is released. Not covered: a template override
# that queries the narrator would wait on this lock, and a step queued behind
# this one can run while this one's events are still being handled.
_locks = WeakKeyDictionary()


async def knowledge_step(scene) -> None:
    """
    Settle pending revisions, analyze pending passages, update the audience
    summary views and the audience index, then send the events the step
    produced.
    """
    events = StepEvents()
    token = step_events.set(events)
    cancels = cancels_at_start(scene)
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
            summarizer = get_agent("summarizer")
            with summarizer.backlog_approvals(scene):
                await _settle_and_analyze(scene, summarizer, stop_if_cancelled)
    finally:
        step_events.reset(token)
        events.closed = True
        for name, emission in events:
            await async_signals.get(name).send(emission)


async def _settle_and_analyze(scene, summarizer, stop_if_cancelled) -> None:
    # lines pushed since the last step; registered after the revisions settle,
    # so a refresh never analyzes them inside its journal. A revised one is
    # registered and counted by its own refresh.
    new = [
        message
        for message in message_sources(scene)
        if message.knowledge is None
        and eligible_passage(message)
        and (message.revision_state is None or message.revision_matches_baseline)
    ]
    with counting_new_lines(
        scene,
        {message.id: summarizer.perception_requests(scene, message) for message in new},
    ):
        await catch_up_revisions(scene)
    stop_if_cancelled()
    summarizer.register_perception_sources(scene, new)
    await summarizer.ensure_perceptions(scene, new={message.id for message in new})
    stop_if_cancelled()
    await summarizer.repair_summary_views(scene)
    stop_if_cancelled()
    memory = get_agent("memory")
    if memory.audience_index_writable(scene):
        await memory.ensure_audience_index(scene)
        stop_if_cancelled()
