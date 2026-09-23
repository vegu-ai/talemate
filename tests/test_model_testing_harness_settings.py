import json
import shutil
from pathlib import Path

import pytest

from talemate import instance
from talemate.load import load_scene_from_data

HARNESS = Path(__file__).parent.parent / "scenes" / "model-testing-harness"


async def _noop(*args, **kwargs):
    return None


async def _no_documents(*args, **kwargs):
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["model-testing-harness.json", "restore.json"])
async def test_harness_runs_with_knowledge_effort_off(
    persistence_scene_factory, tmp_path, monkeypatch, filename
):
    shutil.copytree(HARNESS, tmp_path / "model-testing-harness")
    scene = persistence_scene_factory()
    memory = instance.get_agent("memory")
    monkeypatch.setattr(memory, "set_db", _noop, raising=False)
    monkeypatch.setattr(memory, "get_document", _no_documents, raising=False)
    conversation = instance.get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    conversation.actions["character_knowledge"].config["memory_pass"].value = True

    data = json.loads((HARNESS / filename).read_text())
    scene = await load_scene_from_data(scene, data, name=filename)

    assert scene.agent_settings_link == "model-testing-harness.json"
    assert conversation.scene is scene
    assert conversation.character_knowledge_enabled is False
    assert conversation.knowledge_perspective_filter is False
    assert conversation.knowledge_memory_pass is False
