import os
import json
import glob
import tempfile
import shutil
import pytest
from datetime import datetime, timezone

from _changelog_test_helpers import persist_test_mutation, make_changelog_scene
from talemate.scene_message import NarratorMessage
from talemate.changelog import (
    save_changelog,
    reconstruct_scene_data,
    reconstruct_cleanup,
    write_reconstructed_scene,
    list_revisions,
    rollback_scene_to_revision,
    delete_changelog_files,
    _changelog_log_path,
    _base_path,
    _latest_path,
    _read_json_or_default,
    _write_json,
    _ensure_log_initialized,
    _load_base_scene_data,
    _load_latest_scene_data,
    _ensure_latest_initialized,
    _apply_delta,
    _compute_delta,
    _parse_delta_path,
    _delta_reproduces_state,
    _serialize_scene_plain,
    check_chain_divergence,
    ChangelogDivergedError,
    ChangelogCorruptedError,
    _read_changelog_log_strict,
    _get_changelog_files,
    _get_latest_changelog_file,
    _get_overall_latest_revision,
    _get_file_size,
    _SceneRef,
    MAX_CHANGELOG_FILE_SIZE,
    InMemoryChangelog,
    rebase_changelog_chain,
    read_rebase_marker,
    _rebase_marker_path,
    REORDERED_LISTS_KEY,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_scene(temp_dir):
    # Real ``Scene`` subclass (see _changelog_test_helpers.ChangelogScene) with
    # ``serialize`` exposed as a settable attribute so tests can drive arbitrary
    # payloads. ``filename``/``save_dir``/``changelog_dir``/``rev``/``_changelog``
    # remain the real ``Scene`` fields/properties — renames or removals will
    # break these tests.
    return make_changelog_scene(
        temp_dir,
        filename="test_scene.json",
        initial_serialize={
            "characters": [],
            "entries": [],
            "metadata": {"version": "1.0"},
        },
    )


def test_changelog_log_path(mock_scene):
    """Test changelog log path generation."""
    expected = os.path.join(
        mock_scene.changelog_dir, "test_scene.json.changelog.0.json"
    )
    result = _changelog_log_path(mock_scene, 0)
    assert result == expected
    assert os.path.exists(mock_scene.changelog_dir)

    # Test with different start revision
    expected = os.path.join(
        mock_scene.changelog_dir, "test_scene.json.changelog.123.json"
    )
    result = _changelog_log_path(mock_scene, 123)
    assert result == expected


def test_base_path(mock_scene):
    """Test base path generation."""
    expected = os.path.join(mock_scene.changelog_dir, "test_scene.json.base.json")
    result = _base_path(mock_scene)
    assert result == expected


def test_latest_path(mock_scene):
    """Test latest path generation."""
    expected = os.path.join(mock_scene.changelog_dir, "test_scene.json.latest.json")
    result = _latest_path(mock_scene)
    assert result == expected


def test_read_json_or_default_file_exists(temp_dir):
    """Test reading existing JSON file."""
    test_data = {"test": "data"}
    test_file = os.path.join(temp_dir, "test.json")

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    result = _read_json_or_default(test_file, {})
    assert result == test_data


def test_read_json_or_default_file_missing(temp_dir):
    """Test reading non-existent JSON file returns default."""
    test_file = os.path.join(temp_dir, "missing.json")
    default = {"default": "value"}

    result = _read_json_or_default(test_file, default)
    assert result == default


def test_read_json_or_default_invalid_json(temp_dir):
    """Test reading invalid JSON file returns default."""
    test_file = os.path.join(temp_dir, "invalid.json")
    default = {"default": "value"}

    with open(test_file, "w") as f:
        f.write("invalid json content")

    result = _read_json_or_default(test_file, default)
    assert result == default


def test_write_json(temp_dir):
    """Test writing JSON data to file."""
    test_data = {"test": "data", "number": 42}
    test_file = os.path.join(temp_dir, "subdir", "test.json")

    _write_json(test_file, test_data)

    assert os.path.exists(test_file)
    with open(test_file, "r") as f:
        result = json.load(f)
    assert result == test_data


def test_write_json_leaves_no_tmp_files(temp_dir):
    """The atomic write cleans up after itself."""
    test_file = os.path.join(temp_dir, "test.json")

    _write_json(test_file, {"a": 1})

    assert os.listdir(temp_dir) == ["test.json"]


def test_write_json_failed_replace_keeps_original(temp_dir, monkeypatch):
    """A failed atomic replace leaves the pre-existing file intact."""
    test_file = os.path.join(temp_dir, "test.json")
    with open(test_file, "w") as f:
        json.dump({"original": True}, f)

    def _failing_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("talemate.changelog.os.replace", _failing_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        _write_json(test_file, {"corrupted": True})

    with open(test_file) as f:
        assert json.load(f) == {"original": True}


def test_read_changelog_log_strict_missing(temp_dir):
    """A missing changelog log reads as None (not an error)."""
    assert _read_changelog_log_strict(os.path.join(temp_dir, "missing.json")) is None


def test_read_changelog_log_strict_corrupted_raises(temp_dir):
    """A corrupted changelog log raises instead of reading as empty."""
    test_file = os.path.join(temp_dir, "scene.json.changelog.0.json")
    with open(test_file, "w") as f:
        f.write('{"deltas": [{"rev": 1, "delta": ')

    with pytest.raises(ChangelogCorruptedError, match="Unreadable changelog file"):
        _read_changelog_log_strict(test_file)


def test_read_changelog_log_strict_wrong_shape_raises(temp_dir):
    """Valid JSON that is not a changelog log shape raises as malformed."""
    for content in (
        "[]",
        "null",
        '{"deltas": "invalid"}',
        '{"deltas": [], "latest_rev": "three"}',
    ):
        test_file = os.path.join(temp_dir, "scene.json.changelog.0.json")
        with open(test_file, "w") as f:
            f.write(content)

        with pytest.raises(ChangelogCorruptedError, match="Malformed changelog file"):
            _read_changelog_log_strict(test_file)


def test_load_base_scene_data_corrupted_raises_changelog_error(mock_scene):
    """A corrupted base snapshot raises ChangelogCorruptedError, not JSONDecodeError."""
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)
    with open(_base_path(mock_scene), "w") as f:
        f.write('{"history": [')

    with pytest.raises(ChangelogCorruptedError, match="Unreadable changelog file"):
        _load_base_scene_data(mock_scene)


@pytest.mark.asyncio
async def test_check_chain_divergence_missing_latest_raises(mock_scene):
    """A chain without a latest snapshot cannot be verified — must not read healthy."""
    await save_changelog(mock_scene)
    os.remove(_latest_path(mock_scene))

    with pytest.raises(ChangelogCorruptedError, match="latest snapshot is missing"):
        await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
async def test_check_chain_divergence_unreadable_latest_raises(mock_scene):
    """An unreadable latest snapshot cannot be verified — must not read healthy."""
    await save_changelog(mock_scene)
    with open(_latest_path(mock_scene), "w") as f:
        f.write("not json")

    with pytest.raises(ChangelogCorruptedError, match="latest snapshot is unreadable"):
        await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
async def test_restore_refused_on_diverged_chain(mock_scene):
    """Scene.restore(from_rev=...) — the live rollback path — refuses divergence."""
    await save_changelog(mock_scene)

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    with open(_latest_path(mock_scene)) as f:
        latest = json.load(f)
    latest["characters"][0]["name"] = "Bob"
    with open(_latest_path(mock_scene), "w") as f:
        json.dump(latest, f)

    with pytest.raises(ChangelogDivergedError, match="Refusing to restore"):
        await mock_scene.restore(from_rev=1)


@pytest.mark.asyncio
async def test_quarantine_corrupted_changelog_files(mock_scene):
    """A corrupted segment is renamed aside and the save path recovers."""
    from talemate.changelog import quarantine_corrupted_changelog_files

    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "w") as f:
        f.write('{"deltas": [{"rev": 1, "delta": ')

    quarantined = quarantine_corrupted_changelog_files(mock_scene)

    assert quarantined == [f"{log_path}.corrupted"]
    assert not os.path.exists(log_path)
    assert os.path.exists(f"{log_path}.corrupted")
    assert _get_changelog_files(mock_scene) == []

    # the marker records the loss: the chain is unverifiable from now on
    marker_path = os.path.join(
        mock_scene.changelog_dir, f"{mock_scene.filename}.quarantine.json"
    )
    assert os.path.exists(marker_path)
    with pytest.raises(ChangelogCorruptedError, match="quarantined"):
        await check_chain_divergence(mock_scene)

    # the save path works again and continues above the live scene revision
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": ["new"],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 2


@pytest.mark.asyncio
async def test_quarantine_leaves_healthy_chain_alone(mock_scene):
    from talemate.changelog import quarantine_corrupted_changelog_files

    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    assert quarantine_corrupted_changelog_files(mock_scene) == []
    assert list_revisions(mock_scene) == [1]


@pytest.mark.asyncio
async def test_quarantine_corrupted_latest_snapshot(mock_scene):
    """A corrupted latest snapshot is renamed aside; no marker (no deltas lost)."""
    from talemate.changelog import quarantine_corrupted_changelog_files

    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    latest_path = _latest_path(mock_scene)
    with open(latest_path, "w") as f:
        f.write("not json")

    quarantined = quarantine_corrupted_changelog_files(mock_scene)

    assert quarantined == [f"{latest_path}.corrupted"]
    assert not os.path.exists(latest_path)

    # no segments were lost, so no marker — but until the next append
    # rewrites the latest snapshot, the chain cannot be verified
    marker_path = os.path.join(
        mock_scene.changelog_dir, f"{mock_scene.filename}.quarantine.json"
    )
    assert not os.path.exists(marker_path)
    with pytest.raises(ChangelogCorruptedError, match="latest snapshot is missing"):
        await check_chain_divergence(mock_scene)

    # the next append recovers: latest is reinitialized and the delta written
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": ["new"],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 2


@pytest.mark.asyncio
async def test_quarantine_marker_makes_gap_unverifiable(mock_scene):
    """End-state agreement cannot prove a quarantined segment did not matter.

    base {x:0,y:0}; rev 1 (x:0→1) in its own segment, corrupted and
    quarantined; surviving revs 2 (y:0→1) and 3 (x:1→2). Reconstruction
    without rev 1 still yields {x:2,y:1} == latest (delta application
    writes new_value unconditionally), so only the quarantine marker stands
    between this chain and a false "healthy" verdict.
    """
    from talemate.changelog import quarantine_corrupted_changelog_files

    os.makedirs(mock_scene.changelog_dir, exist_ok=True)
    with open(_base_path(mock_scene), "w") as f:
        json.dump({"x": 0, "y": 0}, f)
    with open(_latest_path(mock_scene), "w") as f:
        json.dump({"x": 2, "y": 1}, f)

    def _segment(start_rev, deltas, latest_rev):
        return {
            "version": 1,
            "base": "test_scene.json.base.json",
            "start_rev": start_rev,
            "deltas": deltas,
            "latest_rev": latest_rev,
        }

    seg0 = _changelog_log_path(mock_scene, 0)
    with open(seg0, "w") as f:
        json.dump(
            _segment(
                0,
                [
                    {
                        "rev": 1,
                        "ts": 1,
                        "delta": {"values_changed": {"root['x']": {"new_value": 1}}},
                        "meta": {},
                    }
                ],
                1,
            ),
            f,
        )
    seg2 = _changelog_log_path(mock_scene, 2)
    with open(seg2, "w") as f:
        json.dump(
            _segment(
                2,
                [
                    {
                        "rev": 2,
                        "ts": 2,
                        "delta": {"values_changed": {"root['y']": {"new_value": 1}}},
                        "meta": {},
                    },
                    {
                        "rev": 3,
                        "ts": 3,
                        "delta": {"values_changed": {"root['x']": {"new_value": 2}}},
                        "meta": {},
                    },
                ],
                3,
            ),
            f,
        )

    # complete chain verifies healthy
    assert await check_chain_divergence(mock_scene) == []

    with open(seg0, "w") as f:
        f.write('{"deltas": [{"rev": 1, "delta": ')

    quarantined = quarantine_corrupted_changelog_files(mock_scene)
    assert quarantined == [f"{seg0}.corrupted"]

    # the counterexample: the end state still matches the latest snapshot…
    reconstructed = await reconstruct_scene_data(mock_scene)
    assert (reconstructed["x"], reconstructed["y"]) == (2, 1)

    # …but the marker makes the chain unverifiable instead of "healthy"
    with pytest.raises(ChangelogCorruptedError, match="quarantined"):
        await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
