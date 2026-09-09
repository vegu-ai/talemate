import json

import pytest

import test_supported_facts
from talemate.agents.summarize.perceptions import parse_perceptions, perception_context
from talemate.knowledge.evidence import (
    extraction_evidence,
    passage_spans,
    view_evidence,
)
from talemate.knowledge.perspective_models import PassageEvidence, PerspectiveOutput
from talemate.knowledge.perspectives import set_source_perspectives, source_reference
from talemate.knowledge.schema import ParsedFact
from talemate.knowledge.supported_facts import contributions_for_source
from talemate.scene_message import NarratorMessage

supported_scene = test_supported_facts.supported_scene


@pytest.fixture(autouse=True)
def passage_embeddings(supported_scene, monkeypatch):
    import numpy as np
    from unittest.mock import AsyncMock

    vectors = {
        "Alice rings the bell.": [1, 0, 0],
        "Alice rang the bell.": [1, 0.01, 0],
        "The bell was rung by Alice.": [1, 0.02, 0],
        "The bell is rung by Alice.": [1, 0.02, 0],
        "Bob privately fears the signal.": [0, 1, 0],
        "Bob fears the signal.": [0, 1, 0],
        "Bob fears what Alice will do.": [0, 1, 0],
        "Bob plans to betray Alice.": [0, 1, 0],
        "Alice holds the bell.": [1, 0, 0.5],
        "Bob holds the bell.": [1, 0, -0.5],
    }

    async def embed(texts):
        rows = np.array([vectors[text] for text in texts], dtype=float)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)

    memory = supported_scene[2]
    monkeypatch.setattr(memory, "embed_texts", AsyncMock(side_effect=embed))
    return vectors


def evidence_message(scene, private="Bob privately fears the signal."):
    message = NarratorMessage(
        message=f"Alice rings the bell. {private}",
        present=["Alice", "Bob"],
    )
    scene.history.append(message)
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice rings the bell.",
                "evidence_spans": [0],
            },
            {
                "audience": ["Bob"],
                "status": "ready",
                "text": message.message,
                "evidence_spans": [0, 1],
            },
        ],
    )
    return message, source_reference(scene, "message", message.id)


def test_passage_span_ids_are_deterministic():
    assert passage_spans("One sentence. Another!\nA final line") == (
        "One sentence.",
        "Another!",
        "A final line",
    )


@pytest.mark.parametrize("indexes", [[-1], [True], ["0"], [0, 0]])
def test_invalid_span_indexes_are_rejected(indexes):
    with pytest.raises(ValueError):
        PerspectiveOutput(
            audience=["Alice"], status="ready", text="A bell.", evidence_spans=indexes
        )


def test_omitted_view_cannot_claim_evidence():
    with pytest.raises(ValueError, match="Only a ready"):
        PerspectiveOutput(audience=["Alice"], status="omitted", evidence_spans=[0])


def test_perception_response_keeps_explicit_evidence():
    payload = {
        "views": [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "A bell.",
                "knowledge_ids": [],
                "passage_ids": [],
                "evidence_spans": [0],
            }
        ]
    }
    assert parse_perceptions(json.dumps(payload), ("Alice",))[0].evidence_spans == (0,)


def test_shared_extraction_offers_only_fully_perceived_spans(supported_scene):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    offered = extraction_evidence(scene, [source], ("Alice", "Bob"))
    assert offered == [{"id": f"M{message.id}R1S0", "text": "Alice rings the bell."}]
    context = perception_context(scene, message)
    assert context["passage"]["evidence_spans"] == [
        {"id": 0, "text": "Alice rings the bell."},
        {"id": 1, "text": "Bob privately fears the signal."},
    ]


@pytest.mark.asyncio
async def test_host_rejects_unoffered_evidence(supported_scene):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    with pytest.raises(ValueError, match="offered span"):
        set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": "A bell.",
                    "evidence_spans": [2],
                },
            ],
        )
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        (fact,) = await contributions_for_source(
            scene,
            source,
            ("Alice",),
            [
                ParsedFact(
                    text="Bob fears the signal.", evidence_id=f"M{message.id}R1S1"
                ),
            ],
        )
    assert fact.evidence is None
    assert any(entry["event"] == "dropping unsupported fact evidence" for entry in logs)


