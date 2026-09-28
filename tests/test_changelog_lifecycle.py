import asyncio
import json
import math
import threading
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.changelog import (
    SceneChangelog,
    capture_snapshot,
    delete_scene_revisions,
    fork_scene_at_revision,
    save_changelog,
    scene_ref_from_path,
)
from talemate.export import ExportOptions, export_talemate_complete
from talemate.instance import get_agent
from talemate.load import load_scene, load_scene_from_zip
from talemate.save import scene_data_dumps
from talemate.scene_message import NarratorMessage
from talemate.storage.changelog import ConcurrentSaveError, SnapshotStore
from talemate.storage.blobs import BlobCorruptedError


@pytest.fixture
def persisted_scene(persistence_scene_factory, monkeypatch):
    scene = persistence_scene_factory()
    scene.name, scene.project_name, scene.filename = (
        "Revisions",
        "revisions",
        "scene.json",
    )
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(scene, "reset_memory", AsyncMock())
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "set_db", AsyncMock(), raising=False)
    monkeypatch.setattr(memory, "close_db", Mock(), raising=False)
    monkeypatch.setattr(
        memory, "get_document", AsyncMock(return_value={}), raising=False
    )
    return scene


def write_scene(scene):
    path = Path(scene.full_path)
    path.write_text(scene_data_dumps(scene.serialize))
    return path


@pytest.mark.parametrize("seed_before_load", [False, True])
async def test_upgrade_load_uses_recorded_revs_and_forks_without_later_turns(
    persisted_scene, seed_before_load
):
    scene = persisted_scene
    scene.history = [NarratorMessage("Early passage", rev=52)]
    path = write_scene(scene)
    original = path.read_bytes()
    legacy = path.parent / "changelog"
    legacy.mkdir()
    old_chain = legacy / "scene.json.base.json"
    old_chain.write_text('{"unreadable": "old chain"}')
    other = path.parent / "other.json"
    other.write_bytes(original)
    if seed_before_load:
        await save_changelog(scene_ref_from_path(str(path)))
    await load_scene(scene, str(path))
    assert scene.rev == 0
    assert scene.history[0].rev == 0
    store = SnapshotStore(scene.save_dir)
    assert await store.head("other.json") is None
    assert path.read_bytes() == original
    assert old_chain.read_text() == '{"unreadable": "old chain"}'
    first_id = scene.history[0].id
    scene.history.append(NarratorMessage("Later turn"))
    await scene.save(force=True)
    fork = await get_agent("creator").fork_scene(first_id, save_name="early")
    assert [m["message"] for m in json.loads(Path(fork).read_text())["history"]] == [
        "Early passage"
    ]
    await load_scene(scene, str(path))
    assert len(await store.entries(path.name)) == 2


@pytest.mark.parametrize(
    "filename,immutable,restore_from",
    [
        ("scene.json", True, "initial.json"),
        ("initial.json", False, ""),
        ("starting-point.json", False, "starting-point.json"),
    ],
)
async def test_load_and_loop_do_not_seed_readonly_or_restore_files(
    persisted_scene, filename, immutable, restore_from
):
    scene = persisted_scene
    scene.filename, scene.immutable_save, scene.restore_from = (
        filename,
        immutable,
        restore_from,
    )
    scene.history = [NarratorMessage("Unrecorded", rev=52)]
    path = write_scene(scene)
    await load_scene(scene, str(path))
    async with SceneChangelog(scene):
        assert scene.history[0].rev is None
        assert not (path.parent / "data.db").exists()
    if immutable:
        await scene.save(auto=True)
        assert not (path.parent / "data.db").exists()
        await scene.save(save_as=True, copy_name="my-play.json")
        assert scene.history[0].rev == 0
        assert (path.parent / "data.db").exists()


@pytest.mark.parametrize("immutable", [False, True])
async def test_unrecorded_message_requires_save_before_fork(
    persisted_scene, immutable, monkeypatch
):
    scene = persisted_scene
    scene.history = [NarratorMessage("Saved message")]
    await scene.save(force=True)
    scene.immutable_save = immutable
    added = NarratorMessage("Unsaved message")
    scene.history.append(added)
    if immutable:
        await scene.save(auto=True)
    emitted = Mock()
    monkeypatch.setattr("talemate.agents.creator.assistant.emit", emitted)
    assert added.rev is None
    assert (
        await get_agent("creator").fork_scene(added.id, save_name="unrecorded") is None
    )
    assert not (Path(scene.save_dir) / "unrecorded.json").exists()
    assert any(
        ("Save As first" if immutable else "Save the scene") in str(call)
        for call in emitted.call_args_list
    )
    await scene.save(copy_name="saved-copy.json")
    assert added.rev == 1
    path = await get_agent("creator").fork_scene(added.id, save_name="recorded")
    assert (
        json.loads(Path(path).read_text())["history"][-1]["message"]
        == "Unsaved message"
    )


