"""
Tests for the scene time migration on the load and changelog paths.

Scene time used to be persisted as ISO8601 durations ("P1M", "PT1H") and is
now integer seconds. Saves, changelog snapshots and changelog deltas written
before that switch are never rewritten on disk, so every path that feeds
persisted scene data back into scene state has to convert on read.

The fixtures under ``tests/data/scene_time_migration`` are hand-authored in
the OLD format: a scene file (revision 1), a base snapshot (revision 0), a
latest snapshot and a single delta between the two revisions. They stand in
for a scene that was last saved before the migration.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

import talemate.agents.tts.voice_library as voice_library
import talemate.instance as instance
from _changelog_test_helpers import make_changelog_scene
from conftest import MockScene, bootstrap_scene
from talemate.changelog import (
    InMemoryChangelog,
    _base_path,
    _compute_delta,
    _latest_path,
    _load_latest_scene_data,
    append_scene_delta,
    fork_scene_at_revision,
    reconstruct_cleanup,
    reconstruct_scene_data,
    rollback_scene_to_revision,
)
from talemate.load import load_scene_from_data
from talemate.util.time import migrate_scene_time
from talemate.scene_message import TimePassageMessage
from talemate.shared_context import SharedContext
from talemate.tale_mate import Scene

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "data", "scene_time_migration")
SCENE_FILE = "legacy-time-scene.json"

SHARED_CONTEXT_FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "data", "shared_context_migration"
)
SHARED_CONTEXT_FILE = "legacy-shared-context.json"

MONTH = 2_592_000
HOUR = 3600
DAY = 86400

# Scene time the fixture's history adds up to: the last no-end archive entry
# ("P3M") plus both time passage messages ("PT1H" + "P1D").
EXPECTED_SCENE_TS = 3 * MONTH + HOUR + DAY


def _read_fixture(name: str = SCENE_FILE) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), "r") as f:
        return json.load(f)


def _assert_scene_time_is_int(data: dict):
    assert isinstance(data["ts"], int)
    for message in data["history"]:
        if message["typ"] == "time":
            assert isinstance(message["ts"], int)
    for entry in data["archived_history"]:
        assert isinstance(entry["ts"], int)
    for layer in data["layered_history"]:
        for entry in layer:
            assert isinstance(entry["ts"], int)
            assert isinstance(entry["ts_start"], int)
            assert isinstance(entry["ts_end"], int)


def _digests(root: str) -> dict[str, str]:
    """Map of relative path -> sha256 for every file under ``root``."""
    digests = {}
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            with open(path, "rb") as f:
                digests[os.path.relpath(path, root)] = hashlib.sha256(
                    f.read()
                ).hexdigest()
    return digests


@pytest.fixture
def fixture_copy(tmp_path):
    """Copy of the fixture set the changelog tests may write into."""
    target = str(tmp_path / "legacy-scene")
    shutil.copytree(FIXTURE_DIR, target)
    return target


@pytest.fixture
def changelog_scene(fixture_copy):
    scene = make_changelog_scene(
        fixture_copy,
        filename=SCENE_FILE,
        initial_serialize=_read_fixture(),
    )
    return scene


# ---------------------------------------------------------------------------
# migrate_scene_time
# ---------------------------------------------------------------------------


class TestMigrateSceneTime:
    def test_converts_every_location(self):
        data = migrate_scene_time(_read_fixture())

        assert data["ts"] == 3 * MONTH + 25 * HOUR
        assert [m["ts"] for m in data["history"] if m["typ"] == "time"] == [HOUR, DAY]
        assert [e["ts"] for e in data["archived_history"]] == [
            MONTH,
            3 * MONTH,
            3 * MONTH + HOUR,
        ]

        layer_entry = data["layered_history"][0][0]
        assert layer_entry["ts"] == MONTH
        assert layer_entry["ts_start"] == MONTH
        assert layer_entry["ts_end"] == 3 * MONTH + HOUR

    def test_leaves_non_time_messages_alone(self):
        data = migrate_scene_time(_read_fixture())

        narrator = data["history"][0]
        assert narrator["typ"] == "narrator"
        assert "ts" not in narrator

    def test_idempotent(self):
        once = migrate_scene_time(_read_fixture())
        twice = migrate_scene_time(json.loads(json.dumps(once)))

        assert twice == once

    def test_missing_keys_stay_missing(self):
        data = migrate_scene_time(
            {
                "history": [{"typ": "time", "message": "later"}],
                "archived_history": [{"text": "no timestamps"}],
                "layered_history": [[{"text": "no timestamps", "ts": "PT1H"}]],
            }
        )

        assert "ts" not in data
        assert "ts" not in data["history"][0]
        assert data["archived_history"][0] == {"text": "no timestamps"}
        assert "ts_start" not in data["layered_history"][0][0]

    def test_null_timestamps_stay_null(self):
        data = migrate_scene_time(
            {"layered_history": [[{"ts": "PT1H", "ts_start": None, "ts_end": None}]]}
        )

        entry = data["layered_history"][0][0]
        assert entry["ts"] == HOUR
        assert entry["ts_start"] is None
        assert entry["ts_end"] is None

    def test_integers_pass_through(self):
        data = migrate_scene_time(
            {
                "ts": 900,
                "history": [{"typ": "time", "ts": 60}],
                "archived_history": [{"ts": 0, "ts_start": 0, "ts_end": 120}],
            }
        )

        assert data["ts"] == 900
        assert data["history"][0]["ts"] == 60
        assert data["archived_history"][0] == {"ts": 0, "ts_start": 0, "ts_end": 120}

    def test_empty_scene_data(self):
        assert migrate_scene_time({}) == {}

    @pytest.mark.parametrize(
        "scene_data",
        [
            {"ts": "not a duration"},
            {"history": [{"typ": "time", "ts": "1 hour"}]},
            {"archived_history": [{"text": "x", "ts": "P"}]},
            {"layered_history": [[{"text": "x", "ts_end": ""}]]},
        ],
    )
    def test_malformed_value_raises(self, scene_data):
        with pytest.raises(ValueError):
            migrate_scene_time(scene_data)

    def test_tolerant_mode_repairs_malformed_values(self):
        data = migrate_scene_time(
            {
                "ts": "not a duration",
                "history": [
                    {"typ": "time", "ts": "1 hour"},
                    {"typ": "time", "ts": "PT1H"},
                ],
                "archived_history": [{"text": "x", "ts": ""}],
                "layered_history": [[{"text": "x", "ts": "P1M", "ts_end": "P"}]],
            },
            tolerant=True,
        )

        # non-nullable locations fall back to zero
        assert data["ts"] == 0
        assert data["history"][0]["ts"] == 0
        assert data["archived_history"][0]["ts"] == 0
        # only the nullable range bounds fall back to null
        assert data["layered_history"][0][0]["ts_end"] is None
        # everything readable still migrates
        assert data["history"][1]["ts"] == HOUR
        assert data["layered_history"][0][0]["ts"] == MONTH

    def test_tolerant_mode_repairs_non_finite_values(self):
        data = migrate_scene_time(
            {
                "ts": float("inf"),
                "archived_history": [{"text": "x", "ts": float("nan")}],
                "layered_history": [[{"text": "x", "ts_end": float("-inf")}]],
            },
            tolerant=True,
        )

        assert data["ts"] == 0
        assert data["archived_history"][0]["ts"] == 0
        assert data["layered_history"][0][0]["ts_end"] is None


# ---------------------------------------------------------------------------
# Full scene load
# ---------------------------------------------------------------------------


@pytest.fixture
def load_env(tmp_path, monkeypatch):
    """Agent stack + scenes directory a legacy scene can be loaded into."""
    scene = MockScene()
    bootstrap_scene(scene)
    monkeypatch.setattr(
        Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)), raising=True
    )
    scene.project_name = "legacy-time-scene"

    memory = instance.get_agent("memory")
    monkeypatch.setattr(memory, "set_db", _noop, raising=False)
    monkeypatch.setattr(memory, "get_document", _no_documents, raising=False)
    voice_library.VOICE_LIBRARY = voice_library.VoiceLibrary(voices={})

    return scene


async def _noop(*args, **kwargs):
    return None


async def _no_documents(*args, **kwargs):
    return {}


@pytest.mark.asyncio
async def test_load_scene_migrates_legacy_time(load_env):
    scene = await load_scene_from_data(load_env, _read_fixture(), name=SCENE_FILE)

    assert scene.ts == EXPECTED_SCENE_TS

    time_messages = [m for m in scene.history if isinstance(m, TimePassageMessage)]
    assert [m.ts for m in time_messages] == [HOUR, DAY]

    # Entries without an `end` index keep their persisted timestamp; the rest
    # are recomputed by fix_time().
    assert scene.archived_history[0]["ts"] == MONTH
    assert scene.archived_history[1]["ts"] == 3 * MONTH
    for entry in scene.archived_history:
        assert isinstance(entry["ts"], int)

    for layer in scene.layered_history:
        for entry in layer:
            assert isinstance(entry["ts"], int)
            assert isinstance(entry["ts_start"], int)
            assert isinstance(entry["ts_end"], int)


@pytest.mark.asyncio
async def test_load_scene_leaves_fixture_files_untouched(load_env):
    before = _digests(FIXTURE_DIR)
    await load_scene_from_data(load_env, _read_fixture(), name=SCENE_FILE)
    assert _digests(FIXTURE_DIR) == before


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_context_migrates_static_history():
    shared = SharedContext(
        filepath=Path(SHARED_CONTEXT_FIXTURE_DIR) / SHARED_CONTEXT_FILE
    )
    await shared.init_from_file()

    assert [entry.ts for entry in shared.static_history] == [MONTH, 3 * MONTH + HOUR]
    for entry in shared.static_history:
        assert isinstance(entry.ts, int)


@pytest.mark.asyncio
async def test_load_scene_with_legacy_shared_context(load_env):
    shared_context_dir = Path(load_env.shared_context_dir)
    shared_context_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        os.path.join(SHARED_CONTEXT_FIXTURE_DIR, SHARED_CONTEXT_FILE),
        shared_context_dir,
    )

    scene_data = _read_fixture()
    scene_data["shared_context"] = SHARED_CONTEXT_FILE

    scene = await load_scene_from_data(load_env, scene_data, name=SCENE_FILE)

    assert [entry.ts for entry in scene.shared_context.static_history] == [
        MONTH,
        3 * MONTH + HOUR,
    ]
    # the shared static entries replace the scene's own static entries, the
    # summarized entry (the only one with an `end`) is kept and re-timed
    assert [entry["ts"] for entry in scene.archived_history[:2]] == [
        MONTH,
        3 * MONTH + HOUR,
    ]
    assert scene.archived_history[2]["end"] == 2
    for entry in scene.archived_history:
        assert isinstance(entry["ts"], int)


@pytest.mark.asyncio
async def test_shared_context_read_leaves_fixture_file_untouched():
    before = _digests(SHARED_CONTEXT_FIXTURE_DIR)
    shared = SharedContext(
        filepath=Path(SHARED_CONTEXT_FIXTURE_DIR) / SHARED_CONTEXT_FILE
    )
    await shared.init_from_file()
    assert _digests(SHARED_CONTEXT_FIXTURE_DIR) == before


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconstruct_base_revision_migrates(changelog_scene):
    data = await reconstruct_scene_data(changelog_scene, to_rev=0)

    assert data["ts"] == 3 * MONTH + HOUR
    assert [m["ts"] for m in data["history"] if m["typ"] == "time"] == [HOUR]
    assert [e["ts"] for e in data["archived_history"]] == [MONTH, 3 * MONTH]


@pytest.mark.asyncio
async def test_reconstruct_delta_revision_migrates(changelog_scene):
    data = await reconstruct_scene_data(changelog_scene, to_rev=1)

    assert data["ts"] == 3 * MONTH + 25 * HOUR
    assert [m["ts"] for m in data["history"] if m["typ"] == "time"] == [HOUR, DAY]
    assert [e["ts"] for e in data["archived_history"]] == [
        MONTH,
        3 * MONTH,
        3 * MONTH + HOUR,
    ]
    layer_entry = data["layered_history"][0][0]
    assert (layer_entry["ts"], layer_entry["ts_start"], layer_entry["ts_end"]) == (
        MONTH,
        MONTH,
        3 * MONTH + HOUR,
    )


@pytest.mark.asyncio
async def test_reconstruct_leaves_changelog_files_untouched(changelog_scene):
    before = _digests(changelog_scene.save_dir)
    await reconstruct_scene_data(changelog_scene, to_rev=0)
    await reconstruct_scene_data(changelog_scene, to_rev=1)
    assert _digests(changelog_scene.save_dir) == before


@pytest.mark.asyncio
async def test_fork_writes_migrated_scene(changelog_scene):
    fork_path = await fork_scene_at_revision(changelog_scene, 0, "forked")

    with open(fork_path, "r") as f:
        forked = json.load(f)

    assert forked["ts"] == 3 * MONTH + HOUR
    assert [e["ts"] for e in forked["archived_history"]] == [MONTH, 3 * MONTH]
    assert forked["immutable_save"] is False


@pytest.mark.asyncio
async def test_rollback_writes_migrated_scene(changelog_scene):
    changelog_before = _digests(changelog_scene.changelog_dir)

    scene_path = await rollback_scene_to_revision(
        changelog_scene, 0, create_backup=True
    )

    with open(scene_path, "r") as f:
        rolled_back = json.load(f)

    assert rolled_back["ts"] == 3 * MONTH + HOUR
    assert [m["ts"] for m in rolled_back["history"] if m["typ"] == "time"] == [HOUR]

    # Rollback rewrites the scene file only; the changelog artifacts it read
    # from stay exactly as they were.
    assert _digests(changelog_scene.changelog_dir) == changelog_before


@pytest.mark.asyncio
async def test_legacy_latest_snapshot_does_not_diff_against_migrated_scene(
    changelog_scene,
):
    """A migrated scene must not diff against its pre-migration snapshot.

    The latest snapshot is the baseline new deltas are computed from. Left
    unmigrated, every scene time field would show up as a change on the first
    save after the migration.
    """
    changelog_scene.serialize = migrate_scene_time(_read_fixture())

    async with InMemoryChangelog(changelog_scene) as changelog:
        assert await changelog.append_delta({"action": "no_op"}) is None

    # ... while a real change still produces a delta that carries integers.
    changelog_scene.serialize = migrate_scene_time(_read_fixture())
    changelog_scene.serialize["ts"] = EXPECTED_SCENE_TS + DAY

    async with InMemoryChangelog(changelog_scene) as changelog:
        assert await changelog.append_delta({"action": "time_passage"}) == 1

    delta = changelog.pending_deltas[0]["delta"]
    assert delta["values_changed"]["root['ts']"]["new_value"] == EXPECTED_SCENE_TS + DAY


@pytest.mark.asyncio
async def test_delta_written_after_migration_reconstructs(changelog_scene):
    """A changelog may mix legacy and migrated revisions.

    Reconstruction only survives that because the migration runs after every
    delta has been applied: an integer delta written post-migration is
    applied on top of ISO8601 values, and the whole result is converted at
    the end.
    """
    scene_data = migrate_scene_time(_read_fixture())
    scene_data["history"].append(
        {
            "typ": "time",
            "message": "A day passes.",
            "ts": DAY,
            "source": "manual",
            "flags": 0,
            "id": 5,
        }
    )
    scene_data["ts"] = 3 * MONTH + 25 * HOUR + DAY
    changelog_scene.serialize = scene_data

    assert await append_scene_delta(changelog_scene, {"action": "time_passage"}) == 2

    latest = await reconstruct_scene_data(changelog_scene)
    assert latest["ts"] == 3 * MONTH + 25 * HOUR + DAY
    assert [m["ts"] for m in latest["history"] if m["typ"] == "time"] == [
        HOUR,
        DAY,
        DAY,
    ]
    _assert_scene_time_is_int(latest)

    # the legacy revisions still reconstruct as integers
    for to_rev in (0, 1):
        _assert_scene_time_is_int(await reconstruct_scene_data(changelog_scene, to_rev))


@pytest.mark.asyncio
async def test_reconstruct_cleanup_repairs_damaged_scene_time():
    """Reconstruction repairs damaged time values instead of aborting.

    Deltas are applied with `force=True`, so a reconstructed revision can carry
    values no parser accepts. Rollback / fork / preview have no way to recover
    from an exception here, so the migration repairs alongside the other
    reconstruction repairs.
    """
    data = _read_fixture()
    data["ts"] = ""
    data["history"][1]["ts"] = "1 hour"
    data["archived_history"][0]["ts"] = ""
    data["layered_history"][0][0]["ts_end"] = "P"

    result = await reconstruct_cleanup(data)

    assert result["ts"] == 0
    assert result["history"][1]["ts"] == 0
    assert result["archived_history"][0]["ts"] == 0
    assert result["layered_history"][0][0]["ts_end"] is None

    # the rest of the timeline reconstructs untouched
    assert result["history"][3]["ts"] == DAY
    assert [e["ts"] for e in result["archived_history"][1:]] == [
        3 * MONTH,
        3 * MONTH + HOUR,
    ]
    assert result["layered_history"][0][0]["ts"] == MONTH
    assert result["name"] == "Legacy Time Scene"


@pytest.mark.asyncio
async def test_repaired_reconstruction_loads_and_commits(load_env, monkeypatch):
    """A repaired revision has to survive the load that follows a rollback.

    Rollback writes the reconstructed data to the scene file, and the load
    that follows commits it to memory. `ArchiveEntry.ts` is not nullable, so
    an entry repaired to null would make the rolled back scene unloadable.
    """
    data = _read_fixture()
    data["archived_history"][0]["ts"] = ""

    repaired = await reconstruct_cleanup(data)
    assert repaired["archived_history"][0]["ts"] == 0

    committed = []

    async def _record(items):
        committed.extend(items)

    memory = instance.get_agent("memory")
    monkeypatch.setattr(memory, "drop_db", lambda: None, raising=False)
    monkeypatch.setattr(memory, "add_many", _record)

    scene = await load_scene_from_data(load_env, repaired, name=SCENE_FILE)
    await scene.commit_to_memory()

    assert scene.archived_history[0]["ts"] == 0
    for entry in scene.archived_history:
        assert isinstance(entry["ts"], int)

    assert [entry["meta"]["ts"] for entry in committed][:2] == [0, 3 * MONTH]


@pytest.mark.asyncio
async def test_reconstruct_survives_damaged_base_snapshot(changelog_scene):
    base_path = _base_path(changelog_scene)
    with open(base_path, "r") as f:
        base_data = json.load(f)
    base_data["archived_history"][0]["ts"] = ""
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    data = await reconstruct_scene_data(changelog_scene, to_rev=0)

    assert data["archived_history"][0]["ts"] == 0
    assert data["archived_history"][1]["ts"] == 3 * MONTH
    assert data["ts"] == 3 * MONTH + HOUR


def test_load_latest_scene_data_survives_damaged_timestamp(changelog_scene):
    """The latest snapshot is a fallback-able optimization, not a hard input."""
    latest_path = _latest_path(changelog_scene)
    with open(latest_path, "r") as f:
        latest_data = json.load(f)
    latest_data["archived_history"][0]["ts"] = ""
    with open(latest_path, "w") as f:
        json.dump(latest_data, f)

    data = _load_latest_scene_data(changelog_scene)

    assert data is not None
    assert data["archived_history"][0]["ts"] == 0
    assert data["ts"] == 3 * MONTH + 25 * HOUR


def test_unmigrated_baseline_would_diff_every_timestamp():
    """Guards the premise of the migration above: the raw legacy snapshot and
    the migrated scene data differ on every scene time field."""
    delta = _compute_delta(_read_fixture(), migrate_scene_time(_read_fixture()))

    changed = set(delta["values_changed"])
    assert "root['ts']" in changed
    assert "root['archived_history'][0]['ts']" in changed
    assert "root['history'][1]['ts']" in changed
    assert "root['layered_history'][0][0]['ts_end']" in changed
