import os
import json
import tempfile
import shutil
import pytest
from unittest.mock import Mock

from talemate.changelog import (
    save_changelog,
    append_scene_delta,
    reconstruct_scene_data,
    write_reconstructed_scene,
    list_revisions,
    rollback_scene_to_revision,
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
    _serialize_scene_plain,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_scene(temp_dir):
    """Create a mock scene object."""
    scene = Mock()
    scene.filename = "test_scene.json"
    scene.save_dir = temp_dir
    scene.changelog_dir = os.path.join(temp_dir, "changelog")
    scene.backups_dir = os.path.join(temp_dir, "backups")
    scene.serialize = {"characters": [], "entries": [], "metadata": {"version": "1.0"}}
    return scene


def test_changelog_log_path(mock_scene):
    """Test changelog log path generation."""
    expected = os.path.join(mock_scene.changelog_dir, "test_scene.json.changelog.json")
    result = _changelog_log_path(mock_scene)
    assert result == expected
    assert os.path.exists(mock_scene.changelog_dir)


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


def test_ensure_log_initialized_new_log(mock_scene):
    """Test initializing a new changelog log."""
    result = _ensure_log_initialized(mock_scene)

    expected_structure = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "deltas": [],
        "latest_rev": 0
    }

    assert result == expected_structure

    # Verify file was created
    log_path = _changelog_log_path(mock_scene)
    assert os.path.exists(log_path)


def test_ensure_log_initialized_existing_log(mock_scene):
    """Test loading existing changelog log."""
    log_path = _changelog_log_path(mock_scene)
    existing_data = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "deltas": [{"rev": 1}, {"rev": 3}, {"rev": 2}],
        "latest_rev": 2
    }

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(existing_data, f)

    result = _ensure_log_initialized(mock_scene)

    # Should update latest_rev to max of deltas
    assert result["latest_rev"] == 3
    assert result["deltas"] == existing_data["deltas"]


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


def test_ensure_latest_initialized_creates_file(mock_scene):
    """Test that ensure_latest_initialized creates latest file from base."""
    base_data = {"test": "base_data"}
    base_path = _base_path(mock_scene)
    latest_path = _latest_path(mock_scene)

    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    _ensure_latest_initialized(mock_scene)

    assert os.path.exists(latest_path)
    with open(latest_path, "r") as f:
        result = json.load(f)
    assert result == base_data


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
    await save_changelog(mock_scene, {})

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

    await save_changelog(mock_scene, {})

    # Base file should be unchanged
    with open(base_path, "r") as f:
        result = json.load(f)
    assert result == original_data


@pytest.mark.asyncio
async def test_append_scene_delta_no_change(mock_scene):
    """Test appending delta when scene hasn't changed."""
    # Initialize scene
    await save_changelog(mock_scene, {})

    # Try to append delta with same data
    result = await append_scene_delta(mock_scene, {"action": "test"})

    # Should return None (no change)
    assert result is None


@pytest.mark.asyncio
async def test_append_scene_delta_with_change(mock_scene):
    """Test appending delta when scene has changed."""
    # Initialize scene
    await save_changelog(mock_scene, {})

    # Change the scene data
    mock_scene.serialize = {"characters": [{"name": "Alice"}], "entries": [], "metadata": {"version": "1.0"}}

    result = await append_scene_delta(mock_scene, {"action": "add_character"})

    # Should return revision 1
    assert result == 1

    # Check that changelog log was updated
    log_path = _changelog_log_path(mock_scene)
    with open(log_path, "r") as f:
        log_data = json.load(f)

    assert log_data["latest_rev"] == 1
    assert len(log_data["deltas"]) == 1
    assert log_data["deltas"][0]["rev"] == 1
    assert log_data["deltas"][0]["meta"] == {"action": "add_character"}


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
        "deltas": [{
            "rev": 1,
            "ts": "2023-01-01T00:00:00Z",
            "delta": delta,
            "meta": {}
        }],
        "latest_rev": 1
    }

    log_path = _changelog_log_path(mock_scene)
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
    _ensure_log_initialized(mock_scene)

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

    _ensure_log_initialized(mock_scene)

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
        "deltas": [
            {"rev": 1},
            {"rev": 3},
            {"rev": 2}
        ],
        "latest_rev": 3
    }

    log_path = _changelog_log_path(mock_scene)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    result = list_revisions(mock_scene)
    assert result == [1, 3, 2]  # Should preserve original order


