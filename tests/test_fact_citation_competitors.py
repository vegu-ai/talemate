from unittest.mock import AsyncMock

import pytest

import test_fact_citation_embeddings
import test_supported_facts
from talemate.agents.memory import MemoryAgent
from talemate.knowledge.fact_reconciliation import fact_knowledge_reason
from talemate.knowledge.graph import bucket
from talemate.knowledge.perspectives import set_source_perspectives, source_reference
from talemate.knowledge.schema import ParsedFact
from talemate.knowledge.supported_facts import replace_source_facts
from talemate.scene_message import NarratorMessage

supported_scene = test_supported_facts.supported_scene
deterministic_citation_embeddings = (
    test_fact_citation_embeddings.deterministic_citation_embeddings
)


def message_view(scene, text, alice_spans, bob_spans, present=None):
    message = NarratorMessage(message=text, present=present or ["Alice", "Bob"])
    scene.history.append(message)
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {
                "audience": [name],
                "status": "ready" if spans is not None else "omitted",
                "text": text if spans is not None else None,
                "evidence_spans": spans or [],
            }
            for name, spans in (("Alice", alice_spans), ("Bob", bob_spans))
        ],
    )
    return source_reference(scene, "message", message.id)


@pytest.mark.asyncio
async def test_summary_private_competitor_from_another_message_vetoes_transfer(
    supported_scene, deterministic_citation_embeddings, monkeypatch
):
    from structlog.testing import capture_logs

    scene, summarizer, memory = supported_scene
    first = message_view(scene, "Alice hands Bob the key.", [0], [0])
    second = message_view(
        scene, "Bob privately plans to steal the charts.", None, [0], ["Bob"]
    )
    scene.archived_history.append(
        {"id": "A1", "text": "A key and a private plan.", "start": 0, "end": 1, "ts": 0}
    )
    set_source_perspectives(
        scene,
        "summary",
        "A1",
        [
            {
                "audience": [name],
                "status": "ready",
                "text": "A key." if name == "Alice" else "A key and a private plan.",
                "sources": [first] if name == "Alice" else [first, second],
            }
            for name in ("Alice", "Bob")
        ],
    )
    embed = deterministic_citation_embeddings
    test_fact_citation_embeddings.real_comparisons(memory, embed, monkeypatch)

    async def summarize(text, *, audience, **kwargs):
        return text, [] if audience == ("Alice",) else [
            ParsedFact(
                text="Bob plans to steal the charts.", evidence_id=f"M{first.id}R1S0"
            )
        ]

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=summarize))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    with capture_logs() as logs:
        assert await summarizer.rebuild_supported_facts(scene) == "ok"
    assert bucket(scene, "Alice") == []
    assert len(bucket(scene, "Bob")) == 1
    assert summarizer.summarize.await_count == 2
    assert embed.call_count == 2
    fact = next(iter(scene.world_state.facts.values()))
    assert fact_knowledge_reason(scene, fact, "Alice") == "Citation not supported"
    assert any(entry["event"] == "citation not supported" for entry in logs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,fact,span",
    [
        (
            "Alice reaches the north gate at dusk. She is alone. The guards do not stop her.",
            "The guards let Alice pass.",
            2,
        ),
        (
            "Alice returns the sword to Bob. He does not take it. It falls to the floor.",
            "Bob refuses the sword.",
            1,
        ),
        (
            "Alice returns the sword to Bob. He does not take it. It falls to the floor.",
            "The sword ends up on the floor.",
            2,
        ),
    ],
)
async def test_public_pronoun_citation_accepts_model_choice(
    supported_scene, deterministic_citation_embeddings, monkeypatch, text, fact, span
):
    scene, _, memory = supported_scene
    source = message_view(scene, text, [0, 1, 2], [0, 1, 2])
    embed = deterministic_citation_embeddings
    test_fact_citation_embeddings.real_comparisons(memory, embed, monkeypatch)
    await replace_source_facts(
        scene,
        [
            (
                source,
                ("Bob",),
                [ParsedFact(text=fact, evidence_id=f"M{source.id}R1S{span}")],
            )
        ],
    )
    assert len(bucket(scene, "Alice")) == 1
    assert bucket(scene, "Alice")[0][0].text == fact
    assert embed.call_count == 1


def test_stored_vector_dedupe_uses_unit_distance():
    assert MemoryAgent._near_duplicates_in(
        ["same", "near", "far"],
        {"anchor": [20, 0]},
        {"same": [3, 0], "near": [4, 0.2], "far": [0, 9]},
        0.15,
    ) == {"same", "near"}


@pytest.mark.asyncio
async def test_extraction_drops_a_citation_with_an_unoffered_competitor(
    supported_scene, deterministic_citation_embeddings, monkeypatch
):
    from talemate.knowledge.supported_facts import contributions_for_source

    scene, _, memory = supported_scene
    source = message_view(
        scene, "Alice rings the bell. Bob privately fears the signal.", [0], [0, 1]
    )
    test_fact_citation_embeddings.real_comparisons(
        memory, deterministic_citation_embeddings, monkeypatch
    )
    (item,) = await contributions_for_source(
        scene,
        source,
        ("Alice",),
        [ParsedFact(text="Bob fears the signal.", evidence_id=f"M{source.id}R1S0")],
    )
    assert item.evidence is None
    assert item.citation_rejected
    assert item.evidence_competitors[0].span == 1


@pytest.mark.asyncio
async def test_competitor_certificate_survives_save_and_checks_current_views(
    supported_scene, deterministic_citation_embeddings, monkeypatch
):
    from talemate.knowledge.schema import Fact

    scene, _, memory = supported_scene
    source = message_view(
        scene,
        "Alice reaches the north gate at dusk. She is alone. The guards do not stop her.",
        [0, 1, 2],
        [0, 1, 2],
    )
    test_fact_citation_embeddings.real_comparisons(
        memory, deterministic_citation_embeddings, monkeypatch
    )
    await replace_source_facts(
        scene,
        [
            (
                source,
                ("Bob",),
                [
                    ParsedFact(
                        text="The guards let Alice pass.",
                        evidence_id=f"M{source.id}R1S2",
                    )
                ],
            )
        ],
    )
    fact = next(iter(scene.world_state.facts.values()))
    restored = Fact.model_validate_json(fact.model_dump_json())
    assert restored == fact
    assert all(
        item.evidence_competitors[0].span == 0 for item in restored.contributions
    )
    scene.world_state.facts[fact.id] = restored
    assert len(bucket(scene, "Alice")) == 1
    memory.embed_texts = AsyncMock(side_effect=AssertionError("Read must not embed"))
    message = scene.history[0]
    outputs = [
        view.model_dump(exclude={"revision"}) for view in message.knowledge.views
    ]
    outputs[0]["evidence_spans"] = [2]
    set_source_perspectives(scene, "message", message.id, outputs)
    assert bucket(scene, "Alice") == []
    assert len(bucket(scene, "Bob")) == 1
    assert (
        fact_knowledge_reason(scene, scene.world_state.facts[fact.id], "Alice")
        == "Citation not supported"
    )
    memory.embed_texts.assert_not_awaited()
