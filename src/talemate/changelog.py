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
import glob
# import re

from talemate.save import SceneEncoder

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


log = structlog.get_logger("talemate.changelog")

# Maximum file size before splitting to a new changelog file (in bytes)
MAX_CHANGELOG_FILE_SIZE = 500 * 1024  # 500KB

# Fields to exclude from delta computation (e.g., volatile session IDs)
# Supports both exact paths and regex patterns
EXCLUDE_FROM_DELTAS = [
    "root['memory_session_id']",
    "root['saved_memory_session_id']",
    "root['world_state']['characters']",
    "root['world_state']['items']",
    "root['world_state']['location']",
    "root['world_state']['reinforce']",
    "root['world_state']['pins']",
    "root['world_state']['character_name_mappings']",
    # TODO move these to agent modules
    "root['agent_state']['director']['cached_guidance']",
    "root['agent_state']['summarizer']['cached_analysis_conversation']",
    "root['agent_state']['summarizer']['cached_analysis_narration']",
    "root['agent_state']['summarizer']['scene_analysis']",
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


def _changelog_log_path(scene: "Scene", start_rev: int = 0):
    """
    Get the path to a changelog log file for a scene.

    Creates the changelog directory if it doesn't exist.

    Args:
        scene: The scene object
        start_rev: The starting revision number for this changelog file

    Returns:
        str: Path to the changelog log file
    """
    os.makedirs(scene.changelog_dir, exist_ok=True)
    return os.path.join(
        scene.changelog_dir, f"{scene.filename}.changelog.{start_rev}.json"
    )


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


def _utc_timestamp_now() -> int:
    """
    Get the current UTC timestamp in unix seconds.

    Returns:
        int: Current UTC timestamp as unix seconds (rounded)
    """
    return int(datetime.now(timezone.utc).timestamp())


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


def _get_changelog_files(scene: "Scene") -> list[tuple[int, str]]:
    """
    Get all changelog files for a scene, sorted by starting revision.

    Returns:
        list[tuple[int, str]]: List of (start_rev, file_path) tuples sorted by start_rev
    """
    pattern = os.path.join(scene.changelog_dir, f"{scene.filename}.changelog.*.json")
    files = glob.glob(pattern)
    result = []

    for file_path in files:
        basename = os.path.basename(file_path)
        # Extract start_rev from filename like "scene.json.changelog.123.json"
        parts = basename.split(".")
        if len(parts) >= 4 and parts[-1] == "json" and parts[-3] == "changelog":
            try:
                start_rev = int(parts[-2])
                result.append((start_rev, file_path))
            except ValueError:
                continue

    return sorted(result)


def _get_latest_changelog_file(scene: "Scene") -> tuple[int, str]:
    """
    Get the changelog file with the highest starting revision.

    Returns:
        tuple[int, str]: (start_rev, file_path) of the latest changelog file
    """
    files = _get_changelog_files(scene)
    if files:
        return files[-1]  # Last item has highest start_rev
    else:
        # No files exist, return first file
        return (0, _changelog_log_path(scene, 0))


def _ensure_log_initialized(scene: "Scene", start_rev: int = 0) -> dict:
    """
    Ensure a changelog log file exists and is properly initialized.

    Creates a new changelog log file with default structure if it doesn't exist,
    or loads and validates an existing one. Ensures the latest_rev field is
    correctly set to the maximum revision number found in deltas.

    Args:
        scene: The scene object
        start_rev: The starting revision for this changelog file

    Returns:
        dict: The changelog log data structure containing version, base, deltas, start_rev, and latest_rev
    """
    log_path = _changelog_log_path(scene, start_rev)
    base_filename = f"{scene.filename}.base.json"
    default_content = {
        "version": 1,
        "base": base_filename,
        "start_rev": start_rev,
        "deltas": [],
        "latest_rev": start_rev,
    }
    content = _read_json_or_default(log_path, default_content)
    content.setdefault("version", 1)
    content.setdefault("base", base_filename)
    content.setdefault("start_rev", start_rev)
    content.setdefault("deltas", [])
    try:
        max_rev = max(
            [d.get("rev", start_rev) for d in content.get("deltas", [])] or [start_rev]
        )
    except Exception:
        max_rev = start_rev
    content["latest_rev"] = max(content.get("latest_rev", start_rev), max_rev)
    if not os.path.exists(log_path):
        _write_json(log_path, content)
    return content


def _get_file_size(file_path: str) -> int:
    """
    Get the size of a file in bytes.

    Args:
        file_path: Path to the file

    Returns:
        int: File size in bytes, or 0 if file doesn't exist
    """
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0


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
        ignore_type_in_groups=[(type(None), str, int, float, bool, list, dict)],
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

    When a changelog file exceeds MAX_CHANGELOG_FILE_SIZE, a new file is created.

    Args:
        scene: The scene object to create a delta for
        meta: Optional metadata to store with this revision

    Returns:
        int | None: The new revision number if changes were found, None if unchanged
    """
    if not os.path.exists(_base_path(scene)):
        await save_changelog(scene)

    # Find the latest changelog file and get the overall latest revision
    latest_rev = _get_overall_latest_revision(scene)

    _ensure_latest_initialized(scene)
    prev_data = _load_latest_scene_data(scene)
    if prev_data is None:
        prev_data = await reconstruct_scene_data(scene, to_rev=latest_rev)

    curr_data = _serialize_scene_plain(scene)

    delta = _compute_delta(prev_data, curr_data)
    if not delta:
        return None

    new_rev = latest_rev + 1

    # Find the appropriate file to append to
    start_rev, log_path = _get_latest_changelog_file(scene)
    log_data = _ensure_log_initialized(scene, start_rev)

    # Check if current file would exceed size limit after adding this delta
    new_delta_entry = {
        "rev": new_rev,
        "ts": _utc_timestamp_now(),
        "delta": delta,
        "meta": meta or {},
    }

    # Estimate size of new entry (rough approximation)
    estimated_entry_size = len(json.dumps(new_delta_entry))
    current_file_size = _get_file_size(log_path)

    if (
        current_file_size > 0
        and (current_file_size + estimated_entry_size) > MAX_CHANGELOG_FILE_SIZE
    ):
        # Create a new changelog file starting with this revision
        start_rev = new_rev
        log_path = _changelog_log_path(scene, start_rev)
        log_data = _ensure_log_initialized(scene, start_rev)
        log.debug("changelog_file_split", new_file=log_path, start_rev=start_rev)

    # Append to the appropriate file
    deltas = log_data.get("deltas", [])
    deltas.append(new_delta_entry)
    log_data["deltas"] = deltas
    log_data["latest_rev"] = new_rev

    _write_json(log_path, log_data)
    log.debug("append_scene_delta", rev=new_rev, file=log_path)
    _write_json(_latest_path(scene), curr_data)
    return new_rev


def _get_overall_latest_revision(scene: "Scene") -> int:
    """
    Get the latest revision number across all changelog files.

    Returns:
        int: The highest revision number found, or 0 if no revisions exist
    """
    files = _get_changelog_files(scene)
    if not files:
        return 0

    latest_rev = 0
    for start_rev, file_path in files:
        log_data = _read_json_or_default(file_path, {})
        file_latest = log_data.get("latest_rev", start_rev)
        latest_rev = max(latest_rev, file_latest)

    return latest_rev


async def reconstruct_cleanup(data: dict) -> dict:
    """
    Cleanup the reconstructed scene data.
    """
    if data.get("shared_context"):
        # Disconnect from shared_context since we cannot reconstruct shared world context
        # to a specific revision, so the sane thing to do is disconnect the scene from it
        log.info(
            "Disconnecting reconstructed scene from shared_context",
            shared_context=data.get("shared_context"),
        )
        data["shared_context"] = ""
    return data


async def reconstruct_scene_data(scene: "Scene", to_rev: int | None = None) -> dict:
    """
    Reconstruct scene data at a specific revision by applying deltas.

    Starts from the base scene data (revision 0) and sequentially applies
    all deltas up to the target revision to reconstruct the scene state.
    Reads from all changelog files as needed.

    Args:
        scene: The scene object to reconstruct
        to_rev: Target revision number, or None for latest revision

    Returns:
        dict: The reconstructed scene data at the specified revision
    """
    if to_rev is None:
        to_rev = _get_overall_latest_revision(scene)

    data = _load_base_scene_data(scene)

    if to_rev <= 0:
        data = await reconstruct_cleanup(data)
        return data

    # Collect all deltas from all changelog files, up to target revision
    all_deltas = []
    files = _get_changelog_files(scene)

    for start_rev, file_path in files:
        if start_rev > to_rev:
            break  # Files are sorted by start_rev, so we can stop here

        log_data = _read_json_or_default(file_path, {})
        file_deltas = log_data.get("deltas", [])

        for entry in file_deltas:
            if entry.get("rev", 0) <= to_rev:
                all_deltas.append(entry)
            else:
                break  # Deltas should be in order within a file

    # Sort deltas by revision number to ensure correct application order
    all_deltas.sort(key=lambda x: x.get("rev", 0))

    # Apply deltas in order
    for entry in all_deltas:
        delta_obj = entry.get("delta") or {}
        if delta_obj:
            data = _apply_delta(data, delta_obj)

    data = await reconstruct_cleanup(data)

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

    Searches all changelog files to collect revision numbers.

    Args:
        scene: The scene object to list revisions for

    Returns:
        list[int]: List of revision numbers sorted in ascending order
    """
    all_revisions = []
    files = _get_changelog_files(scene)

    for _, file_path in files:
        log_data = _read_json_or_default(file_path, {})
        file_revisions = [d.get("rev", 0) for d in log_data.get("deltas", [])]
        all_revisions.extend(file_revisions)

    return sorted(all_revisions, reverse=True)


def list_revision_entries(scene: "Scene") -> list[dict]:
    """
    Get a list of revision entries with timestamps.

    Returns:
        list[dict]: [{"rev": int, "ts": int} ...] sorted by rev ascending
    """
    entries: list[dict] = []
    files = _get_changelog_files(scene)
    for _, file_path in files:
        log_data = _read_json_or_default(file_path, {})
        for entry in log_data.get("deltas", []):
            rev = entry.get("rev")
            ts = entry.get("ts")
            if isinstance(rev, int) and isinstance(ts, int):
                entries.append({"rev": rev, "ts": ts})
    return sorted(entries, key=lambda x: x["rev"], reverse=True)


def latest_revision_at(scene: "Scene", at_ts: int) -> int | None:
    """
    Return the greatest revision whose timestamp is <= at_ts.

    Args:
        at_ts: UTC unix seconds

    Returns:
        int | None: revision number or None if none exist
    """
    entries = list_revision_entries(scene)
    best_rev = None
    for e in entries:
        if e["ts"] <= at_ts:
            best_rev = e["rev"]
        else:
            break
    return best_rev


def delete_changelog_files(scene: "Scene") -> dict:
    """
    Delete all changelog artifacts for a scene: base, latest, and segmented changelog files.

    Args:
        scene: Scene object (only `filename` and `changelog_dir` are required)

    Returns:
        dict: {
            "deleted": list[str],  # file paths deleted
            "dir_removed": str | None,  # changelog dir path if removed, else None
        }
    """
    deleted: list[str] = []

    try:
        # Collect files to delete
        files = []
        base_path = _base_path(scene)
        latest_path = _latest_path(scene)
        files.append(base_path)
        files.append(latest_path)
        files.extend([fp for _, fp in _get_changelog_files(scene)])

        # Delete files if they exist
        for fpath in set(files):
            try:
                if os.path.exists(fpath) and os.path.isfile(fpath):
                    os.remove(fpath)
                    deleted.append(fpath)
                    log.debug("deleted_changelog_file", path=fpath)
            except FileNotFoundError:
                pass
            except Exception as e:
                log.warning("failed_delete_changelog_file", path=fpath, error=e)

        # Attempt to remove the directory if empty
        dir_removed: str | None = None
        try:
            if os.path.isdir(scene.changelog_dir) and not os.listdir(
                scene.changelog_dir
            ):
                os.rmdir(scene.changelog_dir)
                dir_removed = scene.changelog_dir
                log.debug("removed_empty_changelog_dir", path=dir_removed)
        except OSError:
            dir_removed = None

        return {"deleted": deleted, "dir_removed": dir_removed}
    except Exception as e:
        log.warning("delete_changelog_files_failed", error=e)
        return {"deleted": deleted, "dir_removed": None}


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


class InMemoryChangelog:
    """
    In-memory changelog context manager that accumulates deltas and commits them on demand.

    This allows maintaining deltas during scene loop turns without writing to disk,
    and only committing during save operations.

    Usage:
        async with InMemoryChangelog(scene) as changelog:
            # Make changes to scene
            await changelog.append_delta({"action": "character_added"})
            # More changes...
            await changelog.append_delta({"action": "dialogue_added"})
            # Deltas are automatically committed on exit
    """

    def __init__(self, scene: "Scene"):
        self.scene = scene
        self.pending_deltas: list[dict] = []
        self.last_state: dict | None = None
        self.committed = False

    async def __aenter__(self):
        """Initialize the in-memory changelog context."""
        # Store the current state as our baseline
        self.last_state = _serialize_scene_plain(self.scene)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def append_delta(self, meta: dict | None = None) -> int | None:
        """
        Append a delta for the current scene state to the in-memory list.

        Args:
            meta: Optional metadata to store with this revision

        Returns:
            int | None: The actual revision number this delta will have when committed, None if unchanged
        """
        curr_data = _serialize_scene_plain(self.scene)
        delta = _compute_delta(self.last_state, curr_data)

        if not delta:
            return None

        # Calculate the real revision number this delta will have when committed
        # Use scene.rev as baseline (no file I/O needed)
        next_real_rev = self.scene.rev + len(self.pending_deltas) + 1

        # Store the actual revision number that will be used when committing
        delta_entry = {
            "rev": next_real_rev,
            "ts": _utc_timestamp_now(),
            "delta": delta,
            "meta": meta or {},
        }

        self.pending_deltas.append(delta_entry)
        self.last_state = curr_data  # Update baseline for next delta

        log.debug(
            "append_in_memory_delta",
            next_real_rev=next_real_rev,
            total_pending=len(self.pending_deltas),
        )
        return next_real_rev

    async def commit(self) -> list[int]:
        """
        Commit all pending deltas to the persistent changelog files.
        After committing, the changelog can continue to accumulate new deltas.

        Returns:
            list[int]: List of committed revision numbers
        """
        if not self.pending_deltas:
            return []

        # Ensure base changelog is initialized
        if not os.path.exists(_base_path(self.scene)):
            await save_changelog(self.scene)

        committed_revs = []

        # Write each delta directly to the changelog files
        # Use the revision numbers that were already calculated and stored
        for entry in self.pending_deltas:
            # Delta entry already has the correct revision number
            real_delta_entry = entry

            # Find the appropriate changelog file to append to
            start_rev, log_path = _get_latest_changelog_file(self.scene)
            log_data = _ensure_log_initialized(self.scene, start_rev)

            # Check if we need to create a new file due to size limits
            log.debug("commit_in_memory_deltas", real_delta_entry=real_delta_entry)
            estimated_size = len(json.dumps(real_delta_entry))
            current_size = _get_file_size(log_path)

            entry_rev = real_delta_entry["rev"]
            if (
                current_size > 0
                and (current_size + estimated_size) > MAX_CHANGELOG_FILE_SIZE
            ):
                # Create a new changelog file starting with this revision
                start_rev = entry_rev
                log_path = _changelog_log_path(self.scene, start_rev)
                log_data = _ensure_log_initialized(self.scene, start_rev)
                log.debug(
                    "changelog_file_split", new_file=log_path, start_rev=start_rev
                )

            # Append the delta to the file
            log_data["deltas"].append(real_delta_entry)
            log_data["latest_rev"] = entry_rev

            # Write the updated log data
            _write_json(log_path, log_data)

            committed_revs.append(entry_rev)
            log.debug("committed_in_memory_delta", rev=entry_rev)

        # Update the latest snapshot file with the final scene state
        _write_json(_latest_path(self.scene), self.last_state)

        # Clear pending deltas but don't mark as committed so we can continue accumulating
        self.pending_deltas.clear()

        # Update scene.rev to the highest committed revision
        if committed_revs:
            self.scene.rev = max(committed_revs)

        log.debug("commit_in_memory_deltas", committed_revs=committed_revs)
        return committed_revs

    @property
    def has_pending_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        return bool(self.pending_deltas) and not self.committed

    @property
    def pending_count(self) -> int:
        """Get the number of pending deltas."""
        return len(self.pending_deltas)

    @property
    def next_revision(self) -> int:
        """Get the revision number that the next delta will have when committed."""
        return self.scene.rev + len(self.pending_deltas) + 1
