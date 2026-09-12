from talemate.instance import get_agent
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.supported_facts import sanitize_fact_links
from talemate.knowledge.topics import prune_topics
from talemate.knowledge.changes import KnowledgeChange, emit_knowledge_changes


def prune_dialogue_facts(world_state, fact_ids=None):
    removed = set()
    for fact in world_state.facts.values():
        if fact.source != "dialogue" or (
            fact_ids is not None and fact.id not in fact_ids
        ):
            continue
        if fact.archive_sources or fact.contributions:
            fact.dialogue_sources = ()
            fact.restatements = max(
                0, sum(source.count for source in fact.archive_sources) - 1
            )
            fact.message_id = None
            fact.message_digest = None
            fact.archive_id = (
                fact.archive_sources[0].archive_id if fact.archive_sources else None
            )
            fact.source = "summary"
            continue
        removed.add(fact.id)
    if not removed:
        return removed
    for identity in removed:
        del world_state.facts[identity]
    world_state.knowledge = [
        edge for edge in world_state.knowledge if edge.target not in removed
    ]
    sanitize_fact_links(world_state.facts)
    prune_topics(world_state)
    return removed


def prune_invalid_dialogue_facts(scene):
    sources = {message.id: message for message in scene.history}
    # Ledger edges can outlive the dialogue message that originally inferred them.
    # Once that source is permanently deleted, keep the edge but stop treating it as
    # a transient reply-side write when cache dependencies take a history boundary.
    for edge in scene.world_state.knowledge:
        if edge.message_id is not None and edge.message_id not in sources:
            edge.message_id = None
    facts = [
        fact for fact in scene.world_state.facts.values() if fact.source == "dialogue"
    ]
    if not facts:
        return set()

    def source_digest_current(message_id, message_digest):
        message = sources.get(message_id)
        if message is None:
            return False
        digest = content_digest(message.perception_text)
        if message_digest == digest:
            return True
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

    invalid = set()
    for fact in facts:
        if not fact.dialogue_sources:
            if not source_digest_current(fact.message_id, fact.message_digest):
                invalid.add(fact.id)
            continue

        retained = tuple(
            support
            for support in fact.dialogue_sources
            if source_digest_current(support.message_id, support.message_digest)
        )
        removed_count = sum(
            support.count
            for support in fact.dialogue_sources
            if support not in retained
        )
        if retained:
            fact.dialogue_sources = retained
            fact.restatements = max(0, fact.restatements - removed_count)
            if not source_digest_current(fact.message_id, fact.message_digest):
                fact.message_id = retained[0].message_id
                fact.message_digest = retained[0].message_digest
            continue

        fact.dialogue_sources = ()
        fact.restatements = max(0, fact.restatements - removed_count)
        fact.message_id = None
        fact.message_digest = None
        if fact.archive_sources or fact.contributions:
            fact.archive_id = (
                fact.archive_sources[0].archive_id if fact.archive_sources else None
            )
            fact.source = "summary"
        else:
            invalid.add(fact.id)
    return prune_dialogue_facts(scene.world_state, invalid)


def invalidate_dialogue_facts(scene):
    facts = {
        fact.id: fact
        for fact in scene.world_state.facts.values()
        if fact.source == "dialogue"
    }
    removed = prune_invalid_dialogue_facts(scene)
    if removed:
        get_agent("summarizer").queue_fact_memory(scene, removed)
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
