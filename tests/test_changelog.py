import copy
import json
from pathlib import Path

import pytest

from _changelog_test_helpers import (
    make_changelog_scene,
    persist_test_mutation,
    revision_entries,
)
from talemate.changelog import (
    capture_snapshot,
    save_changelog,
    reconstruct_scene_data,
    fork_scene_at_revision,
    scene_ref_from_path,
    resolve_fork_save_name,
    ForkSaveNameError,
    ForkTargetMissingError,
)
from talemate.storage.blobs import BlobCorruptedError
from talemate.storage.changelog import (
    SnapshotStore,
    ConcurrentSaveError,
    RevisionMissingError,
)


@pytest.fixture
def saved_data():
    return {
        "format_version": 1,
        "knowledge_eligibility": "legacy",
        "history": [],
        "character_data": {},
        "archived_history": [],
        "layered_history": [],
        "ts": 0,
        "world_state": {},
        "game_state": {},
        "intro": "A lamp on the shore.",
    }


async def test_each_manifest_preserves_complete_state_and_order(tmp_path, saved_data):
    scene = make_changelog_scene(str(tmp_path), initial_serialize=saved_data)
    await save_changelog(scene)
    expected = [copy.deepcopy(saved_data)]
    for value in [True, 1, 1.0, "1", None, [], {}, {"a'\"b": [False, 0]}]:
        scene.serialize = copy.deepcopy(scene.serialize)
        scene.serialize["new_section"] = value
        scene.serialize["history"].append(
            {
                "id": len(expected),
                "message": f"line {len(expected)}",
                "rev": len(expected),
            }
        )
        scene.serialize["history"].reverse()
        assert await persist_test_mutation(scene) == len(expected)
        expected.append(copy.deepcopy(scene.serialize))
    store = SnapshotStore(tmp_path)
    for revision, data in enumerate(expected):
        assert json.dumps(
            await store.assemble(scene.filename, revision), sort_keys=True
        ) == json.dumps(data, sort_keys=True)
    scene.serialize["history"].pop()
    scene.serialize.pop("new_section")
    await persist_test_mutation(scene)
    assert await store.assemble(scene.filename) == scene.serialize


async def test_fork_keeps_parent_revisions_without_blob_copies(tmp_path, saved_data):
    scene = make_changelog_scene(str(tmp_path), initial_serialize=saved_data)
    await save_changelog(scene)
    for rev in (1, 2, 3):
        scene.serialize["history"].append({"id": rev, "message": str(rev), "rev": rev})
        await persist_test_mutation(scene)
    store = SnapshotStore(tmp_path)
    count = await store.db.read(
        lambda c: c.execute("SELECT count(*) FROM storage_blobs").fetchone()[0]
    )
    path = await fork_scene_at_revision(scene, 2, "branch", expect_message_id=2)
    assert (
        await store.db.read(
            lambda c: c.execute("SELECT count(*) FROM storage_blobs").fetchone()[0]
        )
        == count
    )
    fork = scene_ref_from_path(path)
    entries = await revision_entries(store, fork.filename)
    assert [r.rev for r in entries] == [0, 1, 2]
    assert entries[-1].is_fork
    assert all(r.inherited for r in entries)
    assert [m["rev"] for m in json.loads(Path(path).read_text())["history"]] == [1, 2]
    state = await store.assemble("branch.json")
    state["history"].append({"id": 9, "message": "new branch", "rev": 3})
    head = await store.head("branch.json")
    snapshot = capture_snapshot(state)
    revision = await store.append(
        "branch.json", snapshot.manifest, snapshot.changed, expected_head=head.id
    )
    assert revision.rev == 3
    assert (await store.assemble("scene.json"))["history"][-1]["id"] == 3
    assert (await store.assemble("branch.json"))["history"][-1]["id"] == 9


async def test_source_deletion_keeps_fork_ancestors_and_collects_unreachable_data(
    tmp_path, saved_data
):
    scene = make_changelog_scene(str(tmp_path), initial_serialize=saved_data)
    await save_changelog(scene)
    scene.serialize["intro"] = "fork here"
    await persist_test_mutation(scene)
    store = SnapshotStore(tmp_path)
    await store.fork("scene.json", 1, "branch.json")
    scene.serialize["intro"] = "only in source"
    await persist_test_mutation(scene)
    removed = await store.delete("scene.json")
    assert removed["revisions"] == 1
    assert removed["blobs"] == 1
    assert (await store.assemble("branch.json", 0))["intro"] == "A lamp on the shore."
    assert (await store.assemble("branch.json", 1))["intro"] == "fork here"
    assert await store.head("scene.json") is None
    assert (await store.delete("branch.json"))["revisions"] == 2
    assert (
        await store.db.read(
            lambda c: c.execute("SELECT count(*) FROM storage_blobs").fetchone()[0]
        )
        == 0
    )


