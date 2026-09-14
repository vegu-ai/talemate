from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import test_supported_facts
from talemate.history import HistoryEntry
from talemate.knowledge.facts import facts_for_entry
from talemate.knowledge.graph import bucket
from talemate.knowledge.schema import ParsedFact
from talemate.load import load_scene_from_data
from talemate.tale_mate import Scene

supported_scene = test_supported_facts.supported_scene
STOCK = (
    Path(__file__).resolve().parents[1] / "scenes/infinity-quest/infinity-quest.json"
)


@pytest.fixture
async def infinity_scene(supported_scene, monkeypatch, tmp_path):
    scene, summarizer, memory = supported_scene
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    monkeypatch.setattr(memory, "set_db", AsyncMock())
    monkeypatch.setattr(memory, "close_db", Mock())
    monkeypatch.setattr(memory, "get_document", AsyncMock(return_value={}))
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    data = json.loads(STOCK.read_text())
    await load_scene_from_data(scene, deepcopy(data), name="infinity-facts-test.json")
    return scene, summarizer, memory, data


async def test_stock_fresh_load_preserves_standard_and_source_visibility(
    infinity_scene,
):
    scene, _, _, data = infinity_scene
    assert scene.knowledge_eligibility == "legacy" and scene.knowledge is None
    assert not scene.can_change_knowledge_eligibility
    assert not scene.history and len(scene.archived_history) == 6
    assert scene.world_state.fact_counter == len(scene.world_state.facts) == 12
    assert len({fact.text for fact in scene.world_state.facts.values()}) == 12
    assert "agent_config" not in data and "knowledge" not in data
    assert scene.intro == data["intro"] and scene.description == data["description"]
    all_ids = set()
    for index, entry in enumerate(scene.archived_history):
        assert entry.get("start") is None and entry.get("end") is None
        assert entry["facts_status"] == "ok"
        facts = facts_for_entry(scene, entry["id"])
        assert facts
        for fact in facts:
            all_ids.add(fact.id)
            assert fact.archive_id == entry["id"]
            assert fact.ts == entry["ts"] == fact.last_seen_ts
            assert fact.present == entry["present"]
            assert fact.source == "summary" and not fact.known_by
            assert fact.restated_by == () and fact.message_id is None
        expected = ["Elmer", "Kaira"] if index < 5 else ["Elmer"]
        assert entry["present"] == expected
    assert all_ids == set(scene.world_state.facts)
    assert len(bucket(scene, "Elmer")) == 12
    assert len(bucket(scene, "Kaira")) == 9
    assert not bucket(scene, "Uninvolved visitor")


async def test_stock_regeneration_and_save_reload_keep_independent_history(
    infinity_scene, monkeypatch
):
    scene, summarizer, _, _ = infinity_scene
    original_entries = deepcopy(scene.archived_history)
    original_ts = scene.ts
    target = scene.archived_history[-1]
    retained = {
        fact.id: fact.model_dump()
        for fact in scene.world_state.facts.values()
        if fact.archive_id != target["id"]
    }
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=(
                "Unused rewrite",
                [ParsedFact(text="Elmer could not remember the last six hours.")],
            )
        ),
    )
    for _ in range(2):
        assert (
            await summarizer.regenerate_facts(HistoryEntry(**target, index=5, layer=0))
            == "ok"
        )
        assert len(scene.world_state.facts) == 10
        assert len(facts_for_entry(scene, target["id"])) == 1
        assert len(bucket(scene, "Kaira")) == 9
        assert all(
            scene.world_state.facts[identity].model_dump() == value
            for identity, value in retained.items()
        )
    before = json.loads(scene.json)
    await scene.save()
    path = Path(scene.save_dir) / scene.filename
    saved = json.loads(path.read_text())
    await load_scene_from_data(scene, deepcopy(saved), name=scene.filename)
    assert (
        json.loads(scene.json)["world_state"]["facts"] == before["world_state"]["facts"]
    )
    assert scene.archived_history == original_entries
    assert scene.ts == original_ts and not scene.history
    assert scene.knowledge_eligibility == "legacy"
    assert not scene.can_change_knowledge_eligibility
    assert len(bucket(scene, "Kaira")) == 9