@pytest.mark.asyncio
async def test_fact_resolves_evidence_to_source_revision(supported_scene):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    (contribution,) = await contributions_for_source(
        scene,
        source,
        ("Alice",),
        [
            ParsedFact(text="Alice rings the bell.", evidence_id=f"M{message.id}R1S0"),
        ],
    )
    assert contribution.evidence == PassageEvidence(
        message_id=message.id, revision=1, span=0
    )
    scene.edit_message(message.id, "The bell is silent.")
    assert view_evidence(scene, source, "Alice") == {}


def test_summary_evidence_follows_each_audiences_dependencies(supported_scene):
    scene, _, _ = supported_scene
    message, source = evidence_message(scene)
    scene.archived_history.append(
        {"id": "A1", "text": "A bell and a fear.", "start": 0, "end": 0, "ts": 1}
    )
    set_source_perspectives(
        scene,
        "summary",
        "A1",
        [
            {
                "audience": [name],
                "status": "ready",
                "text": "A bell.",
                "sources": [source],
            }
            for name in ("Alice", "Bob")
        ],
    )
    summary = source_reference(scene, "summary", "A1")
    assert len(view_evidence(scene, summary, "Alice")) == 1
    assert len(view_evidence(scene, summary, "Bob")) == 2
    assert (
        extraction_evidence(scene, [summary], ("Alice",))[0]["id"]
        == f"M{message.id}R1S0"
    )


def test_persistence_distinguishes_old_views_from_explicit_no_citations():
    old = PerspectiveOutput(audience=["Alice"], status="ready", text="A bell.")
    current = PerspectiveOutput(
        audience=["Alice"], status="ready", text="A bell.", evidence_spans=[]
    )
    assert "evidence_spans" not in old.model_dump()
    assert current.model_dump()["evidence_spans"] == ()


def test_evidence_excerpts_stay_inside_client_budget():
    from talemate.knowledge.evidence import budget_evidence
    from talemate.util import count_tokens

    evidence = [
        {"id": f"M1R1S{i}", "text": "A long public statement. " * 200}
        for i in range(1000)
    ]
    offered = budget_evidence(evidence, 8192, 4000)
    assert 0 < count_tokens(offered) <= 1024
    assert all(len(line) < 185 for line in offered.splitlines())
    assert len(offered.splitlines()) < len(evidence)
    assert budget_evidence(evidence, 8192, 8190) == ""


@pytest.mark.asyncio
async def test_summary_without_fact_extraction_does_not_walk_evidence(
    supported_scene, monkeypatch
):
    from unittest.mock import AsyncMock, Mock

    scene, summarizer, _ = supported_scene
    evidence_message(scene)
    scene.archived_history.append(
        {"id": "A1", "text": "A bell.", "start": 0, "end": 0, "ts": 1}
    )
    summarizer.actions["archive"].config["extract_facts"].value = False
    monkeypatch.setattr(summarizer, "summarize", AsyncMock(return_value="A bell."))
    walk = Mock(side_effect=AssertionError("Evidence should not be collected"))
    monkeypatch.setattr(
        "talemate.agents.summarize.audience_summaries.extraction_evidence", walk
    )
    await summarizer.ensure_summary_views(scene, "A1")
    assert summarizer.summarize.await_count == 2
    walk.assert_not_called()


@pytest.mark.asyncio
async def test_old_ready_view_does_not_trigger_automatic_analysis(
    supported_scene, monkeypatch
):
    from unittest.mock import AsyncMock

    scene, summarizer, _ = supported_scene
    message, _ = evidence_message(scene)
    message.knowledge = message.knowledge.model_copy(
        update={
            "views": tuple(
                view.model_copy(update={"evidence_spans": None})
                for view in message.knowledge.views
            )
        }
    )
    analyze = AsyncMock()
    monkeypatch.setattr(summarizer, "analyze_perceptions", analyze)
    await summarizer.ensure_perceptions(scene)
    analyze.assert_not_awaited()
    assert all(view.evidence_spans is None for view in message.knowledge.views)