async def test_save_as_replaces_destination_ancestry_and_keeps_source(persisted_scene):
    scene = persisted_scene
    scene.filename = "b.json"
    scene.history = [NarratorMessage("B only", rev=0)]
    await scene.save(force=True)
    b_id = (await SnapshotStore(scene.save_dir).head("b.json")).id
    scene.filename = "a.json"
    scene._changelog = None
    scene.history = [NarratorMessage("A early", id=scene.history[0].id)]
    await scene.save(force=True)
    scene.history.append(NarratorMessage("A later"))
    await scene.save(force=True)
    source = Path(scene.full_path).read_bytes()
    await scene.save(save_as=True, copy_name="b.json")
    store = SnapshotStore(scene.save_dir)
    entries = await store.entries("b.json")
    assert [e.rev for e in entries] == [0, 1, 2]
    assert [e.inherited for e in entries] == [True, True, False]
    assert [m.rev for m in scene.history] == [0, 1]
    assert (Path(scene.save_dir) / "a.json").read_bytes() == source
    assert (
        await store.db.read(
            lambda c: c.execute(
                "SELECT count(*) FROM changelog_revisions WHERE id=?", (b_id,)
            ).fetchone()[0]
        )
        == 0
    )
    path = await get_agent("creator").fork_scene(scene.history[0].id, save_name="early")
    assert [m["message"] for m in json.loads(Path(path).read_text())["history"]] == [
        "A early"
    ]


@pytest.mark.parametrize("failure", ["append", "insert", "collect"])
async def test_failed_save_as_preserves_destination_and_can_retry(
    persisted_scene, monkeypatch, failure
):
    scene = persisted_scene
    scene.filename = "b.json"
    scene.history = [NarratorMessage("B story")]
    await scene.save(force=True)
    scene.history.append(NarratorMessage("B later"))
    await scene.save(force=True)
    destination = Path(scene.full_path)
    original_file = destination.read_bytes()
    store = SnapshotStore(scene.save_dir)
    original_head = await store.head("b.json")
    original_revisions = [await store.assemble("b.json", rev) for rev in (0, 1)]
    scene.filename, scene._changelog = "a.json", None
    scene.history = [NarratorMessage("A story", id=scene.history[0].id)]
    await scene.save(force=True)
    source_head = await store.head("a.json")
    with monkeypatch.context() as patch:
        error = OSError("database or disk is full")
        if failure == "append":
            patch.setattr(SnapshotStore, "append", AsyncMock(side_effect=error))
        else:
            patch.setattr(
                "talemate.storage.changelog."
                + ("_insert_revision" if failure == "insert" else "_collect"),
                Mock(side_effect=error),
            )
        with pytest.raises(OSError, match="database or disk is full"):
            await scene.save(save_as=True, copy_name="b.json")
    assert destination.read_bytes() == original_file
    assert await store.head("b.json") == original_head
    assert [await store.assemble("b.json", rev) for rev in (0, 1)] == original_revisions
    assert await store.head("a.json") == source_head
    assert scene.filename == "a.json"
    assert scene._changelog.ref.filename == "a.json"
    scene.history.append(NarratorMessage("Keep playing A"))
    await scene.save(auto=True)
    assert destination.read_bytes() == original_file
    assert await store.head("b.json") == original_head
    await scene.save(save_as=True, copy_name="b.json")
    assert [entry.inherited for entry in await store.entries("b.json")] == [
        True,
        True,
        False,
    ]
    assert (await store.assemble("b.json"))["history"][-1][
        "message"
    ] == "Keep playing A"