async def test_quarantine_continues_revision_namespace(mock_scene):
    """New revisions continue above the quarantined range, not from 0."""
    from talemate.changelog import quarantine_corrupted_changelog_files

    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    # a later segment (start_rev 5) that is corrupted
    seg5 = _changelog_log_path(mock_scene, 5)
    with open(seg5, "w") as f:
        f.write('{"deltas": [{"rev": 5, "delta": ')

    quarantined = quarantine_corrupted_changelog_files(mock_scene)
    assert f"{seg5}.corrupted" in quarantined

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": ["new"],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 6


@pytest.mark.asyncio
async def test_quarantine_rev_hint_reaches_in_memory_changelog(mock_scene):
    """The production save path numbers new revisions above the lost range.

    Drives the same helper scene load uses, so the pin covers the actual
    order (quarantine writes the marker BEFORE scene.rev is resolved from
    it), then the InMemoryChangelog numbering the game loop saves through.
    """
    from talemate.load import _quarantine_and_resolve_rev

    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    # a later segment (start_rev 5), corrupted
    seg5 = _changelog_log_path(mock_scene, 5)
    with open(seg5, "w") as f:
        f.write('{"deltas": [{"rev": 5, "delta": ')

    _quarantine_and_resolve_rev(mock_scene)
    assert mock_scene.rev == 5

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": ["new"],
            "metadata": {"version": "1.0"},
        }
        rev = await changelog.append_delta({"action": "post-quarantine"})

    assert rev == 6


@pytest.mark.asyncio
async def test_quarantine_non_utf8_latest_snapshot(mock_scene):
    """A non-UTF-8 latest snapshot is quarantined, not fatal to the pass."""
    from talemate.changelog import quarantine_corrupted_changelog_files

    await save_changelog(mock_scene)
    latest_path = _latest_path(mock_scene)
    with open(latest_path, "wb") as f:
        f.write(b'\xff\xfe{"broken": "}')

    quarantined = quarantine_corrupted_changelog_files(mock_scene)
    assert quarantined == [f"{latest_path}.corrupted"]


@pytest.mark.asyncio
async def test_unreadable_marker_fails_closed(mock_scene):
    """An existing-but-unparseable marker still means 'quarantined'."""
    await save_changelog(mock_scene)

    marker_path = os.path.join(
        mock_scene.changelog_dir, f"{mock_scene.filename}.quarantine.json"
    )
    with open(marker_path, "w") as f:
        f.write("not json")

    with pytest.raises(ChangelogCorruptedError, match="quarantined"):
        await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
async def test_orphan_quarantined_segment_fails_closed(mock_scene):
    """Quarantined segment files without a marker still fail closed.

    Backstop for a failed marker write: the renamed files themselves are
    treated as evidence of quarantine.
    """
    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    _, log_path = _get_latest_changelog_file(mock_scene)
    os.replace(log_path, f"{log_path}.corrupted")

    with pytest.raises(ChangelogCorruptedError, match="quarantined"):
        await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
async def test_quarantine_survives_marker_write_failure(mock_scene):
    """A failed marker write still quarantines, and the chain stays refused."""
    from talemate.changelog import quarantine_corrupted_changelog_files

    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "w") as f:
        f.write('{"deltas": [{"rev": 1, "delta": ')

    # a directory where the marker file belongs makes the write fail
    marker_path = os.path.join(
        mock_scene.changelog_dir, f"{mock_scene.filename}.quarantine.json"
    )
    os.makedirs(marker_path)

    quarantined = quarantine_corrupted_changelog_files(mock_scene)
    assert quarantined == [f"{log_path}.corrupted"]

    with pytest.raises(ChangelogCorruptedError, match="quarantined"):
        await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
async def test_latest_only_quarantine_heals_healthy(mock_scene):
    """After a latest-only quarantine the next append leaves a healthy chain.

    Pins the heal-from-reconstruction fix: a base-baselines catch-up delta
    would double-apply the list append on replay and report diverged forever.
    """
    from talemate.changelog import quarantine_corrupted_changelog_files

    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [],
        "entries": ["a", "b"],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    with open(_latest_path(mock_scene), "w") as f:
        f.write("not json")
    quarantine_corrupted_changelog_files(mock_scene)

    mock_scene.serialize = {
        "characters": [],
        "entries": ["a", "b", "c"],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 2

    reconstructed = await reconstruct_scene_data(mock_scene)
    assert reconstructed["entries"] == ["a", "b", "c"]
    assert await check_chain_divergence(mock_scene) == []


@pytest.mark.asyncio
async def test_reconstruct_raises_on_corrupted_changelog_log(mock_scene):
    """Reconstruction must fail loudly rather than drop a corrupted file's deltas."""
    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "w") as f:
        f.write('{"deltas": [{"rev": 1, "delta": ')

    with pytest.raises(ChangelogCorruptedError):
        await reconstruct_scene_data(mock_scene)
    with pytest.raises(ChangelogCorruptedError):
        list_revisions(mock_scene)
    with pytest.raises(ChangelogCorruptedError):
        await persist_test_mutation(mock_scene, {"action": "retry"})


def test_load_latest_scene_data_corrupted_returns_none(mock_scene):
    """The latest snapshot stays tolerant: unreadable -> None (callers rebuild it)."""
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)
    with open(_latest_path(mock_scene), "w") as f:
        f.write("not json")

    assert _load_latest_scene_data(mock_scene) is None


@pytest.mark.asyncio
async def test_get_overall_latest_revision_non_strict_skips_corrupted(mock_scene):
    """Scene load stays alive on a corrupted changelog file (strict=False)."""
    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "w") as f:
        f.write('{"deltas": [{"rev": 1, "delta": ')

    with pytest.raises(ChangelogCorruptedError):
        _get_overall_latest_revision(mock_scene)
    assert _get_overall_latest_revision(mock_scene, strict=False) == 0


def test_ensure_log_initialized_new_log(mock_scene):
    """Test initializing a new changelog log."""
    result = _ensure_log_initialized(mock_scene, 0)

    expected_structure = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "start_rev": 0,
        "deltas": [],
        "latest_rev": 0,
    }

    assert result == expected_structure

    # Verify file was created
    log_path = _changelog_log_path(mock_scene, 0)
    assert os.path.exists(log_path)


def test_ensure_log_initialized_existing_log(mock_scene):
    """Test loading existing changelog log."""
    log_path = _changelog_log_path(mock_scene, 0)
    existing_data = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "start_rev": 0,
        "deltas": [{"rev": 1}, {"rev": 3}, {"rev": 2}],
        "latest_rev": 2,
    }

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(existing_data, f)

    result = _ensure_log_initialized(mock_scene, 0)

    # Should update latest_rev to max of deltas
    assert result["latest_rev"] == 3
    assert result["deltas"] == existing_data["deltas"]
    assert result["start_rev"] == 0


def test_load_base_scene_data(mock_scene):
    """Test loading base scene data."""
    base_data = {"test": "base_data"}
    base_path = _base_path(mock_scene)

    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    result = _load_base_scene_data(mock_scene)
    assert result == base_data


def test_load_latest_scene_data_exists(mock_scene):
    """Test loading existing latest scene data."""
    latest_data = {"test": "latest_data"}
    latest_path = _latest_path(mock_scene)

    os.makedirs(os.path.dirname(latest_path), exist_ok=True)
    with open(latest_path, "w") as f:
        json.dump(latest_data, f)

    result = _load_latest_scene_data(mock_scene)
    assert result == latest_data


def test_load_latest_scene_data_missing(mock_scene):
    """Test loading non-existent latest scene data returns None."""
    result = _load_latest_scene_data(mock_scene)
    assert result is None


@pytest.mark.asyncio
async def test_ensure_latest_initialized_creates_file(mock_scene):
    """With no segments, the latest snapshot is initialized from the base."""
    base_data = {"test": "base_data"}
    base_path = _base_path(mock_scene)
    latest_path = _latest_path(mock_scene)

    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    await _ensure_latest_initialized(mock_scene)

    assert os.path.exists(latest_path)
    with open(latest_path, "r") as f:
        result = json.load(f)
    assert result == base_data


@pytest.mark.asyncio
async def test_ensure_latest_initialized_heals_from_reconstruction(mock_scene):
    """With segments present, the latest snapshot heals from the chain tip —
    initializing from base would make the next append double-apply list ops."""
    await save_changelog(mock_scene)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": ["one"],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    os.remove(_latest_path(mock_scene))
    await _ensure_latest_initialized(mock_scene)

    with open(_latest_path(mock_scene)) as f:
        healed = json.load(f)
    assert healed["entries"] == ["one"]
    assert healed["characters"] == [{"name": "Alice"}]


def test_compute_delta_no_change():
    """Test computing delta when there are no changes."""
    data1 = {"a": 1, "b": {"c": 2}}
    data2 = {"a": 1, "b": {"c": 2}}

    delta = _compute_delta(data1, data2)
    assert delta == {}


def test_compute_delta_with_changes():
    """Test computing delta when there are changes."""
    data1 = {"a": 1, "b": {"c": 2}}
    data2 = {"a": 1, "b": {"c": 3}, "d": 4}

    delta = _compute_delta(data1, data2)
    assert delta != {}


def test_apply_delta():
    """Test applying a delta to data."""
    import deepdiff

    original = {"a": 1, "b": {"c": 2}}
    modified = {"a": 1, "b": {"c": 3}, "d": 4}

    diff = deepdiff.DeepDiff(original, modified)
    delta_dict = diff._to_delta_dict()

    result = _apply_delta(original, delta_dict)
    assert result == modified


def test_serialize_scene_plain(mock_scene):
    """Test serializing scene to plain dict."""
    mock_scene.serialize = {"test": "data"}

    result = _serialize_scene_plain(mock_scene)
    assert result == {"test": "data"}


@pytest.mark.asyncio
async def test_save_changelog_new_scene(mock_scene):
    """Test saving changelog for a new scene."""
    await save_changelog(mock_scene)

    # Check that base and latest files were created
    base_path = _base_path(mock_scene)
    latest_path = _latest_path(mock_scene)

    assert os.path.exists(base_path)
    assert os.path.exists(latest_path)

    # Both should contain the serialized scene data
    with open(base_path, "r") as f:
        base_data = json.load(f)
    with open(latest_path, "r") as f:
        latest_data = json.load(f)

    assert base_data == mock_scene.serialize
    assert latest_data == mock_scene.serialize


@pytest.mark.asyncio
async def test_save_changelog_existing_scene(mock_scene):
    """Test that save_changelog doesn't overwrite existing base."""
    base_path = _base_path(mock_scene)
    original_data = {"original": "data"}

    # Create existing base file
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(original_data, f)

    await save_changelog(mock_scene)

    # Base file should be unchanged
    with open(base_path, "r") as f:
        result = json.load(f)
    assert result == original_data


@pytest.mark.asyncio
async def test_in_memory_changelog_unchanged_state_writes_no_delta(mock_scene):
    """Test appending delta when scene hasn't changed."""
    # Initialize scene
    await save_changelog(mock_scene)

    # Try to append delta with same data
    result = await persist_test_mutation(mock_scene, {"action": "test"})

    # Should return None (no change)
    assert result is None


