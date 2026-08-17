"""Unit tests for ``Scene.restore()`` — reset to the scene's restore point.

The timeline is fork-only, so a restore point save file is the only thing
``restore()`` ever loads.
"""

from __future__ import annotations

import os

import pytest

import talemate.load
from talemate.tale_mate import Scene


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setattr(
        Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)), raising=True
    )
    scene = Scene()
    scene.project_name = "test_project"
    os.makedirs(scene.save_dir, exist_ok=True)
    scene.filename = "scene.json"
    scene.restore_from = "baseline.json"

    monkeypatch.setattr(scene, "reset", lambda: None)
    monkeypatch.setattr(scene, "emit_status", lambda **kwargs: None)

    async def noop():
        return None

    monkeypatch.setattr(scene, "remove_all_actors", noop)
    monkeypatch.setattr(scene, "reset_memory", noop)
    return scene


@pytest.fixture
def loaded(monkeypatch):
    """Record what ``restore()`` hands to ``load_scene``."""
    calls = []

    async def fake_load_scene(scene, path, *args, **kwargs):
        calls.append(path)
        return scene

    monkeypatch.setattr(talemate.load, "load_scene", fake_load_scene)
    return calls


async def test_restore_loads_the_restore_point(scene, loaded):
    await scene.restore()

    assert loaded == [os.path.join(scene.save_dir, "baseline.json")]
    # the restored state is not the save it came from — it needs a name of its own
    assert scene.filename is None


async def test_restore_saves_a_copy_when_asked(scene, loaded, monkeypatch):
    saved = {}

    async def fake_save(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(scene, "save", fake_save)

    await scene.restore(save_as="checkpoint")

    assert loaded == [os.path.join(scene.save_dir, "baseline.json")]
    assert saved == {"save_as": True, "copy_name": "checkpoint"}
    assert scene.restore_from == "baseline.json"


async def test_restore_without_a_restore_point_does_nothing(scene, loaded):
    scene.restore_from = ""

    await scene.restore()

    assert loaded == []
    assert scene.filename == "scene.json"
