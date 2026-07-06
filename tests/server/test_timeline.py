"""
Unit tests for the timeline websocket plugin.

The plugin exposes the scene timeline / rollback UX:

- ``list_revisions`` → changelog revision entries (plus the base snapshot)
- ``preview`` → message-history tail of the scene reconstructed at a revision
- ``fork`` → new scene file written from a revision
- ``rollback`` → in-place rollback of the active scene (backup, restore,
  save) — exercised here with the scene-side effects spied, since the real
  ``Scene.restore``/``Scene.save`` need a full agent stack.

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

    # the scene file itself, for pre-rollback backups
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


async def test_rollback(plugin, scene, temp_dir, monkeypatch):
    order: list[tuple] = []

    async def _spy_restore(from_rev=None, **kwargs):
        order.append(("restore", from_rev))
        # the real restore() loads via a temp file, which clears the
        # filename and leaves rev resolved against the temp name
        scene.filename = None
        scene.rev = 0

    async def _spy_save(**kwargs):
        order.append(("save", scene.filename, scene.rev))

    async def _spy_emit_history():
        order.append(("emit_history",))

    monkeypatch.setattr(scene, "restore", _spy_restore)
    monkeypatch.setattr(scene, "save", _spy_save)
    monkeypatch.setattr(scene, "emit_history", _spy_emit_history)
    scene.immutable_save = False

    await plugin.handle_rollback({"rev": 1})

    # filename and rev were pointed back at the original scene file before saving
    assert order == [("restore", 1), ("save", "test_scene.json", 3), ("emit_history",)]

    # a pre-rollback backup of the scene file was written
    backups = os.listdir(scene.backups_dir)
    assert len(backups) == 1
    assert backups[0].startswith("test_scene_pre_rollback_")

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "error" not in done


async def test_rollback_rejects_immutable_save(plugin, scene):
    scene.immutable_save = True

    await plugin.handle_rollback({"rev": 1})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "immutable" in done["error"]["message"]


async def test_rollback_requires_saved_scene(plugin, scene):
    scene.filename = ""

    await plugin.handle_rollback({"rev": 1})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "saved" in done["error"]["message"]