@pytest.mark.asyncio
async def test_in_memory_changelog_persists_delta(mock_scene):
    """Test appending delta when scene has changed."""
    # Initialize scene
    await save_changelog(mock_scene)

    # Change the scene data
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }

    result = await persist_test_mutation(mock_scene, {"action": "add_character"})

    # Should return revision 1
    assert result == 1

    # Check that changelog log was updated
    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "r") as f:
        log_data = json.load(f)

    assert log_data["latest_rev"] == 1
    assert len(log_data["deltas"]) == 1
    assert log_data["deltas"][0]["rev"] == 1
    assert log_data["deltas"][0]["meta"] == {"action": "add_character"}


def test_delta_reproduces_state():
    """A real computed delta reproduces its target state; a bogus one doesn't."""
    prev = {"a": 1, "history": ["x"]}
    curr = {"a": 2, "history": ["x", "y"]}

    assert _delta_reproduces_state(prev, curr, _compute_delta(prev, curr))

    bogus = {"values_changed": {"root['a']": {"new_value": 999}}}
    assert not _delta_reproduces_state(prev, curr, bogus)


def test_delta_reproduces_state_ignores_excluded_paths():
    """Excluded subtrees legitimately differ and must not fail verification."""
    prev = {"a": 1, "world_state": {"characters": {"Alice": {"emotion": "calm"}}}}
    curr = {"a": 2, "world_state": {"characters": {"Alice": {"emotion": "angry"}}}}

    delta = _compute_delta(prev, curr)
    assert _delta_reproduces_state(prev, curr, delta)


@pytest.mark.asyncio
async def test_in_memory_changelog_verification_failure_skips_write(
    mock_scene, monkeypatch
):
    """A delta that does not reproduce the scene state must not be written.

    The latest snapshot stays at the previous state so the next append
    retries from the same baseline instead of diverging the chain.
    """
    from structlog.testing import capture_logs

    await save_changelog(mock_scene)

    bogus_delta = {"values_changed": {"root['a']": {"new_value": 999}}}
    monkeypatch.setattr("talemate.changelog._compute_delta", lambda p, c: bogus_delta)

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }

    with capture_logs() as logs:
        result = await persist_test_mutation(mock_scene, {"action": "add_character"})

    assert result is None
    assert any(
        log["event"] == "delta_verification_failed" and log["log_level"] == "error"
        for log in logs
    )

    # nothing written: no revisions, latest snapshot still the base state
    assert list_revisions(mock_scene) == []
    with open(_latest_path(mock_scene)) as f:
        assert json.load(f) == {
            "characters": [],
            "entries": [],
            "metadata": {"version": "1.0"},
        }


@pytest.mark.asyncio
async def test_in_memory_append_delta_verification_failure(mock_scene, monkeypatch):
    """InMemoryChangelog refuses a delta that does not reproduce the state."""
    from structlog.testing import capture_logs

    await save_changelog(mock_scene)

    async with InMemoryChangelog(mock_scene) as changelog:
        last_state_before = changelog.last_state

        bogus_delta = {"values_changed": {"root['a']": {"new_value": 999}}}
        monkeypatch.setattr(
            "talemate.changelog._compute_delta", lambda p, c: bogus_delta
        )

        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        with capture_logs() as logs:
            result = await changelog.append_delta({"action": "add_character"})

        assert result is None
        assert changelog.pending_count == 0
        assert changelog.last_state is last_state_before
        assert any(
            log["event"] == "delta_verification_failed" and log["log_level"] == "error"
            for log in logs
        )


@pytest.mark.asyncio
async def test_reconstruct_scene_data_base_only(mock_scene):
    """Test reconstructing scene data at revision 0."""
    base_data = {"test": "base"}
    base_path = _base_path(mock_scene)

    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    result = await reconstruct_scene_data(mock_scene, to_rev=0)
    assert result == base_data


@pytest.mark.asyncio
async def test_reconstruct_scene_data_with_deltas(mock_scene):
    """Test reconstructing scene data with deltas applied."""
    # Setup base data
    base_data = {"characters": [], "entries": []}
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    # Setup changelog with delta
    import deepdiff

    modified_data = {"characters": [{"name": "Alice"}], "entries": []}
    diff = deepdiff.DeepDiff(base_data, modified_data)
    delta = diff._to_delta_dict()

    log_data = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "deltas": [{"rev": 1, "ts": 1672531200, "delta": delta, "meta": {}}],
        "latest_rev": 1,
    }

    log_path = _changelog_log_path(mock_scene, 0)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    result = await reconstruct_scene_data(mock_scene, to_rev=1)
    assert result == modified_data


@pytest.mark.asyncio
async def test_write_reconstructed_scene(mock_scene):
    """Test writing reconstructed scene to file."""
    # Setup base data
    base_data = {"test": "data"}
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    # Initialize log
    _ensure_log_initialized(mock_scene, 0)

    output_path = await write_reconstructed_scene(mock_scene, 0, "custom_output.json")

    expected_path = os.path.join(mock_scene.save_dir, "custom_output.json")
    assert output_path == expected_path
    assert os.path.exists(output_path)

    with open(output_path, "r") as f:
        result = json.load(f)
    assert result == base_data


@pytest.mark.asyncio
async def test_write_reconstructed_scene_default_filename(mock_scene):
    """Test writing reconstructed scene with default filename."""
    base_data = {"test": "data"}
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    _ensure_log_initialized(mock_scene, 0)

    output_path = await write_reconstructed_scene(mock_scene, 0)

    expected_filename = "test_scene-rev-0.json"
    expected_path = os.path.join(mock_scene.save_dir, expected_filename)
    assert output_path == expected_path


def test_list_revisions_empty(mock_scene):
    """Test listing revisions when there are none."""
    result = list_revisions(mock_scene)
    assert result == []


def test_list_revisions_with_deltas(mock_scene):
    """Test listing revisions with existing deltas."""
    log_data = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "deltas": [{"rev": 1}, {"rev": 3}, {"rev": 2}],
        "latest_rev": 3,
    }

    log_path = _changelog_log_path(mock_scene, 0)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    result = list_revisions(mock_scene)
    assert result == [
        3,
        2,
        1,
    ]  # Should be sorted by revision number descending (newest first)


@pytest.mark.asyncio
async def test_check_chain_divergence_no_changelog(mock_scene):
    """No changelog artifacts → nothing to check (None)."""
    assert await check_chain_divergence(mock_scene) is None


@pytest.mark.asyncio
async def test_check_chain_divergence_healthy(mock_scene):
    """A chain that reconstructs the latest snapshot reports no divergence."""
    await save_changelog(mock_scene)

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": ["one"],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    assert await check_chain_divergence(mock_scene) == []


@pytest.mark.asyncio
async def test_check_chain_divergence_masks_excluded_paths(mock_scene):
    """Excluded subtrees (world_state) diverge by design and must be masked."""
    await save_changelog(mock_scene)

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
        "world_state": {"characters": {"Alice": {"emotion": "calm"}}},
    }
    assert await persist_test_mutation(mock_scene) == 1

    # excluded subtrees are never captured by deltas, so the latest snapshot
    # legitimately carries newer values than reconstruction can produce
    with open(_latest_path(mock_scene)) as f:
        latest = json.load(f)
    latest["world_state"]["characters"]["Alice"]["emotion"] = "angry"
    with open(_latest_path(mock_scene), "w") as f:
        json.dump(latest, f)

    assert await check_chain_divergence(mock_scene) == []


@pytest.mark.asyncio
async def test_check_chain_divergence_detects_divergence(mock_scene):
    """A latest snapshot the chain cannot reproduce is reported as diverged."""
    await save_changelog(mock_scene)

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    # simulate chain/latest drift: a tracked value the deltas never recorded
    with open(_latest_path(mock_scene)) as f:
        latest = json.load(f)
    latest["characters"][0]["name"] = "Bob"
    with open(_latest_path(mock_scene), "w") as f:
        json.dump(latest, f)

    divergent = await check_chain_divergence(mock_scene)
    assert divergent
    assert any("characters" in path for path in divergent)


@pytest.mark.asyncio
async def test_check_chain_divergence_caches_result(mock_scene, monkeypatch):
    """Repeat checks against unchanged files reuse the cached verdict."""
    await save_changelog(mock_scene)

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1
    assert await check_chain_divergence(mock_scene) == []

    async def _boom(*args, **kwargs):
        raise AssertionError("reconstruction ran despite unchanged fingerprint")

    monkeypatch.setattr("talemate.changelog.reconstruct_scene_data", _boom)
    assert await check_chain_divergence(mock_scene) == []


@pytest.mark.asyncio
async def test_rollback_refused_on_diverged_chain(mock_scene):
    """Rollback on a diverged chain raises instead of baking losses in."""
    await save_changelog(mock_scene)

    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }
    assert await persist_test_mutation(mock_scene) == 1

    with open(_latest_path(mock_scene)) as f:
        latest = json.load(f)
    latest["characters"][0]["name"] = "Bob"
    with open(_latest_path(mock_scene), "w") as f:
        json.dump(latest, f)

    with pytest.raises(ChangelogDivergedError, match="Refusing to roll back"):
        await rollback_scene_to_revision(mock_scene, 0)


@pytest.mark.asyncio
async def test_rollback_scene_to_revision_invalid_rev(mock_scene):
    """Test rollback with invalid revision number."""
    # Setup some revisions
    log_data = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "deltas": [{"rev": 1}, {"rev": 2}],
        "latest_rev": 2,
    }

    log_path = _changelog_log_path(mock_scene, 0)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    with pytest.raises(ValueError, match="Invalid revision: 5. Latest available is 2."):
        await rollback_scene_to_revision(mock_scene, 5)

    with pytest.raises(
        ValueError, match="Invalid revision: -1. Latest available is 2."
    ):
        await rollback_scene_to_revision(mock_scene, -1)


@pytest.mark.asyncio
async def test_rollback_scene_to_revision_with_backup(mock_scene):
    """Test rollback creates backup and updates scene file."""
    # Setup base data
    base_data = {"version": "base"}
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)
    # a healthy chain always has a latest snapshot beside the base
    with open(_latest_path(mock_scene), "w") as f:
        json.dump(base_data, f)

    # Setup current scene file
    current_data = {"version": "current"}
    current_path = os.path.join(mock_scene.save_dir, mock_scene.filename)
    with open(current_path, "w") as f:
        json.dump(current_data, f)

    # Setup log with revision 1
    _ensure_log_initialized(mock_scene, 0)

    result_path = await rollback_scene_to_revision(mock_scene, 0, create_backup=True)

    # Check that current file was updated to base data
    assert result_path == current_path
    with open(current_path, "r") as f:
        result = json.load(f)
    assert result == base_data

    # Check that backup was created
    assert os.path.exists(mock_scene.backups_dir)
    backup_files = os.listdir(mock_scene.backups_dir)
    assert len(backup_files) == 1
    assert backup_files[0].startswith("test_scene_pre_rollback_")


@pytest.mark.asyncio
async def test_rollback_scene_to_revision_no_backup(mock_scene):
    """Test rollback without creating backup."""
    # Setup base data
    base_data = {"version": "base"}
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)
    # a healthy chain always has a latest snapshot beside the base
    with open(_latest_path(mock_scene), "w") as f:
        json.dump(base_data, f)

    # Setup current scene file
    current_path = os.path.join(mock_scene.save_dir, mock_scene.filename)
    with open(current_path, "w") as f:
        json.dump({"version": "current"}, f)

    _ensure_log_initialized(mock_scene, 0)

    await rollback_scene_to_revision(mock_scene, 0, create_backup=False)

    # Should not create backup directory
    assert not os.path.exists(mock_scene.backups_dir)