async def test_damaged_blob_only_blocks_revisions_that_use_it(tmp_path, saved_data):
    scene = make_changelog_scene(str(tmp_path), initial_serialize=saved_data)
    first = await save_changelog(scene)
    scene.serialize["intro"] = "another state"
    await persist_test_mutation(scene)
    store = SnapshotStore(tmp_path)
    digest = first.manifest.sections["intro"]
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?", (b"broken", digest)
        )
    )
    assert (await reconstruct_scene_data(scene, 1))["intro"] == "another state"
    with pytest.raises(BlobCorruptedError, match=digest):
        await fork_scene_at_revision(scene, 0, "broken")
    assert not (tmp_path / "broken.json").exists()
    assert len(await revision_entries(store, "scene.json")) == 2


async def test_missing_revision_and_message_refuse_fork(tmp_path, saved_data):
    scene = make_changelog_scene(str(tmp_path), initial_serialize=saved_data)
    await save_changelog(scene)
    with pytest.raises(RevisionMissingError):
        await fork_scene_at_revision(scene, 7, "missing")
    with pytest.raises(ForkTargetMissingError):
        await fork_scene_at_revision(scene, 0, "missing", expect_message_id=50)
    assert not (tmp_path / "missing.json").exists()


@pytest.mark.parametrize("name", ["", "../escape", "/tmp/escape", "two/parts"])
def test_invalid_fork_name_is_rejected(tmp_path, name):
    scene = make_changelog_scene(str(tmp_path))
    with pytest.raises(ForkSaveNameError):
        resolve_fork_save_name(scene, name)


async def test_existing_destination_is_never_overwritten(tmp_path, saved_data):
    scene = make_changelog_scene(str(tmp_path), initial_serialize=saved_data)
    await save_changelog(scene)
    destination = tmp_path / "occupied.json"
    destination.write_text("keep me")
    with pytest.raises(ForkSaveNameError):
        await fork_scene_at_revision(scene, 0, "occupied")
    assert destination.read_text() == "keep me"


async def test_stale_writer_is_rejected_without_partial_blobs(tmp_path, saved_data):
    scene = make_changelog_scene(str(tmp_path), initial_serialize=saved_data)
    original = await save_changelog(scene)
    store = SnapshotStore(tmp_path)
    scene.serialize["intro"] = "new head"
    await persist_test_mutation(scene)
    snapshot = capture_snapshot({**saved_data, "intro": "stale attempt"})
    with pytest.raises(ConcurrentSaveError):
        await store.append(
            scene.filename,
            snapshot.manifest,
            snapshot.changed,
            expected_head=original.id,
        )
    assert (await store.assemble(scene.filename))["intro"] == "new head"
    assert (
        await store.db.read(
            lambda c: c.execute("SELECT count(*) FROM changelog_revisions").fetchone()[
                0
            ]
        )
        == 2
    )


async def test_nested_fork_lists_each_ancestor_fork_point(tmp_path):
    scene = make_changelog_scene(
        str(tmp_path), initial_serialize={"history": [], "intro": "root"}
    )
    await save_changelog(scene)
    scene.serialize["intro"] = "source turn"
    await persist_test_mutation(scene)
    store = SnapshotStore(tmp_path)
    await store.fork(scene.filename, 1, "branch.json")
    scene.filename = "branch.json"
    scene.serialize["intro"] = "branch turn"
    await persist_test_mutation(scene)
    await store.fork(scene.filename, 2, "nested.json")
    entries = await revision_entries(store, "nested.json")
    assert [entry.rev for entry in entries if entry.is_fork] == [1, 2]
    assert entries[-1].origin == "branch.json"


async def test_append_references_only_changed_content_and_gc_protects_other_features(
    tmp_path,
):
    from talemate.storage import blobs

    data = {
        "history": [{"id": i, "message": str(i), "rev": 0} for i in range(2500)],
        "intro": "root",
    }
    scene = make_changelog_scene(str(tmp_path), initial_serialize=data)
    await save_changelog(scene)
    store = SnapshotStore(tmp_path)

    async def references():
        return await store.db.read(
            lambda c: c.execute(
                "SELECT count(*) FROM storage_blob_refs WHERE namespace='changelog'"
            ).fetchone()[0]
        )

    original_count = await references()
    head = await store.head(scene.filename)
    protected_digest = head.manifest.sections["intro"]
    await store.db.write(
        lambda c: blobs.reference(
            c,
            blobs.BlobReference(
                namespace="another_feature",
                owner="record",
                slot="intro",
                digest=protected_digest,
            ),
        )
    )
    scene.serialize["history"].append({"id": 2500, "message": "one new message"})
    await persist_test_mutation(scene)
    assert await references() == original_count + 2
    await store.delete(scene.filename)
    assert await references() == 0
    assert (
        await store.db.read(lambda c: blobs.get(c, protected_digest))
    ).data == b'"root"'


async def test_incomplete_manifest_is_rejected_atomically(tmp_path):
    store = SnapshotStore(tmp_path)
    capture = capture_snapshot({"history": [], "intro": "missing content"})
    with pytest.raises(ValueError, match="must be supplied"):
        await store.append("scene.json", capture.manifest, [], expected_head=None)
    assert await store.head("scene.json") is None
