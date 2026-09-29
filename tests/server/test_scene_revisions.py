"""
Unit tests for Scene revisions websocket plugin.

The plugin exposes the scene revisions UX:

- ``list_revisions`` → a page of revision groups (one per message span)
- ``preview`` → message-history tail of the scene reconstructed at a revision
- ``fork`` → new scene file written from a revision

In-place rollback is not exposed — see ``test_rollback_route_is_gone``.

Both the active-scene path and the headless ``scene_path`` scaffold path
(used from the load screen) are covered.
"""

import json
import os

import pytest

from _changelog_test_helpers import persist_test_mutation, make_changelog_scene
from talemate.changelog import save_changelog
from talemate.storage.changelog import SnapshotStore
from talemate.server.scene_revisions import SceneRevisionsPlugin


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
        assert await persist_test_mutation(scene) == rev

    scene.rev = 3

    with open(os.path.join(temp_dir, scene.filename), "w") as f:
        json.dump(scene.serialize, f)

    return scene


@pytest.fixture
def plugin(scene):
    return SceneRevisionsPlugin(_MockWebsocketHandler(scene))


async def test_list_revisions_active(plugin):
    await plugin.handle_list_revisions({})

    (response,) = plugin.websocket_handler.by_action("revisions")
    data = response["data"]

    assert data["scene_path"] is None
    assert [group["revisions"][0]["rev"] for group in data["groups"]] == [3, 2, 1, 0]
    assert data["groups"][0]["message"]["text"] == "Narrator line 3"
    assert data["groups"][-1]["revisions"][0]["is_base"] is True
    assert data["total_revisions"] == 4
    assert data["next_before_rev"] is None


async def test_list_revisions_passes_the_query(plugin):
    await plugin.handle_list_revisions(
        {
            "request_id": "page-2",
            "query": {"span": 2, "limit": 1, "before_rev": 3, "search": "LINE 2"},
        }
    )

    (response,) = plugin.websocket_handler.by_action("revisions")
    data = response["data"]

    assert data["request_id"] == "page-2"
    assert data["before_rev"] == 3
    assert [
        [entry["rev"] for entry in group["revisions"]] for group in data["groups"]
    ] == [[2, 1]]
    assert (data["groups"][0]["first_message"], data["groups"][0]["last_message"]) == (
        1,
        2,
    )


async def test_list_revisions_rejects_an_invalid_span(plugin):
    with pytest.raises(ValueError):
        await plugin.handle_list_revisions({"query": {"span": 0}})


async def test_list_revisions_headless(scene, temp_dir):
    # no active scene — the scaffold is built from scene_path alone
    plugin = SceneRevisionsPlugin(_MockWebsocketHandler(None))
    scene_path = os.path.join(temp_dir, scene.filename)

    await plugin.handle_list_revisions({"scene_path": scene_path})

    (response,) = plugin.websocket_handler.by_action("revisions")
    data = response["data"]

    assert data["scene_path"] == scene_path
    assert data["total_revisions"] == 4


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
    plugin = SceneRevisionsPlugin(_MockWebsocketHandler(None))
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
    plugin = SceneRevisionsPlugin(_MockWebsocketHandler(None))
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


async def test_fork_refuses_a_blank_name(plugin, scene, temp_dir):
    """A name that is only whitespace would write a save nobody can identify."""
    for save_name in ("   ", ""):
        plugin.websocket_handler.messages.clear()

        await plugin.handle_fork({"rev": 1, "save_name": save_name})

        (done,) = plugin.websocket_handler.by_action("operation_done")
        assert "not a valid save name" in done["error"]["message"]

    assert [f for f in os.listdir(temp_dir) if f.endswith(".json")] == [scene.filename]


async def test_rollback_route_is_gone(plugin, scene, temp_dir):
    """No scene revision action may overwrite an existing scene file."""
    scene_path = os.path.join(temp_dir, scene.filename)
    with open(scene_path) as f:
        before = f.read()

    await plugin.handle({"action": "rollback", "rev": 1})

    with open(scene_path) as f:
        assert f.read() == before

    assert plugin.websocket_handler.messages == []
    assert not os.path.exists(os.path.join(scene.save_dir, "backups"))


async def test_damaged_preview_reports_selected_revision_and_request(plugin, scene):
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"damaged", head.manifest.history_chunks[-1]),
        )
    )
    await plugin.handle_preview({"rev": 3, "request_id": "preview-3"})
    (failed,) = plugin.websocket_handler.by_action("operation_done")
    assert failed["error"]
    assert failed["request_id"] == "preview-3"
    assert failed["failed_action"] == "preview"
    assert failed["rev"] == 3
    assert failed["code"] == "damaged_blob"
    assert "blob" not in failed["error"]["message"]
    assert not plugin.websocket_handler.by_action("preview")
    await plugin.handle_preview({"rev": 2})
    assert plugin.websocket_handler.by_action("preview")
    await plugin.handle_fork({"rev": 3, "save_name": "damaged"})
    assert not os.path.exists(os.path.join(scene.save_dir, "damaged.json"))


async def test_revisions_show_inherited_origins_and_fork_point(plugin, scene):
    store = SnapshotStore(scene.save_dir)
    await store.fork(scene.filename, 2, "branch.json")
    await plugin.handle_list_revisions(
        {"scene_path": os.path.join(scene.save_dir, "branch.json")}
    )
    (response,) = plugin.websocket_handler.by_action("revisions")
    entries = [
        entry for group in response["data"]["groups"] for entry in group["revisions"]
    ]
    assert [entry["rev"] for entry in entries] == [2, 1, 0]
    assert all(
        entry["origin"] == scene.filename and entry["inherited"] for entry in entries
    )
    assert entries[0]["is_fork"]


async def test_missing_revision_cannot_create_a_fork(plugin, scene):
    await plugin.handle_fork({"rev": 500, "save_name": "missing"})
    assert not os.path.exists(os.path.join(scene.save_dir, "missing.json"))
    (failed,) = plugin.websocket_handler.by_action("operation_done")
    assert failed["error"]


async def test_save_without_revisions_has_an_empty_list(scene):
    plugin = SceneRevisionsPlugin(_MockWebsocketHandler(scene))
    await plugin.handle_list_revisions(
        {"scene_path": os.path.join(scene.save_dir, "new.json")}
    )
    (response,) = plugin.websocket_handler.by_action("revisions")
    assert response["data"]["groups"] == []
    assert response["data"]["total_revisions"] == 0
