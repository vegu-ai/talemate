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
    _serialize_scene_plain,
    _get_changelog_files,
    _get_latest_changelog_file,
    _get_overall_latest_revision,
    _get_file_size,
    MAX_CHANGELOG_FILE_SIZE,
    InMemoryChangelog,
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
    scene.rev = 0  # Initialize revision to 0
    scene._changelog = None  # Explicitly set to None to avoid Mock auto-creation
    return scene


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
async def test_append_scene_delta_no_change(mock_scene):
    """Test appending delta when scene hasn't changed."""
    # Initialize scene
    await save_changelog(mock_scene)

    # Try to append delta with same data
    result = await append_scene_delta(mock_scene, {"action": "test"})

    # Should return None (no change)
    assert result is None


@pytest.mark.asyncio
async def test_append_scene_delta_with_change(mock_scene):
    """Test appending delta when scene has changed."""
    # Initialize scene
    await save_changelog(mock_scene)

    # Change the scene data
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}],
        "entries": [],
        "metadata": {"version": "1.0"},
    }

    result = await append_scene_delta(mock_scene, {"action": "add_character"})

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

    # Setup current scene file
    current_path = os.path.join(mock_scene.save_dir, mock_scene.filename)
    with open(current_path, "w") as f:
        json.dump({"version": "current"}, f)

    _ensure_log_initialized(mock_scene, 0)

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
        "memory_session_id": "abc123",  # Should be excluded (in EXCLUDE_FROM_DELTAS)
        "saved_memory_session_id": "def456",  # Should be excluded (in EXCLUDE_FROM_DELTAS)
        "entries": [],
    }

    # Append delta (exclusions happen automatically)
    rev = await append_scene_delta(mock_scene, {"action": "test"})

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
async def test_append_scene_delta_with_regex_exclusions(mock_scene):
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

    rev = await append_scene_delta(mock_scene, {"action": "test_regex"})

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
    rev1 = await append_scene_delta(mock_scene, {"action": "add_alice"})
    assert rev1 == 1

    # Second change
    mock_scene.serialize = {
        "characters": [{"name": "Alice"}, {"name": "Bob"}],
        "version": "1.0",
    }
    rev2 = await append_scene_delta(mock_scene, {"action": "add_bob"})
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
async def test_append_scene_delta_creates_new_file_when_size_exceeded(mock_scene):
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
        rev = await append_scene_delta(mock_scene, {"action": "test"})
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
    await append_scene_delta(mock_scene, {"action": "existing_change"})

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
async def test_in_memory_changelog_with_save_changelog_bug(mock_scene):
    """
    Test that reproduces the bug where save_changelog() is called while
    InMemoryChangelog has pending changes, causing duplication.

    This simulates:
    1. Scene starts with InMemoryChangelog context
    2. Messages are added (pending in memory)
    3. save_changelog() is called (creates base with pending changes baked in)
    4. InMemoryChangelog.commit() is called (writes same changes as deltas)
    5. Reconstruction duplicates messages
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
        # This saves the base with ALL 4 messages already in it
        await save_changelog(mock_scene)

        # Commit the pending deltas
        # This writes deltas that try to add messages 3 and 4 again
        await changelog.commit()

    # Now reconstruct to revision 4
    reconstructed = await reconstruct_scene_data(mock_scene, to_rev=4)

    # BUG: The reconstructed history will have duplicates
    # Base has 4 messages + deltas add 2 more = 6 messages (with duplicates)
    history = reconstructed.get("history", [])

    # This assertion SHOULD pass (4 messages) but currently FAILS (6 messages due to bug)
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
    # Create a scene with changelogs
    scene1 = Mock()
    scene1.filename = "scene_to_delete.json"
    scene1.save_dir = os.path.join(temp_dir, "project1")
    scene1.changelog_dir = os.path.join(scene1.save_dir, "changelog")
    scene1.serialize = {"characters": [], "data": "scene1"}
    scene1.rev = 0
    scene1._changelog = None

    # Initialize changelog for scene1
    await save_changelog(scene1)

    # Verify changelog files were created
    assert os.path.exists(_base_path(scene1))
    assert os.path.exists(_latest_path(scene1))

    # Now simulate the bug: calling delete_changelog_files with a different scene
    # (or None, which would be self.scene when no scene is loaded)
    wrong_scene = Mock()
    wrong_scene.filename = "different_scene.json"  # Wrong filename!
    wrong_scene.save_dir = os.path.join(temp_dir, "project2")  # Wrong directory!
    wrong_scene.changelog_dir = os.path.join(wrong_scene.save_dir, "changelog")

    # Try to delete with wrong scene reference
    result = delete_changelog_files(wrong_scene)

    # BUG: This will try to delete files for "different_scene.json" in "project2"
    # but scene1's files are in "project1" with filename "scene_to_delete.json"
    # So scene1's changelog files will NOT be deleted

    # Verify scene1's changelog files still exist (they were not deleted)
    assert os.path.exists(_base_path(scene1)), "Base file should still exist due to bug"
    assert os.path.exists(_latest_path(scene1)), "Latest file should still exist due to bug"

    # Now show the correct way: construct scene reference from the file path
    scene_path = os.path.join(scene1.save_dir, scene1.filename)
    scene_dir = os.path.dirname(scene_path)
    scene_filename = os.path.basename(scene_path)
    correct_scene_ref = type('Scene', (), {
        'save_dir': scene_dir,
        'filename': scene_filename,
        'changelog_dir': os.path.join(scene_dir, 'changelog'),
    })()

    # Delete with correct reference
    result = delete_changelog_files(correct_scene_ref)

    # Now the files should be deleted
    assert not os.path.exists(_base_path(scene1)), "Base file should be deleted"
    assert not os.path.exists(_latest_path(scene1)), "Latest file should be deleted"
    assert len(result.get("deleted", [])) >= 2, "Should have deleted at least base and latest"
