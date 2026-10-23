import asyncio
import json
from pathlib import Path

import pytest

from _changelog_test_helpers import (
    make_changelog_scene,
    persist_test_mutation,
    revision_entries,
)
from talemate.changelog import (
    SceneChangelog,
    save_changelog,
    export_scene_revisions,
    import_scene_revisions,
    reconstruct_scene_data,
)
from talemate.scene_message import NarratorMessage
from talemate.storage.changelog import SnapshotStore


async def test_export_import_copies_only_selected_ancestry(tmp_path):
    scene = make_changelog_scene(
        str(tmp_path / "source"),
        initial_serialize={"history": [], "character_data": {}, "intro": "shared"},
    )
    await save_changelog(scene)
    scene.serialize["intro"] = "fork point"
    await persist_test_mutation(scene)
    store = SnapshotStore(scene.save_dir)
    await store.fork(scene.filename, 1, "fork.json")
    scene.serialize["intro"] = "private sibling content"
    await persist_test_mutation(scene)
    other = make_changelog_scene(
        scene.save_dir,
        filename="unrelated.json",
        initial_serialize={"history": [], "intro": "unrelated private"},
    )
    await save_changelog(other)
    scene.filename = "fork.json"
    destination = tmp_path / "export/data.db"
    await export_scene_revisions(scene, destination)
    raw = destination.read_bytes()
    assert b"private sibling content" not in raw
    assert b"unrelated private" not in raw
    incoming = SnapshotStore(destination.parent)
    assert len(await revision_entries(incoming, "scene.json")) == 2
    assert await incoming.head("unrelated.json") is None
    imported = make_changelog_scene(str(tmp_path / "import"), filename="renamed.json")
    await import_scene_revisions(destination, imported)
    restored = SnapshotStore(imported.save_dir)
    assert (await restored.assemble("renamed.json", 0))["intro"] == "shared"
    assert (await restored.assemble("renamed.json", 1))["intro"] == "fork point"
    assert [r.rev for r in await revision_entries(restored, "renamed.json")] == [0, 1]


async def test_normal_save_records_current_file_and_stamps_new_messages(
    persistence_scene_factory,
):
    scene = persistence_scene_factory()
    scene.name = "Snapshot save"
    scene.filename = "saved.json"
    scene.immutable_save = False
    scene.history = [NarratorMessage("First passage")]
    await scene.save(auto=True)
    first = scene.history[0]
    scene.history.append(NarratorMessage("Second passage"))
    await scene.save(auto=True)
    assert first.rev == 0
    assert scene.history[1].rev == 1
    saved = json.loads(Path(scene.full_path).read_text())
    assert saved == await SnapshotStore(scene.save_dir).assemble(scene.filename)
    assert [
        m["message"] for m in (await reconstruct_scene_data(scene, 0))["history"]
    ] == ["First passage"]


async def test_failed_revision_write_rolls_back_stamps_and_retries(
    persistence_scene_factory, monkeypatch
):
    scene = persistence_scene_factory()
    scene.name, scene.filename = "Snapshot", "scene.json"
    await scene.save(force=True)
    previous_file = Path(scene.full_path).read_bytes()
    message = NarratorMessage("Keep on retry")
    scene.history.append(message)

    async def fail(*args, **kwargs):
        raise OSError("database full")

    with monkeypatch.context() as patch:
        patch.setattr(SnapshotStore, "append", fail)
        with pytest.raises(OSError, match="database full"):
            await scene.save(auto=True)
    assert message.rev is None
    assert Path(scene.full_path).read_bytes() == previous_file
    await scene.save(auto=True)
    assert message.rev == 1
    assert (await SnapshotStore(scene.save_dir).head(scene.filename)).rev == 1


async def test_save_as_binds_destination_and_preserves_source(
    persistence_scene_factory,
):
    scene = persistence_scene_factory()
    scene.name, scene.filename = "Snapshot", "source.json"
    await scene.save(force=True)
    source = Path(scene.full_path).read_bytes()
    scene.history.append(NarratorMessage("Fork progress"))
    await scene.save(save_as=True, copy_name="copy.json")
    store = SnapshotStore(scene.save_dir)
    assert (Path(scene.save_dir) / "source.json").read_bytes() == source
    assert len(await revision_entries(store, "copy.json")) == 2
    assert (await revision_entries(store, "copy.json"))[0].is_fork
    assert (await store.assemble("source.json"))["history"] == []
    assert (await store.assemble("copy.json"))["history"][-1][
        "message"
    ] == "Fork progress"


async def test_two_simultaneous_saves_serialize_per_scene(persistence_scene_factory):
    scene = persistence_scene_factory()
    scene.name, scene.filename = "Snapshot", "scene.json"
    await asyncio.gather(scene.save(force=True), scene.save(force=True))
    entries = await revision_entries(SnapshotStore(scene.save_dir), scene.filename)
    assert [entry.rev for entry in entries] == [0, 1]
    assert json.loads(Path(scene.full_path).read_text()) == await SnapshotStore(
        scene.save_dir
    ).assemble(scene.filename)


@pytest.mark.parametrize("change_intro", [False, True])
async def test_new_revision_can_save_after_an_older_blob_is_damaged(
    persistence_scene_factory,
    change_intro,
):
    scene = persistence_scene_factory()
    scene.name, scene.filename, scene.intro = "Snapshot", "scene.json", "older intro"
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"broken", head.manifest.sections["intro"]),
        )
    )
    scene._changelog = SceneChangelog(scene)
    if change_intro:
        scene.intro = "new intro"
    await scene.save(force=True)
    assert (await store.assemble(scene.filename))["intro"] == scene.intro


async def test_recorded_revision_zero_fork_uses_saved_world_state(
    persistence_scene_factory, monkeypatch
):
    from talemate.instance import get_agent

    scene = persistence_scene_factory()
    scene.name, scene.filename, scene.intro = (
        "Snapshot",
        "source.json",
        "Original introduction",
    )
    scene.history = [NarratorMessage("First saved message")]
    await scene.save(force=True)
    scene.intro = "Later unsaved introduction"
    creator = get_agent("creator")
    monkeypatch.setattr(creator, "scene", scene, raising=False)
    path = await creator.fork_scene(scene.history[0].id, save_name="from-zero")
    assert json.loads(Path(path).read_text())["intro"] == "Original introduction"
    entries = await revision_entries(SnapshotStore(scene.save_dir), "from-zero.json")
    assert len(entries) == 1 and entries[0].is_fork and entries[0].inherited


async def test_stale_writer_cannot_silently_overwrite_on_retry(
    persistence_scene_factory,
):
    from talemate.changelog import capture_snapshot
    from talemate.storage.changelog import ConcurrentSaveError

    scene = persistence_scene_factory()
    scene.name, scene.filename = "Snapshot", "source.json"
    await scene.save(force=True)
    store = SnapshotStore(scene.save_dir)
    head = await store.head(scene.filename)
    data = await store.assemble(scene.filename)
    data["intro"] = "Changed by another writer"
    capture = capture_snapshot(data)
    await store.append(
        scene.filename, capture.manifest, capture.changed, expected_head=head.id
    )
    scene.intro = "Stale change"
    for _ in range(2):
        with pytest.raises(ConcurrentSaveError):
            await scene.save(force=True)
    assert (await store.assemble(scene.filename))[
        "intro"
    ] == "Changed by another writer"