async def test_failed_save_as_from_readonly_keeps_source_locked(
    persisted_scene, monkeypatch
):
    scene = persisted_scene
    scene.history = [NarratorMessage("Protected story")]
    scene.immutable_save = True
    path = write_scene(scene)
    original = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(
            SnapshotStore, "append", AsyncMock(side_effect=OSError("disk full"))
        )
        with pytest.raises(OSError, match="disk full"):
            await scene.save(save_as=True, copy_name="copy.json")
    assert scene.filename == "scene.json" and scene.immutable_save
    scene.history.append(NarratorMessage("Unsaved turn"))
    await scene.save(auto=True)
    assert path.read_bytes() == original
    assert not Path(scene.save_dir, "copy.json").exists()


async def test_cancelled_save_as_finishes_json_and_revision_together(
    persisted_scene, monkeypatch
):
    from talemate.emit import async_signals
    from talemate.storage import changelog as storage

    scene = persisted_scene
    scene.filename = "b.json"
    scene.history = [NarratorMessage("B story")]
    await scene.save(force=True)
    scene.filename, scene._changelog = "a.json", None
    scene.history = [NarratorMessage("A story")]
    await scene.save(force=True)
    scene.history.append(NarratorMessage("Unsaved A turn"))
    source_file = Path(scene.full_path).read_bytes()
    started, finish = threading.Event(), threading.Event()
    insert = storage._insert_revision

    def paused_insert(connection, revision):
        started.set()
        assert finish.wait(5)
        insert(connection, revision)

    events = []

    async def receive(event):
        assert not scene._save_lock.locked()
        events.append(event)

    signals = [
        async_signals.get(name)
        for name in ("scene.revision_forked", "scene.revision_saved")
    ]
    for signal in signals:
        signal.connect(receive)
    monkeypatch.setattr(storage, "_insert_revision", paused_insert)
    saving = asyncio.create_task(scene.save(save_as=True, copy_name="b.json"))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        saving.cancel()
        await asyncio.sleep(0)
        assert not saving.done()
        assert scene._save_lock.locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await saving
    finally:
        finish.set()
        await asyncio.gather(saving, return_exceptions=True)
        for signal in signals:
            signal.disconnect(receive)
    store = SnapshotStore(scene.save_dir)
    saved = json.loads(Path(scene.save_dir, "b.json").read_text())
    assert saved == await store.assemble("b.json")
    assert [m["message"] for m in saved["history"]] == ["A story", "Unsaved A turn"]
    assert Path(scene.save_dir, "a.json").read_bytes() == source_file
    assert scene.filename == "b.json" and scene.saved
    assert scene._changelog.head == await store.head("b.json")
    assert [event.operation for event in events] == ["fork", "save"]
    assert all(event.error is None for event in events)


async def test_stale_writer_can_keep_local_turns_in_save_as(persisted_scene):
    scene = persisted_scene
    scene.history = [NarratorMessage("Shared starting point")]
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    original = await store.head(scene.filename)
    external = await store.assemble(scene.filename)
    external["history"].append(NarratorMessage("Other backend's turn", rev=1).to_dict())
    captured = capture_snapshot(external)
    current = await store.append(
        scene.filename, captured.manifest, captured.changed, expected_head=original.id
    )
    path = Path(scene.full_path)
    path.write_text(scene_data_dumps(external))
    external_file = path.read_bytes()
    scene.history.append(NarratorMessage("My unsaved turn"))
    for _ in range(2):
        with pytest.raises(ConcurrentSaveError):
            await scene.save(force=True)
    await scene.save(save_as=True, copy_name="keep-my-work.json")
    saved = json.loads(Path(scene.full_path).read_text())
    assert saved == await store.assemble(scene.filename)
    assert [m["message"] for m in saved["history"]] == [
        "Shared starting point",
        "My unsaved turn",
    ]
    assert (await store.head(scene.filename)).parent_id == original.id
    assert [entry.inherited for entry in await store.entries(scene.filename)] == [
        True,
        False,
    ]
    assert await store.head("scene.json") == current
    assert path.read_bytes() == external_file


@pytest.mark.parametrize("retain_old_head", [False, True])
async def test_save_as_refuses_replaced_source_ancestry(
    persisted_scene, retain_old_head
):
    scene = persisted_scene
    scene.history = [NarratorMessage("Old source")]
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    if retain_old_head:
        await store.fork(scene.filename, 0, "retained.json")
    replaced = scene.serialize
    replaced["history"] = [NarratorMessage("Replacement source", rev=0)]
    captured = capture_snapshot(replaced)
    current = await store.append(
        scene.filename,
        captured.manifest,
        captured.changed,
        expected_head=None,
        replace=True,
    )
    path = Path(scene.full_path)
    path.write_text(scene_data_dumps(captured.data))
    current_file = path.read_bytes()
    scene.history.append(NarratorMessage("Local work"))
    with pytest.raises(ConcurrentSaveError):
        await scene.save(save_as=True, copy_name="refused.json")
    assert scene.filename == "scene.json"
    assert await store.head(scene.filename) == current
    assert path.read_bytes() == current_file
    assert await store.head("refused.json") is None
    assert not Path(scene.save_dir, "refused.json").exists()