@pytest.mark.asyncio
async def test_changelog_excludes_volatile_fields(mock_scene):
    """Test that paths in EXCLUDE_FROM_DELTAS are not included in deltas."""
    # Initialize scene
    await save_changelog(mock_scene)

    # Change both excluded and included fields
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],  # Should be tracked
        "memory_session_id": "abc123",  # Should be excluded (in EXCLUDE_FROM_DELTAS)
        "saved_memory_session_id": "def456",  # Should be excluded (in EXCLUDE_FROM_DELTAS)
        "entries": [],
    }

    # Append delta (exclusions happen automatically)
    rev = await persist_test_mutation(mock_scene, {"action": "test"})

    # Should create a revision since characters changed
    assert rev == 1

    # Check the delta only contains character changes
    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "r") as f:
        log_data = json.load(f)

    delta_entry = log_data["deltas"][0]
    delta = delta_entry["delta"]

    # Should have character changes but not memory session changes
    # Get all changed paths from different delta types
    all_changed_paths = []
    for delta_type in [
        "values_changed",
        "iterable_item_added",
        "dictionary_item_added",
    ]:
        if delta_type in delta:
            all_changed_paths.extend(delta[delta_type].keys())

    # Should contain character change
    assert any("characters" in path for path in all_changed_paths)

    # Should NOT contain memory session changes (automatically excluded)
    assert not any("memory_session_id" in path for path in all_changed_paths)


@pytest.mark.asyncio
async def test_changelog_excludes_regex_fields(mock_scene):
    """Test that regex patterns in EXCLUDE_FROM_DELTAS_REGEX work correctly."""
    # Initialize scene with world_state containing reinforce array
    mock_scene.serialize = {
        "characters": [],
        "world_state": {
            "reinforce": [
                {"due": "2024-01-01", "id": 1},
                {"due": "2024-01-02", "id": 2},
            ]
        },
    }
    await save_changelog(mock_scene)

    # Change both the 'due' fields and add character (both should be tracked since no regex patterns are defined)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],  # Should be tracked
        "world_state": {
            "reinforce": [
                {
                    "due": "2024-02-01",
                    "id": 1,
                },  # Will be tracked since no regex exclusion is defined
                {
                    "due": "2024-02-02",
                    "id": 2,
                },  # Will be tracked since no regex exclusion is defined
            ]
        },
    }

    rev = await persist_test_mutation(mock_scene, {"action": "test_regex"})

    # Should create revision for both character and due field changes
    assert rev == 1

    # Check that delta contains both character and due field changes since no regex exclusion is active
    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "r") as f:
        log_data = json.load(f)

    delta_entry = log_data["deltas"][0]
    delta = delta_entry["delta"]

    # Get all changed paths
    all_changed_paths = []
    for delta_type in [
        "values_changed",
        "iterable_item_added",
        "dictionary_item_added",
    ]:
        if delta_type in delta:
            all_changed_paths.extend(delta[delta_type].keys())

    # Should contain character change
    assert any("characters" in path for path in all_changed_paths)

    # Since no regex exclusions are defined, 'due' field changes should be included
    # This test verifies the system works correctly when EXCLUDE_FROM_DELTAS_REGEX is empty
    assert len(all_changed_paths) > 0  # Should have changes tracked


@pytest.mark.asyncio
async def test_full_workflow(mock_scene):
    """Test complete workflow: save -> append -> reconstruct -> rollback."""
    # Initial save
    initial_data = {"characters": [], "version": "1.0"}
    mock_scene.serialize = initial_data
    await save_changelog(mock_scene)

    # First change
    mock_scene.serialize = {"characters": [{"name": "Alice"}], "version": "1.0"}
    rev1 = await persist_test_mutation(mock_scene, {"action": "add_alice"})
    assert rev1 == 1

    # Second change
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}, {"name": "Bob"}],
        "version": "1.0",
    }
    rev2 = await persist_test_mutation(mock_scene, {"action": "add_bob"})
    assert rev2 == 2

    # List revisions
    revisions = list_revisions(mock_scene)
    assert revisions == [2, 1]  # Sorted descending (newest first)

    # Reconstruct at different points
    rev0_data = await reconstruct_scene_data(mock_scene, to_rev=0)
    assert rev0_data == initial_data

    rev1_data = await reconstruct_scene_data(mock_scene, to_rev=1)
    assert len(rev1_data["characters"]) == 1
    assert rev1_data["characters"][0]["name"] == "Alice"

    rev2_data = await reconstruct_scene_data(mock_scene, to_rev=2)
    assert len(rev2_data["characters"]) == 2

    # Write reconstructed scene
    output_path = await write_reconstructed_scene(mock_scene, 1)
    assert os.path.exists(output_path)

    # Create current scene file for rollback test
    current_path = os.path.join(mock_scene.save_dir, mock_scene.filename)
    with open(current_path, "w") as f:
        json.dump({"current": "state"}, f)

    # Rollback to revision 1
    await rollback_scene_to_revision(mock_scene, 1)

    with open(current_path, "r") as f:
        rolled_back = json.load(f)
    assert len(rolled_back["characters"]) == 1
    assert rolled_back["characters"][0]["name"] == "Alice"


def test_get_changelog_files_empty(mock_scene):
    """Test getting changelog files when none exist."""
    result = _get_changelog_files(mock_scene)
    assert result == []


def test_get_changelog_files_multiple(mock_scene):
    """Test getting multiple changelog files."""
    # Create multiple changelog files
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)

    files = [
        (0, _changelog_log_path(mock_scene, 0)),
        (100, _changelog_log_path(mock_scene, 100)),
        (50, _changelog_log_path(mock_scene, 50)),
    ]

    for start_rev, path in files:
        with open(path, "w") as f:
            json.dump({"start_rev": start_rev, "deltas": []}, f)

    result = _get_changelog_files(mock_scene)

    # Should be sorted by start_rev
    expected = [(0, files[0][1]), (50, files[2][1]), (100, files[1][1])]
    assert result == expected


def test_get_latest_changelog_file_empty(mock_scene):
    """Test getting latest changelog file when none exist."""
    result = _get_latest_changelog_file(mock_scene)
    expected_path = _changelog_log_path(mock_scene, 0)
    assert result == (0, expected_path)


def test_get_latest_changelog_file_multiple(mock_scene):
    """Test getting latest changelog file from multiple files."""
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)

    # Create multiple files
    for start_rev in [0, 50, 100]:
        path = _changelog_log_path(mock_scene, start_rev)
        with open(path, "w") as f:
            json.dump({"start_rev": start_rev, "deltas": []}, f)

    result = _get_latest_changelog_file(mock_scene)
    expected_path = _changelog_log_path(mock_scene, 100)
    assert result == (100, expected_path)


def test_get_overall_latest_revision_empty(mock_scene):
    """Test getting overall latest revision when no files exist."""
    result = _get_overall_latest_revision(mock_scene)
    assert result == 0


def test_get_overall_latest_revision_multiple_files(mock_scene):
    """Test getting overall latest revision across multiple files."""
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)

    # Create files with different latest revisions
    files_data = [
        (0, {"start_rev": 0, "latest_rev": 10, "deltas": []}),
        (50, {"start_rev": 50, "latest_rev": 75, "deltas": []}),
        (100, {"start_rev": 100, "latest_rev": 150, "deltas": []}),
    ]

    for start_rev, data in files_data:
        path = _changelog_log_path(mock_scene, start_rev)
        with open(path, "w") as f:
            json.dump(data, f)

    result = _get_overall_latest_revision(mock_scene)
    assert result == 150


def test_get_file_size_existing(temp_dir):
    """Test getting size of existing file."""
    test_file = os.path.join(temp_dir, "test.txt")
    content = "Hello, World!"

    with open(test_file, "w") as f:
        f.write(content)

    result = _get_file_size(test_file)
    assert result == len(content)


def test_get_file_size_missing(temp_dir):
    """Test getting size of non-existent file."""
    test_file = os.path.join(temp_dir, "missing.txt")
    result = _get_file_size(test_file)
    assert result == 0


@pytest.mark.asyncio
async def test_in_memory_commit_creates_new_file_when_size_exceeded(mock_scene):
    """Test that a new changelog file is created when size limit is exceeded."""
    # Initialize scene
    await save_changelog(mock_scene)

    # Mock the file size to exceed limit
    original_get_file_size = _get_file_size

    def mock_get_file_size(path):
        if "changelog.0.json" in path:
            return MAX_CHANGELOG_FILE_SIZE + 1000  # Exceeds limit
        return original_get_file_size(path)

    # Patch the function temporarily
    import talemate.changelog

    talemate.changelog._get_file_size = mock_get_file_size

    try:
        # Change the scene data to trigger delta creation
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        # This should create a new file because current file "exceeds" size limit
        rev = await persist_test_mutation(mock_scene, {"action": "test"})
        assert rev == 1

        # Should have created a new file starting at revision 1
        files = _get_changelog_files(mock_scene)
        assert len(files) >= 1

        # The new revision should be in a file starting at rev 1
        rev1_file_exists = any(start_rev == 1 for start_rev, _ in files)
        assert rev1_file_exists

    finally:
        # Restore original function
        talemate.changelog._get_file_size = original_get_file_size


# InMemoryChangelog tests


@pytest.mark.asyncio
async def test_in_memory_changelog_basic_usage(mock_scene):
    """Test basic usage of InMemoryChangelog."""
    # Initialize scene
    await save_changelog(mock_scene)

    async with InMemoryChangelog(mock_scene) as changelog:
        # Initially no pending changes
        assert not changelog.has_pending_changes
        assert changelog.pending_count == 0

        # Make a change to the scene
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        # Append delta
        real_rev = await changelog.append_delta({"action": "add_character"})

        # Should have pending changes now
        assert changelog.has_pending_changes
        assert changelog.pending_count == 1
        assert real_rev == 1  # First real revision (base scene is rev 0)

        # Make another change
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}, {"name": "Bob"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        real_rev2 = await changelog.append_delta({"action": "add_bob"})
        assert changelog.pending_count == 2
        assert real_rev2 == 2  # Second real revision

        # Manually commit the changes
        await changelog.commit()

    # After context exit, changes should be committed
    assert not changelog.has_pending_changes
    assert changelog.pending_count == 0

    # Check that real revisions were created
    revisions = list_revisions(mock_scene)
    assert len(revisions) == 2
    assert revisions == [2, 1]  # Should be in descending order


@pytest.mark.asyncio
async def test_in_memory_changelog_no_changes(mock_scene):
    """Test InMemoryChangelog with no scene changes."""
    await save_changelog(mock_scene)

    async with InMemoryChangelog(mock_scene) as changelog:
        # Try to append delta with no changes
        virtual_rev = await changelog.append_delta({"action": "no_change"})

        # Should return None for no changes
        assert virtual_rev is None
        assert not changelog.has_pending_changes
        assert changelog.pending_count == 0

    # No revisions should be created
    revisions = list_revisions(mock_scene)
    assert revisions == []


@pytest.mark.asyncio
async def test_in_memory_changelog_manual_commit(mock_scene):
    """Test manually committing changes before context exit."""
    await save_changelog(mock_scene)

    async with InMemoryChangelog(mock_scene) as changelog:
        # Make a change
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        await changelog.append_delta({"action": "add_character"})
        assert changelog.has_pending_changes

        # Manually commit
        committed_revs = await changelog.commit()

        # Should have committed the change
        assert not changelog.has_pending_changes
        assert len(committed_revs) == 1
        assert committed_revs[0] == 1

        # Should be able to append after commit (changelog can be reused)
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}, {"name": "Bob"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        rev = await changelog.append_delta({"action": "add_bob"})
        assert (
            rev == 2
        )  # Real revision for new pending delta (after first committed rev)
        assert changelog.has_pending_changes


@pytest.mark.asyncio
async def test_in_memory_changelog_empty_commit(mock_scene):
    """Test committing when there are no pending deltas."""
    await save_changelog(mock_scene)

    async with InMemoryChangelog(mock_scene) as changelog:
        # Commit with no pending deltas
        committed_revs = await changelog.commit()

        # Should return empty list
        assert committed_revs == []
        assert not changelog.has_pending_changes


@pytest.mark.asyncio
async def test_in_memory_changelog_multiple_commits(mock_scene):
    """Test that multiple commits work correctly (changelog can be reused)."""
    await save_changelog(mock_scene)

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        await changelog.append_delta({"action": "add_character"})
        committed_revs = await changelog.commit()
        assert len(committed_revs) == 1
        assert not changelog.has_pending_changes

        # Second commit with no changes should return empty list
        committed_revs2 = await changelog.commit()
        assert len(committed_revs2) == 0


@pytest.mark.asyncio
async def test_in_memory_changelog_preserves_metadata(mock_scene):
    """Test that metadata is preserved during commit."""
    await save_changelog(mock_scene)

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }

        test_meta = {
            "action": "add_character",
            "user": "test",
            "timestamp": "2024-01-01",
        }
        await changelog.append_delta(test_meta)

        # Manually commit the changes
        await changelog.commit()

    # Check that metadata was preserved in the changelog
    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "r") as f:
        log_data = json.load(f)

    assert len(log_data["deltas"]) == 1
    delta_entry = log_data["deltas"][0]
    assert delta_entry["meta"] == test_meta


