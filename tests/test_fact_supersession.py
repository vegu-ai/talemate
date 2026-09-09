from unittest.mock import AsyncMock

import pytest

from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.absence import absence_facts
from talemate.knowledge.chronology import (
    DAY,
    ranked_facts,
    ranked_fact_documents,
    render_fact,
)
from talemate.knowledge.facts import facts_for_entry, previous_facts
from talemate.knowledge.graph import facts_about, bucket, superseded_chain
from talemate.knowledge.perspectives import add_disclosure, source_reference
from talemate.knowledge.schema import Fact, ParsedFact, Topic
from talemate.knowledge.standard_analysis import (
    standard_analysis_context,
    standard_analysis_fingerprint,
)
from talemate.knowledge.supported_facts import contributions_for_source
from talemate.knowledge.topics import known_facts
from talemate.prompts import Prompt


@pytest.fixture(params=["legacy", "perception"])
def fact_scene(scene, request, monkeypatch):
    scene.knowledge_eligibility = request.param
    scene.ts = 10 * DAY
    scene.active_characters = []
    scene.character_data = {name: Character(name=name) for name in ("Mara", "Bob")}
    monkeypatch.setattr(
        Prompt,
        "request",
        AsyncMock(side_effect=AssertionError("Unexpected generation")),
    )
    return scene


async def record(scene, identity, text, audience=("Mara", "Bob"), supersedes=None):
    fact = Fact(
        id=identity,
        text=text,
        present=list(audience),
        subjects=["sextant"],
        ts=scene.ts,
        supersedes=supersedes,
        archive_id="opening",
    )
    if scene.knowledge_eligibility == "perception":
        disclosure = add_disclosure(scene, text, audience)
        reference = source_reference(scene, "disclosure", disclosure.id)
        fact.contributions = await contributions_for_source(
            scene,
            reference,
            audience,
            [ParsedFact(text=text, subjects=["sextant"], supersedes=supersedes)],
        )
    scene.world_state.facts[identity] = fact
    scene.ts += DAY
    return fact


async def pair(scene, audience=("Mara", "Bob")):
    old = await record(scene, "F1", "Mara keeps the sextant in the drawer.")
    new = await record(
        scene,
        "F2",
        "Mara moved the sextant to her bag.",
        audience=audience,
        supersedes=old.id,
    )
    return old, new


@pytest.mark.asyncio
async def test_sextant_pair_is_one_prompt_fact_and_access_is_unchanged(fact_scene):
    old, new = await pair(fact_scene)
    before = fact_scene.world_state.model_dump()
    selected = facts_about(fact_scene, "sextant", character="Mara")
    assert [fact.id for fact in selected] == [new.id]
    line = render_fact(fact_scene, selected[0])
    assert "(formerly: Mara keeps the sextant in the drawer.)" in line
    assert line.count("ago)") == 1
    assert old.id not in line
    assert "formerly" not in render_fact(fact_scene, selected[0], extraction=True)
    assert [fact.id for fact, _ in bucket(fact_scene, "Mara")] == [old.id, new.id]
    assert facts_for_entry(fact_scene, "opening") == [old, new]
    assert [fact.id for fact in superseded_chain(fact_scene, new.id)] == [old.id]
    assert fact_scene.world_state.model_dump() == before
    assert "formerly" not in selected[0].model_dump()


@pytest.mark.asyncio
async def test_chain_keeps_only_latest_and_one_predecessor(fact_scene):
    old, middle = await pair(fact_scene)
    latest = await record(
        fact_scene, "F3", "Mara gave the sextant to the captain.", supersedes=middle.id
    )
    selected = facts_about(fact_scene, "sextant", character="Mara")
    assert [fact.id for fact in selected] == [latest.id]
    line = render_fact(fact_scene, selected[0])
    assert middle.text in line
    assert old.text not in line
    assert line.count("formerly:") == 1


@pytest.mark.asyncio
async def test_viewer_keeps_old_fact_until_they_know_successor(fact_scene):
    old, new = await pair(fact_scene, audience=("Mara",))
    assert [
        fact.id for fact in facts_about(fact_scene, "sextant", character="Mara")
    ] == [new.id]
    bob = facts_about(fact_scene, "sextant", character="Bob")
    assert [fact.id for fact in bob] == [old.id]
    assert new.text not in render_fact(fact_scene, bob[0])
    assert "formerly:" not in render_fact(fact_scene, bob[0])


@pytest.mark.asyncio
async def test_successor_outside_query_still_suppresses_old_without_injecting_it(
    fact_scene,
):
    old, _ = await pair(fact_scene)
    assert ranked_facts(fact_scene, [old], character="Mara") == []


@pytest.mark.asyncio
async def test_formerly_setting_changes_rendering_only(fact_scene):
    old, new = await pair(fact_scene)
    get_agent("summarizer").actions["fact_chronology"].config[
        "show_formerly"
    ].value = False
    selected = facts_about(fact_scene, "sextant", character="Mara")
    assert [fact.id for fact in selected] == [new.id]
    assert old.text not in render_fact(fact_scene, selected[0])


