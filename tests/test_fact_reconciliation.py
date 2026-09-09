from unittest.mock import AsyncMock

import pytest

import test_supported_facts
import test_fact_evidence
from test_fact_evidence import evidence_message
from talemate.knowledge.fact_reconciliation import fact_knowledge_reason
from talemate.knowledge.graph import bucket
from talemate.knowledge.perspectives import (
    select_character_view,
    set_source_perspectives,
)
from talemate.knowledge.schema import ParsedFact, Topic
from talemate.knowledge.supported_facts import replace_source_facts, prune_contributions
from talemate.knowledge.topics import coverage, topic_facts

supported_scene = test_supported_facts.supported_scene


passage_embeddings = test_fact_evidence.passage_embeddings


async def extract(scene, source, name, text, span=0, **kwargs):
    evidence = f"M{source.id}R{source.revision}S{span}" if span is not None else None
    return await replace_source_facts(
        scene,
        [(source, (name,), [ParsedFact(text=text, evidence_id=evidence, **kwargs)])],
    )


@pytest.mark.asyncio
async def test_present_ready_audience_gets_shared_fact_and_count(supported_scene):
    scene, summarizer, memory = supported_scene
    message, source = evidence_message(scene)
    await extract(
        scene, source, "Alice", "Alice rang the bell.", subjects=["Alice", "Bob"]
    )
    (fact,) = scene.world_state.facts.values()
    (bob,) = bucket(scene, "Bob")
    assert bob[0].id == fact.id
    assert bob[0].contributions[0].inferred_from is not None
    scene.world_state.topics["T1"] = Topic(id="T1", name="Bell", fact_ids=[fact.id])
    (row,) = topic_facts(scene, "Bob", "T1")
    (count,) = coverage(scene, "Bob")
    assert (row.known, row.reason, count.known, count.total) == (
        True,
        "Inferred from shared evidence",
        1,
        1,
    )
    assert memory.embed_texts.await_count == 1
    memory.compare_strings.assert_not_awaited()
    memory.compare_string_lists.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_span_stays_private_even_when_present_character_is_subject(
    supported_scene,
):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    await extract(
        scene,
        source,
        "Bob",
        "Bob fears what Alice will do.",
        span=1,
        subjects=["Alice", "Bob"],
    )
    (fact,) = scene.world_state.facts.values()
    assert bucket(scene, "Alice") == []
    assert fact_knowledge_reason(scene, fact, "Alice") == "Not in their view"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, present, reason",
    [
        ("ready", False, "Not present"),
        ("pending", True, "View pending or failed"),
        ("failed", True, "View pending or failed"),
        ("omitted", True, "Private moment"),
    ],
)
async def test_unready_or_absent_audience_gets_no_inference(
    supported_scene, status, present, reason
):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    message.present = ["Alice", "Bob"] if present else ["Alice"]
    outputs = [
        view.model_dump(exclude={"revision"}) for view in message.knowledge.views
    ]
    outputs[1].update(
        status=status,
        text="A bell." if status == "ready" else None,
        evidence_spans=[0] if status == "ready" else [],
    )
    set_source_perspectives(scene, "message", message.id, outputs)
    await extract(scene, source, "Alice", "Alice rang the bell.")
    (fact,) = scene.world_state.facts.values()
    assert bucket(scene, "Bob") == []
    assert fact_knowledge_reason(scene, fact, "Bob") == reason


@pytest.mark.asyncio
async def test_missing_fact_evidence_does_not_authorize_sharing(supported_scene):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rang the bell.", span=None)
    (fact,) = scene.world_state.facts.values()
    assert bucket(scene, "Bob") == []
    assert fact_knowledge_reason(scene, fact, "Bob") == "Not in their view"


@pytest.mark.asyncio
async def test_rebuild_is_idempotent_and_removing_donor_fact_removes_inference(
    supported_scene,
):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rang the bell.")
    before = scene.world_state.model_dump()
    await extract(scene, source, "Alice", "Alice rang the bell.")
    assert scene.world_state.model_dump() == before
    await replace_source_facts(scene, [(source, ("Alice",), [])])
    assert not scene.world_state.facts
    assert bucket(scene, "Bob") == []