@pytest.mark.asyncio
async def test_rollback_scene_to_revision_invalid_rev(mock_scene):
    """Test rollback with invalid revision number."""
    # Setup some revisions
    log_data = {
        "version": 1,
        "base": "test_scene.json.base.json",
        "deltas": [{"rev": 1}, {"rev": 2}],
        "latest_rev": 2
    }

    log_path = _changelog_log_path(mock_scene)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(log_data, f)

    with pytest.raises(ValueError, match="Invalid revision: 5. Latest available is 2."):
        await rollback_scene_to_revision(mock_scene, 5)

    with pytest.raises(ValueError, match="Invalid revision: -1. Latest available is 2."):
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

    # Setup current scene file
    current_data = {"version": "current"}
    current_path = os.path.join(mock_scene.save_dir, mock_scene.filename)
    with open(current_path, "w") as f:
        json.dump(current_data, f)

    # Setup log with revision 1
    _ensure_log_initialized(mock_scene)

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

    # Setup current scene file
    current_path = os.path.join(mock_scene.save_dir, mock_scene.filename)
    with open(current_path, "w") as f:
        json.dump({"version": "current"}, f)

    _ensure_log_initialized(mock_scene)

    await rollback_scene_to_revision(mock_scene, 0, create_backup=False)

    # Should not create backup directory
    assert not os.path.exists(mock_scene.backups_dir)


@pytest.mark.asyncio
async def test_append_scene_delta_with_exclusions(mock_scene):
    """Test that paths in EXCLUDE_FROM_DELTAS are not included in deltas."""
    # Initialize scene
    await save_changelog(mock_scene)

    # Change both excluded and included fields
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],  # Should be tracked
        "memory_session_id": "abc123",      # Should be excluded (in EXCLUDE_FROM_DELTAS)
        "saved_memory_session_id": "def456", # Should be excluded (in EXCLUDE_FROM_DELTAS)
        "entries": []
    }

    # Append delta (exclusions happen automatically)
    rev = await append_scene_delta(mock_scene, {"action": "test"})

    # Should create a revision since characters changed
    assert rev == 1

    # Check the delta only contains character changes
    log_path = _changelog_log_path(mock_scene)
    with open(log_path, "r") as f:
        log_data = json.load(f)

    delta_entry = log_data["deltas"][0]
    delta = delta_entry["delta"]

    # Should have character changes but not memory session changes
    # Get all changed paths from different delta types
    all_changed_paths = []
    for delta_type in ["values_changed", "iterable_item_added", "dictionary_item_added"]:
        if delta_type in delta:
            all_changed_paths.extend(delta[delta_type].keys())

    # Should contain character change
    assert any("characters" in path for path in all_changed_paths)

    # Should NOT contain memory session changes (automatically excluded)
    assert not any("memory_session_id" in path for path in all_changed_paths)


@pytest.mark.asyncio
async def test_append_scene_delta_with_regex_exclusions(mock_scene):
    """Test that regex patterns in EXCLUDE_FROM_DELTAS_REGEX work correctly."""
    # Initialize scene with world_state containing reinforce array
    mock_scene.serialize = {
        "characters": [],
        "world_state": {
            "reinforce": [
                {"due": "2024-01-01", "id": 1},
                {"due": "2024-01-02", "id": 2}
            ]
        }
    }
    await save_changelog(mock_scene)

    # Change both the 'due' fields (should be excluded) and add character (should be tracked)
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],  # Should be tracked
        "world_state": {
            "reinforce": [
                {"due": "2024-02-01", "id": 1},  # Should be excluded by regex
                {"due": "2024-02-02", "id": 2}   # Should be excluded by regex
            ]
        }
    }

    rev = await append_scene_delta(mock_scene, {"action": "test_regex"})

    # Should create revision for character change but ignore due field changes
    assert rev == 1

    # Check that delta only contains character changes, not 'due' changes
    log_path = _changelog_log_path(mock_scene)
    with open(log_path, "r") as f:
        log_data = json.load(f)

    delta_entry = log_data["deltas"][0]
    delta = delta_entry["delta"]

    # Get all changed paths
    all_changed_paths = []
    for delta_type in ["values_changed", "iterable_item_added", "dictionary_item_added"]:
        if delta_type in delta:
            all_changed_paths.extend(delta[delta_type].keys())

    # Should contain character change
    assert any("characters" in path for path in all_changed_paths)

    # Should NOT contain 'due' field changes (excluded by regex)
    assert not any("'due'" in path for path in all_changed_paths)


@pytest.mark.asyncio
async def test_full_workflow(mock_scene):
    """Test complete workflow: save -> append -> reconstruct -> rollback."""
    # Initial save
    initial_data = {"characters": [], "version": "1.0"}
    mock_scene.serialize = initial_data
    await save_changelog(mock_scene, {})

    # First change
    mock_scene.serialize = {"characters": [{"name": "Alice"}], "version": "1.0"}
    rev1 = await append_scene_delta(mock_scene, {"action": "add_alice"})
    assert rev1 == 1

    # Second change
    mock_scene.serialize = {"characters": [{"name": "Alice"}, {"name": "Bob"}], "version": "1.0"}
    rev2 = await append_scene_delta(mock_scene, {"action": "add_bob"})
    assert rev2 == 2

    # List revisions
    revisions = list_revisions(mock_scene)
    assert revisions == [1, 2]

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