@pytest.mark.asyncio
async def test_in_memory_changelog_updates_latest_snapshot(mock_scene):
    """Test that the latest snapshot file is updated after commit."""
    await save_changelog(mock_scene)

    final_scene_data = {
        "characters": [{"name": "Alice"}, {"name": "Bob"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }

    async with InMemoryChangelog(mock_scene) as changelog:
        # First change
        mock_scene.serialize = {
            "characters": [{"name": "Alice"}],
            "entries": [],
            "metadata": {"version": "1.0"},
        }
        await changelog.append_delta({"action": "add_alice"})

        # Second change
        mock_scene.serialize = final_scene_data
        await changelog.append_delta({"action": "add_bob"})

        # Manually commit the changes
        await changelog.commit()

    # Check that latest snapshot was updated
    latest_path = _latest_path(mock_scene)
    assert os.path.exists(latest_path)

    with open(latest_path, "r") as f:
        latest_data = json.load(f)

    # Should match the final scene state
    assert latest_data == final_scene_data


@pytest.mark.asyncio
async def test_in_memory_changelog_integration_with_existing_revisions(mock_scene):
    """Test that InMemoryChangelog works correctly with existing revisions."""
    # Create some initial revisions using the traditional method
    await save_changelog(mock_scene)

    mock_scene.serialize = {"characters": [{"name": "Existing"}], "entries": []}
    await persist_test_mutation(mock_scene, {"action": "existing_change"})

    # Verify we have revision 1 and update mock_scene.rev to match
    assert _get_overall_latest_revision(mock_scene) == 1
    mock_scene.rev = 1  # In real usage, scene.rev would be updated

    # Now use InMemoryChangelog to add more changes
    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene.serialize = {
            "characters": [{"name": "Existing"}, {"name": "New"}],
            "entries": [],
        }
        await changelog.append_delta({"action": "add_new_character"})

        mock_scene.serialize = {
            "characters": [{"name": "Existing"}, {"name": "New"}, {"name": "Another"}],
            "entries": [],
        }
        await changelog.append_delta({"action": "add_another_character"})

        # Manually commit the changes
        await changelog.commit()

    # Should now have revisions 1, 2, 3
    revisions = list_revisions(mock_scene)
    assert revisions == [3, 2, 1]
    assert _get_overall_latest_revision(mock_scene) == 3


@pytest.mark.asyncio
async def test_in_memory_changelog_baselines_on_committed_snapshot(mock_scene):
    """Mutations made between a commit and entering a new InMemoryChangelog
    context must still land in the delta chain — the baseline is the last
    committed snapshot, not the live scene state. Otherwise stored delta
    values diverge from reconstructions and item removals get silently
    skipped when applied (deepdiff verifies removed values)."""
    await save_changelog(mock_scene)

    items = [{"id": idx} for idx in range(1, 4)]
    mock_scene.serialize = {"history": list(items)}
    await persist_test_mutation(mock_scene)
    mock_scene.rev = 1

    # mutate the scene BEFORE the in-memory changelog is entered
    # (mirrors load-time mutations like message meta stamps)
    items[1] = {"id": 2, "meta": {"agent": "narrator"}}
    mock_scene.serialize = {"history": list(items)}

    async with InMemoryChangelog(mock_scene) as changelog:
        # remove the last two items (mirrors a rollback truncating history)
        mock_scene.serialize = {"history": [items[0]]}
        await changelog.append_delta()
        await changelog.commit()

    reconstructed = await reconstruct_scene_data(mock_scene, to_rev=2)
    # _repair_history backfills message fields on bare entries; ids are
    # what matters — both removals must have actually applied
    assert [entry["id"] for entry in reconstructed["history"]] == [1]


@pytest.mark.asyncio
async def test_reconstruct_scene_data_disconnects_shared_context(mock_scene):
    """Test that shared_context is automatically disconnected during reconstruction."""
    # Setup base scene with shared_context
    base_data = {
        "characters": [],
        "entries": [],
        "shared_context": "world.json",  # Scene has shared context
    }
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    # Test reconstruction at revision 0 (base only)
    result = await reconstruct_scene_data(mock_scene, to_rev=0)

    # Verify shared_context was disconnected
    assert result["shared_context"] == ""
    assert result["characters"] == []
    assert result["entries"] == []


@pytest.mark.asyncio
async def test_reconstruct_scene_data_with_deltas_disconnects_shared_context(
    mock_scene,
):
    """Test that shared_context is disconnected even when applying deltas."""
    # Setup base scene with shared_context
    base_data = {"characters": [], "entries": [], "shared_context": "world.json"}
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    # Setup changelog with delta that adds a character (but keeps shared_context)
    import deepdiff

    modified_data = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "shared_context": "world.json",  # Still has shared context in the delta
    }
    diff = deepdiff.DeepDiff(base_data, modified_data)
    delta = diff._to_delta_dict()

    log_data = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "start_rev": 0,
        "deltas": [
            {
                "rev": 1,
                "ts": 1672531200,
                "delta": delta,
                "meta": {"action": "add_character"},
            }
        ],
        "latest_rev": 1,
    }

    log_path = _changelog_log_path(mock_scene, 0)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    # Reconstruct at revision 1
    result = await reconstruct_scene_data(mock_scene, to_rev=1)

    # Verify character was added but shared_context was disconnected
    assert result["characters"] == [{"name": "Alice"}]
    assert result["shared_context"] == ""  # Should be disconnected


@pytest.mark.asyncio
async def test_reconstruct_scene_data_no_shared_context_unchanged(mock_scene):
    """Test that scenes without shared_context are unchanged during reconstruction."""
    # Setup base scene without shared_context
    base_data = {
        "characters": [],
        "entries": [],
        # No shared_context field
    }
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    # Test reconstruction
    result = await reconstruct_scene_data(mock_scene, to_rev=0)

    # Should be unchanged since there was no shared_context
    assert result == base_data
    assert "shared_context" not in result


@pytest.mark.asyncio
async def test_reconstruct_cleanup_removes_shared_context():
    """Test that reconstruct_cleanup properly removes shared_context."""
    # Data with shared_context
    data_with_shared = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "shared_context": "world.json",
    }

    result = await reconstruct_cleanup(data_with_shared)

    # Should remove shared_context but keep other data
    assert result["characters"] == [{"name": "Alice"}]
    assert result["entries"] == []
    assert result["shared_context"] == ""


@pytest.mark.asyncio
async def test_reconstruct_cleanup_preserves_data_without_shared_context():
    """Test that reconstruct_cleanup preserves data when no shared_context exists."""
    # Data without shared_context
    data_without_shared = {
        "characters": [{"name": "Bob"}],
        "entries": [{"id": 1, "content": "test"}],
        "metadata": {"version": "1.0"},
    }

    result = await reconstruct_cleanup(data_without_shared)

    # Should be unchanged
    assert result == data_without_shared


@pytest.mark.asyncio
async def test_reconstruct_cleanup_repairs_bare_history_entries():
    """Reconstruct repair pass backfills missing fields on bare-fragment history entries."""
    data = {
        "history": [
            {"message": "ok", "typ": "narrator", "source": "ai", "flags": 0},
            {
                "asset_id": "abc123",
                "asset_type": "scene_illustration",
            },
            {"message": "ok2", "typ": "character", "source": "ai", "flags": 0},
        ]
    }

    result = await reconstruct_cleanup(data)

    history = result["history"]
    assert len(history) == 3

    repaired = history[1]
    assert repaired["message"] == ""
    assert repaired["typ"] == "narrator"
    assert repaired["source"] == "ai"
    assert repaired["flags"] == 0
    assert repaired["asset_id"] == "abc123"
    assert repaired["asset_type"] == "scene_illustration"


@pytest.mark.asyncio
async def test_reconstruct_cleanup_repairs_forced_dict_history():
    """An int-keyed dict where history should be a list (Delta force=True
    artifact) is converted back to a list ordered by index — issue #81."""
    data = {
        "history": {
            2: {"message": "third", "typ": "narrator", "source": "ai", "flags": 0},
            1: {"message": "second", "typ": "narrator", "source": "ai", "flags": 0},
        }
    }

    result = await reconstruct_cleanup(data)

    history = result["history"]
    assert isinstance(history, list)
    assert [entry["message"] for entry in history] == ["second", "third"]
    # the preview handler slices this — must not raise
    assert history[-20:] == history


@pytest.mark.asyncio
async def test_reconstruct_cleanup_repairs_forced_dict_history_string_keys():
    """Index keys arrive as strings when the corrupted data round-tripped
    through JSON — those convert too, and bare entries still get repaired."""
    data = {"history": {"1": {"asset_id": "abc123"}, "0": {"m": 0}}}

    result = await reconstruct_cleanup(data)

    history = result["history"]
    assert isinstance(history, list)
    assert len(history) == 2
    assert history[1]["asset_id"] == "abc123"
    # _repair_history runs after the coercion and backfills required fields
    for entry in history:
        assert entry["typ"] == "narrator"
        assert "message" in entry


@pytest.mark.asyncio
async def test_reconstruct_cleanup_repairs_all_forced_list_fields():
    """Every list field is normalized, including nested layered_history layers."""
    data = {
        "history": {0: {"message": "a", "typ": "narrator"}},
        "archived_history": {0: {"text": "summary"}},
        "layered_history": {0: [{"text": "layer0"}], 1: {0: {"text": "layer1"}}},
        "active_characters": {0: "Alice", 1: "Bob"},
        "game_state_watch_paths": {0: "game.state.foo"},
    }

    result = await reconstruct_cleanup(data)

    assert isinstance(result["history"], list)
    assert result["archived_history"] == [{"text": "summary"}]
    assert result["layered_history"] == [[{"text": "layer0"}], [{"text": "layer1"}]]
    assert result["active_characters"] == ["Alice", "Bob"]
    assert result["game_state_watch_paths"] == ["game.state.foo"]


@pytest.mark.asyncio
async def test_reconstruct_cleanup_leaves_legit_dicts_and_lists_alone():
    """Dicts with non-index keys and healthy lists pass through untouched."""
    data = {
        "history": [{"message": "a", "typ": "narrator", "source": "ai", "flags": 0}],
        # malformed digit-ish key — must not be treated as an index (and must
        # not raise from int())
        "archived_history": {"--5": {"text": "x"}},
        "character_data": {"Alice": {"name": "Alice"}},
        "agent_state": {"0_custom": True, "narrator": {}},
    }

    result = await reconstruct_cleanup(data)

    assert result["history"] == data["history"]
    assert result["archived_history"] == {"--5": {"text": "x"}}
    assert result["character_data"] == {"Alice": {"name": "Alice"}}
    assert result["agent_state"] == {"0_custom": True, "narrator": {}}