@pytest.mark.asyncio
async def test_later_audience_batch_keeps_and_refreshes_inferred_facts(supported_scene):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await replace_source_facts(scene, [(source, ("Bob",), [])])
    assert len(bucket(scene, "Bob")) == 1
    assert len(scene.world_state.facts) == 1


@pytest.mark.asyncio
async def test_near_duplicate_views_merge_without_replacing_direct_wording(
    supported_scene, monkeypatch
):
    scene, _, memory = supported_scene
    _, source = evidence_message(scene)
    matcher = AsyncMock(return_value=0.01)
    monkeypatch.setattr(
        "talemate.knowledge.fact_comparisons.FactComparisons.distance", matcher
    )
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await extract(scene, source, "Bob", "The bell was rung by Alice.")
    assert len(scene.world_state.facts) == 1
    assert bucket(scene, "Alice")[0][0].text == "Alice rang the bell."
    assert bucket(scene, "Bob")[0][0].text == "The bell was rung by Alice."
    assert matcher.await_count >= 1
    before = scene.world_state.model_dump()
    await extract(scene, source, "Alice", "Alice rang the bell.")
    assert scene.world_state.model_dump() == before


@pytest.mark.asyncio
async def test_donor_view_change_revokes_its_inference(supported_scene):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rang the bell.")
    outputs = [
        view.model_dump(exclude={"revision"}) for view in message.knowledge.views
    ]
    outputs[0].update(status="omitted", text=None, evidence_spans=[])
    set_source_perspectives(scene, "message", message.id, outputs)
    assert bucket(scene, "Bob") == []


@pytest.mark.asyncio
async def test_pruning_donor_keeps_recipients_independent_fact(supported_scene):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await extract(scene, source, "Bob", "Bob fears the signal.", span=1)
    donor = select_character_view(scene, source, "Alice").source
    prune_contributions(scene.world_state, [donor])
    assert [fact.text for fact, _ in bucket(scene, "Bob")] == ["Bob fears the signal."]


@pytest.mark.asyncio
async def test_inference_preserves_supersession_when_recipient_knows_predecessor(
    supported_scene,
):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice holds the bell.")
    (previous,) = scene.world_state.facts.values()
    await extract(scene, source, "Bob", "Bob holds the bell.", supersedes=previous.id)
    newer = next(
        fact for fact in scene.world_state.facts.values() if fact.id != previous.id
    )
    assert newer.supersedes == previous.id
    assert (
        next(
            fact for fact, _ in bucket(scene, "Alice") if fact.id == newer.id
        ).supersedes
        == previous.id
    )


@pytest.mark.asyncio
async def test_merge_remaps_links_and_topic_membership(supported_scene, monkeypatch):
    scene, _, memory = supported_scene
    _, source = evidence_message(scene)
    monkeypatch.setattr(
        "talemate.knowledge.fact_comparisons.FactComparisons.distance",
        AsyncMock(return_value=0.9),
    )
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await extract(scene, source, "Bob", "The bell was rung by Alice.")
    first, second = scene.world_state.facts.values()
    from talemate.knowledge.schema import Fact

    scene.world_state.facts["F99"] = Fact(
        id="F99", text="The bell fell silent.", supersedes=second.id
    )
    scene.world_state.fact_counter = 99
    scene.world_state.topics["T1"] = Topic(
        id="T1", name="Bell", fact_ids=[first.id, second.id]
    )
    monkeypatch.setattr(
        "talemate.knowledge.fact_comparisons.FactComparisons.distance",
        AsyncMock(return_value=0.01),
    )
    await extract(scene, source, "Bob", "The bell was rung by Alice.")
    assert scene.world_state.facts["F99"].supersedes == first.id
    assert scene.world_state.topics["T1"].fact_ids == [first.id]


