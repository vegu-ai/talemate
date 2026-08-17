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

from _changelog_test_helpers import persist_test_mutation, make_changelog_scene
from talemate.changelog import save_changelog
from talemate.scene_message import NarratorMessage
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
        assert await persist_test_mutation(scene) == rev

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


async def test_fork_warns_on_unverifiable_chain(plugin, scene, temp_dir, monkeypatch):
    """Fork proceeds on an unverifiable chain with a warning status."""
    latest_path = os.path.join(scene.changelog_dir, f"{scene.filename}.latest.json")
    with open(latest_path, "w") as f:
        f.write("not json")

    emitted = []
    monkeypatch.setattr(
        "talemate.server.websocket_plugin.emit",
        lambda typ, *args, **kwargs: emitted.append((typ, kwargs)),
    )

    await plugin.handle_fork({"rev": 2, "save_name": "forked_unverifiable"})

    assert os.path.exists(os.path.join(temp_dir, "forked_unverifiable.json"))
    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "error" not in done

    status_emissions = [kw for typ, kw in emitted if typ == "status"]
    assert status_emissions
    assert status_emissions[0]["status"] == "warning"
    assert "could not be verified" in status_emissions[0]["message"]


async def test_fork_warning_names_quarantined_segments(
    plugin, scene, temp_dir, monkeypatch
):
    """With a quarantine marker, the fork warning says why — not 'latest snapshot'."""
    from talemate.changelog import (
        _get_latest_changelog_file,
        quarantine_corrupted_changelog_files,
    )

    _, log_path = _get_latest_changelog_file(scene)
    with open(log_path, "w") as f:
        f.write('{"deltas": [{"rev": 3, "delta": ')
    quarantine_corrupted_changelog_files(scene)

    emitted = []
    monkeypatch.setattr(
        "talemate.server.websocket_plugin.emit",
        lambda typ, *args, **kwargs: emitted.append((typ, kwargs)),
    )

    await plugin.handle_fork({"rev": 2, "save_name": "forked_quarantined"})

    assert os.path.exists(os.path.join(temp_dir, "forked_quarantined.json"))
    status_emissions = [kw for typ, kw in emitted if typ == "status"]
    assert status_emissions
    assert status_emissions[0]["status"] == "warning"
    assert "quarantined" in status_emissions[0]["message"]


async def test_fork_warns_on_diverged_chain(plugin, scene, temp_dir, monkeypatch):
    """Fork proceeds on a diverged chain but emits a warning status."""
    latest_path = os.path.join(scene.changelog_dir, f"{scene.filename}.latest.json")
    with open(latest_path) as f:
        latest = json.load(f)
    latest["intro"] = "rewritten outside the chain"
    with open(latest_path, "w") as f:
        json.dump(latest, f)

    emitted = []
    monkeypatch.setattr(
        "talemate.server.websocket_plugin.emit",
        lambda typ, *args, **kwargs: emitted.append((typ, kwargs)),
    )

    await plugin.handle_fork({"rev": 2, "save_name": "forked_diverged"})

    # the fork is still written
    assert os.path.exists(os.path.join(temp_dir, "forked_diverged.json"))
    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "error" not in done

    status_emissions = [kw for typ, kw in emitted if typ == "status"]
    assert status_emissions
    assert status_emissions[0]["status"] == "warning"
    assert "diverged" in status_emissions[0]["message"]


async def test_preview_on_diverged_chain_logs_warning(plugin, scene):
    from structlog.testing import capture_logs

    latest_path = os.path.join(scene.changelog_dir, f"{scene.filename}.latest.json")
    with open(latest_path) as f:
        latest = json.load(f)
    latest["intro"] = "rewritten outside the chain"
    with open(latest_path, "w") as f:
        json.dump(latest, f)

    with capture_logs() as logs:
        await plugin.handle_preview({"rev": 2, "max_messages": 1})

    assert plugin.websocket_handler.by_action("preview")
    assert any(
        log["event"] == "preview_from_diverged_chain" and log["log_level"] == "warning"
        for log in logs
    )


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
    """No timeline action may overwrite an existing scene file."""
    scene_path = os.path.join(temp_dir, scene.filename)
    with open(scene_path) as f:
        before = f.read()

    await plugin.handle({"action": "rollback", "rev": 1})

    with open(scene_path) as f:
        assert f.read() == before

    assert plugin.websocket_handler.messages == []
    assert not os.path.exists(os.path.join(scene.save_dir, "backups"))


def _emit_history_spy(scene):
    """Stand-in for ``Scene.emit_history``, which needs a full agent stack.

    Records ``scene.rev`` at call time so ordering against the reset is
    observable.
    """
    calls: list[int] = []

    async def emit_history():
        calls.append(scene.rev)

    emit_history.calls = calls
    return emit_history


