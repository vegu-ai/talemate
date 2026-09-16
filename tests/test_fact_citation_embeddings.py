import asyncio
import threading
from types import MethodType
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

import test_supported_facts
from test_fact_evidence import evidence_message
from talemate.agents.memory import MemoryAgent
from talemate.history import ArchiveEntry
from talemate.knowledge.perspectives import (
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.knowledge.fact_reconciliation import fact_knowledge_reason
from talemate.knowledge.graph import bucket
from talemate.knowledge.schema import ParsedFact
from talemate.knowledge.supported_facts import replace_source_facts

supported_scene = test_supported_facts.supported_scene


def real_comparisons(memory, embed, monkeypatch):
    monkeypatch.setattr(
        type(memory), "embedding_function", property(lambda self: embed)
    )
    for name in ("embed_texts", "compare_strings", "compare_string_lists"):
        monkeypatch.setattr(
            memory, name, MethodType(getattr(MemoryAgent, name), memory)
        )


@pytest.mark.asyncio
async def test_comparisons_normalize_and_batch_off_the_event_loop(
    supported_scene, monkeypatch
):
    _, _, memory = supported_scene
    loop_thread = threading.get_ident()
    calls = []

    def embed(texts):
        assert threading.get_ident() != loop_thread
        calls.append(texts)
        return [
            {"a": [3, 0], "b": [0, 7], "c": [19, 0], "zero": [0, 0]}[text]
            for text in texts
        ]

    real_comparisons(memory, embed, monkeypatch)
    assert (await memory.compare_strings("a", "c"))["euclidean_distance"] == 0
    result = await memory.compare_string_lists(
        ["a", "b"], ["b", "c"], distance_threshold=0.15
    )
    assert calls == [["a", "c"], ["a", "b", "c"]]
    assert {(i, j) for i, j, _ in result["distance_matches"]} == {(0, 1), (1, 0)}
    assert result["euclidean_distance_matrix"][0, 0] == pytest.approx(2**0.5)
    assert np.isfinite(await memory.embed_texts(["zero"])).all()


@pytest.mark.asyncio
async def test_300_message_rebuild_embeds_once_per_passage(
    supported_scene, monkeypatch
):
    scene, summarizer, memory = supported_scene
    for _ in range(300):
        evidence_message(scene)
    for index, message in enumerate(scene.history):
        identity = f"chapter-{message.id}"
        scene.archived_history.append(
            ArchiveEntry(id=identity, text="c", start=index, end=index).model_dump(
                exclude_none=True
            )
        )
        set_source_perspectives(
            scene,
            "summary",
            identity,
            [
                {
                    "audience": [name],
                    "status": "ready",
                    "text": "c",
                    "sources": [
                        select_character_view(
                            scene, source_reference(scene, "message", message.id), name
                        ).source
                    ],
                }
                for name in ("Alice", "Bob")
            ],
        )
    loop_thread = threading.get_ident()
    calls = []
    facts = [f"Public fact {i}." for i in range(12)]
    vectors = {
        "Alice rings the bell.": [1, 0],
        "Bob privately fears the signal.": [0, 1],
        **{text: [1, i / 100] for i, text in enumerate(facts)},
    }

    def embed(texts):
        assert threading.get_ident() != loop_thread
        calls.append(texts)
        return [vectors[text] for text in texts]

    async def extract(text, *, fact_evidence, **kwargs):
        return [
            ParsedFact(text=fact, evidence_id=fact_evidence[0]["id"]) for fact in facts
        ]

    real_comparisons(memory, embed, monkeypatch)
    monkeypatch.setattr(summarizer, "extract_facts", AsyncMock(side_effect=extract))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(heartbeat())
    try:
        assert await summarizer.rebuild_supported_facts(scene) == "ok"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(calls) == 300
    assert all(set(batch) == set(vectors) for batch in calls)
    assert summarizer.extract_facts.await_count == 600
    assert len(scene.world_state.facts) == 3600
    assert ticks >= 300


@pytest.fixture
def deterministic_citation_embeddings():
    vectors = {
        "Alice rings the bell.": [4, 0, 0],
        "The bell was rung by Alice.": [2, 0.1, 0],
        "Bob plans to betray Alice.": [0, 3, 0],
        "Bob privately fears the signal.": [0, 5, 0],
        "Bob fears the signal.": [0, 4, 0],
        "Alice hands Bob the key.": [4, 0, 0],
        "Bob privately plans to steal the charts.": [0, 5, 0],
        "Bob plans to steal the charts.": [0, 4, 0],
        "Alice reaches the north gate at dusk.": [4, 0, 0],
        "She is alone.": [0, 0, 4],
        "The guards do not stop her.": [2, 2, 0],
        "The guards let Alice pass.": [4, 1, 0],
        "Alice returns the sword to Bob.": [4, 0, 0],
        "He does not take it.": [0, 4, 0],
        "It falls to the floor.": [0, 0, 4],
        "Bob refuses the sword.": [0, 3, 0],
        "The sword ends up on the floor.": [0, 0, 3],
    }
    return Mock(side_effect=lambda texts: [vectors[text] for text in texts])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,span,shared",
    [
        ("The bell was rung by Alice.", 0, True),
        ("Bob plans to betray Alice.", 0, False),
        ("Bob privately fears the signal.", 0, False),
        ("Bob privately fears the signal.", 1, False),
    ],
)
async def test_embedding_comparisons_rank_citations_and_preserve_private_subjects(
    supported_scene,
    monkeypatch,
    deterministic_citation_embeddings,
    text,
    span,
    shared,
):
    from structlog.testing import capture_logs

    scene, _, memory = supported_scene
    private = (
        "Bob plans to betray Alice."
        if "betray" in text
        else "Bob privately fears the signal."
    )
    _, source = evidence_message(scene, private=private)
    embed = deterministic_citation_embeddings
    real_comparisons(memory, embed, monkeypatch)
    with capture_logs() as logs:
        await replace_source_facts(
            scene,
            [
                (
                    source,
                    ("Bob",),
                    [
                        ParsedFact(
                            text=text,
                            evidence_id=f"M{source.id}R1S{span}",
                            subjects=["ALICE", "Robert"],
                        )
                    ],
                )
            ],
        )
    assert bool(bucket(scene, "Alice")) is shared
    assert len(bucket(scene, "Bob")) == 1
    expected_batch = ["Alice rings the bell.", private]
    if text not in expected_batch:
        expected_batch.append(text)
    embed.assert_called_once_with(expected_batch)
    fact = next(iter(scene.world_state.facts.values()))
    rejected = not shared and span == 0
    assert not fact.contributions[0].citation_rejected
    if rejected:
        assert fact.contributions[0].evidence_competitors
        assert fact.contributions[0].evidence is not None
        assert fact_knowledge_reason(scene, fact, "Alice") == "Citation not supported"
        assert any(entry["event"] == "citation not supported" for entry in logs)
