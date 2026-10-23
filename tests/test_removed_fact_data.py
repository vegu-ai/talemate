"""Unreleased development data is dropped without changing authored access."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

import test_scene_format

load_env = test_scene_format.load_env
from talemate.load import load_scene_from_data


@pytest.mark.asyncio
async def test_development_save_drops_facts_and_keeps_views_and_authored_rules(
    load_env,
):
    data = json.loads(
        (Path(__file__).parent / "data/knowledge_perspectives/scene.json").read_text()
    )
    world = data.setdefault("world_state", {})
    world.update(
        {
            "facts": {"F1": {"id": "F1", "text": "Obsolete story fact."}},
            "fact_counter": 1,
            "topics": {"T1": {"fact_ids": ["F1"]}},
            "topics_fact_count": 1,
            "knowledge": [
                {"character": "Bob", "target": "F1", "kind": "grant"},
                {"character": "Bob", "target": "F1", "kind": "unlearn"},
                {
                    "character": "Bob",
                    "target": "F9",
                    "kind": "grant",
                    "anchor": {"text": "Removed fact"},
                },
                {
                    "id": "authored",
                    "character": "Bob",
                    "target": "Alice.description",
                    "kind": "grant",
                },
            ],
        }
    )
    original_knowledge = deepcopy(data["history"][0]["knowledge"])
    for source in [*data["history"], *data["archived_history"]]:
        source["facts_status"] = "ok"
        for view in source.get("knowledge", {}).get("views", []):
            view["evidence_spans"] = [0, 1]
    data["history"][0]["revision_state"] = {
        "completed_features": ["facts", "learning", "perceptions"],
        "phase_receipts": {"facts": "old", "learning": "old", "perceptions": "current"},
        "refresh_journal": {"baseline": {"facts": {"F1": {}}}, "writes": {"edges": {}}},
        "pending_index_repair": {"archive_ids": ["summary-1"], "fact_ids": ["F1"]},
    }
    await load_scene_from_data(load_env, data, name="development.json")
    saved = json.loads(load_env.json)
    assert (
        not {"facts", "fact_counter", "topics", "topics_fact_count"}
        & saved["world_state"].keys()
    )
    assert [edge["id"] for edge in saved["world_state"]["knowledge"]] == ["authored"]
    assert saved["history"][0]["knowledge"] == original_knowledge
    assert all("facts_status" not in entry for entry in saved["archived_history"])
    assert "evidence_spans" not in json.dumps(saved)
    revision = saved["history"][0]["revision_state"]
    assert revision["completed_features"] == ["perceptions"]
    assert revision["phase_receipts"] == {"perceptions": "current"}
    assert not revision.get("refresh_journal")
    assert revision["pending_index_repair"] == {"archive_ids": ["summary-1"]}
    await load_scene_from_data(load_env, deepcopy(saved), name="development.json")
    assert (
        json.loads(load_env.json)["world_state"]["knowledge"]
        == saved["world_state"]["knowledge"]
    )
