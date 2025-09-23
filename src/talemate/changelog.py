"""
Scene Changelog System

This module implements a comprehensive changelog system for TaleMate scenes that tracks
all changes over time using delta compression. It provides functionality to:

- Store incremental changes (deltas) between scene revisions
- Reconstruct any previous scene state by applying deltas
- Roll back scenes to previous revisions with optional backups
- Optimize performance using base + latest snapshot caching

Architecture:
-----------
The changelog system uses three types of files per scene:

1. **Base Snapshot** (`<scene>.base.json`):
   - The initial scene state (revision 0)
   - Never modified after creation

2. **Latest Snapshot** (`<scene>.latest.json`):
   - Cached state of the most recent revision
   - Used for optimization to avoid full reconstruction when computing new deltas

3. **Changelog Log** (`<scene>.changelog.json`):
   - Contains all delta entries with metadata
   - Structure: {"version": 1, "base": "filename", "deltas": [...], "latest_rev": N}
   - Each delta entry: {"rev": N, "ts": "ISO-timestamp", "delta": {...}, "meta": {...}}

Delta Storage:
-------------
Deltas are computed using DeepDiff and stored as serializable dictionaries.
The system can reconstruct any revision by starting from the base snapshot
and sequentially applying deltas up to the target revision.

Performance Optimization:
------------------------
- Avoids full scene reconstruction on every delta computation by comparing
  against the latest snapshot instead of reconstructing from base + deltas
- Updates the latest snapshot after each successful delta append
- Lazy initialization of changelog files only when needed

Usage Example:
-------------
```python
# Initialize changelog for a scene
await save_changelog(scene)

# Append changes when scene is modified
rev = await append_scene_delta(scene, {"action": "character_added"})

# Volatile fields are automatically excluded via EXCLUDE_FROM_DELTAS and EXCLUDE_FROM_DELTAS_REGEX
rev = await append_scene_delta(scene, {"action": "edit"})

# Reconstruct scene at specific revision
scene_data = await reconstruct_scene_data(scene, to_rev=5)

# Roll back to previous state
await rollback_scene_to_revision(scene, to_rev=3, create_backup=True)
```

File Layout:
-----------
```
<scene_save_dir>/
├── scene.json              # Current scene file
└── changelog/
    ├── scene.json.base.json      # Base snapshot (rev 0)
    ├── scene.json.latest.json    # Latest snapshot (optimization)
    └── scene.json.changelog.json # Delta log with metadata
```
"""

from typing import TYPE_CHECKING
import json
import os
import structlog
import deepdiff
from datetime import datetime, timezone
import shutil
# import re

from talemate.save import SceneEncoder

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


log = structlog.get_logger("talemate.changelog")


# Fields to exclude from delta computation (e.g., volatile session IDs)
# Supports both exact paths and regex patterns
EXCLUDE_FROM_DELTAS = [
    "root['memory_session_id']",
    "root['saved_memory_session_id']",
]

# Regex patterns for wildcard exclusions (e.g., array indices)

EXCLUDE_FROM_DELTAS_REGEX = [
    # Add regex patterns as needed:
    # re.compile(r"root\['some_array'\]\[\d+\]\['volatile_field'\]"),
]


async def save_changelog(scene: "Scene"):
    """
    Initialize the changelog system for a scene by creating base and latest snapshot files.

    This function sets up the initial changelog structure by creating:
    - A base snapshot file (rev0) containing the current scene state
    - A latest snapshot file for optimization purposes

    Only creates files if the base snapshot doesn't already exist.

    Args:
        scene: The scene object to initialize changelog for
        changelog: Legacy parameter (currently unused)

    Returns:
        None
    """
    base_file = f"{scene.filename}.base.json"
    base_path = os.path.join(scene.changelog_dir, base_file)

    serialized_scene = scene.serialize

    if not os.path.exists(base_path):
        os.makedirs(scene.changelog_dir, exist_ok=True)
        with open(base_path, "w") as f:
            log.debug("Changelog base file created", path=base_path)
            json.dump(serialized_scene, f, indent=2, cls=SceneEncoder)
        # initialize latest snapshot to base
        latest_path = _latest_path(scene)
        with open(latest_path, "w") as f:
            json.dump(serialized_scene, f, indent=2, cls=SceneEncoder)
        return


