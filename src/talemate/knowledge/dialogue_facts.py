from talemate.instance import get_agent
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.supported_facts import sanitize_fact_links
from talemate.knowledge.topics import prune_topics
from talemate.knowledge.changes import KnowledgeChange, emit_knowledge_changes


def prune_dialogue_facts(world_state, fact_ids=None):
    removed = {
        fact.id
        for fact in world_state.facts.values()
        if fact.source == "dialogue" and (fact_ids is None or fact.id in fact_ids)
    }
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
    facts = [
        fact for fact in scene.world_state.facts.values() if fact.source == "dialogue"
    ]
    if not facts:
        return set()
    sources = {message.id: message for message in scene.history}
    invalid = {
        fact.id
        for fact in facts
        if fact.message_id not in sources
        or fact.message_digest
        != content_digest(sources[fact.message_id].perception_text)
    }
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