@pytest.mark.asyncio
async def test_known_fact_inspection_keeps_both_records(fact_scene):
    old, new = await pair(fact_scene)
    prompts, total = known_facts(fact_scene, "Mara")
    assert [fact.id for fact in prompts] == [new.id]
    assert total == 2
    inspection = await fact_scene.world_state_manager.get_character_knowledge("Mara")
    assert {fact.id for fact in inspection.known_facts} == {old.id, new.id}
    assert all("formerly:" not in fact.text for fact in inspection.known_facts)


@pytest.mark.asyncio
async def test_standard_analysis_absence_and_ledger_candidates(scene, monkeypatch):
    scene.character_data = {
        "Mara": Character(name="Mara"),
        "Bob": Character(name="Bob"),
    }
    scene.active_characters = []
    scene.ts = 10 * DAY
    old, new = await pair(scene, audience=("Mara",))
    request = AsyncMock(side_effect=AssertionError("Unexpected generation"))
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveScene(scene):
        absence = await absence_facts(scene, "Bob")
        assert [fact.id for fact in absence] == [new.id]
        context = await standard_analysis_context(
            scene, scene.character_data["Mara"], 3000
        )
    assert "[F1]" not in context["text"]
    assert "[F2]" in context["text"]
    assert "formerly:" in context["text"]
    assert [fact.id for fact in previous_facts(scene)] == [new.id, old.id]
    assert all(
        "formerly:" not in render_fact(scene, fact, extraction=True)
        for fact in previous_facts(scene)
    )
    request.assert_not_awaited()


def test_formerly_setting_invalidates_standard_analysis(scene):
    scene.character_data = {"Mara": Character(name="Mara")}
    character = scene.character_data["Mara"]
    before = standard_analysis_fingerprint(scene, character, "conversation", 3000)
    get_agent("summarizer").actions["fact_chronology"].config[
        "show_formerly"
    ].value = False
    assert before != standard_analysis_fingerprint(
        scene, character, "conversation", 3000
    )


@pytest.mark.asyncio
async def test_memory_selection_respects_viewer_and_preserves_raw_text(fact_scene):
    old, new = await pair(fact_scene, audience=("Mara",))
    docs = [
        MemoryDocument(fact.text, {"typ": "fact"}, fact.id, fact.text)
        for fact in (old, new)
    ]
    selected = ranked_fact_documents(fact_scene, docs, character="Mara")
    assert [doc.id for doc in selected] == [new.id]
    assert selected[0].raw == new.text
    assert "formerly:" in str(selected[0])
    bob = ranked_fact_documents(fact_scene, docs[:1], character="Bob")
    assert [doc.id for doc in bob] == [old.id]


@pytest.mark.asyncio
async def test_formerly_survives_memory_merge_rerank_and_cache(fact_scene, monkeypatch):
    from types import SimpleNamespace

    scene = fact_scene
    old, new = await pair(scene)
    memory = get_agent("memory")
    documents = [
        MemoryDocument(f.text, {"typ": "fact"}, f.id, f.text) for f in (old, new)
    ]
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=documents))
    monkeypatch.setattr(type(memory), "retrieval_rerank", property(lambda self: True))
    monkeypatch.setattr(
        type(memory), "reranker", property(lambda self: SimpleNamespace(error=None))
    )
    monkeypatch.setattr(
        memory, "rerank", AsyncMock(side_effect=lambda queries, docs: docs)
    )
    with ActiveScene(scene):
        result = await memory._multi_query(
            ["sextant", "drawer"], iterate=5, ranking_viewer="Bob"
        )
    assert [doc.id for doc in result] == [new.id]
    assert result[0].raw == new.text
    assert result[0].fact_predecessor.id == old.id
    assert str(result[0]).count("formerly:") == 1
    assert old.text in str(result[0])
    cached = ranked_fact_documents(scene, result, character="Bob")
    assert cached == result
    get_agent("summarizer").actions["fact_chronology"].config[
        "show_formerly"
    ].value = False
    assert "formerly:" not in str(
        ranked_fact_documents(scene, cached, character="Bob")[0]
    )
    get_agent("summarizer").actions["fact_chronology"].config[
        "show_formerly"
    ].value = True
    assert "formerly:" in str(ranked_fact_documents(scene, cached, character="Bob")[0])