@pytest.mark.parametrize("save_as", [None, "restored.json"])
async def test_restore_then_save_starts_fresh_without_played_ancestry(
    persisted_scene, save_as
):
    scene = persisted_scene
    scene.history = [NarratorMessage("Restore point")]
    scene.restore_from = "initial.json"
    await scene.save_restore("initial.json")
    await scene.save(force=True)
    scene.history.append(NarratorMessage("Played after restore point"))
    await scene.save(force=True)
    await scene.restore(save_as=save_as)
    if save_as is None:
        assert scene.filename is None
        await scene.save()
    store = SnapshotStore(scene.save_dir)
    entries = await store.entries(scene.filename)
    assert len(entries) == 1
    assert entries[0].rev == 0 and not entries[0].inherited and not entries[0].is_fork
    assert [m.message for m in scene.history] == ["Restore point"]
    assert scene.history[0].rev == 0
    assert await store.head("initial.json") is None
    assert len(await store.entries("scene.json")) == 2


async def test_imported_revision_fork_load_save_stays_in_import_project(
    persisted_scene, tmp_path, monkeypatch
):
    scene = persisted_scene
    scene.history = [NarratorMessage("Original passage")]
    await scene.save(force=True)
    original_dir = Path(scene.save_dir)
    occupied = original_dir / "branch.json"
    occupied.write_text(
        scene_data_dumps({**scene.serialize, "intro": "Original project checkpoint"})
    )
    original = occupied.read_bytes()
    archive = await export_talemate_complete(
        scene, ExportOptions(name="Imported", reset_progress=False)
    )
    path = tmp_path / "imported.zip"
    path.write_bytes(archive)
    monkeypatch.setattr("talemate.load.SCENES_DIR", tmp_path)
    await load_scene_from_zip(scene, str(path))
    imported_dir = Path(scene.save_dir)
    assert imported_dir != original_dir
    path = await fork_scene_at_revision(scene, 0, "branch")
    assert json.loads(Path(path).read_text())["project_name"] == imported_dir.name
    await load_scene(scene, path)
    assert Path(scene.save_dir) == imported_dir
    scene.history.append(NarratorMessage("Imported fork progress"))
    await scene.save(force=True)
    assert occupied.read_bytes() == original
    assert (
        json.loads((imported_dir / "branch.json").read_text())["history"][-1]["message"]
        == "Imported fork progress"
    )
    assert len(await SnapshotStore(imported_dir).entries("branch.json")) == 2


async def test_fork_can_reuse_filename_whose_file_was_deleted(persisted_scene):
    scene = persisted_scene
    scene.history = [NarratorMessage("First")]
    await scene.save(force=True)
    first = await fork_scene_at_revision(scene, 0, "reused")
    Path(first).unlink()
    scene.history.append(NarratorMessage("Second"))
    await scene.save(force=True)
    second = await fork_scene_at_revision(scene, 1, "reused")
    assert len(json.loads(Path(second).read_text())["history"]) == 2
    assert [
        e.rev for e in await SnapshotStore(scene.save_dir).entries("reused.json")
    ] == [0, 1]


async def test_copy_fork_replaces_stale_chain_before_load(persisted_scene):
    scene = persisted_scene
    scene.filename = "branch.json"
    scene.history = [NarratorMessage("Old branch")]
    await scene.save(force=True)
    scene.history.append(NarratorMessage("Old later"))
    await scene.save(force=True)
    old_ids = [m.id for m in scene.history]
    Path(scene.full_path).unlink()
    scene.filename, scene._changelog = None, None
    scene.history = [
        NarratorMessage("New copy", id=old_ids[0]),
        NarratorMessage("Omit", id=old_ids[1]),
    ]
    path = await get_agent("creator").fork_scene(old_ids[0], save_name="branch")
    store = SnapshotStore(scene.save_dir)
    assert await store.head("branch.json") is None
    await load_scene(scene, path)
    assert scene.rev == 0
    assert [m.rev for m in scene.history] == [0]
    assert [m.message for m in scene.history] == ["New copy"]
    entries = await store.entries("branch.json")
    assert len(entries) == 1 and entries[0].is_base and not entries[0].inherited
    fork = await get_agent("creator").fork_scene(old_ids[0], save_name="verified")
    assert [m["message"] for m in json.loads(Path(fork).read_text())["history"]] == [
        "New copy"
    ]


