"""
Facts follow their message: removal when the message goes, unbinding for
the facts that outlive it, and the load-time drop of records from before
message binding existed.
"""

from typing import TYPE_CHECKING

import structlog

from talemate.instance import get_agent
from talemate.knowledge.changes import KnowledgeChange, emit_knowledge_changes
from talemate.knowledge.facts import (
    _drop_restatements,
    _promote_restatement,
    fact_is_independent,
)
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.supported_facts import sanitize_fact_links
from talemate.knowledge.topics import prune_topics

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "binding_state",
    "detach_message_fact",
    "remove_message_facts",
    "rebind_message_facts",
    "prune_missing_message_facts",
    "invalidate_message_facts",
    "prune_legacy_facts",
]

log = structlog.get_logger("talemate.knowledge.message_facts")


def detach_message_fact(world_state, fact, *, edges: bool = True) -> bool:
    """
    Take the message out of a fact. True when the fact survives: through a
    restatement that becomes its origin, or because the author made it
    independent (an edit; with `edges`, a hand-granted edge too). An unbound
    fact is the author's from then on: the shape the load-time prune keeps.
    """
    if _promote_restatement(fact):
        return True
    if fact_is_independent(world_state, fact, edges=edges):
        fact.message_id = None
        fact.message_digest = None
        fact.archive_id = None
        fact.source = "manual"
        return True
    return False


def binding_state(fact) -> tuple:
    """What a removal can change on a fact without removing it."""
    return (
        fact.message_id,
        fact.message_digest,
        fact.archive_id,
        fact.source,
        fact.ts,
        tuple(fact.present or ()) if fact.present is not None else None,
        fact.restated_by,
    )


def _finish_removal(world_state, removed: set[str]) -> set[str]:
    if not removed:
        return removed
    for identity in removed:
        world_state.facts.pop(identity, None)
    world_state.knowledge = [
        edge for edge in world_state.knowledge if edge.target not in removed
    ]
    sanitize_fact_links(world_state.facts)
    prune_topics(world_state)
    return removed


def remove_message_facts(world_state, message_id: int) -> set[str]:
    """
    Drop the message from every fact: restatements by it go, facts that came
    from it are removed unless something else keeps them. Returns the ids of
    the removed facts.
    """
    removed = set()
    for fact in list(world_state.facts.values()):
        # a perspective fact follows its views, not the message directly
        if fact.contributions:
            continue
        _drop_restatements(fact, lambda item: item.message_id == message_id)
        if fact.message_id != message_id:
            continue
        if not detach_message_fact(world_state, fact):
            removed.add(fact.id)
    return _finish_removal(world_state, removed)


def rebind_message_facts(world_state, message_id: int, digest: str) -> set[str]:
    """
    Bind the facts of a message to its current text: the rule for an edit
    that no extraction follows. Returns the ids of the facts that changed.
    """
    changed = set()
    for fact in world_state.facts.values():
        if fact.contributions:
            continue
        if fact.message_id == message_id and fact.message_digest != digest:
            fact.message_digest = digest
            changed.add(fact.id)
        for item in fact.restated_by:
            if item.message_id == message_id and item.message_digest != digest:
                item.message_digest = digest
                changed.add(fact.id)
    return changed


def _message_current(scene: "Scene", message_id, message_digest) -> bool:
    message = scene.get_message(message_id)
    if message is None:
        return False
    if message_digest == content_digest(message.perception_text):
        return True
    # a pending revision keeps the fact until the refresh re-extracts it
    state = getattr(message, "revision_state", None)
    return bool(
        state
        and not message.revision_matches_baseline
        and message_digest
        in {
            state.baseline_digest,
            (state.refresh_journal or {}).get("baseline_content_digest"),
        }
    )