def _diverge_chain(scene):
    """Rewrite the latest snapshot outside the chain (end-state divergence)."""
    latest_path = os.path.join(scene.changelog_dir, f"{scene.filename}.latest.json")
    with open(latest_path) as f:
        latest = json.load(f)
    latest["intro"] = "rewritten outside the chain"
    with open(latest_path, "w") as f:
        json.dump(latest, f)


async def test_list_revisions_reports_chain_ok(plugin):
    await plugin.handle_list_revisions({})

    (response,) = plugin.websocket_handler.by_action("revisions")
    assert response["data"]["chain"] == {"status": "ok", "detail": None}
    assert response["data"]["rebase"] is None


async def test_list_revisions_reports_diverged_chain(plugin, scene):
    _diverge_chain(scene)

    await plugin.handle_list_revisions({})

    (response,) = plugin.websocket_handler.by_action("revisions")
    assert response["data"]["chain"]["status"] == "diverged"


async def test_repair_rebases_diverged_chain(plugin, scene, monkeypatch):
    _diverge_chain(scene)
    emit_history = _emit_history_spy(scene)
    monkeypatch.setattr(scene, "emit_history", emit_history)

    await plugin.handle_repair({})

    # the frontend is re-fed the history: its fork targets named revisions of
    # the chain that was just archived
    assert emit_history.calls == [0]

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "error" not in done

    # the active scene restarts the revision namespace
    assert scene.rev == 0

    # the handler pushes a refreshed revisions list: only the base remains,
    # the chain reports healthy, and the rebase marker explains the gap
    (revisions_msg,) = plugin.websocket_handler.by_action("revisions")
    data = revisions_msg["data"]
    assert [entry["rev"] for entry in data["revisions"]] == [0]
    assert data["chain"]["status"] == "ok"
    assert data["rebase"]["rebases"][0]["rebased_from_rev"] == 3

    # the old chain is preserved under changelog/rebased-*/
    preserved = [d for d in os.listdir(scene.changelog_dir) if d.startswith("rebased-")]
    assert len(preserved) == 1
    assert os.listdir(os.path.join(scene.changelog_dir, preserved[0]))

    # the chain reconstructs exactly again
    from talemate.changelog import check_chain_divergence

    assert await check_chain_divergence(scene) == []


async def test_repair_refuses_healthy_chain(plugin):
    await plugin.handle_repair({})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "Nothing to repair" in done["error"]["message"]


async def test_repair_headless(scene, temp_dir):
    """Repair works from the load screen via scene_path (no active scene)."""
    _diverge_chain(scene)
    plugin = TimelinePlugin(_MockWebsocketHandler(None))
    scene_path = os.path.join(temp_dir, scene.filename)

    await plugin.handle_repair({"scene_path": scene_path})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "error" not in done
    (revisions_msg,) = plugin.websocket_handler.by_action("revisions")
    assert revisions_msg["data"]["scene_path"] == scene_path
    assert revisions_msg["data"]["chain"]["status"] == "ok"
    # the active scene's rev is untouched (there is none)
    assert scene.rev == 3


async def test_repair_by_path_syncs_the_loaded_scene(
    plugin, scene, temp_dir, monkeypatch
):
    """A scene_path naming the scene that is loaded right now must repair the
    live scene, not a disk-only scaffold that leaves it on the old namespace."""
    _diverge_chain(scene)
    emit_history = _emit_history_spy(scene)
    monkeypatch.setattr(scene, "emit_history", emit_history)
    message = NarratorMessage("Narrator line 3", id=3, rev=3)
    scene.history = [message]
    scene_path = os.path.join(temp_dir, scene.filename)

    await plugin.handle_repair({"scene_path": scene_path})

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "error" not in done
    assert scene.rev == 0
    assert message.rev == 0
    assert emit_history.calls == [0]

    (revisions_msg,) = plugin.websocket_handler.by_action("revisions")
    assert revisions_msg["data"]["scene_path"] == scene_path
    assert revisions_msg["data"]["chain"]["status"] == "ok"


async def test_repair_reports_write_failure(plugin, scene, monkeypatch):
    """A filesystem failure during the rebase is reported, not raised out of
    the handler — the chain was restored, so the session stays usable."""
    _diverge_chain(scene)

    base_path = os.path.join(scene.changelog_dir, f"{scene.filename}.base.json")
    real_replace = os.replace
    failed = []

    def failing_replace(src, dst, **kwargs):
        if dst == base_path and not failed:
            failed.append(dst)
            raise OSError("no space left on device")
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)

    await plugin.handle_repair({})

    monkeypatch.undo()

    (done,) = plugin.websocket_handler.by_action("operation_done")
    assert "Repair failed" in done["error"]["message"]
    assert "no space left" in done["error"]["message"]
    assert not plugin.websocket_handler.by_action("revisions")
    assert scene.rev == 3