@pytest.mark.asyncio
async def test_reconstruct_refuses_missing_history_parent(mock_scene):
    """Issue #81 family, new policy (#295): an iterable_item_added delta
    targeting a missing history parent means the chain has diverged — strict
    replay refuses loudly instead of force-fabricating an int-keyed dict and
    repairing it into a loadable-but-wrong list."""
    base_data = {"characters": [], "entries": []}  # no history at all
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    log_data = {
        "version": 1,
        "base": f"{mock_scene.filename}.base.json",
        "start_rev": 0,
        "deltas": [
            {
                "rev": 1,
                "ts": 1672531200,
                "delta": {
                    "iterable_item_added": {
                        "root['history'][1]": {
                            "message": "hello",
                            "typ": "narrator",
                            "source": "ai",
                            "flags": 0,
                        }
                    }
                },
                "meta": {},
            }
        ],
        "latest_rev": 1,
    }
    log_path = _changelog_log_path(mock_scene, 0)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    with pytest.raises(ChangelogDivergedError, match="rev 1"):
        await reconstruct_scene_data(mock_scene, to_rev=1)


@pytest.mark.asyncio
async def test_reconstruct_refuses_orphan_dict_add(mock_scene):
    """Issue #81 family, new policy (#295): a dict-add on a non-existent
    history index means the chain has diverged — strict replay refuses
    loudly instead of force-inflating the list and backfilling the gap."""
    base_data = {
        "history": [
            {"message": "hello", "typ": "narrator", "source": "ai", "flags": 0},
        ],
    }
    base_path = _base_path(mock_scene)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    log_data = {
        "version": 1,
        "base": f"{mock_scene.filename}.base.json",
        "start_rev": 0,
        "deltas": [
            {
                "rev": 1,
                "ts": 1672531200,
                "delta": {
                    "dictionary_item_added": {
                        "root['history'][1]['asset_id']": "abc123",
                        "root['history'][1]['asset_type']": "scene_illustration",
                    }
                },
                "meta": {},
            }
        ],
        "latest_rev": 1,
    }
    log_path = _changelog_log_path(mock_scene, 0)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    with pytest.raises(ChangelogDivergedError, match="rev 1"):
        await reconstruct_scene_data(mock_scene, to_rev=1)


@pytest.mark.asyncio
async def test_warn_on_orphan_delta_ops(monkeypatch):
    """Warner fires for ops whose parent is absent, stays silent when the parent is present."""
    from talemate import changelog as changelog_mod
    from talemate.changelog import _warn_on_orphan_delta_ops

    delta = {
        "dictionary_item_added": {
            "root['history'][0]['asset_id']": "abc",
            "root['history'][0]['asset_type']": "scene_illustration",
        }
    }

    captured: list[tuple[str, dict]] = []

    def fake_warning(event, **kwargs):
        captured.append((event, kwargs))

    monkeypatch.setattr(changelog_mod.log, "warning", fake_warning)

    _warn_on_orphan_delta_ops({"history": []}, delta)

    orphan_warnings = [
        kw for ev, kw in captured if ev == "delta_op_targets_missing_parent"
    ]
    assert len(orphan_warnings) == 2
    paths = {kw["path"] for kw in orphan_warnings}
    assert paths == {
        "root['history'][0]['asset_id']",
        "root['history'][0]['asset_type']",
    }

    captured.clear()
    _warn_on_orphan_delta_ops({"history": [{"message": "a", "typ": "narrator"}]}, delta)
    assert not [ev for ev, _ in captured if ev == "delta_op_targets_missing_parent"]


@pytest.mark.asyncio
async def test_in_memory_changelog_with_save_changelog_bug(mock_scene):
    """
    Regression test for the bug where save_changelog() is called while
    InMemoryChangelog has pending changes, causing duplication.

    This simulates:
    1. Scene starts with InMemoryChangelog context
    2. Messages are added (pending in memory)
    3. save_changelog() is called — it must base the snapshot on the
       changelog's initial_state, not the live scene with pending changes
    4. InMemoryChangelog.commit() is called (writes the changes as deltas)
    5. Reconstruction must not duplicate messages
    """
    # Start with a scene that has history
    initial_history = [
        {"id": 1, "message": "First message", "rev": 1},
        {"id": 2, "message": "Second message", "rev": 2},
    ]
    mock_scene.serialize = {"history": initial_history, "characters": []}
    mock_scene.rev = 2

    # Open InMemoryChangelog context (captures current state)
    async with InMemoryChangelog(mock_scene) as changelog:
        # Set _changelog on mock_scene to simulate real scene behavior
        mock_scene._changelog = changelog

        # Add more messages
        mock_scene.serialize = {
            "history": initial_history
            + [
                {"id": 3, "message": "Third message", "rev": 3},
                {"id": 4, "message": "Fourth message", "rev": 4},
            ],
            "characters": [],
        }

        # Append deltas for the new messages
        await changelog.append_delta({"action": "add_message_3"})
        await changelog.append_delta({"action": "add_message_4"})

        # Now save_changelog() is called (e.g., during a fork operation)
        await save_changelog(mock_scene)

        # Commit the pending deltas
        await changelog.commit()

    # Now reconstruct to revision 4
    reconstructed = await reconstruct_scene_data(mock_scene, to_rev=4)

    history = reconstructed.get("history", [])

    assert len(history) == 4, (
        f"Expected 4 messages, got {len(history)}: {[m['message'] for m in history]}"
    )

    # Verify no duplicates by checking message IDs
    message_ids = [msg["id"] for msg in history]
    assert len(message_ids) == len(set(message_ids)), (
        f"Duplicate message IDs found: {message_ids}"
    )


@pytest.mark.asyncio
async def test_delete_changelog_files_with_wrong_scene_reference(temp_dir):
    """
    Test that reproduces the bug where delete_changelog_files is called with
    the wrong scene reference (or self.scene from the wrong context).

    This simulates the bug in server/config.py:handle_delete_scene where
    delete_changelog_files(self.scene) is called instead of constructing
    a proper scene reference from the deleted file path.
    """
    # Real ``Scene`` (subclass) for the scene whose changelog we'll create.
    scene1 = make_changelog_scene(
        os.path.join(temp_dir, "project1"),
        filename="scene_to_delete.json",
        initial_serialize={"characters": [], "data": "scene1"},
    )

    # Initialize changelog for scene1
    await save_changelog(scene1)

    # Verify changelog files were created
    assert os.path.exists(_base_path(scene1))
    assert os.path.exists(_latest_path(scene1))

    # Now simulate the bug: calling delete_changelog_files with a different scene
    # (or None, which would be self.scene when no scene is loaded). Real Scene
    # again — wrong filename and wrong save_dir.
    wrong_scene = make_changelog_scene(
        os.path.join(temp_dir, "project2"),
        filename="different_scene.json",
    )

    # Try to delete with wrong scene reference
    result = delete_changelog_files(wrong_scene)

    # BUG: This will try to delete files for "different_scene.json" in "project2"
    # but scene1's files are in "project1" with filename "scene_to_delete.json"
    # So scene1's changelog files will NOT be deleted

    # Verify scene1's changelog files still exist (they were not deleted)
    assert os.path.exists(_base_path(scene1)), "Base file should still exist due to bug"
    assert os.path.exists(_latest_path(scene1)), (
        "Latest file should still exist due to bug"
    )

    # Now show the correct way: construct a real ``_SceneRef`` (the type
    # production code uses for this exact purpose — a lightweight scene
    # reference for changelog operations). This is the same type
    # ``ensure_changelogs_for_all_scenes`` builds internally.
    correct_scene_ref = _SceneRef(
        filename=scene1.filename,
        save_dir=scene1.save_dir,
        data={},
    )

    # Delete with correct reference
    result = delete_changelog_files(correct_scene_ref)

    # Now the files should be deleted
    assert not os.path.exists(_base_path(scene1)), "Base file should be deleted"
    assert not os.path.exists(_latest_path(scene1)), "Latest file should be deleted"
    assert len(result.get("deleted", [])) >= 2, (
        "Should have deleted at least base and latest"
    )


# --- Strict replay (issue #295) -------------------------------------------


def _write_segment(scene, start_rev, deltas, latest_rev):
    path = _changelog_log_path(scene, start_rev)
    with open(path, "w") as f:
        json.dump(
            {
                "version": 1,
                "base": f"{scene.filename}.base.json",
                "start_rev": start_rev,
                "deltas": deltas,
                "latest_rev": latest_rev,
            },
            f,
        )
    return path


def test_apply_delta_strict_iterable_item_added_past_end_raises():
    """An addition past the end of the baseline list was silently dropped."""
    data = {"history": [{"id": 0}]}
    delta = {"iterable_item_added": {"root['history'][2]": {"id": 1}}}
    with pytest.raises(ChangelogDivergedError, match="out of range"):
        _apply_delta(data, delta)


def test_apply_delta_strict_iterable_item_removed_value_mismatch_raises():
    """deepdiff skips value-mismatched removals even with raise_errors=True —
    the pre-check is what makes them loud."""
    data = {"history": [{"id": 0}]}
    delta = {"iterable_item_removed": {"root['history'][0]": {"id": 99}}}
    with pytest.raises(ChangelogDivergedError, match="does not match"):
        _apply_delta(data, delta)


def test_apply_delta_strict_iterable_item_removed_out_of_range_raises():
    data = {"history": [{"id": 0}]}
    delta = {"iterable_item_removed": {"root['history'][3]": {"id": 0}}}
    with pytest.raises(ChangelogDivergedError, match="no such list item"):
        _apply_delta(data, delta)


def test_apply_delta_strict_values_changed_missing_parent_raises():
    """The #291 stub fabrication: values_changed under a missing parent."""
    data = {"character": None}
    delta = {
        "values_changed": {
            "root['character']['details']['x']": {"new_value": 1, "old_value": 2}
        }
    }
    with pytest.raises(ChangelogDivergedError):
        _apply_delta(data, delta)


def test_apply_delta_healthy_ops_apply():
    data = {"history": [{"id": 0}], "x": 1}
    delta = {
        "iterable_item_added": {"root['history'][1]": {"id": 1}},
        "values_changed": {"root['x']": {"new_value": 2, "old_value": 1}},
        "dictionary_item_added": {"root['y']": 3},
    }
    result = _apply_delta(data, delta)
    assert result == {"history": [{"id": 0}, {"id": 1}], "x": 2, "y": 3}


def test_delta_reproduces_state_refuses_force_only_delta():
    """A delta that only applies under force mode must not be written."""
    prev = {"x": 1}
    curr = {"x": 1, "a": {"b": 2}}
    delta = {"values_changed": {"root['a']['b']": {"new_value": 2}}}
    assert not _delta_reproduces_state(prev, curr, delta)


def test_compute_delta_rewrites_iterable_opcodes_as_full_list():
    """deepdiff represents a reorder as opcode namedtuples, which do not
    survive the JSON round-trip the chain goes through on disk."""
    prev = {"entries": ["a", "b", "c", "d", "e"]}
    curr = {"entries": ["c", "d", "e", "a", "b"]}

    delta = _compute_delta(prev, curr)

    assert "_iterable_opcodes" not in delta
    assert delta["values_changed"]["root['entries']"] == {
        "new_value": ["c", "d", "e", "a", "b"],
        "old_value": ["a", "b", "c", "d", "e"],
    }
    assert delta[REORDERED_LISTS_KEY] == ["root['entries']"]
    assert _delta_reproduces_state(prev, curr, delta)


def test_apply_delta_reordered_list_value_mismatch_raises():
    """deepdiff applies values_changed blind, so a full-list op would restore
    the recorded post-state over a diverged list — the marker is what makes
    the mismatch loud."""
    data = {"entries": ["a", "b", "c"]}
    delta = {
        "values_changed": {
            "root['entries']": {
                "new_value": ["d", "c", "b", "a"],
                "old_value": ["a", "b", "c", "d"],
            }
        },
        REORDERED_LISTS_KEY: ["root['entries']"],
    }
    with pytest.raises(ChangelogDivergedError, match="does not match"):
        _apply_delta(data, delta)


def test_apply_delta_reordered_list_matching_value_applies():
    data = {"entries": ["a", "b", "c"], "x": 1}
    delta = {
        "values_changed": {
            "root['entries']": {
                "new_value": ["c", "b", "a"],
                "old_value": ["a", "b", "c"],
            }
        },
        REORDERED_LISTS_KEY: ["root['entries']"],
    }
    assert _apply_delta(data, delta) == {"entries": ["c", "b", "a"], "x": 1}


