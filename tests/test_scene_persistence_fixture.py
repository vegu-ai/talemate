import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import talemate.instance as instance
from talemate.character import Character
from talemate.load import load_scene_from_data
from talemate.scene_message import NarratorMessage
from talemate.world_state import ContextPin


@pytest.mark.parametrize("reset", [False, True])
@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_real_save_as_and_reload(
    persistence_scene_factory, monkeypatch, reset, mode
):
    scene = persistence_scene_factory()
    scene.knowledge_eligibility = mode
    scene.name = "Persistence fixture"
    scene.project_name = "persistence-fixture"
    scene.intro = '"Saved intro."\nSecond line.'
    scene.character_data["Hero"] = Character(name="Hero", greeting_text="Raw greeting")
    scene.history = [NarratorMessage(message="Saved history", source="ai")]
    scene.world_state.pins["missing"] = ContextPin(entry_id="missing", active=True)
    original_memory_id = scene.memory_id
    memory = instance.get_agent("memory")
    close = Mock(wraps=memory.close_db)
    drop = Mock(wraps=memory.drop_db)
    setup = Mock(wraps=memory._set_db)
    monkeypatch.setattr(memory, "close_db", close)
    monkeypatch.setattr(memory, "drop_db", drop)
    monkeypatch.setattr(memory, "_set_db", setup)

    await scene.save(copy_name="first.json")

    close.assert_called_once_with(scene)
    drop.assert_called_once_with()
    setup.assert_called_once_with()
    assert scene.memory_id != original_memory_id
    saved_path = Path(scene.full_path)
    saved_data = json.loads(saved_path.read_text())
    assert saved_data["intro"] == '"Saved intro."\nSecond line.'
    assert saved_data["knowledge_eligibility"] == mode
    assert saved_data["history"][0]["message"] == "Saved history"
    assert "missing" in saved_data["world_state"]["pins"]
    scene.intro = "Unsaved edit"

    reloaded = persistence_scene_factory()
    memory = instance.get_agent("memory")
    lookup = Mock(wraps=memory._get_document)
    monkeypatch.setattr(memory, "_get_document", lookup)
    await load_scene_from_data(reloaded, saved_data, reset=reset, name=str(saved_path))

    assert reloaded is not scene
    assert reloaded.knowledge_eligibility == mode
    assert reloaded.intro == '"Saved intro."\nSecond line.'
    assert reloaded.character_data["Hero"].greeting_text == "Raw greeting"
    assert [message.message for message in reloaded.history] == (
        [] if reset else ["Saved history"]
    )
    lookup.assert_called_once_with([] if reset else ["missing"])
    assert reloaded.world_state.pins == {}

    reloaded.intro = "Second saved intro"
    await reloaded.save(copy_name="second.json")
    second_path = Path(reloaded.full_path)
    assert second_path != saved_path
    assert json.loads(saved_path.read_text())["intro"] == '"Saved intro."\nSecond line.'
    second_data = json.loads(second_path.read_text())
    third = persistence_scene_factory()
    await load_scene_from_data(third, second_data, name=str(second_path))
    assert third.intro == "Second saved intro"
    assert third.filename == "second.json"
    assert third.knowledge_eligibility == mode