@pytest.mark.asyncio
async def test_standard_rag_cache_hit_and_miss_keep_bobs_only_version(
    scene, monkeypatch
):
    from talemate.agents.context import ActiveAgent
    from talemate.scene_message import NarratorMessage

    scene.character_data = {name: Character(name=name) for name in ("Mara", "Bob")}
    scene.active_characters = []
    scene.ts = 10 * DAY
    old, new = await pair(scene, audience=("Mara",))
    scene.rag_cache = {}
    scene.history = [
        NarratorMessage(
            message="Bob studies the sextant in the drawer.", present=["Bob"]
        )
    ]
    memory = get_agent("memory")
    get = AsyncMock(
        return_value=[
            MemoryDocument(f.text, {"typ": "fact"}, f.id, f.text) for f in (old,)
        ]
    )
    monkeypatch.setattr(memory, "get", get)
    monkeypatch.setattr(
        memory,
        "audience_operation",
        AsyncMock(side_effect=AssertionError("Standard entered audience retrieval")),
    )
    conversation = get_agent("conversation")
    conversation.actions["use_long_term_memory"].config["cache"].value = True
    conversation.actions["use_long_term_memory"].config[
        "retrieval_method"
    ].value = "queries"
    conversation.actions["character_knowledge"].config["memory_pass"].value = False
    monkeypatch.setattr(
        get_agent("world_state"),
        "analyze_text_and_extract_context_via_queries",
        AsyncMock(return_value=[]),
    )
    with ActiveScene(scene), ActiveAgent(conversation, conversation.rag_build):
        live = await conversation.rag_build(scene.character_data["Bob"])
        calls = get.await_count
        cached = await conversation.rag_build(scene.character_data["Bob"])
    assert [doc.id for doc in live] == [old.id]
    assert cached == live
    assert get.await_count == calls
    assert all("viewer" not in call.kwargs for call in get.await_args_list)


@pytest.mark.asyncio
async def test_relationship_node_uses_one_viewer_for_facts_and_text(fact_scene):
    from _node_test_helpers import run_node
    from talemate.game.engine.nodes.knowledge import RelationshipTimeline

    old, new = await pair(fact_scene, audience=("Mara",))
    output = await run_node(
        RelationshipTimeline(),
        scene=fact_scene,
        inputs={"a": "Mara", "b": "sextant", "character": "Bob"},
    )
    assert [fact["id"] for fact in output["facts"]] == [old.id]
    assert old.text in output["text"]
    assert new.text not in output["text"]


@pytest.mark.asyncio
async def test_rankers_reuse_the_bucket_they_already_built(fact_scene, monkeypatch):
    from unittest.mock import Mock
    from talemate.knowledge import topics, graph

    old, new = await pair(fact_scene)
    known = Mock(wraps=topics.known_bucket)
    monkeypatch.setattr(topics, "known_bucket", known)
    topics.known_facts(fact_scene, "Bob")
    assert known.call_count == 1
    known.reset_mock()
    ranked_fact_documents(
        fact_scene,
        [MemoryDocument(f.text, {"typ": "fact"}, f.id, f.text) for f in (old, new)],
        character="Bob",
    )
    assert known.call_count == 1
    known.reset_mock()
    bucket_spy = Mock(wraps=graph.bucket)
    monkeypatch.setattr(graph, "bucket", bucket_spy)
    assert [fact.id for fact in graph.facts_about(fact_scene, "sextant", "Bob")] == [
        new.id
    ]
    assert bucket_spy.call_count == 1
    known.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("predecessor_known", [True, False])
async def test_standard_topic_first_preserves_formerly_through_rerank_and_cache(
    scene, monkeypatch, predecessor_known
):
    from types import SimpleNamespace
    import numpy as np

    scene.character_data = {name: Character(name=name) for name in ("Mara", "Bob")}
    scene.active_characters = []
    scene.ts = 10 * DAY
    old = await record(
        scene,
        "F1",
        "Mara keeps the sextant in the drawer.",
        audience=("Mara", "Bob") if predecessor_known else ("Mara",),
    )
    new = await record(
        scene, "F2", "Mara moved the sextant to her bag.", supersedes=old.id
    )
    scene.world_state.topics["T1"] = Topic(
        id="T1", name="sextant", fact_ids=[old.id, new.id]
    )
    memory = get_agent("memory")
    memory.topic_centroids = {"T1": np.array([1.0, 0.0])}
    memory.actions["topics"].enabled = True
    monkeypatch.setattr(
        memory, "embed_text", AsyncMock(return_value=np.array([1.0, 0.0]))
    )
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    fetch = AsyncMock(
        return_value={
            new.id: MemoryDocument(new.text, {"typ": "fact"}, new.id, new.text)
        }
    )
    monkeypatch.setattr(memory, "get_document", fetch)
    monkeypatch.setattr(type(memory), "retrieval_rerank", property(lambda self: True))
    monkeypatch.setattr(
        type(memory), "reranker", property(lambda self: SimpleNamespace(error=None))
    )
    rerank = AsyncMock(side_effect=lambda queries, docs: docs)
    monkeypatch.setattr(memory, "rerank", rerank)
    with ActiveScene(scene):
        result = await memory._multi_query(
            ["sextant"], iterate=5, topic_first=True, ranking_viewer="Bob"
        )
    fetch.assert_awaited_once_with([new.id])
    rerank.assert_awaited_once()
    for documents in (result, ranked_fact_documents(scene, result, character="Bob")):
        assert [doc.id for doc in documents] == [new.id]
        assert documents[0].raw == new.text
        assert str(documents[0]).count("formerly:") == int(predecessor_known)
        assert (old.text in str(documents[0])) is predecessor_known
        predecessor = documents[0].fact_predecessor
        assert (predecessor.id if predecessor else None) == (
            old.id if predecessor_known else None
        )