def test_apply_delta_unmarked_values_changed_is_not_verified():
    """Full-subtree world-state ops carry an old_value that predates the base
    snapshot — validating every values_changed would break their unmask path."""
    data = {"world_state": {"pins": {"a": 1}}}
    delta = {
        "values_changed": {
            "root['world_state']['pins']": {"new_value": {"b": 2}, "old_value": None}
        }
    }
    assert _apply_delta(data, delta) == {"world_state": {"pins": {"b": 2}}}


def test_delta_reproduces_state_refuses_unserializable_delta():
    """Applying in memory is not enough — reconstruction replays the delta as
    it was written to disk."""
    prev = {"x": None}
    curr = {"x": {1, 2}}
    delta = {"values_changed": {"root['x']": {"new_value": {1, 2}, "old_value": None}}}
    assert not _delta_reproduces_state(prev, curr, delta)


@pytest.mark.asyncio
async def test_list_reorder_delta_replays_from_disk(mock_scene):
    mock_scene.serialize = {"entries": ["a", "b", "c", "d", "e"], "metadata": {}}
    await save_changelog(mock_scene)

    reordered = {"entries": ["c", "d", "e", "a", "b"], "metadata": {}}
    mock_scene.serialize = reordered

    assert await persist_test_mutation(mock_scene) == 1
    assert await reconstruct_scene_data(mock_scene, to_rev=1) == reordered
    assert await check_chain_divergence(mock_scene) == []


def test_parse_delta_path_double_quoted_key():
    """deepdiff quotes with double quotes when the key holds an apostrophe."""
    assert _parse_delta_path("root[\"O'Brien\"]['tags'][1]") == ["O'Brien", "tags", 1]
    assert _parse_delta_path("root['a'][3]['b']") == ["a", 3, "b"]
    assert _parse_delta_path("no root prefix") == []


@pytest.mark.asyncio
async def test_apostrophe_key_delta_replays_from_disk(mock_scene):
    """A key like ``O'Brien`` over a list value must not read as divergence."""
    mock_scene.serialize = {"characters": {"O'Brien": {"tags": ["stern"]}}}
    await save_changelog(mock_scene)

    appended = {"characters": {"O'Brien": {"tags": ["stern", "tired"]}}}
    mock_scene.serialize = appended
    assert await persist_test_mutation(mock_scene) == 1

    changed = {"characters": {"O'Brien": {"tags": ["stern", "weary"]}}}
    mock_scene.serialize = changed
    assert await persist_test_mutation(mock_scene) == 2

    assert await reconstruct_scene_data(mock_scene, to_rev=1) == appended
    assert await reconstruct_scene_data(mock_scene, to_rev=2) == changed
    assert await check_chain_divergence(mock_scene) == []


@pytest.mark.asyncio
async def test_reconstruct_strict_failure_names_revision(mock_scene):
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)
    with open(_base_path(mock_scene), "w") as f:
        json.dump({"history": [], "x": 0}, f)
    _write_segment(
        mock_scene,
        0,
        [
            {
                "rev": 1,
                "ts": 1,
                "delta": {"values_changed": {"root['x']": {"new_value": 1}}},
                "meta": {},
            },
            {
                "rev": 2,
                "ts": 2,
                "delta": {"iterable_item_added": {"root['history'][7]": {"id": 1}}},
                "meta": {},
            },
        ],
        2,
    )

    with pytest.raises(ChangelogDivergedError, match="rev 2"):
        await reconstruct_scene_data(mock_scene)


@pytest.mark.asyncio
async def test_check_chain_divergence_detects_masked_midchain_loss(mock_scene):
    """End-state agreement masks the lost op; strict replay does not.

    rev 2's addition is lost on replay, and the latest snapshot reflects the
    state *without* it, so end-state comparison passes — only strict replay
    flags the chain.
    """
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)
    with open(_base_path(mock_scene), "w") as f:
        json.dump({"history": [{"id": 0}], "x": 1}, f)
    with open(_latest_path(mock_scene), "w") as f:
        json.dump({"history": [{"id": 0}], "x": 2}, f)
    _write_segment(
        mock_scene,
        0,
        [
            {
                "rev": 1,
                "ts": 1,
                "delta": {"values_changed": {"root['x']": {"new_value": 2}}},
                "meta": {},
            },
            {
                "rev": 2,
                "ts": 2,
                "delta": {"iterable_item_added": {"root['history'][5]": {"id": 1}}},
                "meta": {},
            },
        ],
        2,
    )

    divergent = await check_chain_divergence(mock_scene)
    assert divergent and "rev 2" in divergent[0]


@pytest.mark.asyncio
async def test_check_chain_divergence_detects_masked_reorder_loss(mock_scene):
    """A reorder recorded against a list the reconstruction no longer holds.

    The base is short of ``d`` (an earlier loss), yet rev 2 replaces the whole
    list with its recorded post-state, so the reconstruction ends up matching
    the latest snapshot exactly — end-state comparison sees a healthy chain.
    """
    os.makedirs(mock_scene.changelog_dir, exist_ok=True)
    with open(_base_path(mock_scene), "w") as f:
        json.dump({"history": [_full_message(0)], "entries": ["a", "b", "c"]}, f)
    with open(_latest_path(mock_scene), "w") as f:
        json.dump({"history": [_full_message(0)], "entries": ["d", "c", "b", "a"]}, f)
    _write_segment(
        mock_scene,
        0,
        [
            {
                "rev": 1,
                "ts": 1,
                "delta": {"values_changed": {"root['entries'][0]": {"new_value": "a"}}},
                "meta": {},
            },
            {
                "rev": 2,
                "ts": 2,
                "delta": {
                    "values_changed": {
                        "root['entries']": {
                            "new_value": ["d", "c", "b", "a"],
                            "old_value": ["a", "b", "c", "d"],
                        }
                    },
                    REORDERED_LISTS_KEY: ["root['entries']"],
                },
                "meta": {},
            },
        ],
        2,
    )

    with pytest.raises(ChangelogDivergedError, match="rev 2"):
        await reconstruct_scene_data(mock_scene)

    divergent = await check_chain_divergence(mock_scene)
    assert divergent and "rev 2" in divergent[0]


# --- Rebase repair (issue #295) -------------------------------------------


def _full_message(idx: int) -> dict:
    # full SceneMessage shape — a bare fragment would trip _repair_history in
    # reconstruct_cleanup and read as divergence against the latest snapshot
    return {
        "id": idx,
        "message": f"message {idx}",
        "typ": "narrator",
        "source": "ai",
        "flags": 0,
    }


def _make_diverged_chain(scene):
    """A chain whose rev 2 op no longer applies, with a latest snapshot that
    masks the loss under end-state comparison."""
    os.makedirs(scene.changelog_dir, exist_ok=True)
    with open(_base_path(scene), "w") as f:
        json.dump({"history": [_full_message(0)], "x": 1}, f)
    with open(_latest_path(scene), "w") as f:
        json.dump({"history": [_full_message(0)], "x": 2}, f)
    _write_segment(
        scene,
        0,
        [
            {
                "rev": 1,
                "ts": 1,
                "delta": {"values_changed": {"root['x']": {"new_value": 2}}},
                "meta": {},
            },
            {
                "rev": 2,
                "ts": 2,
                "delta": {
                    "iterable_item_added": {"root['history'][5]": _full_message(1)}
                },
                "meta": {},
            },
        ],
        2,
    )


@pytest.mark.asyncio
async def test_rebase_diverged_chain(mock_scene):
    """The latest snapshot becomes the new base; the old chain is preserved."""
    _make_diverged_chain(mock_scene)
    assert await check_chain_divergence(mock_scene)

    result = await rebase_changelog_chain(mock_scene)

    assert result["rebased_from_rev"] == 2
    preserved_dir = os.path.join(mock_scene.changelog_dir, result["preserved_to"])
    assert os.path.isdir(preserved_dir)
    preserved = os.listdir(preserved_dir)
    assert f"{mock_scene.filename}.base.json" in preserved
    assert f"{mock_scene.filename}.changelog.0.json" in preserved

    # the new base is the old latest snapshot, with message revs zeroed into
    # the fresh namespace; the latest snapshot is normalized the same way
    rebased = {"history": [{**_full_message(0), "rev": 0}], "x": 2}
    with open(_base_path(mock_scene)) as f:
        assert json.load(f) == rebased
    with open(_latest_path(mock_scene)) as f:
        assert json.load(f) == rebased
    # the pre-rebase latest snapshot is preserved with the old chain
    assert f"{mock_scene.filename}.latest.json" in preserved

    # the fresh chain verifies clean and restarts the revision namespace
    assert await check_chain_divergence(mock_scene) == []
    assert list_revisions(mock_scene) == []

    marker = read_rebase_marker(mock_scene)
    assert marker["rebases"][0]["rebased_from_rev"] == 2
    assert marker["rebases"][0]["preserved_to"] == result["preserved_to"]

    # appends continue from revision 1 against the rebased state
    mock_scene.serialize = {"history": [_full_message(0)], "x": 3}
    assert await persist_test_mutation(mock_scene) == 1
    assert await check_chain_divergence(mock_scene) == []


@pytest.mark.asyncio
async def test_rebase_refuses_healthy_chain(mock_scene):
    await save_changelog(mock_scene)
    mock_scene.serialize = {"characters": [], "entries": ["a"], "metadata": {}}
    assert await persist_test_mutation(mock_scene) == 1

    with pytest.raises(ValueError, match="healthy"):
        await rebase_changelog_chain(mock_scene)


@pytest.mark.asyncio
async def test_rebase_no_changelog_raises(mock_scene):
    with pytest.raises(ValueError, match="nothing to rebase"):
        await rebase_changelog_chain(mock_scene)


@pytest.mark.asyncio
async def test_rebase_missing_latest_refuses(mock_scene):
    """No sound state to rebase onto."""
    _make_diverged_chain(mock_scene)
    os.remove(_latest_path(mock_scene))

    with pytest.raises(ChangelogCorruptedError, match="no sound state"):
        await rebase_changelog_chain(mock_scene)


@pytest.mark.asyncio
async def test_rebase_unverifiable_quarantined_chain(mock_scene):
    """A quarantined chain (unverifiable) is eligible for rebase; the
    quarantine artifacts are preserved with the old chain."""
    from talemate.changelog import quarantine_corrupted_changelog_files

    _make_diverged_chain(mock_scene)
    _, log_path = _get_latest_changelog_file(mock_scene)
    with open(log_path, "w") as f:
        f.write('{"deltas": [{"rev": 1, "delta": ')
    quarantined = quarantine_corrupted_changelog_files(mock_scene)
    assert quarantined

    result = await rebase_changelog_chain(mock_scene)

    preserved_dir = os.path.join(mock_scene.changelog_dir, result["preserved_to"])
    preserved = os.listdir(preserved_dir)
    assert f"{mock_scene.filename}.changelog.0.json.corrupted" in preserved
    assert f"{mock_scene.filename}.quarantine.json" in preserved
    assert await check_chain_divergence(mock_scene) == []


def _changelog_dir_contents(scene) -> dict:
    contents = {}
    for name in os.listdir(scene.changelog_dir):
        path = os.path.join(scene.changelog_dir, name)
        if os.path.isfile(path):
            with open(path) as f:
                contents[name] = f.read()
    return contents


@pytest.mark.asyncio
async def test_rebase_failure_restores_the_chain(mock_scene, monkeypatch):
    """A failed rebase must not leave the scene without a base: with a latest
    snapshot and no base the chain reads as healthy and empty."""
    _make_diverged_chain(mock_scene)
    before = _changelog_dir_contents(mock_scene)

    base_path = _base_path(mock_scene)
    real_replace = os.replace
    failed = []

    def failing_replace(src, dst, **kwargs):
        # only the install fails — the rollback restores the old base the
        # same way and has to be able to run
        if dst == base_path and not failed:
            failed.append(dst)
            raise OSError("no space left on device")
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="no space left"):
        await rebase_changelog_chain(mock_scene)

    monkeypatch.undo()

    assert _changelog_dir_contents(mock_scene) == before
    assert not os.path.exists(_rebase_marker_path(mock_scene))
    assert glob.glob(os.path.join(mock_scene.changelog_dir, "rebased-*")) == []
    assert await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