@pytest.mark.asyncio
async def test_miscited_private_plan_never_reaches_public_recipient(supported_scene):
    scene, _, memory = supported_scene
    _, source = evidence_message(scene, private="Bob plans to betray Alice.")
    await extract(
        scene, source, "Bob", "Bob plans to betray Alice.", subjects=["Alice", "Bob"]
    )
    assert bucket(scene, "Alice") == []
    assert bucket(scene, "Bob")[0][0].text == "Bob plans to betray Alice."
    memory.compare_strings.assert_not_awaited()
    fact = next(iter(scene.world_state.facts.values()))
    assert fact.contributions[0].evidence is not None
    assert fact.contributions[0].evidence_competitors
    assert fact_knowledge_reason(scene, fact, "Alice") == "Citation not supported"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "citations,subjects,shared",
    [([], ["Bob"], False), ([], [], False), (None, ["Bob"], False)],
)
async def test_public_subject_requires_cited_current_view(
    supported_scene, citations, subjects, shared
):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    outputs = [
        view.model_dump(exclude={"revision"}) for view in message.knowledge.views
    ]
    outputs[1]["evidence_spans"] = citations
    set_source_perspectives(scene, "message", message.id, outputs)
    await extract(scene, source, "Alice", "Alice rings the bell.", subjects=subjects)
    assert bool(bucket(scene, "Bob")) is shared


@pytest.mark.asyncio
async def test_unknown_presence_does_not_cut_supported_inference(supported_scene):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    message.present = None
    await extract(scene, source, "Alice", "Alice rings the bell.")
    assert len(bucket(scene, "Bob")) == 1


@pytest.mark.asyncio
async def test_same_event_with_different_citations_collapses_exactly(supported_scene):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rings the bell.")
    await extract(scene, source, "Bob", "Alice rings the bell.", span=1)
    assert len(scene.world_state.facts) == 1
    assert len(bucket(scene, "Alice")) == len(bucket(scene, "Bob")) == 1


@pytest.mark.asyncio
async def test_near_match_allows_intersecting_subject_sets_and_does_not_infer(
    supported_scene,
):
    scene, _, memory = supported_scene
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rings the bell.", subjects=["Alice"])
    memory.compare_strings.reset_mock()
    await extract(
        scene, source, "Bob", "The bell is rung by Alice.", subjects=["Alice", "bell"]
    )
    assert len(scene.world_state.facts) == 1
    assert all(
        item.inferred_from is None
        for fact in scene.world_state.facts.values()
        for item in fact.contributions
    )
    memory.compare_strings.assert_not_awaited()


@pytest.mark.asyncio
async def test_reason_distinguishes_missing_citation_stale_revision_and_pending(
    supported_scene,
):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    await extract(scene, source, "Bob", "Bob fears the signal.", span=1)
    fact = next(iter(scene.world_state.facts.values()))
    assert fact_knowledge_reason(scene, fact, "Alice") == "Not in their view"
    item = fact.contributions[0]
    stale = fact.model_copy(
        update={
            "contributions": (
                item.model_copy(
                    update={
                        "evidence": item.evidence.model_copy(update={"revision": 99})
                    }
                ),
            )
        }
    )
    assert fact_knowledge_reason(scene, stale, "Alice") == "View being rebuilt"
    outputs = [
        view.model_dump(exclude={"revision"}) for view in message.knowledge.views
    ]
    outputs[0].update(status="pending", text=None, evidence_spans=[])
    set_source_perspectives(scene, "message", message.id, outputs)
    assert fact_knowledge_reason(scene, stale, "Alice") == "View pending or failed"


def test_topics_share_one_read_context_and_coverage_cache(supported_scene, monkeypatch):
    from talemate.knowledge import topics
    from unittest.mock import Mock

    scene, _, _ = supported_scene
    for number in range(2):
        scene.world_state.topics[str(number)] = Topic(
            id=str(number), name="Bell", fact_ids=[]
        )
    constructor = Mock(wraps=topics.PerspectiveReadContext)
    monkeypatch.setattr(topics, "PerspectiveReadContext", constructor)
    monkeypatch.setattr(topics, "_known", lambda *args: [])
    rows = Mock(wraps=topics.topic_facts)
    monkeypatch.setattr(topics, "topic_facts", rows)
    topics.topics_facts(scene, "Alice", ["0", "1"])
    constructor.assert_called_once_with(scene)
    assert (
        rows.call_args_list[0].kwargs["cache"] is rows.call_args_list[1].kwargs["cache"]
    )


