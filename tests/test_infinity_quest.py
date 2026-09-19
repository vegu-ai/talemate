from copy import deepcopy
import json
from pathlib import Path

import pytest

import test_scene_format

load_env = test_scene_format.load_env
from talemate.load import load_scene_from_data

STOCK = (
    Path(__file__).resolve().parents[1] / "scenes/infinity-quest/infinity-quest.json"
)


@pytest.mark.asyncio
async def test_stock_load_and_save_keep_authored_history(load_env):
    scene = load_env
    data = json.loads(STOCK.read_text())
    await load_scene_from_data(scene, deepcopy(data), name="infinity-test.json")
    assert scene.knowledge_eligibility == "legacy" and scene.knowledge is None
    assert not scene.can_change_knowledge_eligibility
    assert not scene.history and len(scene.archived_history) == 6
    assert "agent_config" not in data and "knowledge" not in data
    assert scene.intro == data["intro"] and scene.description == data["description"]
    for index, entry in enumerate(scene.archived_history):
        assert entry.get("start") is None and entry.get("end") is None
        assert entry["present"] == (["Elmer", "Kaira"] if index < 5 else ["Elmer"])
        assert "facts_status" not in entry
    assert "facts" not in data["world_state"]
    original_entries = deepcopy(scene.archived_history)
    original_ts = scene.ts
    await scene.save()
    saved = json.loads((Path(scene.save_dir) / scene.filename).read_text())
    await load_scene_from_data(scene, deepcopy(saved), name=scene.filename)
    assert scene.archived_history == original_entries
    assert scene.ts == original_ts and not scene.history
    assert scene.knowledge_eligibility == "legacy"
    assert not scene.can_change_knowledge_eligibility