def prune_missing_message_facts(scene: "Scene", *, edges: bool = True) -> set[str]:
    """
    Facts whose message is gone, or whose message changed with no revision
    pending, lose it; the ones nothing else supports are removed. A reset of
    the whole history passes `edges=False`: a hand grant keeps a fact through
    the loss of one message, not through the loss of the story it came from.
    """
    world_state = scene.world_state
    sources = {message.id for message in scene.history}
    # Ledger edges can outlive the message that inferred them. Once that
    # source is gone, keep the edge but stop treating it as a transient
    # reply-side write when cache dependencies take a history boundary.
    for edge in world_state.knowledge:
        if edge.message_id is not None and edge.message_id not in sources:
            edge.message_id = None
    removed = set()
    for fact in list(world_state.facts.values()):
        if fact.contributions:
            continue
        _drop_restatements(
            fact,
            lambda item: item.message_id is not None
            and not _message_current(scene, item.message_id, item.message_digest),
        )
        if fact.message_id is None:
            continue
        if _message_current(scene, fact.message_id, fact.message_digest):
            continue
        if not detach_message_fact(world_state, fact, edges=edges):
            removed.add(fact.id)
    return _finish_removal(world_state, removed)


def invalidate_message_facts(scene: "Scene") -> set[str]:
    facts = {fact.id: fact for fact in scene.world_state.facts.values()}
    before = {identity: binding_state(fact) for identity, fact in facts.items()}
    removed = prune_missing_message_facts(scene)
    # a promoted or unbound fact changed too: its document follows
    changed = removed | {
        identity
        for identity, fact in scene.world_state.facts.items()
        if identity in before and binding_state(fact) != before[identity]
    }
    if changed:
        get_agent("summarizer").queue_fact_memory(scene, changed)
    if removed:
        emit_knowledge_changes(
            scene,
            [
                KnowledgeChange(character=name, target=identity, kind="revoke")
                for identity in removed
                for name in facts[identity].present or []
            ],
            labels={identity: facts[identity].text for identity in removed},
        )
        scene.emit_status()
    return removed


def prune_legacy_facts(world_state: dict, archived_history: list[dict]) -> set[str]:
    """
    Drop, from a serialized world state, the fact records written before
    facts were bound to messages: dialogue facts, contributions from message
    views, and extraction facts of a summarized span without a message id.
    Facts that have no message by design (manual, offscreen, disclosure and
    static-entry facts) stay. Returns the removed fact ids.
    """
    facts = world_state.get("facts") or {}
    static_ids = {
        entry.get("id")
        for entry in archived_history
        if entry.get("end") is None and entry.get("id")
    }
    removed = set()
    for identity, values in list(facts.items()):
        values.pop("dialogue_sources", None)
        values.pop("archive_sources", None)
        contributions = [
            item
            for item in values.get("contributions") or []
            if (item.get("source") or {}).get("kind") != "message"
        ]
        if len(contributions) != len(values.get("contributions") or []):
            values["contributions"] = contributions
        source = values.get("source", "summary")
        if source == "dialogue":
            removed.add(identity)
        elif source in ("perspective", "disclosure"):
            if not contributions:
                removed.add(identity)
        elif source == "summary" and values.get("message_id") is None:
            if values.get("archive_id") not in static_ids:
                removed.add(identity)
    if not removed:
        return removed
    log.warning("dropping facts recorded before message binding", count=len(removed))
    world_state["facts"] = {
        key: value for key, value in facts.items() if key not in removed
    }
    world_state["knowledge"] = [
        edge
        for edge in world_state.get("knowledge") or []
        if edge.get("target") not in removed
    ]
    for fact in world_state["facts"].values():
        if fact.get("supersedes") in removed:
            fact["supersedes"] = None
        for contribution in fact.get("contributions") or []:
            if contribution.get("supersedes") in removed:
                contribution["supersedes"] = None
    for topic in (world_state.get("topics") or {}).values():
        topic["fact_ids"] = [
            fact_id for fact_id in topic.get("fact_ids", []) if fact_id not in removed
        ]
    return removed
