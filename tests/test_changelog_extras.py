"""Additional tests for talemate.changelog covering gaps in test_changelog.py.

Focuses on:
- _SceneRef helper (used internally by ensure_changelogs_for_all_scenes)
- list_revision_entries / latest_revision_at
- delete_changelog_files behavior on missing/error paths
- write_reconstructed_scene with overrides
- InMemoryChangelog property and edge cases
- ensure_changelogs_for_all_scenes (full disk-walking flow)
- _apply_delta error path
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from _changelog_test_helpers import (
    ChangelogScene,
    make_changelog_scene,
    persist_test_mutation,
)
from talemate import changelog as changelog_mod
from talemate.agents.creator.assistant import AssistantMixin
from talemate.changelog import (
    ForkTargetMissingError,
    InMemoryChangelog,
    _apply_delta,
    _base_path,
    _changelog_log_path,
    _latest_path,
    _SceneRef,
    delete_changelog_files,
    ensure_changelogs_for_all_scenes,
    fork_scene_at_revision,
    latest_revision_at,
    list_revision_entries,
    reconstruct_scene_data,
    save_changelog,
    write_reconstructed_scene,
)
from talemate.emit.signals import handlers
from talemate.scene_message import SceneMessage


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_scene(temp_dir):
    # Real ``Scene`` subclass (see _changelog_test_helpers.ChangelogScene) with
    # ``serialize`` exposed as a settable attribute so tests can drive arbitrary
    # payloads. ``filename``/``save_dir``/``changelog_dir``/``rev``/``_changelog``
    # remain the real ``Scene`` fields/properties — renames or removals will
    # break these tests.
    return make_changelog_scene(temp_dir)


# ---------------------------------------------------------------------------
# _SceneRef
# ---------------------------------------------------------------------------


class TestSceneRef:
    def test_constructs_with_provided_attributes(self, temp_dir):
        ref = _SceneRef(filename="x.json", save_dir=temp_dir, data={"a": 1})
        assert ref.filename == "x.json"
        assert ref.save_dir == temp_dir
        assert ref.changelog_dir == os.path.join(temp_dir, "changelog")
        assert ref.serialize == {"a": 1}


# ---------------------------------------------------------------------------
# list_revision_entries / latest_revision_at
# ---------------------------------------------------------------------------


class TestListRevisionEntries:
    def test_returns_empty_when_no_deltas(self, mock_scene):
        assert list_revision_entries(mock_scene) == []

    def test_returns_entries_sorted_by_rev_desc(self, mock_scene):
        log_path = _changelog_log_path(mock_scene, 0)
        log_data = {
            "deltas": [
                {"rev": 1, "ts": 100},
                {"rev": 3, "ts": 300},
                {"rev": 2, "ts": 200},
            ]
        }
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(log_data, f)

        entries = list_revision_entries(mock_scene)
        assert [e["rev"] for e in entries] == [3, 2, 1]
        assert [e["ts"] for e in entries] == [300, 200, 100]

    def test_ignores_entries_with_non_int_rev_or_ts(self, mock_scene):
        log_path = _changelog_log_path(mock_scene, 0)
        log_data = {
            "deltas": [
                {"rev": 1, "ts": 100},
                {"rev": "not-int", "ts": 200},
                {"rev": 2, "ts": "not-int"},
                {"rev": 3, "ts": 300},
            ]
        }
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(log_data, f)

        entries = list_revision_entries(mock_scene)
        # Only entries with both rev:int and ts:int are returned.
        revs = [e["rev"] for e in entries]
        assert revs == [3, 1]


class TestLatestRevisionAt:
    def test_returns_none_when_no_revisions_exist(self, mock_scene):
        assert latest_revision_at(mock_scene, at_ts=999_999) is None

    def test_returns_greatest_revision_within_timestamp_window(self, mock_scene):
        # `list_revision_entries` returns entries sorted DESC by rev. The
        # function returns the first rev whose ts is <= at_ts, i.e. the
        # GREATEST rev satisfying the constraint.
        log_path = _changelog_log_path(mock_scene, 0)
        log_data = {
            "deltas": [
                {"rev": 1, "ts": 100},
                {"rev": 2, "ts": 200},
                {"rev": 3, "ts": 300},
            ]
        }
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(log_data, f)

        # at_ts=350: all three qualify; greatest rev is 3.
        assert latest_revision_at(mock_scene, at_ts=350) == 3
        # at_ts=250: rev 3 (ts 300) doesn't qualify; rev 2 (ts 200) does.
        assert latest_revision_at(mock_scene, at_ts=250) == 2
        # at_ts=99: nothing qualifies.
        assert latest_revision_at(mock_scene, at_ts=99) is None

    def test_with_only_old_entries_returns_oldest(self, mock_scene):
        # Single entry whose ts <= at_ts should return that rev.
        log_path = _changelog_log_path(mock_scene, 0)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            json.dump({"deltas": [{"rev": 5, "ts": 100}]}, f)

        assert latest_revision_at(mock_scene, at_ts=200) == 5
        assert latest_revision_at(mock_scene, at_ts=50) is None


# ---------------------------------------------------------------------------
# delete_changelog_files
# ---------------------------------------------------------------------------


class TestDeleteChangelogFiles:
    @pytest.mark.asyncio
    async def test_deletes_base_latest_and_segments_and_removes_dir(self, mock_scene):
        # Set up real files
        await save_changelog(mock_scene)
        # Modify and append to create a delta file
        mock_scene.serialize = {"history": [], "characters": [{"name": "A"}]}
        await persist_test_mutation(mock_scene, {})

        # Sanity: base, latest, and a segment all exist
        assert os.path.exists(_base_path(mock_scene))
        assert os.path.exists(_latest_path(mock_scene))
        assert os.path.exists(_changelog_log_path(mock_scene, 0))

        result = delete_changelog_files(mock_scene)

        # All three artifact files should be gone.
        assert not os.path.exists(_base_path(mock_scene))
        assert not os.path.exists(_latest_path(mock_scene))
        assert not os.path.exists(_changelog_log_path(mock_scene, 0))
        # changelog dir is empty → removed
        assert result["dir_removed"] == mock_scene.changelog_dir
        assert len(result["deleted"]) == 3

    def test_does_not_error_when_files_dont_exist(self, mock_scene):
        # No setup at all → delete should be a no-op without raising
        result = delete_changelog_files(mock_scene)
        assert result["deleted"] == []
        # No directory to remove either.
        assert result["dir_removed"] is None

    def test_keeps_directory_when_extra_files_present(self, mock_scene, temp_dir):
        # Create the changelog dir + an unrelated file inside it
        os.makedirs(mock_scene.changelog_dir, exist_ok=True)
        extra_file = os.path.join(mock_scene.changelog_dir, "unrelated.txt")
        with open(extra_file, "w") as f:
            f.write("dont touch me")

        result = delete_changelog_files(mock_scene)
        # Dir is not empty → not removed
        assert result["dir_removed"] is None
        assert os.path.exists(extra_file)


# ---------------------------------------------------------------------------
# write_reconstructed_scene with overrides
# ---------------------------------------------------------------------------


class TestWriteReconstructedSceneOverrides:
    @pytest.mark.asyncio
    async def test_overrides_are_applied_to_reconstructed_data(self, mock_scene):
        # Initialize base
        mock_scene.serialize = {"name": "original-name", "value": 1}
        await save_changelog(mock_scene)

        out_path = await write_reconstructed_scene(
            mock_scene,
            to_rev=0,
            output_filename="overridden.json",
            overrides={"name": "patched-name", "extra": True},
        )

        with open(out_path) as f:
            data = json.load(f)

        # Override applied while keeping original keys
        assert data["name"] == "patched-name"
        assert data["value"] == 1
        assert data["extra"] is True


# ---------------------------------------------------------------------------
# _apply_delta error path
# ---------------------------------------------------------------------------


class TestApplyDeltaErrors:
    def test_raises_on_invalid_delta_payload(self):
        # Pass an entirely invalid delta object (a string) — Delta() will
        # try to deserialize it as a pickle and raise UnpicklingError.
        # _apply_delta catches and re-raises after logging.
        with pytest.raises(Exception):
            _apply_delta({"a": 1}, "not a dict, totally invalid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# InMemoryChangelog properties
# ---------------------------------------------------------------------------


class TestInMemoryChangelogProperties:
    @pytest.mark.asyncio
    async def test_next_revision_starts_at_scene_rev_plus_one(self, mock_scene):
        await save_changelog(mock_scene)
        mock_scene.rev = 5

        async with InMemoryChangelog(mock_scene) as changelog:
            # No pending deltas → next is 6.
            assert changelog.next_revision == 6

            # Append one pending delta → next becomes 7.
            mock_scene.serialize = {"history": [], "characters": [{"name": "A"}]}
            await changelog.append_delta({})
            assert changelog.next_revision == 7

    @pytest.mark.asyncio
    async def test_pending_count_reflects_appended_deltas(self, mock_scene):
        await save_changelog(mock_scene)

        async with InMemoryChangelog(mock_scene) as changelog:
            assert changelog.pending_count == 0

            mock_scene.serialize = {"history": [], "characters": [{"name": "A"}]}
            await changelog.append_delta({})
            assert changelog.pending_count == 1

            mock_scene.serialize = {
                "history": [],
                "characters": [{"name": "A"}, {"name": "B"}],
            }
            await changelog.append_delta({})
            assert changelog.pending_count == 2


# ---------------------------------------------------------------------------
# ensure_changelogs_for_all_scenes
# ---------------------------------------------------------------------------


class TestEnsureChangelogsForAllScenes:
    @pytest.mark.asyncio
    async def test_creates_base_and_latest_for_scene_without_either(self, temp_dir):
        # Lay out: <temp>/project1/scene.json
        project = Path(temp_dir) / "project1"
        project.mkdir()
        scene_file = project / "scene.json"
        scene_file.write_text(json.dumps({"history": [], "characters": []}))

        # Run the bulk ensurer over the temp scenes root.
        await ensure_changelogs_for_all_scenes(root=str(temp_dir))

        # Both base + latest should now exist.
        base = project / "changelog" / "scene.json.base.json"
        latest = project / "changelog" / "scene.json.latest.json"
        assert base.exists()
        assert latest.exists()

    @pytest.mark.asyncio
    async def test_creates_latest_when_base_exists_but_latest_missing(self, temp_dir):
        project = Path(temp_dir) / "p"
        project.mkdir()
        scene_file = project / "s.json"
        scene_file.write_text(json.dumps({"x": 1}))

        # Pre-create base only, no latest.
        cl_dir = project / "changelog"
        cl_dir.mkdir()
        base_file = cl_dir / "s.json.base.json"
        base_file.write_text(json.dumps({"x": 1}))

        await ensure_changelogs_for_all_scenes(root=str(temp_dir))

        latest = cl_dir / "s.json.latest.json"
        assert latest.exists()
        assert json.loads(latest.read_text()) == {"x": 1}

    @pytest.mark.asyncio
    async def test_no_op_when_root_missing(self, temp_dir):
        # Use a path that doesn't exist — the function should warn and return.
        await ensure_changelogs_for_all_scenes(root=os.path.join(temp_dir, "nope"))
        # No raise, nothing to assert beyond not-raising.

    @pytest.mark.asyncio
    async def test_skips_unreadable_scene_file(self, temp_dir, monkeypatch):
        # Create a scene file with invalid JSON.
        project = Path(temp_dir) / "p"
        project.mkdir()
        bad = project / "broken.json"
        bad.write_text("{ not valid json")

        # Should not raise — bad file is skipped.
        await ensure_changelogs_for_all_scenes(root=str(temp_dir))
        # No base/latest created for broken scene
        assert not (project / "changelog" / "broken.json.base.json").exists()

    @pytest.mark.asyncio
    async def test_processes_multiple_scene_files_in_alphabetical_order(self, temp_dir):
        project = Path(temp_dir) / "p"
        project.mkdir()
        for name in ["b.json", "a.json"]:
            (project / name).write_text(json.dumps({"name": name}))

        await ensure_changelogs_for_all_scenes(root=str(temp_dir))

        cl_dir = project / "changelog"
        assert (cl_dir / "a.json.base.json").exists()
        assert (cl_dir / "b.json.base.json").exists()


# ---------------------------------------------------------------------------
# Reconstruction edge cases (cover branches at 651, 665, 682)
# ---------------------------------------------------------------------------


class TestReconstructionEdgeCases:
    @pytest.mark.asyncio
    async def test_reconstruct_with_to_rev_none_uses_overall_latest(self, mock_scene):
        await save_changelog(mock_scene)
        mock_scene.serialize = {"history": [], "characters": [{"name": "A"}]}
        await persist_test_mutation(mock_scene, {})

        # to_rev=None → should reconstruct at overall latest revision
        result = await reconstruct_scene_data(mock_scene, to_rev=None)
        assert result["characters"] == [{"name": "A"}]

    @pytest.mark.asyncio
    async def test_reconstruct_stops_at_target_rev_in_multi_file_changelog(
        self, mock_scene
    ):
        # Multiple revisions, ensure deltas past target_rev are not applied.
        await save_changelog(mock_scene)

        mock_scene.serialize = {"history": [], "characters": [{"name": "A"}]}
        rev1 = await persist_test_mutation(mock_scene, {})
        assert rev1 == 1

        mock_scene.serialize = {
            "history": [],
            "characters": [{"name": "A"}, {"name": "B"}],
        }
        rev2 = await persist_test_mutation(mock_scene, {})
        assert rev2 == 2

        # Reconstruct at rev=1 — only A should be present.
        result = await reconstruct_scene_data(mock_scene, to_rev=1)
        assert result["characters"] == [{"name": "A"}]

    @pytest.mark.asyncio
    async def test_reconstruct_returns_base_when_to_rev_zero(self, mock_scene):
        await save_changelog(mock_scene)
        mock_scene.serialize = {"history": [], "characters": [{"name": "A"}]}
        await persist_test_mutation(mock_scene, {})

        result = await reconstruct_scene_data(mock_scene, to_rev=0)
        # No deltas applied → base data only
        assert result["characters"] == []


# ---------------------------------------------------------------------------
# Append-time rev stamping (issue #297)
# ---------------------------------------------------------------------------


class _DynamicHistoryScene(ChangelogScene):
    """``serialize`` derived live from ``history``, so rev stamps applied to
    message objects flow into the delta that ``append_delta`` computes."""

    @property
    def serialize(self):  # type: ignore[override]
        return {
            "history": [m.to_dict() for m in self.history],
            "characters": [],
        }

    @serialize.setter
    def serialize(self, value):
        pass


def _history_scene(tmp_dir: str) -> _DynamicHistoryScene:
    os.makedirs(tmp_dir, exist_ok=True)
    return _DynamicHistoryScene(save_dir=tmp_dir)


class TestAppendDeltaRevStamp:
    @pytest.mark.asyncio
    async def test_rev_stamp_recorded_with_appended_rev(self, temp_dir):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)

        msg = SceneMessage(message="hello")
        assert msg.rev == 0
        scene.history.append(msg)

        async with InMemoryChangelog(scene) as changelog:
            rev = await changelog.append_delta()
            assert rev == 1
            assert msg.rev == 1
            assert await changelog.commit() == [1]

        # The stamp is part of the delta: the reconstruction at the stamped
        # rev contains the message, carrying that rev.
        reconstructed = await reconstruct_scene_data(scene, to_rev=1)
        entry = next(e for e in reconstructed["history"] if e["id"] == msg.id)
        assert entry["rev"] == 1

    @pytest.mark.asyncio
    async def test_rev_stamp_sequences_with_pending_deltas(self, temp_dir):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)

        async with InMemoryChangelog(scene) as changelog:
            m1 = SceneMessage(message="one")
            scene.history.append(m1)
            assert await changelog.append_delta() == 1

            m2 = SceneMessage(message="two")
            scene.history.append(m2)
            assert await changelog.append_delta() == 2

            assert (m1.rev, m2.rev) == (1, 2)
            await changelog.commit()

        # Reconstruction at rev 1 contains m1 but not yet m2.
        reconstructed = await reconstruct_scene_data(scene, to_rev=1)
        ids = [e["id"] for e in reconstructed["history"]]
        assert m1.id in ids
        assert m2.id not in ids

    @pytest.mark.asyncio
    async def test_rev_stamp_rolls_back_when_delta_refused(self, temp_dir):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)

        msg = SceneMessage(message="hello")
        scene.history.append(msg)

        with mock.patch(
            "talemate.changelog._delta_reproduces_state", return_value=False
        ):
            async with InMemoryChangelog(scene) as changelog:
                assert await changelog.append_delta() is None
                # The refusal means the stamped rev never exists — the
                # message must not keep it.
                assert msg.rev == 0
                assert changelog.pending_count == 0

        # The next append retries from the same baseline and re-stamps.
        async with InMemoryChangelog(scene) as changelog:
            assert await changelog.append_delta() == 1
            assert msg.rev == 1

    @pytest.mark.asyncio
    async def test_rev_stamp_skips_messages_already_in_chain(self, temp_dir):
        # A message already recorded in the chain without a rev (legacy
        # scene, or history inherited by a fork) keeps rev 0: no revision of
        # this chain has it as its tip, so re-stamping it would point at a
        # reconstruction that also contains everything after it.
        scene = _history_scene(temp_dir)
        legacy = SceneMessage(message="old")
        scene.history.append(legacy)
        await save_changelog(scene)

        async with InMemoryChangelog(scene) as changelog:
            new = SceneMessage(message="new")
            scene.history.append(new)
            assert await changelog.append_delta() == 1

            assert legacy.rev == 0
            assert new.rev == 1


# ---------------------------------------------------------------------------
# Fork containment validation and rev zeroing (issue #297)
# ---------------------------------------------------------------------------


async def _scene_with_two_revs(tmp_dir: str):
    """Scene on disk with rev 1 (message id 1) and rev 2 (messages 1+2)."""
    m1 = {"id": 1, "message": "one", "typ": "narrator", "source": "ai", "flags": 0}
    m2 = {"id": 2, "message": "two", "typ": "narrator", "source": "ai", "flags": 0}

    scene = make_changelog_scene(tmp_dir)
    await save_changelog(scene)

    async with InMemoryChangelog(scene) as changelog:
        scene.serialize = {"history": [{**m1, "rev": 1}], "characters": []}
        assert await changelog.append_delta() == 1
        scene.serialize = {
            "history": [{**m1, "rev": 1}, {**m2, "rev": 2}],
            "characters": [],
        }
        assert await changelog.append_delta() == 2
        await changelog.commit()
    return scene


class TestForkContainment:
    @pytest.mark.asyncio
    async def test_fork_containment_raises_for_missing_message(self, temp_dir):
        scene = await _scene_with_two_revs(temp_dir)

        # Message 2 only exists at rev 2 — expecting it at rev 1 must refuse.
        with pytest.raises(ForkTargetMissingError):
            await fork_scene_at_revision(scene, 1, "forked", expect_message_id=2)

    @pytest.mark.asyncio
    async def test_fork_containment_passes_for_present_message(self, temp_dir):
        scene = await _scene_with_two_revs(temp_dir)

        out_path = await fork_scene_at_revision(scene, 1, "forked", expect_message_id=1)
        with open(out_path) as f:
            data = json.load(f)
        assert [e["id"] for e in data["history"]] == [1]

    @pytest.mark.asyncio
    async def test_fork_without_expectation_is_unchanged(self, temp_dir):
        scene = await _scene_with_two_revs(temp_dir)

        # The timeline-revision fork passes no message expectation.
        out_path = await fork_scene_at_revision(scene, 2, "forked")
        with open(out_path) as f:
            data = json.load(f)
        assert [e["id"] for e in data["history"]] == [1, 2]


class TestForkRevZero:
    @pytest.mark.asyncio
    async def test_fork_rev_zero_reconstructive(self, temp_dir):
        scene = await _scene_with_two_revs(temp_dir)

        out_path = await fork_scene_at_revision(scene, 2, "forked")
        with open(out_path) as f:
            data = json.load(f)

        # A fork starts its own chain at rev 0 — the source chain's revs are
        # meaningless in it and must not survive.
        assert [e["rev"] for e in data["history"]] == [0, 0]


class TestCreatorForkScene:
    """CreatorAgent.fork_scene: containment fallback and shallow rev zeroing.

    Calls ``fork_scene.__wrapped__`` to bypass the ``@set_processing``
    decorator (status emission is not under test).
    """

    def _scene_with_messages(self, tmp_dir, revs):
        scene = make_changelog_scene(tmp_dir)
        messages = []
        for i, rev in enumerate(revs):
            msg = SceneMessage(message=f"message {i}")
            msg.rev = rev
            messages.append(msg)
        scene.history = messages
        scene.serialize = {
            "history": [m.to_dict() for m in messages],
            "characters": [],
        }
        return scene, messages

    @pytest.mark.asyncio
    async def test_fork_scene_passes_expect_message_id(self, temp_dir):
        scene, messages = self._scene_with_messages(temp_dir, [5, 6])
        agent = mock.Mock()
        agent.scene = scene

        with (
            mock.patch("talemate.agents.creator.assistant.emit"),
            mock.patch(
                "talemate.agents.creator.assistant.fork_scene_at_revision",
                new=mock.AsyncMock(return_value="/tmp/fork.json"),
            ) as fork_mock,
        ):
            out_path = await AssistantMixin.fork_scene.__wrapped__(
                agent, message_id=messages[1].id, save_name="recon"
            )

        assert out_path == "/tmp/fork.json"
        fork_mock.assert_awaited_once()
        assert fork_mock.await_args.args[:3] == (scene, 6, "recon")
        assert fork_mock.await_args.kwargs["expect_message_id"] == messages[1].id

    @pytest.mark.asyncio
    async def test_fork_scene_falls_back_to_shallow_when_target_missing(self, temp_dir):
        scene, messages = self._scene_with_messages(temp_dir, [5, 6])
        agent = mock.Mock()
        agent.scene = scene

        with (
            mock.patch("talemate.agents.creator.assistant.emit"),
            mock.patch(
                "talemate.agents.creator.assistant.fork_scene_at_revision",
                new=mock.AsyncMock(side_effect=ForkTargetMissingError("gone")),
            ) as fork_mock,
        ):
            out_path = await AssistantMixin.fork_scene.__wrapped__(
                agent, message_id=messages[1].id, save_name="fallback-fork"
            )

        fork_mock.assert_awaited_once()
        with open(out_path) as f:
            data = json.load(f)
        assert [e["id"] for e in data["history"]] == [m.id for m in messages]
        assert [e["rev"] for e in data["history"]] == [0, 0]

    @pytest.mark.asyncio
    async def test_fork_rev_zero_shallow_preserves_live_scene(self, temp_dir):
        # Fork target has rev 0 → shallow fork; inherited revs on earlier
        # messages are zeroed in the fork but not on the live scene.
        scene, messages = self._scene_with_messages(temp_dir, [5, 0, 7])
        agent = mock.Mock()
        agent.scene = scene

        with mock.patch("talemate.agents.creator.assistant.emit"):
            out_path = await AssistantMixin.fork_scene.__wrapped__(
                agent, message_id=messages[1].id, save_name="shallow-fork"
            )

        with open(out_path) as f:
            data = json.load(f)
        assert [e["id"] for e in data["history"]] == [messages[0].id, messages[1].id]
        assert [e["rev"] for e in data["history"]] == [0, 0]
        assert [m.rev for m in messages] == [5, 0, 7]


# ---------------------------------------------------------------------------
# Rev-stamp robustness: ghost-rev windows, emission, backfill, save ordering
# ---------------------------------------------------------------------------


class TestAppendDeltaRevStampRobustness:
    @pytest.mark.asyncio
    async def test_rev_stamp_rolls_back_on_exception(self, temp_dir):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)

        msg = SceneMessage(message="hello")
        scene.history.append(msg)

        with mock.patch(
            "talemate.changelog._compute_delta",
            side_effect=RuntimeError("boom"),
        ):
            async with InMemoryChangelog(scene) as changelog:
                with pytest.raises(RuntimeError):
                    await changelog.append_delta()

        # No ghost rev left on the live message.
        assert msg.rev == 0

    @pytest.mark.asyncio
    async def test_rev_stamp_emits_message_revs_on_commit(self, temp_dir):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)

        captured = []

        def _capture(emission, **kwargs):
            captured.append(emission)

        handlers["message_revs"].connect(_capture)
        try:
            msg = SceneMessage(message="hello")
            scene.history.append(msg)
            async with InMemoryChangelog(scene) as changelog:
                await changelog.append_delta()
                # Staging alone emits nothing: with auto_save off a staged rev
                # exists only in pending_deltas, and the UI must not learn a
                # rev the committed chain cannot reconstruct.
                assert captured == []
                await changelog.commit()
        finally:
            handlers["message_revs"].disconnect(_capture)

        assert len(captured) == 1
        emission = captured[0]
        assert emission.typ == "message_revs"
        assert emission.websocket_passthrough is True
        assert emission.data == {"revs": [{"id": msg.id, "rev": 1}]}

    @pytest.mark.asyncio
    async def test_backfill_message_revs_from_latest_snapshot(self, temp_dir):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)

        msg = SceneMessage(message="hello")
        scene.history.append(msg)
        async with InMemoryChangelog(scene) as changelog:
            assert await changelog.append_delta() == 1
            await changelog.commit()

        # A scene file can lag the chain (crash between commit and file
        # write): the message comes back with rev 0 while the chain's latest
        # snapshot knows its rev.
        msg.rev = 0

        async with InMemoryChangelog(scene) as changelog:
            # Backfilled from the snapshot on enter...
            assert msg.rev == 1

            # ...and treated as known by the next append, not re-stamped.
            msg2 = SceneMessage(message="two")
            scene.history.append(msg2)
            assert await changelog.append_delta() == 2
            assert msg.rev == 1
            assert msg2.rev == 2

    @pytest.mark.asyncio
    async def test_save_writes_stamped_revs(self, temp_dir):
        # save() must append/commit the changelog before serializing the
        # scene file, or the file lags the chain by one save and a reload
        # loses the last turn's revs.
        scene = _history_scene(temp_dir)
        scene.name = "rev-stamp-save-test"
        await save_changelog(scene)

        msg = SceneMessage(message="hello")
        scene.history.append(msg)

        with mock.patch(
            "talemate.tale_mate.Scene.add_to_recent_scenes", new=mock.AsyncMock()
        ):
            async with InMemoryChangelog(scene) as changelog:
                scene._changelog = changelog
                await scene.save(auto=True)

        with open(os.path.join(temp_dir, scene.filename)) as f:
            data = json.load(f)
        assert data["history"][0]["rev"] == 1
        assert data["history"][0]["id"] == msg.id


def _changelog_artifacts(scene) -> dict[str, bytes]:
    if not os.path.isdir(scene.changelog_dir):
        return {}
    artifacts = {}
    for name in os.listdir(scene.changelog_dir):
        path = os.path.join(scene.changelog_dir, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                artifacts[name] = f.read()
    return artifacts


class TestCommitTransaction:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_target", ["segment", "latest"])
    async def test_failed_commit_restores_disk_and_retries_once(
        self, temp_dir, monkeypatch, failure_target
    ):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)
        before = _changelog_artifacts(scene)
        message = SceneMessage(message="hello")
        scene.history.append(message)
        emitted = []

        def capture(emission, **kwargs):
            emitted.append(emission)

        handlers["message_revs"].connect(capture)
        try:
            async with InMemoryChangelog(scene) as changelog:
                assert await changelog.append_delta() == 1
                real_write = changelog_mod._write_json
                failed = []

                def failing_write(path, data, cls=None):
                    is_target = (
                        ".changelog." in os.path.basename(path)
                        if failure_target == "segment"
                        else path == _latest_path(scene)
                    )
                    if is_target and not failed:
                        failed.append(path)
                        raise OSError(f"simulated {failure_target} failure")
                    return real_write(path, data, cls=cls)

                monkeypatch.setattr(changelog_mod, "_write_json", failing_write)
                with pytest.raises(OSError, match=f"simulated {failure_target}"):
                    await changelog.commit()

                assert _changelog_artifacts(scene) == before
                assert changelog.pending_count == 1
                assert scene.rev == 0
                assert message.rev == 1
                assert emitted == []

                monkeypatch.setattr(changelog_mod, "_write_json", real_write)
                assert await changelog.commit() == [1]

                assert changelog.pending_count == 0
                assert scene.rev == 1
        finally:
            handlers["message_revs"].disconnect(capture)

        assert [entry["rev"] for entry in list_revision_entries(scene)] == [1]
        assert len(emitted) == 1

    @pytest.mark.asyncio
    async def test_failed_base_initialization_leaves_no_artifacts(
        self, temp_dir, monkeypatch
    ):
        scene = _history_scene(temp_dir)
        message = SceneMessage(message="hello")

        async with InMemoryChangelog(scene) as changelog:
            scene._changelog = changelog
            scene.history.append(message)
            assert await changelog.append_delta() == 1
            real_write = changelog_mod._write_json

            def failing_write(path, data, cls=None):
                if path == _base_path(scene):
                    raise OSError("simulated base failure")
                return real_write(path, data, cls=cls)

            monkeypatch.setattr(changelog_mod, "_write_json", failing_write)
            with pytest.raises(OSError, match="simulated base failure"):
                await changelog.commit()

            assert _changelog_artifacts(scene) == {}
            assert changelog.pending_count == 1
            assert scene.rev == 0
            assert message.rev == 1

    @pytest.mark.asyncio
    async def test_failed_split_segment_removes_new_file(self, temp_dir, monkeypatch):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)
        async with InMemoryChangelog(scene) as changelog:
            scene.history.append(SceneMessage(message="one"))
            assert await changelog.append_delta() == 1
            assert await changelog.commit() == [1]

            scene.history.append(SceneMessage(message="two"))
            assert await changelog.append_delta() == 2
            before = _changelog_artifacts(scene)
            real_write = changelog_mod._write_json
            split_calls = []

            def failing_write(path, data, cls=None):
                if path.endswith(".changelog.2.json"):
                    split_calls.append(path)
                    if len(split_calls) == 2:
                        raise OSError("simulated split failure")
                return real_write(path, data, cls=cls)

            monkeypatch.setattr(changelog_mod, "MAX_CHANGELOG_FILE_SIZE", 1)
            monkeypatch.setattr(changelog_mod, "_write_json", failing_write)
            with pytest.raises(OSError, match="simulated split failure"):
                await changelog.commit()

            assert _changelog_artifacts(scene) == before
            assert changelog.pending_count == 1
            assert scene.rev == 1

            monkeypatch.setattr(changelog_mod, "_write_json", real_write)
            assert await changelog.commit() == [2]

        assert [entry["rev"] for entry in list_revision_entries(scene)] == [2, 1]

    @pytest.mark.asyncio
    async def test_failed_replace_restores_existing_segment_bytes(
        self, temp_dir, monkeypatch
    ):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)

        async with InMemoryChangelog(scene) as changelog:
            scene.history.append(SceneMessage(message="one"))
            assert await changelog.append_delta() == 1
            assert await changelog.commit() == [1]

            scene.history.append(SceneMessage(message="two"))
            assert await changelog.append_delta() == 2
            before = _changelog_artifacts(scene)
            log_path = _changelog_log_path(scene, 0)
            latest_path = _latest_path(scene)
            real_replace = changelog_mod.os.replace
            failed = []
            rollback_replacements = []

            def failing_replace(src, dst):
                if ".rollback.tmp." in os.fspath(src):
                    rollback_replacements.append(os.fspath(dst))
                if os.fspath(dst) == latest_path and not failed:
                    failed.append(os.fspath(dst))
                    raise OSError("simulated atomic replace failure")
                return real_replace(src, dst)

            monkeypatch.setattr(changelog_mod.os, "replace", failing_replace)
            with pytest.raises(OSError, match="simulated atomic replace failure"):
                await changelog.commit()

            assert _changelog_artifacts(scene) == before
            assert rollback_replacements == [log_path]
            assert changelog.pending_count == 1
            assert scene.rev == 1

            monkeypatch.setattr(changelog_mod.os, "replace", real_replace)
            assert await changelog.commit() == [2]

        assert [entry["rev"] for entry in list_revision_entries(scene)] == [2, 1]

    @pytest.mark.asyncio
    async def test_failed_rollback_poisoned_instance_cannot_duplicate_revision(
        self, temp_dir, monkeypatch
    ):
        scene = _history_scene(temp_dir)
        await save_changelog(scene)
        log_path = _changelog_log_path(scene, 0)

        async with InMemoryChangelog(scene) as changelog:
            scene.history.append(SceneMessage(message="one"))
            assert await changelog.append_delta() == 1
            real_write = changelog_mod._write_json
            real_remove = changelog_mod.os.remove

            def failing_write(path, data, cls=None):
                if path == _latest_path(scene):
                    raise OSError("simulated latest failure")
                return real_write(path, data, cls=cls)

            def failing_remove(path):
                if os.fspath(path) == log_path:
                    raise PermissionError("simulated rollback failure")
                return real_remove(path)

            monkeypatch.setattr(changelog_mod, "_write_json", failing_write)
            monkeypatch.setattr(changelog_mod.os, "remove", failing_remove)
            with pytest.raises(
                ExceptionGroup,
                match="Changelog commit failed and its rollback also failed",
            ):
                await changelog.commit()

            monkeypatch.setattr(changelog_mod, "_write_json", real_write)
            monkeypatch.setattr(changelog_mod.os, "remove", real_remove)
            assert [entry["rev"] for entry in list_revision_entries(scene)] == [1]
            assert changelog.pending_count == 1
            assert scene.rev == 0

            with pytest.raises(RuntimeError, match="reload the scene"):
                await changelog.commit()
            with pytest.raises(RuntimeError, match="reload the scene"):
                await changelog.append_delta()

        assert [entry["rev"] for entry in list_revision_entries(scene)] == [1]


# ---------------------------------------------------------------------------
# Fork guards: beyond-latest revision, writer zeroing
# ---------------------------------------------------------------------------


class TestForkGuards:
    @pytest.mark.asyncio
    async def test_fork_beyond_latest_rev_raises(self, temp_dir):
        scene = await _scene_with_two_revs(temp_dir)

        # A rev that never materialized cannot reconstruct "at the message".
        with pytest.raises(ForkTargetMissingError):
            await fork_scene_at_revision(scene, 99, "forked")
        with pytest.raises(ForkTargetMissingError):
            await fork_scene_at_revision(scene, 99, "forked", expect_message_id=2)

    @pytest.mark.asyncio
    async def test_write_reconstructed_scene_zero_message_revs(self, temp_dir):
        scene = await _scene_with_two_revs(temp_dir)

        out_path = await write_reconstructed_scene(
            scene, 2, "zeroed.json", zero_message_revs=True
        )
        with open(out_path) as f:
            data = json.load(f)
        assert [e["rev"] for e in data["history"]] == [0, 0]

    @pytest.mark.asyncio
    async def test_write_reconstructed_scene_default_keeps_revs(self, temp_dir):
        scene = await _scene_with_two_revs(temp_dir)

        out_path = await write_reconstructed_scene(scene, 2, "kept.json")
        with open(out_path) as f:
            data = json.load(f)
        assert [e["rev"] for e in data["history"]] == [1, 2]
