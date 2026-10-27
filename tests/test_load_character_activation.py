"""
Tests for the activation state the load paths produce.

`Scene.actors` and `Scene.active_characters` are one fact: a character is
active when it has an actor. Both load paths have to leave the scene that way,
whatever the saved data says.
"""

import json
from unittest.mock import patch

import pytest

import talemate.agents.tts.voice_library as voice_library
import talemate.instance as instance
from conftest import MockScene, bootstrap_scene
from talemate.load import (
    handle_no_player_character,
    transfer_character,
    load_scene,
    load_scene_from_data,
    new_scene,
)
from talemate.character import Character
from talemate.config import get_config
from talemate.context import scene_is_loading
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
    monkeypatch.setattr(memory, "drop_db", _noop, raising=False)
    monkeypatch.setattr(memory, "get_document", _no_documents, raising=False)
    voice_library.VOICE_LIBRARY = voice_library.VoiceLibrary(voices={})

    return scene


def _character(name: str) -> dict:
    return {"name": name, "description": f"{name} is here.", "color": "#ffffff"}


def _character_with_cover(name: str) -> dict:
    return {**_character(name), "cover_image": "some-asset-id"}


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
async def test_load_keeps_one_entry_per_actor(load_env):
    """A saved list naming a character twice yields one entry, not two.

    A second entry outlives the character's actor and hides it from both
    rosters: the active list is built from the actors, the inactive one from
    the names.
    """
    scene = await load_scene_from_data(
        load_env,
        _scene_data(["Alice", "Alice"], ["Alice"]),
        name="activation.json",
    )

    assert scene.active_characters == ["Alice"]


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


@pytest.mark.asyncio
async def test_transfer_character_refuses_a_name_the_scene_has(load_env, tmp_path):
    """The scene already holds a Bob, so the imported one is refused: two
    objects under one name give two actors and one name."""
    source = tmp_path / "source.json"
    source_data = _scene_data(["Bob"], ["Bob"])
    source_data["character_data"]["Bob"] = _character_with_cover("Bob")
    source.write_text(json.dumps(source_data))
    existing = Character(**_character("Bob"))
    await load_env.add_actor(load_env.Actor(existing, None), commit_to_memory=False)

    with (
        patch("talemate.load.transfer_character_cover_image") as cover,
        pytest.raises(ValueError, match='Name "Bob" already exists.'),
    ):
        await transfer_character(load_env, str(source), "Bob")

    # the refusal comes before any asset is copied into the target scene
    cover.assert_not_called()
    assert load_env.character_data["Bob"] is existing
    assert [actor.character for actor in load_env.actors] == [existing]
    assert load_env.active_characters == ["Bob"]


@pytest.mark.asyncio
async def test_default_player_character_sends_one_activation(
    load_env, activation_signal, monkeypatch
):
    """The default player is created by activate_character alone, so the
    signal fires once. Adding the actor first made the helper a no-op that
    sent nothing."""
    activated = []

    async def record(event):
        activated.append(event.character)

    activation_signal.connect(record)
    config = get_config()
    monkeypatch.setattr(config.game.default_player_character, "name", "Zed")

    await handle_no_player_character(load_env)

    assert [character.name for character in activated] == ["Zed"]
    assert load_env.active_characters == ["Zed"]
    assert isinstance(load_env.get_character("Zed").actor, load_env.Player)


@pytest.mark.asyncio
async def test_a_scene_whose_player_is_inactive_adopts_it(
    load_env, activation_signal, monkeypatch, tmp_path
):
    """The configured default player name may already belong to a character in
    the scene. That character is adopted, not shadowed by a blank default.

    The activation it sends carries the loading context, which is what keeps
    subscribers that respond to gameplay activation out of
    the load path.
    """
    config = get_config()
    monkeypatch.setattr(config.game.default_player_character, "name", "Zed")
    scene_data = _scene_data([], ["Zed"])
    scene_data["character_data"]["Zed"]["is_player"] = True
    during_load = []

    async def record(event):
        during_load.append(scene_is_loading.get() is event.scene)

    activation_signal.connect(record)
    scene_file = tmp_path / "activation.json"
    scene_file.write_text(json.dumps(scene_data))

    scene = await load_scene(load_env, str(scene_file))

    assert scene.active_characters == ["Zed"]
    assert scene.character_data["Zed"].description == "Zed is here."
    assert [actor.character for actor in scene.actors] == [scene.character_data["Zed"]]
    assert during_load == [True]


@pytest.mark.asyncio
async def test_transfer_character_refuses_a_name_that_differs_only_in_case(
    load_env, tmp_path
):
    """The scene holds Bob; importing bob would give the scene two records its
    own lookup cannot tell apart, and the deactivate at the end of the transfer
    would then take Bob out instead."""
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_scene_data(["bob"], ["bob"])))
    existing = Character(**_character("Bob"))
    await load_env.add_actor(load_env.Actor(existing, None), commit_to_memory=False)

    with pytest.raises(ValueError, match='Name "bob" already exists.'):
        await transfer_character(load_env, str(source), "bob")

    assert list(load_env.character_data) == ["Bob"]
    assert load_env.active_characters == ["Bob"]


@pytest.mark.asyncio
async def test_load_keeps_a_legacy_scene_with_two_case_variant_names(load_env):
    """A scene saved before names were compared without case holds both records.
    The load attaches an actor to each: the guard refuses a NEW record under a
    taken name, not a record the scene file already carries."""
    scene = await load_scene_from_data(
        load_env,
        _scene_data(["Bob", "bob"], ["Bob", "bob"]),
        name="activation.json",
    )

    assert scene.active_characters == ["Bob", "bob"]
    assert list(scene.inactive_characters) == []


@pytest.mark.asyncio
async def test_a_taken_default_player_name_is_not_adopted(load_env, monkeypatch):
    """Only a character the scene itself calls the player is adopted. Turning an
    NPC into the player is written into the next save."""
    config = get_config()
    monkeypatch.setattr(config.game.default_player_character, "name", "Zed")

    scene = await load_scene_from_data(
        load_env, _scene_data([], ["Zed"]), name="activation.json"
    )

    assert scene.character_data["Zed"].is_player is False
    assert scene.active_characters == []
    assert scene.get_player_character() is None
