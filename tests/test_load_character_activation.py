"""
Tests for the activation state the load paths produce.

`Scene.actors` and `Scene.active_characters` are one fact: a character is
active when it has an actor. Both load paths have to leave the scene that way,
whatever the saved data says.
"""

import json

import pytest

import talemate.agents.tts.voice_library as voice_library
import talemate.instance as instance
from conftest import MockScene, bootstrap_scene
from talemate.load import (
    transfer_character,
    load_scene_from_data,
    new_scene,
)
from talemate.tale_mate import Scene


async def _noop(*args, **kwargs):
    return None


async def _no_documents(*args, **kwargs):
    return {}


@pytest.fixture
def load_env(tmp_path, monkeypatch):
    scene = MockScene()
    bootstrap_scene(scene)
    monkeypatch.setattr(
        Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)), raising=True
    )
    scene.project_name = "activation-scene"

    memory = instance.get_agent("memory")
    monkeypatch.setattr(memory, "set_db", _noop, raising=False)
    monkeypatch.setattr(memory, "get_document", _no_documents, raising=False)
    voice_library.VOICE_LIBRARY = voice_library.VoiceLibrary(voices={})

    return scene


def _character(name: str) -> dict:
    return {"name": name, "description": f"{name} is here.", "color": "#ffffff"}


def _scene_data(active: list[str], characters: list[str]) -> dict:
    data = new_scene()
    data["character_data"] = {name: _character(name) for name in characters}
    data["active_characters"] = active
    return data


@pytest.mark.asyncio
async def test_load_activates_the_saved_characters(load_env):
    scene = await load_scene_from_data(
        load_env, _scene_data(["Alice"], ["Alice", "Bob"]), name="activation.json"
    )

    assert scene.active_characters == ["Alice"]
    assert "Alice" in scene.character_names
    assert list(scene.inactive_characters) == ["Bob"]


@pytest.mark.asyncio
async def test_load_drops_an_active_name_that_has_no_character(load_env):
    """A saved name with no character data cannot become an actor, so it must
    not stay in the active list either."""
    scene_data = _scene_data(["Alice", "Ghost"], ["Alice"])

    scene = await load_scene_from_data(load_env, scene_data, name="activation.json")

    assert scene.active_characters == ["Alice"]
    # the scene works on its own copy of the saved list
    assert scene_data["active_characters"] == ["Alice", "Ghost"]


@pytest.mark.asyncio
async def test_transfer_character_leaves_no_actor(load_env, tmp_path):
    """An imported character is inactive, so it gets no actor."""
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_scene_data(["Bob"], ["Bob"])))

    await transfer_character(load_env, str(source), "Bob")

    assert "Bob" in load_env.character_data
    assert "Bob" not in load_env.character_names
    assert "Bob" not in load_env.active_characters
    assert "Bob" in load_env.inactive_characters