def _changelog_log_path(scene: "Scene"):
    """
    Get the path to the changelog log file for a scene.

    Creates the changelog directory if it doesn't exist.

    Args:
        scene: The scene object

    Returns:
        str: Path to the changelog log file
    """
    os.makedirs(scene.changelog_dir, exist_ok=True)
    return os.path.join(scene.changelog_dir, f"{scene.filename}.changelog.json")


def _base_path(scene: "Scene") -> str:
    """
    Get the path to the base snapshot file for a scene.

    Args:
        scene: The scene object

    Returns:
        str: Path to the base snapshot file (rev0)
    """
    return os.path.join(scene.changelog_dir, f"{scene.filename}.base.json")


def _latest_path(scene: "Scene") -> str:
    """
    Get the path to the latest snapshot file for a scene.

    The latest snapshot is used for optimization to avoid reconstructing
    the entire scene state when computing deltas.

    Args:
        scene: The scene object

    Returns:
        str: Path to the latest snapshot file
    """
    return os.path.join(scene.changelog_dir, f"{scene.filename}.latest.json")


def _utc_iso_now() -> str:
    """
    Get the current UTC timestamp in ISO format.

    Returns:
        str: Current UTC timestamp in ISO 8601 format
    """
    return datetime.now(timezone.utc).isoformat()


def _read_json_or_default(path: str, default):
    """
    Read JSON data from file, returning default value on failure.

    Args:
        path: Path to the JSON file
        default: Default value to return if file doesn't exist or can't be read

    Returns:
        The JSON data from the file, or the default value on error
    """
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        log.error("read_json", error=e, path=path)
        return default