async def test_copy_fork_removes_new_file_when_stale_chain_cleanup_fails(
    persisted_scene, monkeypatch
):
    scene = persisted_scene
    scene.filename = None
    scene.history = [NarratorMessage("Copy me")]
    monkeypatch.setattr(
        SnapshotStore, "delete", AsyncMock(side_effect=OSError("disk full"))
    )
    path = await get_agent("creator").fork_scene(scene.history[0].id, save_name="copy")
    assert path is None
    assert not Path(scene.save_dir, "copy.json").exists()


async def test_overlap_stamps_only_messages_in_committed_capture(
    persisted_scene, monkeypatch
):
    scene = persisted_scene
    scene.history = [NarratorMessage("First")]
    await scene.save(force=True)
    entered, release = asyncio.Event(), asyncio.Event()
    append = SnapshotStore.append

    async def held_append(*args, **kwargs):
        entered.set()
        await release.wait()
        return await append(*args, **kwargs)

    second = NarratorMessage("Second")
    scene.history.append(second)
    with monkeypatch.context() as patch:
        patch.setattr(SnapshotStore, "append", held_append)
        saving = asyncio.create_task(scene.save(force=True))
        await entered.wait()
        third = NarratorMessage("Third, while the write runs")
        scene.history.append(third)
        assert second.rev is None
        release.set()
        await saving
    assert second.rev == 1
    assert third.rev is None
    assert third.id not in scene._changelog.known_ids
    await scene.save(force=True)
    assert third.rev == 2
    path = await get_agent("creator").fork_scene(third.id, save_name="overlap")
    assert json.loads(Path(path).read_text())["history"][-1]["rev"] == 2


async def test_message_revs_emitted_only_after_commit(persisted_scene, monkeypatch):
    scene = persisted_scene
    scene.history = [NarratorMessage("First")]
    emitted = Mock()
    monkeypatch.setattr("talemate.changelog.emit", emitted)
    await scene.save(force=True)
    emitted.assert_called_once_with(
        "message_revs",
        data={"revs": [{"id": scene.history[0].id, "rev": 0}]},
        websocket_passthrough=True,
    )
    assert (await SnapshotStore(scene.save_dir).assemble(scene.filename))["history"][0][
        "rev"
    ] == 0
    emitted.reset_mock()
    scene.history.append(NarratorMessage("Second"))
    with monkeypatch.context() as patch:
        patch.setattr(
            SnapshotStore, "append", AsyncMock(side_effect=OSError("disk full"))
        )
        with pytest.raises(OSError, match="disk full"):
            await scene.save(force=True)
    emitted.assert_not_called()
    assert scene.history[-1].rev is None
    await scene.save(force=True)
    emitted.assert_called_once_with(
        "message_revs",
        data={"revs": [{"id": scene.history[-1].id, "rev": 1}]},
        websocket_passthrough=True,
    )


@pytest.mark.parametrize("recorded", [False, True])
async def test_forks_clear_playthrough_without_mutating_live_scene(
    persisted_scene, recorded
):
    scene = persisted_scene
    scene.history = [NarratorMessage("First"), NarratorMessage("Second")]
    scene.playthrough_progress = scene.history[-1].id
    if recorded:
        await scene.save(force=True)
    else:
        scene.filename = None
    original = scene_data_dumps(scene.serialize)
    path = await get_agent("creator").fork_scene(
        scene.history[0].id, save_name="playthrough"
    )
    assert json.loads(Path(path).read_text())["playthrough_progress"] is None
    assert scene_data_dumps(scene.serialize) == original


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
async def test_legacy_nonfinite_values_load_save_and_fork(persisted_scene, value):
    scene = persisted_scene
    scene.history = [NarratorMessage("Playable legacy scene")]
    scene.game_state.variables["ratio"] = value
    path = write_scene(scene)
    await load_scene(scene, str(path))
    await scene.save(force=True)
    fork = await fork_scene_at_revision(scene, 0, "nonfinite")
    data = json.loads(Path(fork).read_text())
    actual = data["game_state"]["variables"]["ratio"]
    assert math.isnan(actual) if math.isnan(value) else actual == value


