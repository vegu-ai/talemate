"""
Tests for the save-name guard on ``creator.fork_scene``.

Forking from a message reaches this path with a user-typed name. Like the
timeline fork, it must refuse a name that is unsafe as a filename or that
would land on an existing save, rather than escaping the save directory or
overwriting a save with forked data.
"""

import os
import re

import pytest

import talemate.instance as instance
from talemate.scene_message import NarratorMessage

from conftest import MockClient, MockScene, bootstrap_engine


class _ForkScene(MockScene):
    """Real ``Scene`` with ``save_dir`` pointed at a tmp dir.

    The parent exposes ``save_dir`` as a ``@property`` that joins the scenes
    directory with the project name; shadowing it with a class-level plain
    attribute lets the instance own it.
    """

    save_dir = None  # type: ignore[assignment]

    def __init__(self, save_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.save_dir = save_dir


@pytest.fixture
def creator(tmp_path):
    bootstrap_engine()
    scene = _ForkScene(save_dir=str(tmp_path))
    # distinct from the name, so a test can tell which one a generated save
    # name was built from
    scene.filename = "test_scene.json"
    scene.name = "Project Scene"
    scene.history.append(NarratorMessage("the scene begins"))
    agent = instance.get_agent("creator")
    agent.client = MockClient("test_client")
    agent.scene = scene
    return agent


@pytest.fixture
def emitted(monkeypatch):
    """Capture the agent's status emissions as ``(typ, message, kwargs)``."""
    calls = []
    monkeypatch.setattr(
        "talemate.agents.creator.assistant.emit",
        lambda typ, message=None, **kwargs: calls.append((typ, message, kwargs)),
    )
    return calls


def assert_refused(emitted, message):
    assert ("status", message, {"status": "error"}) in emitted


@pytest.fixture
def message_id(creator):
    return creator.scene.history[0].id


async def test_fork_writes_a_new_save(creator, message_id, tmp_path):
    fork_path = await creator.fork_scene(message_id, save_name="forked")

    assert fork_path == os.path.join(str(tmp_path), "forked.json")
    assert os.path.exists(fork_path)


@pytest.mark.parametrize("save_name", [None, ""])
async def test_fork_without_a_name_writes_a_timestamped_save(
    creator, message_id, tmp_path, save_name
):
    fork_path = await creator.fork_scene(message_id, save_name=save_name)

    assert fork_path is not None
    assert os.path.exists(fork_path)
    assert re.fullmatch(
        r"test-scene_fork_\d{8}T\d{6}Z\.json", os.path.basename(fork_path)
    )


async def test_fork_without_a_name_falls_back_to_the_project_name(
    creator, message_id, tmp_path
):
    """New scenes before their first save, and restored scenes, have no
    filename."""
    creator.scene.filename = ""

    fork_path = await creator.fork_scene(message_id)

    assert fork_path is not None
    assert os.path.exists(fork_path)
    assert os.path.basename(fork_path).startswith("project-scene_fork_")


@pytest.mark.parametrize(
    "scene_name,expected_base",
    [
        ("Fate/Stay Night", "fate-stay-night"),
        ("..", "scene"),
    ],
)
async def test_fork_without_a_name_slugs_the_base(
    creator, message_id, tmp_path, scene_name, expected_base
):
    """A scene name the guard would refuse must not make the no-name fork
    impossible — the caller supplied nothing, so there is nothing to correct."""
    creator.scene.filename = ""
    creator.scene.name = scene_name

    fork_path = await creator.fork_scene(message_id)

    assert fork_path is not None
    assert os.path.exists(fork_path)
    assert re.fullmatch(
        rf"{expected_base}_fork_\d{{8}}T\d{{6}}Z\.json", os.path.basename(fork_path)
    )


async def test_fork_refuses_a_name_that_escapes_the_save_dir(
    creator, message_id, tmp_path, emitted
):
    outside = tmp_path.parent / "escaped.json"

    assert await creator.fork_scene(message_id, save_name="../escaped") is None
    assert not outside.exists()
    assert_refused(emitted, "'../escaped' is not a valid save name")


@pytest.mark.parametrize("save_name", ["nested/fork", "..", "with\x00nul"])
async def test_fork_refuses_unsafe_names(creator, message_id, tmp_path, save_name):
    assert await creator.fork_scene(message_id, save_name=save_name) is None
    assert list(tmp_path.iterdir()) == []


async def test_fork_refuses_an_existing_save(creator, message_id, tmp_path, emitted):
    existing = tmp_path / "taken.json"
    existing.write_text("original")

    assert await creator.fork_scene(message_id, save_name="taken") is None
    assert existing.read_text() == "original"
    assert_refused(
        emitted, "A save named 'taken' already exists — pick a different name"
    )