@pytest.mark.asyncio
async def test_source_edit_during_support_check_prevents_publication(supported_scene):
    scene, _, memory = supported_scene
    message, source = evidence_message(scene)

    embed = memory.embed_texts.side_effect

    async def compare(texts):
        result = await embed(texts)
        scene.edit_message(message.id, "The bell is silent.")
        return result

    memory.embed_texts.side_effect = compare
    with pytest.raises(ValueError, match="sources changed"):
        await extract(scene, source, "Alice", "Alice rings the bell.")
    assert not scene.world_state.facts


@pytest.mark.asyncio
async def test_merging_two_audiences_still_checks_an_unmerged_present_subject(
    supported_scene,
):
    from talemate.character import Character

    scene, _, memory = supported_scene
    message, source = evidence_message(scene)
    scene.character_data["Carol"] = Character(name="Carol")
    scene.active_characters.append("Carol")
    message.present.append("Carol")
    outputs = [
        view.model_dump(exclude={"revision"}) for view in message.knowledge.views
    ]
    outputs.append(
        {
            "audience": ["Carol"],
            "status": "ready",
            "text": "Alice rings the bell.",
            "evidence_spans": [0],
        }
    )
    set_source_perspectives(scene, "message", message.id, outputs)
    await extract(
        scene, source, "Alice", "Alice rings the bell.", subjects=["Alice", "Carol"]
    )
    await extract(
        scene,
        source,
        "Bob",
        "The bell is rung by Alice.",
        subjects=["Alice", "Carol", "bell"],
    )
    assert len(scene.world_state.facts) == 1
    assert len(bucket(scene, "Carol")) == 1
    (fact,) = scene.world_state.facts.values()
    assert {
        name
        for item in fact.contributions
        if item.inferred_from is not None
        for name in item.audience
    } == {"Carol"}


@pytest.mark.asyncio
@pytest.mark.parametrize("subjects", [["BOB"], ["Robert"]])
async def test_alias_subjects_merge_and_still_require_recipient_citation(
    supported_scene, subjects
):
    scene, _, _ = supported_scene
    scene.world_state.character_name_mappings = {"Bob": ["Robert"]}
    _, source = evidence_message(scene)
    await extract(scene, source, "Alice", "Alice rings the bell.", subjects=["Bob"])
    await extract(scene, source, "Bob", "The bell is rung by Alice.", subjects=subjects)
    assert len(scene.world_state.facts) == 1
    assert len(bucket(scene, "Bob")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("qualifier", ["subjects", "time_scope", "supersedes"])
async def test_unmerged_phrasings_are_not_cross_inferred(supported_scene, qualifier):
    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    left, right = {}, {}
    if qualifier == "subjects":
        left, right = {"subjects": ["Alice"]}, {"subjects": ["Bob"]}
    await extract(scene, source, "Alice", "Alice rings the bell.", **left)
    first = next(iter(scene.world_state.facts.values()))
    if qualifier == "supersedes":
        from talemate.knowledge.schema import Fact

        scene.world_state.facts["different"] = Fact(
            id="different", text="An earlier event."
        )
    if qualifier in ("time_scope", "supersedes"):
        item = first.contributions[0].model_copy(update={qualifier: "different"})
        scene.world_state.facts[first.id] = first.model_copy(
            update={"contributions": (item,)}
        )
    await extract(scene, source, "Bob", "The bell is rung by Alice.", **right)
    assert len(scene.world_state.facts) == (3 if qualifier == "supersedes" else 2)
    assert len(bucket(scene, "Alice")) == len(bucket(scene, "Bob")) == 1
    assert all(
        item.inferred_from is None
        for fact in scene.world_state.facts.values()
        for item in fact.contributions
    )
