from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import test_supported_facts
from talemate.history import ArchiveEntry, HistoryEntry, validate_history
from talemate.knowledge.facts import facts_for_entry
from talemate.knowledge.graph import bucket
from talemate.knowledge.perspectives import set_source_perspectives
from talemate.knowledge.schema import Fact, ParsedFact
from talemate.load import load_scene_from_data
from talemate.tale_mate import Scene

supported_scene = test_supported_facts.supported_scene


@pytest.fixture
def static_scene(supported_scene, monkeypatch):
    scene, summarizer, memory = supported_scene
    scene.knowledge_eligibility = "legacy"
    scene.ts = 500
    scene.archived_history = [
        ArchiveEntry(
            id="opening", text="Alice repaired the radio.", ts=10, present=["Alice"]
        ).model_dump(exclude_none=True)
    ]
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    return scene, summarizer, memory


def row(scene, index=0):
    return HistoryEntry(**scene.archived_history[index], index=index, layer=0)


@pytest.mark.parametrize(
    "present,known", [(None, {"Alice", "Bob"}), (["Alice"], {"Alice"}), ([], set())]
)
async def test_standard_static_generation_without_progress(
    static_scene, monkeypatch, present, known
):
    scene, summarizer, memory = static_scene
    scene.archived_history[0]["present"] = present
    original = deepcopy(scene.archived_history[0])
    extraction = AsyncMock(
        return_value=(
            "Unused rewritten summary",
            [ParsedFact(text=original["text"], subjects=["radio"])],
        )
    )
    monkeypatch.setattr(summarizer, "summarize", extraction)
    payload = row(scene).model_copy(update={"text": "Untrusted client text"})
    assert not scene.can_change_knowledge_eligibility
    assert await summarizer.regenerate_facts(payload) == "ok"
    extraction.assert_awaited_once_with(
        original["text"], extra_context=[], return_facts=True
    )
    assert scene.history == [] and scene.ts == 500
    assert scene.knowledge_eligibility == "legacy" and scene.knowledge is None
    assert not scene.can_change_knowledge_eligibility
    assert scene.archived_history == [{**original, "facts_status": "ok"}]
    (fact,) = facts_for_entry(scene, "opening")
    assert fact.ts == 10 and fact.archive_id == "opening" and fact.present == present
    assert {name for name in ("Alice", "Bob") if bucket(scene, name)} == known
    assert memory.add_many.await_count > 0


async def test_static_regeneration_replaces_only_its_facts(static_scene, monkeypatch):
    scene, summarizer, _ = static_scene
    unrelated = Fact(
        id="F50", text="Bob keeps a compass.", archive_id="elsewhere", present=["Bob"]
    )
    scene.world_state.facts[unrelated.id] = unrelated
    scene.world_state.fact_counter = 50
    parsed = [ParsedFact(text="Alice repaired the radio.", subjects=["radio"])]
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(return_value=("Unused", parsed))
    )
    for _ in range(3):
        assert await summarizer.regenerate_facts(row(scene)) == "ok"
        assert len(facts_for_entry(scene, "opening")) == 1
        assert len(scene.world_state.facts) == 2
        assert scene.world_state.facts[unrelated.id] == unrelated
    summarizer.summarize.return_value = (
        "Unused",
        [ParsedFact(text="Alice replaced the radio antenna.")],
    )
    await summarizer.regenerate_facts(row(scene))
    assert [fact.text for fact in facts_for_entry(scene, "opening")] == [
        "Alice replaced the radio antenna."
    ]
    assert scene.history == []


async def test_static_extraction_respects_disabled_setting(static_scene, monkeypatch):
    scene, summarizer, _ = static_scene
    summarizer.actions["archive"].config["extract_facts"].value = False
    extraction = AsyncMock()
    monkeypatch.setattr(summarizer, "summarize", extraction)
    before = deepcopy(scene.archived_history)
    assert await summarizer.regenerate_facts(row(scene)) is None
    extraction.assert_not_awaited()
    assert scene.archived_history == before and not scene.world_state.facts


@pytest.mark.parametrize("parsed,status", [(None, "failed"), ([], "ok")])
async def test_static_failed_or_empty_response_keeps_entry_text(
    static_scene, monkeypatch, parsed, status
):
    scene, summarizer, _ = static_scene
    original = deepcopy(scene.archived_history[0])
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(return_value=("Unused", parsed))
    )
    assert await summarizer.regenerate_facts(row(scene)) == status
    assert scene.archived_history == [{**original, "facts_status": status}]
    assert not scene.world_state.facts and not scene.history


async def test_old_static_entry_gets_persistent_source_identity(
    static_scene, monkeypatch
):
    scene, summarizer, _ = static_scene
    scene.archived_history[0].pop("id")
    await validate_history(scene, commit_to_memory=False)
    identity = scene.archived_history[0]["id"]
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=("Unused", [ParsedFact(text="Alice repaired the radio.")])
        ),
    )
    await summarizer.regenerate_facts(row(scene))
    assert facts_for_entry(scene, identity)
    await validate_history(scene, commit_to_memory=False)
    assert scene.archived_history[0]["id"] == identity


