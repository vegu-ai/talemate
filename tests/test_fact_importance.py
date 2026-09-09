import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pydantic
import pytest

from talemate.agents.memory.schema import MemoryDocument
from talemate.agents.summarize.response_specs import SUMMARY_WITH_FACTS_SPEC
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.facts import parse_facts, store_facts, update_fact
from talemate.knowledge.perspective_models import Acquisition, SourceReference
from talemate.knowledge.schema import Fact, FactContribution, ParsedFact
from talemate.knowledge.supported_facts import _replace_contributions, aggregate_fact
from talemate.prompts import Prompt
from talemate.world_state import WorldState


@pytest.fixture
def trivial_chapter():
    return json.loads(
        (
            Path(__file__).parent / "data/fact_importance/trivial_chapter.json"
        ).read_text()
    )


@pytest.mark.parametrize("level", [1, 2, 3])
def test_importance_survives_fact_and_world_state_roundtrip(level):
    parsed = parse_facts(json.dumps([{"text": "Mara moved in.", "importance": level}]))
    assert parsed[0].importance == level
    fact = Fact(id="F1", **parsed[0].model_dump(exclude={"known_by"}))
    state = WorldState(facts={fact.id: fact})
    restored = WorldState.model_validate_json(state.model_dump_json())
    assert restored.facts["F1"].importance == level


@pytest.mark.parametrize("level", [0, 4, -1, 1.5, "unknown", "3.5", True, None])
def test_invalid_importance_defaults_during_extraction_but_edit_stays_strict(
    level, monkeypatch
):
    warning = Mock()
    monkeypatch.setattr("talemate.knowledge.facts.log.warning", warning)
    data = {"text": "Mara moved in.", "importance": level}
    parsed = parse_facts(
        json.dumps(
            [
                {"text": "First hug.", "importance": 3},
                data,
                {"text": "The key is brass.", "importance": 1},
            ]
        )
    )
    assert [item.importance for item in parsed] == [3, 2, 1]
    warning.assert_called_once_with(
        "fact importance unreadable; defaulting to 2", importance=level
    )
    with pytest.raises(pydantic.ValidationError):
        Fact.model_validate({"id": "F1", **data})


@pytest.mark.parametrize(
    "levels", [["3", "2", "1"], [3.0, 2.0, 1.0], ["3.0", "2.0", "1.0"]]
)
def test_readable_importance_keeps_its_value_during_extraction(levels, monkeypatch):
    warning = Mock()
    monkeypatch.setattr("talemate.knowledge.facts.log.warning", warning)
    parsed = parse_facts(
        json.dumps([{"text": "A fact.", "importance": level} for level in levels])
    )
    assert [item.importance for item in parsed] == [3, 2, 1]
    warning.assert_not_called()
    for level in levels:
        with pytest.raises(pydantic.ValidationError):
            Fact(id="F1", text="A fact.", importance=level)


def test_old_facts_and_extraction_without_importance_default_to_state():
    state = WorldState.model_validate({"facts": {"F1": {"id": "F1", "text": "old"}}})
    assert state.facts["F1"].importance == 2
    assert parse_facts('[{"text": "old"}]')[0].importance == 2


@pytest.fixture
def fact_memory(scene, monkeypatch):
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(
        memory, "compare_string_lists", AsyncMock(return_value={"distance_matches": []})
    )
    return memory


@pytest.mark.asyncio
async def test_storage_edit_and_restatement_preserve_importance(
    scene, fact_memory, monkeypatch
):
    with ActiveScene(scene):
        first = (
            await store_facts(
                scene,
                "a1",
                ["Mara"],
                1,
                [ParsedFact(text="Mara moved in.", importance=3)],
                0.15,
            )
        )[0]
        assert first.importance == 3
        edited = first.model_copy(update={"importance": 1})
        assert await update_fact(scene, edited)
        monkeypatch.setattr(
            fact_memory,
            "get",
            AsyncMock(
                return_value=[
                    MemoryDocument(edited.text, {"typ": "fact"}, edited.id, edited.text)
                ]
            ),
        )
        monkeypatch.setattr(
            fact_memory,
            "compare_strings",
            AsyncMock(return_value={"euclidean_distance": 0.01}),
        )
        assert (
            await store_facts(
                scene,
                "a2",
                ["Mara"],
                2,
                [ParsedFact(text="Mara moved into the house.", importance=3)],
                0.15,
            )
            == []
        )
    assert len(scene.world_state.facts) == 1
    assert scene.world_state.facts[first.id].importance == 1
    assert scene.world_state.facts[first.id].restatements == 1


@pytest.mark.parametrize("method", ["short", "long", "balanced", "facts"])
@pytest.mark.parametrize("audience", [False, True])
def test_archive_prompt_salience_and_importance_contract(
    scene, method, audience, trivial_chapter
):
    with ActiveScene(scene):
        rendered = Prompt.get(
            "summarizer.summarize-dialogue",
            vars={
                "scene": scene,
                "dialogue": trivial_chapter["dialogue"],
                "max_tokens": 8192,
                "num_extra_context": 0,
                "extra_context": [],
                "summarization_method": method,
                "extract_facts": True,
                "audience_summary": ("Mara", "Edwin") if audience else None,
                "previous_facts": [Fact(id="F1", text="Mara and Edwin routinely hug.")],
            },
        ).render()
    assert "Between 0 and 12 items" in rendered
    assert "Between 1 and 12" not in rendered
    assert '"importance": 2' in rendered
    assert "integer from 1 to 3" in rendered
    assert "first hug" in rendered and "routinely hug" in rendered
    assert "return []" in rendered
    assert "attribution, uncertainty, tense, time" in rendered
    assert "[F1] Fact: Mara and Edwin routinely hug." in rendered
    assert "Record age (metadata, do not copy): Time unknown" in rendered
    assert "Do not copy it into extracted facts." in rendered
    assert "[F1] (Time unknown)" not in rendered
    if audience:
        assert "A report is a report" in rendered
        assert "appearing in BOTH its text and the source" in rendered
        assert "do not include a known_by field" in rendered


@pytest.mark.asyncio
async def test_trivial_chapter_empty_facts_through_summary_and_storage(
    scene, fact_memory, trivial_chapter, monkeypatch
):
    summarizer = get_agent("summarizer")
    response = trivial_chapter["response"]
    request = AsyncMock(
        return_value=(response, SUMMARY_WITH_FACTS_SPEC.extract_all(response))
    )
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveScene(scene):
        summary, parsed = await summarizer.summarize(
            trivial_chapter["dialogue"], return_facts=True
        )
        assert summary
        assert parsed == trivial_chapter["facts"] == []
        assert await store_facts(scene, "a1", ["Mara", "Edwin"], 1, parsed, 0.15) == []
    assert scene.world_state.facts == {}
    fact_memory.add_many.assert_not_awaited()
    request.assert_awaited_once()


def test_supported_fact_keeps_extracted_and_manually_corrected_importance():
    contribution = FactContribution(
        source=SourceReference(
            kind="message", id=1, revision=1, view_id="v1", view_revision=1
        ),
        acquired=Acquisition(ts=1, order=1),
        audience=("Mara",),
        text="Mara moved in.",
        importance=3,
    )
    facts, _, _ = _replace_contributions({}, set(), [contribution], 0)
    assert facts["F1"].importance == 3
    corrected = facts["F1"].model_copy(update={"importance": 1})
    assert aggregate_fact(corrected, corrected.contributions).importance == 1
