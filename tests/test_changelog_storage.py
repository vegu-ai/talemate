import pytest

from talemate.changelog import (
    capture_snapshot,
    export_scene_revisions,
    import_scene_revisions,
)
from talemate.storage.blobs import BlobCorruptedError
from talemate.storage.changelog import SnapshotStore
from _changelog_test_helpers import make_changelog_scene, revision_entries


async def test_chunks_share_full_prefix_and_keep_manifests_small(tmp_path):
    data = {
        "history": [{"id": i, "message": str(i)} for i in range(512)],
        "intro": "fixed",
    }
    store = SnapshotStore(tmp_path)
    first = capture_snapshot(data)
    head = await store.append(
        "scene.json", first.manifest, first.changed, expected_head=None
    )
    data["history"].append({"id": 512, "message": "append"})
    second = capture_snapshot(data, first.cache)
    assert second.manifest.history_chunks[:-1] == first.manifest.history_chunks
    assert len(second.changed) == 4  # one message and three small digest chunks
    assert len(second.manifest.model_dump_json()) < 400
    await store.append(
        "scene.json", second.manifest, second.changed, expected_head=head.id
    )
    await store.fork("scene.json", 0, "branch.json")
    assert (await revision_entries(store, "scene.json"))[-1].message_count == 513
    assert await store.assemble("scene.json") == data
    await store.delete("scene.json")
    assert len((await store.assemble("branch.json"))["history"]) == 512


async def test_export_names_damaged_revision(tmp_path):
    store = SnapshotStore(tmp_path)
    first = capture_snapshot({"intro": "first", "history": []})
    head = await store.append(
        "scene.json", first.manifest, first.changed, expected_head=None
    )
    second = capture_snapshot({"intro": "second", "history": []})
    await store.append(
        "scene.json", second.manifest, second.changed, expected_head=head.id
    )
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"broken", first.manifest.sections["intro"]),
        )
    )
    with pytest.raises(
        BlobCorruptedError, match="Cannot export revision 0 of scene.json"
    ):
        await store.bundle("scene.json")


@pytest.mark.parametrize("fork", [False, True])
async def test_import_origins_use_save_identity_even_when_archive_name_matches_ancestor(
    tmp_path, fork
):
    store = SnapshotStore(tmp_path / "source")
    capture = capture_snapshot({"history": [], "intro": "source"})
    await store.append(
        "scene.json", capture.manifest, capture.changed, expected_head=None
    )
    filename = "scene.json"
    if fork:
        filename = "branch.json"
        await store.fork("scene.json", 0, filename)
    source = make_changelog_scene(str(tmp_path / "source"), filename=filename)
    archive = tmp_path / "archive" / "data.db"
    await export_scene_revisions(source, archive)
    imported = make_changelog_scene(
        str(tmp_path / "destination"), filename="imported.json"
    )
    await import_scene_revisions(archive, imported)
    target = SnapshotStore(imported.save_dir)
    entries = await revision_entries(target, imported.filename)
    assert entries[0].inherited is fork
    assert entries[0].is_fork is fork
    assert entries[0].origin == ("scene.json" if fork else "imported.json")
    head = await target.head(imported.filename)
    data = await target.assemble(imported.filename)
    data["intro"] = "next"
    capture = capture_snapshot(data)
    await target.append(
        imported.filename, capture.manifest, capture.changed, expected_head=head.id
    )
    assert not (await revision_entries(target, imported.filename))[-1].inherited
    assert (await revision_entries(target, imported.filename))[0].is_fork is fork
