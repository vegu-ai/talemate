import json
import os
from unittest import mock

import pytest

import talemate.instance as instance
from _changelog_test_helpers import make_changelog_scene, persist_test_mutation
from conftest import MockScene, bootstrap_scene
from talemate.changelog import fork_scene_at_revision
from talemate.config.schema import Config, RecentScene, RecentScenes
from talemate.config.state import cleanup_removed_recent_scenes
from talemate.load import load_scene_from_data
from talemate.tale_mate import Scene


async def _noop(*args, **kwargs):
    return None


async def _no_documents(*args, **kwargs):
    return {}


@pytest.fixture
def scene_env(tmp_path, monkeypatch):
    """Agent stack and scenes directory a scene can be loaded and saved in."""
    scene = MockScene()
    bootstrap_scene(scene)
    monkeypatch.setattr(
        Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)), raising=True
    )
    scene.project_name = "deprecated-project"

    memory = instance.get_agent("memory")
    monkeypatch.setattr(memory, "set_db", _noop, raising=False)
    monkeypatch.setattr(memory, "get_document", _no_documents, raising=False)
    # the abstract MemoryAgent's close_db takes no scene, the real one does
    monkeypatch.setattr(memory, "close_db", lambda *args, **kwargs: None)

    return scene


def _scene_data(**overrides) -> dict:
    data = {
        "name": "Simulation Suite",
        "history": [],
        "archived_history": [],
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_load_reads_the_browser_flags(scene_env):
    scene = await load_scene_from_data(
        scene_env, _scene_data(hidden=True, deprecated=True)
    )

    assert scene.hidden is True
    assert scene.deprecated is True


@pytest.mark.asyncio
async def test_load_defaults_the_browser_flags_off(scene_env):
    scene = await load_scene_from_data(scene_env, _scene_data())

    assert scene.hidden is False
    assert scene.deprecated is False


@pytest.mark.asyncio
async def test_serialize_carries_the_browser_flags(scene_env):
    scene = await load_scene_from_data(
        scene_env, _scene_data(hidden=True, deprecated=True)
    )

    assert scene.serialize["hidden"] is True
    assert scene.serialize["deprecated"] is True


@pytest.mark.asyncio
async def test_save_as_clears_the_browser_flags(scene_env):
    scene_env.name = "Simulation Suite"
    scene_env.hidden = True
    scene_env.deprecated = True
    scene_env.immutable_save = True

    with (
        mock.patch(
            "talemate.tale_mate.Scene.add_to_recent_scenes", new=mock.AsyncMock()
        ),
        mock.patch("talemate.tale_mate.Scene.commit_to_memory", new=mock.AsyncMock()),
    ):
        await scene_env.save(copy_name="my-playthrough.json")

    assert scene_env.hidden is False
    assert scene_env.deprecated is False

    with open(os.path.join(scene_env.save_dir, "my-playthrough.json")) as file:
        written = json.load(file)

    assert written["hidden"] is False
    assert written["deprecated"] is False


def test_recent_scenes_push_skips_a_hidden_scene(scene_env):
    scene_env.filename = "shipped.json"
    recents = RecentScenes(scenes=[])

    scene_env.hidden = True
    recents.push(scene_env)
    assert recents.scenes == []

    scene_env.hidden = False
    recents.push(scene_env)
    assert [entry.filename for entry in recents.scenes] == ["shipped.json"]


def _recent(path: str) -> RecentScene:
    return RecentScene(
        name="Simulation Suite",
        path=path,
        filename=os.path.basename(path),
        date="2026-08-29T00:00:00",
    )


def test_cleanup_drops_hidden_recent_scenes(tmp_path):
    hidden = tmp_path / "shipped.json"
    hidden.write_text(json.dumps({"name": "Shipped", "hidden": True}))

    user_save = tmp_path / "my-playthrough.json"
    user_save.write_text(json.dumps({"name": "My Playthrough"}))

    config = Config(
        recent_scenes=RecentScenes(
            scenes=[
                _recent(str(hidden)),
                _recent(str(user_save)),
                _recent(str(tmp_path / "gone.json")),
            ]
        )
    )

    cleanup_removed_recent_scenes(config)

    assert [entry.path for entry in config.recent_scenes.scenes] == [str(user_save)]


@pytest.mark.asyncio
async def test_reconstructive_fork_writes_a_visible_scene(tmp_path):
    # the changelog bootstrap snapshots scene files raw, so a snapshot of a
    # hidden scene carries the flags a reconstruction would otherwise inherit
    scene = make_changelog_scene(
        str(tmp_path),
        filename="shipped.json",
        initial_serialize={
            "name": "Shipped",
            "hidden": True,
            "deprecated": True,
            "history": [],
            "characters": [],
        },
    )

    await persist_test_mutation(scene)

    fork_path = await fork_scene_at_revision(scene, scene.rev, "my-fork")

    with open(fork_path) as file:
        forked = json.load(file)

    assert forked["hidden"] is False
    assert forked["deprecated"] is False


@pytest.mark.asyncio
async def test_an_ordinary_save_keeps_the_browser_flags(scene_env):
    # a hidden scene that is not immutable saves over its own file; the flags
    # have to come back out of serialize or the file silently loses them
    scene_env.name = "Shipped"
    scene_env.filename = "shipped.json"
    scene_env.hidden = True
    scene_env.deprecated = True

    with mock.patch(
        "talemate.tale_mate.Scene.add_to_recent_scenes", new=mock.AsyncMock()
    ):
        await scene_env.save()

    with open(os.path.join(scene_env.save_dir, "shipped.json")) as file:
        written = json.load(file)

    assert written["hidden"] is True
    assert written["deprecated"] is True