async def test_rebase_failure_after_base_install_restores_the_chain(
    mock_scene, monkeypatch
):
    """The latest snapshot joins the atomic sequence: a failure after the new
    base is installed still restores both snapshots."""
    _make_diverged_chain(mock_scene)
    before = _changelog_dir_contents(mock_scene)

    latest_path = _latest_path(mock_scene)
    real_replace = os.replace
    failed = []

    def failing_replace(src, dst, **kwargs):
        if dst == latest_path and not failed:
            failed.append(dst)
            raise OSError("no space left on device")
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="no space left"):
        await rebase_changelog_chain(mock_scene)

    monkeypatch.undo()

    assert _changelog_dir_contents(mock_scene) == before
    assert not os.path.exists(_rebase_marker_path(mock_scene))
    assert glob.glob(os.path.join(mock_scene.changelog_dir, "rebased-*")) == []
    assert await check_chain_divergence(mock_scene)


def _make_diverged_chain_with_stamps(scene):
    """A diverged chain whose snapshots carry message rev stamps from its own
    revision namespace."""
    _make_diverged_chain(scene)
    for path in (_base_path(scene), _latest_path(scene)):
        with open(path) as f:
            data = json.load(f)
        data["history"] = [{**_full_message(0), "rev": 1}]
        with open(path, "w") as f:
            json.dump(data, f)


@pytest.mark.asyncio
async def test_rebase_flushes_staged_deltas_and_restarts_numbering(mock_scene):
    """Issue #295 follow-up: a repair with deltas staged in memory must not
    leave the fresh chain interleaving revisions from both namespaces."""
    _make_diverged_chain(mock_scene)
    mock_scene.serialize = {"history": [_full_message(0)], "x": 2}
    mock_scene.rev = 2

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene._changelog = changelog

        mock_scene.serialize = {"history": [_full_message(0)], "x": 3}
        assert await changelog.append_delta({"action": "staged_a"}) == 3
        mock_scene.serialize = {"history": [_full_message(0)], "x": 4}
        assert await changelog.append_delta({"action": "staged_b"}) == 4

        result = await rebase_changelog_chain(mock_scene)

        # the staged deltas went to the chain that was archived, meta intact
        assert changelog.pending_deltas == []
        with open(
            os.path.join(
                mock_scene.changelog_dir,
                result["preserved_to"],
                f"{mock_scene.filename}.changelog.0.json",
            )
        ) as f:
            preserved = json.load(f)
        assert [entry["rev"] for entry in preserved["deltas"]] == [1, 2, 3, 4]
        assert [entry["meta"] for entry in preserved["deltas"][2:]] == [
            {"action": "staged_a"},
            {"action": "staged_b"},
        ]

        # the fresh chain starts empty and numbers from 1 again
        assert mock_scene.rev == 0
        assert list_revisions(mock_scene) == []

        mock_scene.serialize = {"history": [_full_message(0)], "x": 5}
        assert await changelog.append_delta({"action": "after_repair"}) == 1
        assert await changelog.commit() == [1]

    assert list_revisions(mock_scene) == [1]
    assert await check_chain_divergence(mock_scene) == []
    reconstructed = await reconstruct_scene_data(mock_scene)
    assert reconstructed["x"] == 5


@pytest.mark.asyncio
async def test_rebase_refusal_leaves_staged_deltas_uncommitted(mock_scene):
    """A refused repair must not commit the work auto-save was holding back."""
    await save_changelog(mock_scene)
    mock_scene.serialize = {"characters": [], "entries": ["a"], "metadata": {}}
    assert await persist_test_mutation(mock_scene) == 1
    mock_scene.rev = 1

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene._changelog = changelog
        mock_scene.serialize = {"characters": [], "entries": ["a", "b"], "metadata": {}}
        assert await changelog.append_delta({"action": "staged"}) == 2

        before = _changelog_dir_contents(mock_scene)
        rev_before = mock_scene.rev

        with pytest.raises(ValueError, match="healthy"):
            await rebase_changelog_chain(mock_scene)

        assert _changelog_dir_contents(mock_scene) == before
        assert [entry["meta"] for entry in changelog.pending_deltas] == [
            {"action": "staged"}
        ]
        assert mock_scene.rev == rev_before


@pytest.mark.asyncio
async def test_rebase_flush_emits_no_message_revs(mock_scene, monkeypatch):
    """The flushed revs are zeroed moments later — announcing them would leave
    the UI holding revisions the fresh chain does not have."""
    import talemate.emit

    _make_diverged_chain(mock_scene)
    mock_scene.serialize = {"history": [_full_message(0)], "x": 2}
    mock_scene.rev = 2
    # the rev the staged delta commits at
    message = NarratorMessage("message 0", id=0, rev=3)
    mock_scene.history = [message]

    emitted = []
    monkeypatch.setattr(
        talemate.emit, "emit", lambda typ, *args, **kwargs: emitted.append(typ)
    )

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene._changelog = changelog
        mock_scene.serialize = {"history": [_full_message(0)], "x": 3}
        assert await changelog.append_delta({"action": "staged"}) == 3
        await rebase_changelog_chain(mock_scene)

    assert "message_revs" not in emitted
    assert message.rev == 0


@pytest.mark.asyncio
async def test_rebase_flush_failure_restores_staged_deltas(mock_scene, monkeypatch):
    """A failed flush must not swallow the staged deltas it was writing."""
    from talemate import changelog as changelog_mod

    _make_diverged_chain(mock_scene)
    mock_scene.serialize = {"history": [_full_message(0)], "x": 2}
    mock_scene.rev = 2

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene._changelog = changelog
        mock_scene.serialize = {"history": [_full_message(0)], "x": 3}
        assert await changelog.append_delta({"action": "staged"}) == 3

        before = _changelog_dir_contents(mock_scene)
        real_write = changelog_mod._write_json

        def failing_write(path, data, cls=None):
            if ".changelog." in os.path.basename(path):
                raise OSError("no space left on device")
            return real_write(path, data, cls=cls)

        monkeypatch.setattr(changelog_mod, "_write_json", failing_write)

        with pytest.raises(OSError, match="no space left"):
            await rebase_changelog_chain(mock_scene)

        monkeypatch.undo()

        assert _changelog_dir_contents(mock_scene) == before
        assert glob.glob(os.path.join(mock_scene.changelog_dir, "rebased-*")) == []
        assert [entry["meta"] for entry in changelog.pending_deltas] == [
            {"action": "staged"}
        ]
        assert mock_scene.rev == 2


@pytest.mark.asyncio
async def test_rebase_failure_after_flush_restores_staged_deltas(
    mock_scene, monkeypatch
):
    """The flush joins the atomic sequence: a failure after it un-commits the
    staged deltas rather than leaving them on an unrebased chain."""
    from talemate import changelog as changelog_mod

    _make_diverged_chain(mock_scene)
    mock_scene.serialize = {"history": [_full_message(0)], "x": 2}
    mock_scene.rev = 2

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene._changelog = changelog
        mock_scene.serialize = {"history": [_full_message(0)], "x": 3}
        assert await changelog.append_delta({"action": "staged"}) == 3

        before = _changelog_dir_contents(mock_scene)
        marker_path = _rebase_marker_path(mock_scene)
        real_write = changelog_mod._write_json

        def failing_write(path, data, cls=None):
            if path == marker_path:
                raise OSError("no space left on device")
            return real_write(path, data, cls=cls)

        monkeypatch.setattr(changelog_mod, "_write_json", failing_write)

        with pytest.raises(OSError, match="no space left"):
            await rebase_changelog_chain(mock_scene)

        monkeypatch.undo()

        assert _changelog_dir_contents(mock_scene) == before
        assert not os.path.exists(marker_path)
        assert glob.glob(os.path.join(mock_scene.changelog_dir, "rebased-*")) == []
        assert [entry["meta"] for entry in changelog.pending_deltas] == [
            {"action": "staged"}
        ]
        assert mock_scene.rev == 2
        assert await check_chain_divergence(mock_scene)


@pytest.mark.asyncio
@pytest.mark.skipif(os.geteuid() == 0, reason="root reads through mode 0o000")
async def test_rebase_unreadable_segment_refuses_without_deleting_it(mock_scene):
    """An unreadable segment makes the chain unverifiable — hence eligible for
    repair — but the flush snapshot cannot promise to restore a file it could
    not read, so the repair refuses instead of rolling back over it."""
    _make_diverged_chain(mock_scene)
    mock_scene.serialize = {"history": [_full_message(0)], "x": 2}
    mock_scene.rev = 2

    async with InMemoryChangelog(mock_scene) as changelog:
        mock_scene._changelog = changelog
        mock_scene.serialize = {"history": [_full_message(0)], "x": 3}
        assert await changelog.append_delta({"action": "staged"}) == 3

        _, log_path = _get_latest_changelog_file(mock_scene)
        with open(log_path, "rb") as f:
            segment_before = f.read()

        os.chmod(log_path, 0o000)
        try:
            with pytest.raises(PermissionError):
                await rebase_changelog_chain(mock_scene)

            assert os.path.exists(log_path)
        finally:
            if os.path.exists(log_path):
                os.chmod(log_path, 0o644)

        with open(log_path, "rb") as f:
            assert f.read() == segment_before
        assert [entry["meta"] for entry in changelog.pending_deltas] == [
            {"action": "staged"}
        ]
        assert mock_scene.rev == 2


@pytest.mark.asyncio
async def test_rebase_zeroes_message_revs(mock_scene):
    """Live messages and both snapshots land in the fresh namespace, and the
    next scene-loop context does not restore the archived stamps."""
    _make_diverged_chain_with_stamps(mock_scene)
    mock_scene.serialize = {"history": [{**_full_message(0), "rev": 1}], "x": 2}
    mock_scene.rev = 2
    message = NarratorMessage("message 0", id=0, rev=1)
    mock_scene.history = [message]

    await rebase_changelog_chain(mock_scene)

    assert message.rev == 0
    assert mock_scene.rev == 0
    for path in (_base_path(mock_scene), _latest_path(mock_scene)):
        with open(path) as f:
            assert [entry["rev"] for entry in json.load(f)["history"]] == [0]

    assert await check_chain_divergence(mock_scene) == []

    async with InMemoryChangelog(mock_scene) as changelog:
        # _backfill_message_revs reads the snapshot's revs — zeroed, so there
        # is nothing to re-stamp
        assert message.rev == 0
        assert [entry["rev"] for entry in changelog.last_state["history"]] == [0]


@pytest.mark.asyncio
async def test_rebase_twice_in_the_same_second_preserves_both(mock_scene, monkeypatch):
    """Two repairs within the same second get distinct preserved dirs."""
    from talemate import changelog as changelog_mod

    class _FrozenClock:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 1, 1, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(changelog_mod, "datetime", _FrozenClock)

    _make_diverged_chain(mock_scene)
    first = await rebase_changelog_chain(mock_scene)
    first_base = os.path.join(
        mock_scene.changelog_dir,
        first["preserved_to"],
        f"{mock_scene.filename}.base.json",
    )
    with open(first_base, "w") as f:
        json.dump({"sentinel": True}, f)

    _make_diverged_chain(mock_scene)
    second = await rebase_changelog_chain(mock_scene)

    assert second["preserved_to"] != first["preserved_to"]
    with open(first_base) as f:
        assert json.load(f) == {"sentinel": True}
    assert f"{mock_scene.filename}.base.json" in os.listdir(
        os.path.join(mock_scene.changelog_dir, second["preserved_to"])
    )

    marker = read_rebase_marker(mock_scene)
    assert [entry["preserved_to"] for entry in marker["rebases"]] == [
        first["preserved_to"],
        second["preserved_to"],
    ]
