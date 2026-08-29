"""
Unit tests for the timeline websocket plugin.

The plugin exposes the scene timeline UX:

- ``list_revisions`` → changelog revision entries (plus the base snapshot)
- ``preview`` → message-history tail of the scene reconstructed at a revision
- ``fork`` → new scene file written from a revision

In-place rollback is not exposed — see ``test_rollback_route_is_gone``.

Both the active-scene path and the headless ``scene_path`` scaffold path
(used from the load screen) are covered.
"""

import json
import os

import pytest

from _changelog_test_helpers import make_changelog_scene
from talemate.changelog import (
    append_scene_delta,
    save_changelog,
)
from talemate.server.timeline import TimelinePlugin


class _MockWebsocketHandler:
    """Minimal handler stand-in: exposes ``scene`` and a queue_put list."""

    def __init__(self, scene):
        self._scene = scene
        self.messages: list[dict] = []

    @property
    def scene(self):
        return self._scene

    def queue_put(self, data):
        self.messages.append(data)

    def by_action(self, action):
        return [m for m in self.messages if m.get("action") == action]


def _message(idx: int) -> dict:
    return {
        "message": f"Narrator line {idx}",
        "id": idx,
        "typ": "narrator",
        "source": "ai",
        "flags": 0,
        "rev": idx,
    }


@pytest.fixture
def temp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
async def scene(temp_dir):
    """Changelog-backed scene with three revisions growing its history."""
    scene = make_changelog_scene(
        temp_dir,
        filename="test_scene.json",
        initial_serialize={"history": [], "intro": "Once upon a time"},
    )
    await save_changelog(scene)

    for rev in (1, 2, 3):
        scene.serialize = {
            "history": [_message(idx) for idx in range(1, rev + 1)],
            "intro": "Once upon a time",
        }
        assert await append_scene_delta(scene) == rev

    scene.rev = 3

    with open(os.path.join(temp_dir, scene.filename), "w") as f:
        json.dump(scene.serialize, f)

    return scene


@pytest.fixture
def plugin(scene):
    return TimelinePlugin(_MockWebsocketHandler(scene))


async def test_list_revisions_active(plugin):
    await plugin.handle_list_revisions({})

    (response,) = plugin.websocket_handler.by_action("revisions")
    data = response["data"]

    assert data["scene_path"] is None
    assert [entry["rev"] for entry in data["revisions"]] == [0, 1, 2, 3]
    assert data["revisions"][0]["is_base"] is True
    assert all("ts" in entry for entry in data["revisions"])


async def test_list_revisions_headless(scene, temp_dir):
    # no active scene — the scaffold is built from scene_path alone
    plugin = TimelinePlugin(_MockWebsocketHandler(None))
    scene_path = os.path.join(temp_dir, scene.filename)

    await plugin.handle_list_revisions({"scene_path": scene_path})

    (response,) = plugin.websocket_handler.by_action("revisions")
    data = response["data"]

    assert data["scene_path"] == scene_path
    assert [entry["rev"] for entry in data["revisions"]] == [0, 1, 2, 3]


async def test_list_revisions_requires_scene(plugin):
    plugin.websocket_handler._scene = None

    with pytest.raises(ValueError):
        await plugin.handle_list_revisions({})


async def test_preview(plugin):
    await plugin.handle_preview({"rev": 2, "max_messages": 1})

    (response,) = plugin.websocket_handler.by_action("preview")
    data = response["data"]

    assert data["rev"] == 2
    assert data["total_messages"] == 2
    assert [msg["id"] for msg in data["messages"]] == [2]
    assert data["intro"] == "Once upon a time"


async def test_preview_base_revision(plugin):
    await plugin.handle_preview({"rev": 0})

    (response,) = plugin.websocket_handler.by_action("preview")
    data = response["data"]

    assert data["messages"] == []
    assert data["total_messages"] == 0


async def test_preview_headless(scene, temp_dir):
    plugin = TimelinePlugin(_MockWebsocketHandler(None))
    scene_path = os.path.join(temp_dir, scene.filename)

    await plugin.handle_preview({"rev": 3, "scene_path": scene_path})

    (response,) = plugin.websocket_handler.by_action("preview")
    data = response["data"]

    assert data["scene_path"] == scene_path
    assert [msg["id"] for msg in data["messages"]] == [1, 2, 3]


async def test_fork(plugin, scene, temp_dir):
    await plugin.handle_fork({"rev": 2, "save_name": "forked"})

    fork_path = os.path.join(temp_dir, "forked.json")
    assert os.path.exists(fork_path)

    with open(fork_path) as f:
        fork_data = json.load(f)

    assert [msg["id"] for msg in fork_data["history"]] == [1, 2]
    assert fork_data["immutable_save"] is False
    assert fork_data["memory_id"]

    assert plugin.websocket_handler.by_action("operation_done")
    (load_request,) = [
        m
        for m in plugin.websocket_handler.messages
        if m.get("id") == "load_scene_request"
    ]
    assert load_request["data"]["path"] == fork_path


async def test_fork_headless(scene, temp_dir):
    plugin = TimelinePlugin(_MockWebsocketHandler(None))
    scene_path = os.path.join(temp_dir, scene.filename)

    await plugin.handle_fork(
        {"rev": 1, "save_name": "forked_headless", "scene_path": scene_path}
    )

    fork_path = os.path.join(temp_dir, "forked_headless.json")
    assert os.path.exists(fork_path)

    with open(fork_path) as f:
        fork_data = json.load(f)

    assert [msg["id"] for msg in fork_data["history"]] == [1]


async def test_fork_refuses_to_overwrite_an_existing_save(plugin, scene, temp_dir):
    """Forking onto the live scene's own name leaves that file untouched."""
    scene_path = os.path.join(temp_dir, scene.filename)
    with open(scene_path) as f:
        before = f.read()

    await plugin.handle_fork({"rev": 1, "save_name": "test_scene"})

    with open(scene_path) as f:
        assert f.read() == before

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "already exists" in done["error"]["message"]
    assert not [
        m
        for m in plugin.websocket_handler.messages
        if m.get("id") == "load_scene_request"
    ]


async def test_fork_refuses_a_name_that_escapes_the_save_dir(plugin, scene, tmp_path):
    outside = tmp_path.parent / "escaped.json"

    await plugin.handle_fork({"rev": 1, "save_name": f"../{outside.stem}"})

    assert not outside.exists()
    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "not a valid save name" in done["error"]["message"]


async def test_rollback_route_is_gone(plugin, scene, temp_dir):
    """No timeline action may overwrite an existing scene file."""
    scene_path = os.path.join(temp_dir, scene.filename)
    with open(scene_path) as f:
        before = f.read()

    await plugin.handle({"action": "rollback", "rev": 1})

    with open(scene_path) as f:
        assert f.read() == before

    assert plugin.websocket_handler.messages == []
    assert not os.path.exists(scene.backups_dir)