def _write_json(path: str, data: dict):
    """
    Write JSON data to file, creating parent directories as needed.

    Args:
        path: Path to write the JSON file
        data: Dictionary data to write as JSON

    Returns:
        None
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error("write_json", error=e, path=path)


def _ensure_log_initialized(scene: "Scene") -> dict:
    """
    Ensure the changelog log file exists and is properly initialized.

    Creates a new changelog log file with default structure if it doesn't exist,
    or loads and validates an existing one. Ensures the latest_rev field is
    correctly set to the maximum revision number found in deltas.

    Args:
        scene: The scene object

    Returns:
        dict: The changelog log data structure containing version, base, deltas, and latest_rev
    """
    log_path = _changelog_log_path(scene)
    base_filename = f"{scene.filename}.base.json"
    default_content = {
        "version": 1,
        "base": base_filename,
        "deltas": [],
        "latest_rev": 0,
    }
    content = _read_json_or_default(log_path, default_content)
    content.setdefault("version", 1)
    content.setdefault("base", base_filename)
    content.setdefault("deltas", [])
    try:
        max_rev = max([d.get("rev", 0) for d in content.get("deltas", [])] or [0])
    except Exception:
        max_rev = 0
    content["latest_rev"] = max(content.get("latest_rev", 0), max_rev)
    if not os.path.exists(log_path):
        _write_json(log_path, content)
    return content


def _load_base_scene_data(scene: "Scene") -> dict:
    """
    Load the base scene data (revision 0) from the base snapshot file.

    Args:
        scene: The scene object

    Returns:
        dict: The base scene data

    Raises:
        FileNotFoundError: If the base snapshot file doesn't exist
        json.JSONDecodeError: If the base snapshot file contains invalid JSON
    """
    base_path = _base_path(scene)
    with open(base_path, "r") as f:
        return json.load(f)


def _load_latest_scene_data(scene: "Scene") -> dict | None:
    """
    Load the latest scene data from the latest snapshot file.

    The latest snapshot is used for optimization to avoid reconstructing
    the entire scene state when computing deltas.

    Args:
        scene: The scene object

    Returns:
        dict | None: The latest scene data, or None if file doesn't exist or can't be read
    """
    path = _latest_path(scene)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        log.error("read_latest_failed", error=e, path=path)
        return None


def _ensure_latest_initialized(scene: "Scene") -> None:
    """
    Ensure the latest snapshot file exists, creating it from base if needed.

    This function is used to maintain the optimization cache. If the latest
    snapshot file doesn't exist, it's initialized with the base scene data.

    Args:
        scene: The scene object

    Returns:
        None
    """
    latest = _latest_path(scene)
    if not os.path.exists(latest):
        base_data = _load_base_scene_data(scene)
        _write_json(latest, base_data)


def _apply_delta(data: dict, delta_obj: dict) -> dict:
    """
    Apply a delta (set of changes) to scene data.

    Uses DeepDiff's Delta class to apply the stored changes to reconstruct
    a scene state at a specific revision.

    Args:
        data: The base scene data to apply the delta to
        delta_obj: The delta dictionary containing the changes

    Returns:
        dict: The scene data with the delta applied

    Raises:
        Exception: If the delta cannot be applied (re-raised from deepdiff)
    """
    try:
        delta = deepdiff.Delta(delta_obj)
        return data + delta
    except Exception as e:
        log.error("apply_delta_failed", error=e)
        raise


def _compute_delta(prev: dict, curr: dict) -> dict:
    """
    Compute the delta (difference) between two scene states.

    Uses DeepDiff to calculate the changes needed to transform the previous
    state into the current state. Returns an empty dict if no changes.
    Automatically excludes paths in EXCLUDE_FROM_DELTAS and regex patterns
    in EXCLUDE_FROM_DELTAS_REGEX.

    Args:
        prev: The previous scene state
        curr: The current scene state

    Returns:
        dict: The delta containing the changes, or empty dict if no changes
    """
    diff = deepdiff.DeepDiff(
        prev,
        curr,
        ignore_order=False,
        exclude_paths=EXCLUDE_FROM_DELTAS,
        exclude_regex_paths=EXCLUDE_FROM_DELTAS_REGEX,
    )
    if not diff:
        return {}
    return diff._to_delta_dict()


def _serialize_scene_plain(scene: "Scene") -> dict:
    """
    Serialize a scene to a plain dictionary suitable for JSON storage.

    Converts the scene's serialized data through JSON encoding/decoding
    to ensure it contains only JSON-serializable types. Falls back to
    the raw serialize data if the conversion fails.

    Args:
        scene: The scene object to serialize

    Returns:
        dict: The serialized scene data as a plain dictionary
    """
    try:
        return json.loads(json.dumps(scene.serialize, cls=SceneEncoder))
    except Exception as e:
        log.error("serialize_scene_plain_failed", error=e)
        return scene.serialize


async def append_scene_delta(scene: "Scene", meta: dict | None = None) -> int | None:
    """
    Append a new delta to the changelog if the scene has changed.

    Computes the difference between the latest snapshot and current scene state.
    If changes are found, creates a new revision entry in the changelog with
    the delta and metadata. Updates the latest snapshot for future comparisons.
    Automatically excludes paths listed in EXCLUDE_FROM_DELTAS.

    Args:
        scene: The scene object to create a delta for
        meta: Optional metadata to store with this revision

    Returns:
        int | None: The new revision number if changes were found, None if unchanged
    """
    if not os.path.exists(_base_path(scene)):
        await save_changelog(scene, {})

    log_data = _ensure_log_initialized(scene)
    deltas = log_data.get("deltas", [])
    latest_rev = log_data.get("latest_rev", (deltas[-1]["rev"] if deltas else 0))

    _ensure_latest_initialized(scene)
    prev_data = _load_latest_scene_data(scene)
    if prev_data is None:
        prev_data = await reconstruct_scene_data(scene, to_rev=latest_rev)

    curr_data = _serialize_scene_plain(scene)

    delta = _compute_delta(prev_data, curr_data)
    if not delta:
        return None

    new_rev = latest_rev + 1
    deltas.append(
        {
            "rev": new_rev,
            "ts": _utc_iso_now(),
            "delta": delta,
            "meta": meta or {},
        }
    )
    log_data["deltas"] = deltas
    log_data["latest_rev"] = new_rev
    _write_json(_changelog_log_path(scene), log_data)
    log.debug("append_scene_delta", rev=new_rev)
    _write_json(_latest_path(scene), curr_data)
    return new_rev


async def reconstruct_scene_data(scene: "Scene", to_rev: int | None = None) -> dict:
    """
    Reconstruct scene data at a specific revision by applying deltas.

    Starts from the base scene data (revision 0) and sequentially applies
    all deltas up to the target revision to reconstruct the scene state.

    Args:
        scene: The scene object to reconstruct
        to_rev: Target revision number, or None for latest revision

    Returns:
        dict: The reconstructed scene data at the specified revision
    """
    log_data = _ensure_log_initialized(scene)
    all_deltas = list(log_data.get("deltas", []))

    if to_rev is None:
        to_rev = all_deltas[-1]["rev"] if all_deltas else 0

    data = _load_base_scene_data(scene)

    if to_rev <= 0:
        return data

    for entry in all_deltas:
        if entry.get("rev", 0) > to_rev:
            break
        delta_obj = entry.get("delta") or {}
        if delta_obj:
            data = _apply_delta(data, delta_obj)

    return data


async def write_reconstructed_scene(
    scene: "Scene", to_rev: int, output_filename: str | None = None
) -> str:
    """
    Write a reconstructed scene at a specific revision to a file.

    Reconstructs the scene data at the target revision and writes it to
    a JSON file in the scene's save directory.

    Args:
        scene: The scene object to reconstruct and write
        to_rev: The revision number to reconstruct
        output_filename: Custom filename, or None to auto-generate

    Returns:
        str: Path to the written file
    """
    reconstructed = await reconstruct_scene_data(scene, to_rev=to_rev)
    base_name = os.path.splitext(scene.filename)[0]
    out_name = output_filename or f"{base_name}-rev-{to_rev}.json"
    out_path = os.path.join(scene.save_dir, out_name)
    with open(out_path, "w") as f:
        json.dump(reconstructed, f, indent=2, cls=SceneEncoder)
    log.debug("write_reconstructed_scene", path=out_path, rev=to_rev)
    return out_path


def list_revisions(scene: "Scene") -> list[int]:
    """
    Get a list of all available revision numbers for a scene.

    Args:
        scene: The scene object to list revisions for

    Returns:
        list[int]: List of revision numbers in the order they appear in the changelog
    """
    log_data = _ensure_log_initialized(scene)
    return [d.get("rev", 0) for d in log_data.get("deltas", [])]


async def rollback_scene_to_revision(
    scene: "Scene", to_rev: int, create_backup: bool = True
) -> str:
    """
    Roll back a scene to a previous revision, optionally creating a backup.

    Reconstructs the scene data at the target revision and overwrites the
    current scene file. Can optionally create a timestamped backup of the
    current scene file before rollback.

    Args:
        scene: The scene object to roll back
        to_rev: The revision number to roll back to
        create_backup: Whether to create a backup of the current scene file

    Returns:
        str: Path to the updated scene file

    Raises:
        ValueError: If the target revision is invalid (negative or beyond latest)
    """
    revisions = list_revisions(scene)
    latest_rev = max(revisions) if revisions else 0
    if to_rev < 0 or to_rev > latest_rev:
        raise ValueError(
            f"Invalid revision: {to_rev}. Latest available is {latest_rev}."
        )

    current_path = os.path.join(scene.save_dir, scene.filename)

    backup_path = None
    if create_backup and os.path.exists(current_path):
        os.makedirs(scene.backups_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base_name = os.path.splitext(scene.filename)[0]
        backup_name = f"{base_name}_pre_rollback_{ts}.json"
        backup_path = os.path.join(scene.backups_dir, backup_name)
        try:
            shutil.copy2(current_path, backup_path)
            log.debug("rollback_backup_created", backup_path=backup_path)
        except Exception as e:
            log.error("rollback_backup_failed", error=e, path=current_path)

    reconstructed = await reconstruct_scene_data(scene, to_rev=to_rev)
    with open(current_path, "w") as f:
        json.dump(reconstructed, f, indent=2, cls=SceneEncoder)
    log.info("rollback_applied", path=current_path, rev=to_rev, backup=backup_path)

    return current_path