async def test_damaged_unchanged_message_is_healed_on_next_save(persisted_scene):
    scene = persisted_scene
    scene.history = [
        NarratorMessage(
            "Keep these exact bytes",
            meta={"agent": "narrator", "function": "ai", "arguments": {}},
        )
    ]
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    chunk = await store.db.read(
        lambda c: c.execute(
            "SELECT data FROM storage_blobs WHERE digest=?",
            (head.manifest.history_chunks[0],),
        ).fetchone()[0]
    )
    digest = json.loads(chunk)["messages"][0]
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?", (b"broken", digest)
        )
    )
    expected = scene.history[0].to_dict()
    await load_scene(scene, scene.full_path)
    assert scene.history[0].to_dict() == expected
    await scene.save(force=True)
    assert (await store.assemble(scene.filename, 0))["history"][0][
        "message"
    ] == "Keep these exact bytes"
    assert (await store.assemble(scene.filename))["history"][0][
        "message"
    ] == "Keep these exact bytes"


@pytest.mark.parametrize("reload", [False, True])
async def test_damaged_head_chunk_does_not_block_play_save(persisted_scene, reload):
    scene = persisted_scene
    scene.history = [NarratorMessage("Before damage")]
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"broken", head.manifest.history_chunks[-1]),
        )
    )
    if reload:
        await load_scene(scene, scene.full_path)
    scene.history.append(NarratorMessage("Play after damage"))
    await scene.save(auto=True)
    saved = json.loads(Path(scene.full_path).read_text())
    assert saved["history"][-1]["message"] == "Play after damage"
    assert saved == await store.assemble(scene.filename)
    with pytest.raises(BlobCorruptedError):
        await store.assemble(scene.filename, 0)


async def test_cached_unchanged_chunk_is_repaired_during_play_save(persisted_scene):
    scene = persisted_scene
    scene.history = [NarratorMessage(str(i)) for i in range(257)]
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"broken", head.manifest.history_chunks[0]),
        )
    )
    scene.history.append(NarratorMessage("Next turn"))
    await scene.save(auto=True)
    saved = json.loads(Path(scene.full_path).read_text())
    assert saved == await store.assemble(scene.filename)
    assert len((await store.assemble(scene.filename, 0))["history"]) == 257


@pytest.mark.parametrize("operation", ["delete", "fork", "replace-fork", "save-as"])
async def test_damaged_old_chunk_does_not_block_other_saves(
    persisted_scene, operation, monkeypatch
):
    scene = persisted_scene
    scene.filename = "damaged.json"
    scene.history = [NarratorMessage("Damaged ancestor")]
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    damaged = await store.head(scene.filename)
    scene.history.append(NarratorMessage("Healthy later turn"))
    await scene.save(force=True)
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"broken", damaged.manifest.history_chunks[0]),
        )
    )
    scene.filename, scene._changelog = "healthy.json", None
    scene.history = [NarratorMessage("Unaffected story")]
    await scene.save(force=True)
    if operation == "delete":
        removed = await delete_scene_revisions(scene)
        assert removed == {"revisions": 1, "blobs": 0}
        assert await store.head(scene.filename) is None
    else:
        if operation == "replace-fork":
            old = await fork_scene_at_revision(scene, 0, "branch")
            Path(old).unlink()
        if operation == "save-as":
            await scene.save(save_as=True, copy_name="branch.json")
        elif operation == "fork":
            with monkeypatch.context() as patch:
                collect = Mock(side_effect=AssertionError("Nothing to collect"))
                patch.setattr("talemate.storage.changelog._collect", collect)
                await fork_scene_at_revision(scene, 0, "branch")
                collect.assert_not_called()
        else:
            await fork_scene_at_revision(scene, 0, "branch")
        saved = json.loads(Path(scene.save_dir, "branch.json").read_text())
        assert saved["history"][0]["message"] == "Unaffected story"
        assert (await store.assemble("branch.json"))["history"] == saved["history"]
    assert len((await store.assemble("damaged.json"))["history"]) == 2
    with pytest.raises(BlobCorruptedError):
        await store.assemble("damaged.json", 0)