async def test_missing_progressed_sources_do_not_extract_summary_as_static(
    static_scene, monkeypatch
):
    scene, summarizer, _ = static_scene
    scene.archived_history[0].update(start=0, end=0)
    extraction = AsyncMock()
    monkeypatch.setattr(summarizer, "summarize", extraction)
    assert await summarizer.regenerate_facts(row(scene)) is None
    extraction.assert_not_awaited()


@pytest.mark.parametrize("save_reload", [False, True])
async def test_static_perception_views_preserve_private_audiences(
    static_scene, monkeypatch, tmp_path, save_reload
):
    scene, summarizer, memory = static_scene
    scene.knowledge_eligibility = "perception"
    scene.archived_history[0]["text"] = (
        "Reader-only secret; Alice fixed a radio and Bob found a chart."
    )
    views = [("Alice", "Alice repaired the radio."), ("Bob", "Bob found a chart.")]
    set_source_perspectives(
        scene,
        "summary",
        "opening",
        [{"audience": [name], "status": "ready", "text": text} for name, text in views],
    )
    before = deepcopy(scene.archived_history[0]["knowledge"])

    async def extract(text, **kwargs):
        return "Unused", [ParsedFact(text=text)]

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    for _ in range(2):
        assert await summarizer.regenerate_facts(row(scene)) == "ok"
        assert len(scene.world_state.facts) == 2
        for name, text in views:
            assert [fact.text for fact, _ in bucket(scene, name)] == [text]
    assert scene.archived_history[0]["knowledge"] == before
    assert all(
        "Reader-only" not in call.args[0]
        for call in summarizer.summarize.call_args_list
    )
    assert scene.history == [] and scene.ts == 500
    if save_reload:
        await assert_saved_reload(scene, memory, monkeypatch, tmp_path)
        for name, text in views:
            assert [fact.text for fact, _ in bucket(scene, name)] == [text]
        assert await summarizer.regenerate_facts(row(scene)) == "ok"
        assert len(scene.world_state.facts) == 2


async def assert_saved_reload(scene, memory, monkeypatch, tmp_path):
    original = json.loads(scene.json)
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    monkeypatch.setattr(memory, "set_db", AsyncMock())
    monkeypatch.setattr(memory, "close_db", Mock())
    monkeypatch.setattr(memory, "get_document", AsyncMock(return_value={}))
    await load_scene_from_data(scene, deepcopy(original), name="static-facts.json")
    await scene.save()
    saved = json.loads((Path(scene.save_dir) / "static-facts.json").read_text())
    assert saved["world_state"]["facts"] == original["world_state"]["facts"]
    assert saved["archived_history"] == original["archived_history"]
    assert saved["history"] == original["history"] == []
    assert saved["knowledge_eligibility"] == original["knowledge_eligibility"]


async def test_standard_static_facts_survive_save_reload(
    static_scene, monkeypatch, tmp_path
):
    scene, summarizer, memory = static_scene
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=("Unused", [ParsedFact(text="Alice repaired the radio.")])
        ),
    )
    await summarizer.regenerate_facts(row(scene))
    await assert_saved_reload(scene, memory, monkeypatch, tmp_path)
    assert len(bucket(scene, "Alice")) == 1
    assert not bucket(scene, "Bob")
    await summarizer.regenerate_facts(row(scene))
    assert len(scene.world_state.facts) == 1


@pytest.mark.parametrize("empty_record", [False, True])
async def test_missing_perception_views_never_generate_or_claim_success(
    static_scene, monkeypatch, empty_record
):
    scene, summarizer, _ = static_scene
    scene.knowledge_eligibility = "perception"
    if empty_record:
        set_source_perspectives(scene, "summary", "opening", [])
    extraction = AsyncMock()
    monkeypatch.setattr(summarizer, "summarize", extraction)
    assert (
        "no saved character perspectives"
        in summarizer.fact_source_unavailable_reason(
            scene, ArchiveEntry(**scene.archived_history[0])
        )
    )
    assert await summarizer.regenerate_facts(row(scene)) == "failed"
    extraction.assert_not_awaited()
    assert not scene.world_state.facts


async def test_pending_perception_view_is_not_reader_text_fallback(
    static_scene, monkeypatch
):
    scene, summarizer, _ = static_scene
    scene.knowledge_eligibility = "perception"
    set_source_perspectives(
        scene, "summary", "opening", [{"audience": ["Alice"], "status": "pending"}]
    )
    extraction = AsyncMock()
    monkeypatch.setattr(summarizer, "summarize", extraction)
    assert "must be ready" in summarizer.fact_source_unavailable_reason(
        scene, ArchiveEntry(**scene.archived_history[0])
    )
    assert await summarizer.regenerate_facts(row(scene)) == "failed"
    extraction.assert_not_awaited()
