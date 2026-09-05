"""
Scene Changelog System

This module implements a comprehensive changelog system for TaleMate scenes that tracks
all changes over time using delta compression. It provides functionality to:

- Store incremental changes (deltas) between scene revisions
- Reconstruct any previous scene state by applying deltas
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

# Stage and commit changes when a scene is modified
async with InMemoryChangelog(scene) as changelog:
    rev = await changelog.append_delta({"action": "character_added"})
    await changelog.commit()

# Reconstruct scene at specific revision
scene_data = await reconstruct_scene_data(scene, to_rev=5)
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

from typing import TYPE_CHECKING, Callable
import copy
import json
import os
import structlog
import deepdiff
from deepdiff.path import parse_path
from datetime import datetime, timezone
import glob
import uuid

from talemate.save import SceneEncoder
from talemate.scene.format import (
    SceneFormatError,
    normalize_scene_format,
    read_scene_format,
)
from talemate.knowledge.mode import require_character_knowledge_support
from talemate.path import SCENES_DIR
from talemate.util.data import coerce_forced_list
from talemate.util.time import migrate_scene_time
from talemate.util.path import is_safe_relative_filename
from pathlib import Path

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


log = structlog.get_logger("talemate.changelog")

# Maximum file size before splitting to a new changelog file (in bytes)
MAX_CHANGELOG_FILE_SIZE = 1000 * 1024  # 1MB

# Fields to exclude from delta computation (e.g., volatile session IDs)
# Supports both exact paths and regex patterns
EXCLUDE_FROM_DELTAS = [
    "root['memory_session_id']",
    "root['saved_memory_session_id']",
    "root['world_state']['characters']",
    "root['world_state']['items']",
    "root['world_state']['location']",
    # TODO move these to agent modules
    "root['agent_state']['director']['cached_guidance']",
    "root['agent_state']['summarizer']['cached_analysis_conversation']",
    "root['agent_state']['summarizer']['cached_analysis_narration']",
    "root['agent_state']['summarizer']['scene_analysis']",
]

# User-authored world-state subtrees that deltas track now but that chains
# written before then never recorded. Deltas carry these as full-subtree
# ops, all three together whenever any one changes (see
# _full_subtree_world_state_ops), so replay never depends on the base
# snapshot's values for them, and check_chain_divergence masks them only
# on chains whose deltas never record them.
LEGACY_UNTRACKED_WORLD_STATE = [
    "root['world_state']['reinforce']",
    "root['world_state']['pins']",
    "root['world_state']['character_name_mappings']",
]

# Marker key naming the paths _full_list_opcode_ops rewrote, so replay can
# verify their old_value (see _check_reordered_lists_appliable). deepdiff
# reads a delta dict by its own known keys, so the extra key is ignored on
# apply and needs no stripping.
REORDERED_LISTS_KEY = "_reordered_lists"

# Agent-derived world-state subtrees excluded from deltas above. They are
# refreshed by the world-state agent's analysis cycles, so reconstruction
# overlays them from the latest snapshot: a fork gets the current derived
# state instead of the base snapshot's. Derived from
# EXCLUDE_FROM_DELTAS so the two cannot drift apart.
OVERLAY_FROM_LATEST = tuple(
    path.removeprefix("root['world_state']['").removesuffix("']")
    for path in EXCLUDE_FROM_DELTAS
    if path.startswith("root['world_state']")
)

# Regex patterns for wildcard exclusions (e.g., array indices)

EXCLUDE_FROM_DELTAS_REGEX = [
    # Add regex patterns as needed:
    # re.compile(r"root\['some_array'\]\[\d+\]\['volatile_field'\]"),
]

# Scene-data fields that must always be lists. Delta application with
# force=True can leave an int-keyed dict in their place when an iterable op
# targets a path whose parent is missing (baseline divergence) — deepdiff
# creates ``{index: item}`` instead of a list.
_LIST_FIELDS = (
    "history",
    "archived_history",
    "layered_history",
    "active_characters",
    "game_state_watch_paths",
    "game_state_knob_paths",
)

# Cache for check_chain_divergence verdicts, keyed by (changelog_dir,
# filename) with a stat fingerprint of the changelog artifacts. Bounded:
# the check also runs on unloaded scenes from the load screen, so a
# long-running server could otherwise accumulate entries indefinitely.
_DIVERGENCE_CHECK_CACHE_MAX = 128
_DIVERGENCE_CHECK_CACHE: dict[tuple[str, str], tuple[tuple, list[str] | None]] = {}


# Helper minimal scene reference compatible with this module's helpers
class _SceneRef:
    def __init__(self, filename: str, save_dir: str, data: dict):
        self.filename = filename
        self.save_dir = save_dir
        self.changelog_dir = os.path.join(save_dir, "changelog")
        self.serialize = data


def scene_ref_from_path(scene_path: str) -> _SceneRef:
    """
    Build a minimal scene reference for changelog operations on a scene that
    is not currently loaded, from the path to its scene file.
    """
    return _SceneRef(
        filename=os.path.basename(scene_path),
        save_dir=os.path.dirname(scene_path),
        data={},
    )


async def save_changelog(scene: "Scene"):
    """
    Initialize the changelog system for a scene by creating base and latest snapshot files.

    This function sets up the initial changelog structure by creating:
    - A base snapshot file (rev0) containing the current scene state
    - A latest snapshot file for optimization purposes

    Only creates files if the base snapshot doesn't already exist.

    If an InMemoryChangelog context is active, uses the state from before pending changes
    to avoid duplication when those changes are later committed as deltas.

    Args:
        scene: The scene object to initialize changelog for

    Returns:
        None
    """
    base_file = f"{scene.filename}.base.json"
    base_path = os.path.join(scene.changelog_dir, base_file)

    # Check if there's an active InMemoryChangelog with pending changes
    # If so, use the initial state from before those changes to avoid duplication
    serialized_scene = scene.serialize
    changelog = getattr(scene, "_changelog", None)
    if changelog and changelog.initial_state:
        serialized_scene = changelog.initial_state.copy()
        log.debug(
            "Using InMemoryChangelog.initial_state for base snapshot to avoid duplication",
            pending_deltas=changelog.pending_count,
        )

    if not os.path.exists(base_path):
        os.makedirs(scene.changelog_dir, exist_ok=True)
        try:
            log.debug(
                "Changelog initialized",
                scene=str(
                    Path(scene.save_dir).relative_to(SCENES_DIR) / Path(scene.filename)
                ),
            )
        except ValueError:
            pass
        _write_json(base_path, serialized_scene, cls=SceneEncoder)
        # initialize latest snapshot to base
        _write_json(_latest_path(scene), serialized_scene, cls=SceneEncoder)
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


class ChangelogCorruptedError(Exception):
    """A changelog artifact exists on disk but cannot be parsed."""


def _read_changelog_log_strict(path: str) -> dict | None:
    """Read a changelog log file.

    Returns None when the file does not exist. Raises
    ChangelogCorruptedError when it exists but cannot be parsed or does not
    have the changelog log shape — treating a corrupted log as empty would
    silently drop every delta it holds.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            content = json.load(f)
    except Exception as e:
        raise ChangelogCorruptedError(f"Unreadable changelog file: {path}: {e}") from e
    if (
        not isinstance(content, dict)
        or not isinstance(content.get("deltas"), list)
        or ("latest_rev" in content and not isinstance(content["latest_rev"], int))
    ):
        raise ChangelogCorruptedError(
            f"Malformed changelog file: {path}: not a changelog log structure"
        )
    return content


def _write_json(path: str, data: dict, cls=None):
    """
    Write JSON data to file, creating parent directories as needed.

    Writes to a temporary file and atomically renames it into place, so a
    crash mid-write can never leave a truncated JSON document behind.

    Args:
        path: Path to write the JSON file
        data: Dictionary data to write as JSON
        cls: Optional JSON encoder class (e.g. SceneEncoder)

    Returns:
        None

    Raises:
        Exception: any failure to serialize or write the file
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, cls=cls)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


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
    content = _read_changelog_log_strict(log_path)
    if content is None:
        content = default_content
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
        ChangelogCorruptedError: If the base snapshot file contains invalid JSON
    """
    base_path = _base_path(scene)
    try:
        with open(base_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ChangelogCorruptedError(
            f"Unreadable changelog file: {base_path}: {e}"
        ) from e


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
            data = json.load(f)
        # The snapshot is the baseline every new delta is diffed against. A
        # pre-migration snapshot still holds ISO8601 durations, which would
        # make every scene time field diff against the live (integer)
        # serialization. Migrated in memory only - the file itself is left as
        # written.
        return migrate_scene_time(data, tolerant=True)
    except Exception as e:
        log.error("read_latest_failed", error=e, path=path)
        return None


async def _ensure_latest_initialized(scene: "Scene") -> None:
    """
    Ensure the latest snapshot file exists, creating it if needed.

    With changelog segments present, the snapshot is healed from the
    reconstructed chain tip — initializing it from the base would make the
    next append diff against the base, and the resulting catch-up delta
    double-applies list operations on replay (force-mode application writes
    unconditionally). Without segments, the base is the only state there is.

    Args:
        scene: The scene object

    Returns:
        None
    """
    latest = _latest_path(scene)
    if os.path.exists(latest):
        return
    if _get_changelog_files(scene):
        data = await reconstruct_scene_data(scene)
    else:
        data = _load_base_scene_data(scene)
    _write_json(latest, data)


def _parse_delta_path(path: str) -> list[str | int]:
    """Parse a deepdiff path like ``root['a'][3]['b']`` into ``['a', 3, 'b']``.

    Delegates to deepdiff's own parser, which also handles the double-quoted
    form deepdiff emits for keys containing an apostrophe.

    Returns an empty list for unrecognized formats so callers can short-circuit.
    """
    if not isinstance(path, str) or not path.startswith("root"):
        return []
    try:
        return parse_path(path)
    except Exception:
        return []


def _path_parent_exists(data: dict, path: str) -> bool:
    """Return True if the parent of ``path`` exists in ``data``."""
    parts = _parse_delta_path(path)
    if len(parts) <= 1:
        return True
    obj = data
    for key in parts[:-1]:
        if isinstance(obj, list):
            if not isinstance(key, int) or key < 0 or key >= len(obj):
                return False
            obj = obj[key]
        elif isinstance(obj, dict):
            if key not in obj:
                return False
            obj = obj[key]
        else:
            return False
    return True


def _warn_on_orphan_delta_ops(prev: dict, delta_dict: dict) -> None:
    """Log a warning when a delta op targets a path whose parent doesn't exist in ``prev``."""
    for op_name in ("dictionary_item_added", "values_changed"):
        ops = delta_dict.get(op_name) or {}
        for path in ops:
            if not _path_parent_exists(prev, path):
                log.warning(
                    "delta_op_targets_missing_parent",
                    op=op_name,
                    path=path,
                )


def _resolve_delta_parent(data: dict, path: str) -> tuple:
    """Resolve a delta path's parent container and final key in ``data``.

    Raises ChangelogDivergedError when any segment of the path does not
    exist — the delta was computed against a state this reconstruction no
    longer matches.
    """
    parts = _parse_delta_path(path)
    if not parts:
        raise ChangelogDivergedError(f"unparseable delta path: {path!r}")
    obj = data
    for key in parts[:-1]:
        if isinstance(obj, list) and isinstance(key, int) and 0 <= key < len(obj):
            obj = obj[key]
        elif isinstance(obj, dict) and key in obj:
            obj = obj[key]
        else:
            raise ChangelogDivergedError(f"{path}: {key!r} does not exist")
    return obj, parts[-1]


def _resolve_delta_value(data: dict, path: str):
    """Resolve the value a delta path points at, or None if it does not exist."""
    parts = _parse_delta_path(path)
    if not parts:
        return None
    obj = data
    for key in parts:
        if isinstance(obj, list) and isinstance(key, int) and 0 <= key < len(obj):
            obj = obj[key]
        elif isinstance(obj, dict) and key in obj:
            obj = obj[key]
        else:
            return None
    return obj


def _check_iterable_ops_appliable(data: dict, delta_obj: dict) -> None:
    """Raise ChangelogDivergedError on iterable ops ``data`` cannot take.

    deepdiff verifies a removal's stored value against the list and silently
    skips (or relocates to a nearby matching element) on mismatch even with
    raise_errors=True, so iterable strictness is checked here rather than
    delegated. Ops are checked in deepdiff's own application order (removals
    by descending index, then additions by ascending index), simulating each
    affected list so multi-op deltas see the shifted indexes.
    """
    removed = delta_obj.get("iterable_item_removed") or {}
    added = delta_obj.get("iterable_item_added") or {}
    moved = delta_obj.get("iterable_item_moved") or {}
    if not removed and not added and not moved:
        return

    def _index(path: str) -> int:
        parts = _parse_delta_path(path)
        if not parts or not isinstance(parts[-1], int):
            raise ChangelogDivergedError(f"unparseable iterable op path: {path!r}")
        return parts[-1]

    simulated: dict[str, list] = {}

    def _simulated_list(path: str) -> list:
        parent_key = path[: path.rfind("[")]
        if parent_key not in simulated:
            parent, _ = _resolve_delta_parent(data, path)
            if not isinstance(parent, list):
                raise ChangelogDivergedError(f"{path}: parent is not a list")
            simulated[parent_key] = list(parent)
        return simulated[parent_key]

    # deepdiff replays a move as a removal at the old path plus an insertion
    # at the new one, so both sides join the same checks
    removed_items = list(removed.items()) + [
        (path, (moved_op or {}).get("value")) for path, moved_op in moved.items()
    ]
    added_paths = list(added) + [
        (moved_op or {}).get("new_path") for moved_op in moved.values()
    ]

    for path, expected in sorted(
        removed_items, key=lambda kv: _index(kv[0]), reverse=True
    ):
        sim = _simulated_list(path)
        key = _index(path)
        if key < 0 or key >= len(sim):
            raise ChangelogDivergedError(f"{path}: no such list item")
        if sim[key] != expected:
            raise ChangelogDivergedError(
                f"{path}: stored value does not match the reconstruction"
            )
        del sim[key]

    for path in sorted(added_paths, key=_index):
        sim = _simulated_list(path)
        key = _index(path)
        if key < 0 or key > len(sim):
            raise ChangelogDivergedError(f"{path}: index out of range")
        sim.insert(key, None)


def _check_reordered_lists_appliable(data: dict, delta_obj: dict) -> None:
    """Raise ChangelogDivergedError on a rewritten reorder whose recorded
    ``old_value`` is not what the reconstruction holds.

    deepdiff applies ``values_changed`` blind — it never compares
    ``old_value``, even with raise_errors=True — so a full-list op would
    overwrite an already diverged list with the recorded post-state and hide
    the loss from the divergence check. Only the ops _full_list_opcode_ops
    marked are verified: full-subtree world-state ops deliberately carry an
    ``old_value`` that predates the base snapshot. A marked path whose op is
    gone (rewritten by _full_subtree_world_state_ops) has nothing to check.
    """
    changed = delta_obj.get("values_changed") or {}
    for path in delta_obj.get(REORDERED_LISTS_KEY) or []:
        op = changed.get(path)
        if not isinstance(op, dict):
            continue
        if _resolve_delta_value(data, path) != op.get("old_value"):
            raise ChangelogDivergedError(
                f"{path}: stored list does not match the reconstruction"
            )


def _apply_delta(data: dict, delta_obj: dict) -> dict:
    """
    Apply a delta (set of changes) to scene data.

    Replays strictly: an op the reconstructed state cannot take (missing
    parent, out-of-range or value-mismatched list op) means the chain has
    diverged from the state the delta was computed against, and raises
    ChangelogDivergedError instead of silently dropping the op or
    fabricating a stub. Recovery is a rebase (rebase_changelog_chain).

    Args:
        data: The base scene data to apply the delta to
        delta_obj: The delta dictionary containing the changes

    Returns:
        dict: The scene data with the delta applied

    Raises:
        ChangelogDivergedError: If the delta cannot be applied strictly
    """
    _check_iterable_ops_appliable(data, delta_obj)
    _check_reordered_lists_appliable(data, delta_obj)
    try:
        return data + deepdiff.Delta(delta_obj, raise_errors=True)
    except Exception as e:
        log.error("apply_delta_failed", error=e)
        raise ChangelogDivergedError(
            f"delta does not apply to the reconstructed state: {e}"
        ) from e


def _full_list_opcode_ops(delta_dict: dict, prev: dict, curr: dict) -> None:
    """Replace ``_iterable_opcodes`` ops with full-list ``values_changed`` ops.

    deepdiff represents list reorders as opcode namedtuples, which do not
    survive the JSON round-trip the chain goes through on disk: the delta
    applies in memory but raises on replay. Rewriting the affected lists
    wholesale keeps the delta replayable in its serialized form. An op whose
    path cannot be resolved is dropped, leaving the delta unreproducible so
    the verification refuses it.

    The rewritten paths are recorded under REORDERED_LISTS_KEY: a full-list
    op replaces the list outright, so replay has to verify its ``old_value``
    against the reconstruction or a diverged list would be silently papered
    over (_check_reordered_lists_appliable).
    """
    opcodes = delta_dict.pop("_iterable_opcodes", None) or {}
    rewritten = []
    for path in opcodes:
        prev_list = _resolve_delta_value(prev, path)
        curr_list = _resolve_delta_value(curr, path)
        if not isinstance(prev_list, list) or not isinstance(curr_list, list):
            continue
        delta_dict.setdefault("values_changed", {})[path] = {
            "new_value": copy.deepcopy(curr_list),
            "old_value": copy.deepcopy(prev_list),
        }
        rewritten.append(path)
    if rewritten:
        delta_dict[REORDERED_LISTS_KEY] = rewritten


def _full_subtree_world_state_ops(delta_dict: dict, prev: dict, curr: dict) -> None:
    """Replace incremental ops under the LEGACY_UNTRACKED_WORLD_STATE
    subtrees with full-subtree ``values_changed`` ops.

    Chains written before these subtrees were tracked replay onto a base
    snapshot whose values predate any recording, so an increment computed
    against the latest snapshot silently drops everything the base never
    had. Full-subtree ops make the delta self-sufficient, and they are
    written for all three subtrees whenever any one of them changes: the
    first post-upgrade touch records the whole set, including drift that
    only ever lived in the latest snapshot — which keeps the divergence
    check's all-or-nothing unmask (_chain_records_world_state) correct.
    """
    curr_ws = curr.get("world_state")
    if not isinstance(curr_ws, dict):
        return
    touched = False
    for path in LEGACY_UNTRACKED_WORLD_STATE:
        for ops in delta_dict.values():
            if not isinstance(ops, dict):
                continue
            for op_path in [
                p for p in ops if isinstance(p, str) and p.startswith(path)
            ]:
                del ops[op_path]
                touched = True
    if not touched:
        return
    prev_ws = prev.get("world_state")
    for path in LEGACY_UNTRACKED_WORLD_STATE:
        key = _parse_delta_path(path)[-1]
        if key not in curr_ws:
            continue
        prev_value = prev_ws.get(key) if isinstance(prev_ws, dict) else None
        delta_dict.setdefault("values_changed", {})[path] = {
            "new_value": copy.deepcopy(curr_ws[key]),
            "old_value": copy.deepcopy(prev_value),
        }


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

    delta_dict = diff._to_delta_dict()
    _full_list_opcode_ops(delta_dict, prev, curr)
    _full_subtree_world_state_ops(delta_dict, prev, curr)
    _warn_on_orphan_delta_ops(prev, delta_dict)
    return delta_dict


def _delta_reproduces_state(prev: dict, curr: dict, delta_dict: dict) -> bool:
    """Return True if applying ``delta_dict`` to ``prev`` reproduces ``curr``.

    The comparison uses the same exclusions as delta computation, since
    excluded paths legitimately differ between the two states. A delta that
    fails this check would diverge the reconstruction chain if written.

    Applies strictly: the end-state comparison catches anything a lenient
    application would have skipped, and applying strictly additionally
    guarantees the delta replays under _apply_delta's strict rules.
    """
    try:
        # replay the serialized form, since that is what reconstruction reads
        # back from disk — some deepdiff representations only apply in memory
        applied = _apply_delta(prev, json.loads(json.dumps(delta_dict)))
    except Exception:
        return False
    return not deepdiff.DeepDiff(
        applied,
        curr,
        ignore_order=False,
        exclude_paths=EXCLUDE_FROM_DELTAS,
        exclude_regex_paths=EXCLUDE_FROM_DELTAS_REGEX,
        ignore_type_in_groups=[(type(None), str, int, float, bool, list, dict)],
    )


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


def _get_overall_latest_revision(scene: "Scene", strict: bool = True) -> int:
    """
    Get the latest revision number across all changelog files.

    Includes the quarantine marker's revision hint, so new revisions
    continue above a quarantined range instead of reusing its numbers.

    Args:
        scene: The scene object
        strict: When False, corrupted changelog files are skipped with an
                error log instead of raising — for callers like scene load,
                where the changelog is auxiliary to the scene file itself.

    Returns:
        int: The highest revision number found, or 0 if no revisions exist
    """
    files = _get_changelog_files(scene)
    marker = _read_quarantine_marker(scene)
    if not files:
        return (marker or {}).get("latest_rev_hint", 0)

    latest_rev = 0
    for start_rev, file_path in files:
        try:
            log_data = _read_changelog_log_strict(file_path) or {}
        except ChangelogCorruptedError:
            if strict:
                raise
            log.error(
                "skipping_corrupted_changelog_file",
                path=file_path,
                detail="revision numbers in this file are not counted",
            )
            continue
        file_latest = log_data.get("latest_rev", start_rev)
        latest_rev = max(latest_rev, file_latest)

    return max(latest_rev, (marker or {}).get("latest_rev_hint", 0))


def _repair_forced_list_fields(data: dict) -> int:
    """Restore list fields that force-mode delta application turned into
    int-keyed dicts (see ``_LIST_FIELDS``), including the nested layers of
    ``layered_history``.

    Returns the number of fields repaired.
    """
    repaired: list[str] = []

    for field in _LIST_FIELDS:
        converted, was_forced = coerce_forced_list(data.get(field))
        if was_forced:
            data[field] = converted
            repaired.append(field)

    layered = data.get("layered_history")
    if isinstance(layered, list):
        for i, layer in enumerate(layered):
            converted, was_forced = coerce_forced_list(layer)
            if was_forced:
                layered[i] = converted
                repaired.append(f"layered_history[{i}]")

    if repaired:
        log.warning("repaired_forced_list_fields", fields=repaired)

    return len(repaired)


def _repair_history(data: dict) -> int:
    """Backfill required SceneMessage fields on bare-fragment history entries.

    Returns the number of entries repaired. Indices are not shifted.
    """
    history = data.get("history")
    if not isinstance(history, list):
        return 0

    repaired_indices: list[int] = []
    for i, entry in enumerate(history):
        if not isinstance(entry, dict):
            continue
        if "message" in entry and "typ" in entry:
            continue
        entry.setdefault("message", "")
        entry.setdefault("typ", "narrator")
        entry.setdefault("source", "ai")
        entry.setdefault("flags", 0)
        repaired_indices.append(i)

    if repaired_indices:
        log.warning(
            "repaired_bare_history_entries",
            count=len(repaired_indices),
            indices=repaired_indices,
        )

    return len(repaired_indices)


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

    _repair_forced_list_fields(data)
    _repair_history(data)
    # Runs after the deltas have been applied: revisions written before the
    # scene time migration carry ISO8601 durations in both the base snapshot
    # and the deltas, so they have to reconstruct as-written and be converted
    # at the end.
    migrate_scene_time(data, tolerant=True)
    return data


def _overlay_derived_world_state(data: dict, latest: dict | None) -> None:
    """Overlay the derived world-state subtrees from the latest snapshot.

    The subtrees in OVERLAY_FROM_LATEST are excluded from deltas, so without
    this a reconstruction — at any revision — would carry the base
    snapshot's values. The latest snapshot's values are the freshest known
    and the ones a fork should start from.
    """
    world_state = data.get("world_state")
    latest_world_state = (latest or {}).get("world_state")
    if not isinstance(world_state, dict) or not isinstance(latest_world_state, dict):
        return
    for key in OVERLAY_FROM_LATEST:
        if key in latest_world_state:
            world_state[key] = copy.deepcopy(latest_world_state[key])


async def reconstruct_scene_data(scene: "Scene", to_rev: int | None = None) -> dict:
    """
    Reconstruct scene data at a specific revision by applying deltas.

    Starts from the base scene data (revision 0) and sequentially applies
    all deltas up to the target revision to reconstruct the scene state.
    Reads from all changelog files as needed. The derived world-state
    subtrees (OVERLAY_FROM_LATEST) are taken from the latest snapshot.

    Args:
        scene: The scene object to reconstruct
        to_rev: Target revision number, or None for latest revision

    Returns:
        dict: The reconstructed scene data at the specified revision
    """
    if to_rev is None:
        to_rev = _get_overall_latest_revision(scene)

    data = _load_base_scene_data(scene)
    latest_data = _load_latest_scene_data(scene)

    if to_rev <= 0:
        _overlay_derived_world_state(data, latest_data)
        data = await reconstruct_cleanup(data)
        return data

    # Collect all deltas from all changelog files, up to target revision
    all_deltas = []
    files = _get_changelog_files(scene)

    for start_rev, file_path in files:
        if start_rev > to_rev:
            break  # Files are sorted by start_rev, so we can stop here

        log_data = _read_changelog_log_strict(file_path) or {}
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
            try:
                data = _apply_delta(data, delta_obj)
            except ChangelogDivergedError as e:
                raise ChangelogDivergedError(f"rev {entry.get('rev')}: {e}") from e

    _overlay_derived_world_state(data, latest_data)
    data = await reconstruct_cleanup(data)

    return data


async def write_reconstructed_scene(
    scene: "Scene",
    to_rev: int,
    output_filename: str | None = None,
    overrides: dict | None = None,
    precomputed_data: dict | None = None,
    zero_message_revs: bool = False,
) -> str:
    """
    Write a reconstructed scene at a specific revision to a file.

    Reconstructs the scene data at the target revision and writes it to
    a JSON file in the scene's save directory.

    Args:
        scene: The scene object to reconstruct and write
        to_rev: The revision number to reconstruct
        output_filename: Custom filename, or None to auto-generate
        overrides: Optional overrides to apply to the reconstructed scene
        precomputed_data: Already-reconstructed scene data; skips the
            reconstruction entirely (to_rev then only names the output file)
        zero_message_revs: Zero all history message revs in the written file —
            for outputs that become a new scene with its own chain, where the
            source chain's revs are meaningless

    Returns:
        str: Path to the written file
    """
    reconstructed = (
        precomputed_data
        if precomputed_data is not None
        else await reconstruct_scene_data(scene, to_rev=to_rev)
    )

    metadata = read_scene_format(reconstructed)
    require_character_knowledge_support(metadata)
    if overrides and {"format_version", "knowledge_eligibility"}.intersection(
        overrides
    ):
        raise SceneFormatError(
            "Reconstruction overrides cannot change scene format metadata."
        )
    reconstructed = normalize_scene_format(reconstructed)

    if zero_message_revs:
        for entry in reconstructed.get("history", []):
            entry["rev"] = 0

    if overrides:
        reconstructed.update(overrides)

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
        log_data = _read_changelog_log_strict(file_path) or {}
        file_revisions = [d.get("rev", 0) for d in log_data.get("deltas", [])]
        all_revisions.extend(file_revisions)

    return sorted(all_revisions, reverse=True)


def list_revision_entries(scene: "Scene") -> list[dict]:
    """
    Get a list of revision entries with timestamps.

    Returns:
        list[dict]: [{"rev": int, "ts": int} ...] sorted by rev descending
    """
    entries: list[dict] = []
    files = _get_changelog_files(scene)
    for _, file_path in files:
        log_data = _read_changelog_log_strict(file_path) or {}
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
    # `list_revision_entries` returns entries sorted DESC by rev. Walk from
    # highest rev downward and return the first whose ts is <= at_ts. Don't
    # break on a ts > at_ts: with monotonic ts↔rev ordering it will never
    # appear before a match, but with non-monotonic data we still want to
    # find any older rev that does qualify.
    for e in list_revision_entries(scene):
        if e["ts"] <= at_ts:
            return e["rev"]
    return None


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
        files.append(_quarantine_marker_path(scene))
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


def _changelog_fingerprint(scene: "Scene") -> tuple:
    """Stat fingerprint of all changelog artifacts, for cache invalidation."""
    paths = [_base_path(scene), _latest_path(scene)]
    paths.extend(fp for _, fp in _get_changelog_files(scene))
    fingerprint = []
    for path in paths:
        try:
            st = os.stat(path)
            fingerprint.append((path, st.st_mtime_ns, st.st_size))
        except OSError:
            fingerprint.append((path, None, None))
    return tuple(fingerprint)


def _diff_paths(diff) -> list[str]:
    paths: set[str] = set()
    for val in diff.values():
        if isinstance(val, dict):
            paths.update(str(p) for p in val.keys())
        else:
            paths.update(str(p) for p in val)
    return sorted(paths)


def _chain_records_world_state(scene: "Scene") -> bool:
    """Whether any delta in the chain touches the LEGACY_UNTRACKED_WORLD_STATE subtrees."""
    for _, file_path in _get_changelog_files(scene):
        log_data = _read_changelog_log_strict(file_path) or {}
        for entry in log_data.get("deltas", []):
            for ops in (entry.get("delta") or {}).values():
                if not isinstance(ops, dict):
                    continue
                if any(
                    isinstance(p, str)
                    and p.startswith(tuple(LEGACY_UNTRACKED_WORLD_STATE))
                    for p in ops
                ):
                    return True
    return False


async def check_chain_divergence(scene: "Scene") -> list[str] | None:
    """
    Verify the delta chain by reconstructing the latest revision and
    comparing it against the latest snapshot.

    Paths in EXCLUDE_FROM_DELTAS diverge by design and are masked, as is
    ``shared_context`` (reconstruction deliberately disconnects it). The
    LEGACY_UNTRACKED_WORLD_STATE paths are masked only when no delta in the
    chain records them: such chains predate their tracking, so drift
    between the base snapshot and the latest snapshot there is expected.
    Once a delta records them (as a full-subtree op), reconstruction must
    reproduce the latest snapshot at those paths too.

    Results are cached against a stat fingerprint of the changelog files.

    Returns:
        None: no changelog data to check (treat as healthy)
        []: chain intact — reconstruction reproduces the latest snapshot
        list[str]: divergent deepdiff paths, or the strict replay failure —
            the chain has diverged

    Raises:
        ChangelogCorruptedError: the chain cannot be verified at all — the
            latest snapshot is missing or unreadable, or segments were
            quarantined (end-state comparison cannot prove a lost segment
            did not matter, since later deltas may rewrite the same paths)
    """
    if not os.path.exists(_base_path(scene)):
        return None

    marker = _read_quarantine_marker(scene)
    if marker is not None:
        log.debug("chain_unverifiable_quarantined", marker=marker)
        raise ChangelogCorruptedError("history segments were quarantined as corrupted")
    if _has_quarantined_segments(scene):
        raise ChangelogCorruptedError("history segments were quarantined as corrupted")

    latest_path = _latest_path(scene)
    if not os.path.exists(latest_path):
        raise ChangelogCorruptedError("the latest snapshot is missing")
    latest_data = _load_latest_scene_data(scene)
    if latest_data is None:
        raise ChangelogCorruptedError("the latest snapshot is unreadable")

    cache_key = (os.path.abspath(scene.changelog_dir), scene.filename)
    fingerprint = _changelog_fingerprint(scene)
    cached = _DIVERGENCE_CHECK_CACHE.get(cache_key)
    if cached and cached[0] == fingerprint:
        return cached[1]

    latest_rev = _get_overall_latest_revision(scene)
    try:
        reconstructed = await reconstruct_scene_data(scene, to_rev=latest_rev)
    except ChangelogDivergedError as e:
        # Strict replay failing mid-chain is divergence even when an
        # end-state comparison would have passed (later deltas may rewrite
        # the paths an earlier revision lost).
        divergent_paths = [str(e)]
        log.warning("changelog_chain_diverged", rev=latest_rev, detail=str(e))
        while len(_DIVERGENCE_CHECK_CACHE) >= _DIVERGENCE_CHECK_CACHE_MAX:
            _DIVERGENCE_CHECK_CACHE.pop(next(iter(_DIVERGENCE_CHECK_CACHE)))
        _DIVERGENCE_CHECK_CACHE[cache_key] = (fingerprint, divergent_paths)
        return divergent_paths

    exclude_paths = [*EXCLUDE_FROM_DELTAS, "root['shared_context']"]
    if not _chain_records_world_state(scene):
        exclude_paths += LEGACY_UNTRACKED_WORLD_STATE

    diff = deepdiff.DeepDiff(
        reconstructed,
        latest_data,
        ignore_order=False,
        exclude_paths=exclude_paths,
        exclude_regex_paths=EXCLUDE_FROM_DELTAS_REGEX,
        ignore_type_in_groups=[(type(None), str, int, float, bool, list, dict)],
    )
    divergent_paths = _diff_paths(diff) if diff else []

    if divergent_paths:
        log.warning(
            "changelog_chain_diverged",
            rev=latest_rev,
            paths=divergent_paths[:20],
            total=len(divergent_paths),
        )

    while len(_DIVERGENCE_CHECK_CACHE) >= _DIVERGENCE_CHECK_CACHE_MAX:
        _DIVERGENCE_CHECK_CACHE.pop(next(iter(_DIVERGENCE_CHECK_CACHE)))
    _DIVERGENCE_CHECK_CACHE[cache_key] = (fingerprint, divergent_paths)
    return divergent_paths


class ChangelogDivergedError(ValueError):
    """The delta chain no longer reconstructs its snapshots — an op failed
    strict replay, or the reconstructed tip no longer matches the latest
    snapshot."""


def _quarantine_marker_path(scene: "Scene") -> str:
    return os.path.join(scene.changelog_dir, f"{scene.filename}.quarantine.json")


def _read_quarantine_marker(scene: "Scene") -> dict | None:
    """Read the quarantine marker, failing closed.

    Returns None only when no marker file exists. An existing but
    unparseable (or non-dict) marker still means a quarantine happened —
    returns an empty dict so callers treat the chain as quarantined.
    """
    path = _quarantine_marker_path(scene)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            marker = json.load(f)
        return marker if isinstance(marker, dict) else {}
    except Exception:
        log.error("quarantine_marker_unreadable", path=path)
        return {}


def _has_quarantined_segments(scene: "Scene") -> bool:
    """Whether quarantined segment files are present in the changelog dir.

    Backstop for the marker: renames succeed where a marker write can fail
    (e.g. full disk), so the renamed files themselves are evidence.
    """
    return bool(
        glob.glob(
            os.path.join(
                scene.changelog_dir, f"{scene.filename}.changelog.*.json.corrupted"
            )
        )
    )


def quarantine_corrupted_changelog_files(scene: "Scene") -> list[str]:
    """Rename unreadable changelog artifacts aside (``<file>.corrupted``).

    Covers log segments and the latest snapshot (not the base: without it
    nothing is reconstructable, and every read already fails loudly).

    A corrupted artifact cannot be read, and left in place it makes every
    strict changelog read fail — including the one in the save path, so the
    scene loads but can never save again. Quarantining lets the chain
    continue. When segments were lost, a quarantine marker is written
    *before* anything is renamed: later deltas can rewrite the lost paths,
    so end-state comparison cannot prove the gap mattered —
    ``check_chain_divergence`` treats the marker's presence (or leftover
    quarantined segment files, if the marker write itself failed) as
    unverifiable, so previews and forks warn that they may be missing data
    for the life of the chain. The marker also carries a revision hint so new revisions
    continue above the lost range instead of colliding with it. Files are
    renamed, never deleted.

    Returns the list of quarantined paths (empty when nothing was corrupted).
    """
    # captured before anything is renamed: the highest revision still
    # readable, plus the start revs of the corrupted segments themselves
    pre_quarantine_hint = _get_overall_latest_revision(scene, strict=False)

    quarantined: list[str] = []
    corrupted_segments: list[tuple[int, str]] = []

    for start_rev, file_path in _get_changelog_files(scene):
        try:
            _read_changelog_log_strict(file_path)
        except ChangelogCorruptedError:
            corrupted_segments.append((start_rev, file_path))

    latest_path = _latest_path(scene)
    latest_corrupted = False
    if os.path.exists(latest_path):
        try:
            with open(latest_path) as f:
                json.load(f)
        except Exception:
            latest_corrupted = True

    if corrupted_segments:
        existing = _read_quarantine_marker(scene) or {}
        hint = max(
            pre_quarantine_hint,
            *[start_rev for start_rev, _ in corrupted_segments],
            existing.get("latest_rev_hint", 0),
        )
        marker_path = _quarantine_marker_path(scene)
        try:
            os.makedirs(scene.changelog_dir, exist_ok=True)
            with open(marker_path, "w") as f:
                json.dump(
                    {
                        "ts": _utc_timestamp_now(),
                        "quarantined": existing.get("quarantined", [])
                        + [f"{fp}.corrupted" for _, fp in corrupted_segments],
                        "latest_rev_hint": hint,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            # the renamed-aside segments are still detected via
            # _has_quarantined_segments, so the chain stays fail-closed
            log.error("quarantine_marker_write_failed", path=marker_path, error=e)

    def _quarantine(file_path: str):
        quarantine_path = f"{file_path}.corrupted"
        try:
            os.replace(file_path, quarantine_path)
        except OSError as e:
            log.error("changelog_quarantine_failed", path=file_path, error=e)
            return
        quarantined.append(quarantine_path)
        log.error(
            "changelog_file_quarantined", path=file_path, quarantined_to=quarantine_path
        )

    for _, file_path in corrupted_segments:
        _quarantine(file_path)
    if latest_corrupted:
        _quarantine(latest_path)

    return quarantined


class ForkTargetMissingError(ValueError):
    """The reconstructed history does not contain the fork target message."""


class ForkSaveNameError(ValueError):
    """A fork's save name cannot be used. The message is user-facing."""


def resolve_fork_save_name(scene: "Scene", save_name: str | None) -> str:
    """
    The name a fork may be written under, stripped of surrounding whitespace.

    Both fork entry points — the timeline and the fork button under a message —
    write ``<save_name>.json`` into the scene's save directory, so both resolve
    the name here: a fork must never write over an existing save or outside the
    save directory.

    Raises:
        ForkSaveNameError: the name is unusable, with the reason to show the user.
    """
    name = (save_name or "").strip()
    filename = f"{name}.json"

    if not name or not is_safe_relative_filename(filename, suffix=".json"):
        raise ForkSaveNameError(f"'{save_name}' is not a valid save name")

    if os.path.exists(os.path.join(scene.save_dir, filename)):
        raise ForkSaveNameError(
            f"A save named '{name}' already exists — pick a different name"
        )

    return name


def _rebase_marker_path(scene: "Scene") -> str:
    return os.path.join(scene.changelog_dir, f"{scene.filename}.rebase.json")


def read_rebase_marker(scene: "Scene") -> dict | None:
    """Read the rebase marker, if a rebase ever happened.

    The marker records each rebase so the timeline UI can explain why
    pre-rebase revisions are gone. Tolerant read: an unreadable marker
    reports as never-rebased rather than breaking the timeline.
    """
    path = _rebase_marker_path(scene)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            marker = json.load(f)
        return marker if isinstance(marker, dict) else None
    except Exception:
        log.error("rebase_marker_unreadable", path=path)
        return None


def _snapshot_changelog_flush(scene: "Scene") -> Callable[[], None]:
    """Capture the on-disk state a commit can touch, returning a restore callable.

    A commit can initialize the base, append to the current segment (or split
    off a new one), and rewrite the latest snapshot. The returned callable
    restores every touched file.

    Raises:
        Exception: an existing file could not be read — the transaction refuses
            before writing anything rather than promise a restore it cannot make
    """
    _, log_path = _get_latest_changelog_file(scene)
    segment_pattern = os.path.join(
        scene.changelog_dir, f"{scene.filename}.changelog.*.json"
    )
    contents: dict[str, bytes | None] = {}
    for path in (_base_path(scene), log_path, _latest_path(scene)):
        try:
            with open(path, "rb") as f:
                contents[path] = f.read()
        except FileNotFoundError:
            contents[path] = None
    existing = set(glob.glob(segment_pattern))

    def restore() -> None:
        errors: list[str] = []
        for path, data in contents.items():
            try:
                if data is None:
                    if os.path.exists(path):
                        os.remove(path)
                else:
                    try:
                        with open(path, "rb") as f:
                            if f.read() == data:
                                continue
                    except FileNotFoundError:
                        pass
                    tmp_path = f"{path}.rollback.tmp.{os.getpid()}.{uuid.uuid4().hex}"
                    try:
                        with open(tmp_path, "wb") as f:
                            f.write(data)
                        os.replace(tmp_path, path)
                    except Exception:
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        raise
            except Exception as e:
                log.error("changelog_flush_rollback_failed", path=path, error=e)
                errors.append(f"{path}: {e}")
        for path in set(glob.glob(segment_pattern)) - existing:
            try:
                os.remove(path)
            except Exception as e:
                log.error("changelog_flush_rollback_failed", path=path, error=e)
                errors.append(f"{path}: {e}")
        if errors:
            raise OSError("Changelog rollback failed: " + "; ".join(errors))

    return restore


async def rebase_changelog_chain(scene: "Scene") -> dict:
    """Rebase the changelog chain onto the latest snapshot.

    Recovery for a diverged (or unverifiable) chain: the current
    ``latest.json`` becomes the new base snapshot at revision 0 and the
    chain starts fresh — reconstruction from this point is exact again.
    The old chain (base, segments, latest snapshot, quarantine artifacts) is
    moved to ``changelog/rebased-<UTCts>/`` for forensics, and a rebase
    marker is written so the timeline can explain where pre-rebase history
    went. Pre-rebase history stays exactly as lossy as it was — it is
    preserved, not repaired.

    A live scene is carried onto the fresh chain too: once the chain is known
    repairable, staged deltas are committed to the old chain (so they are
    preserved with it rather than renumbered into the new namespace), and
    afterwards the scene's revision, its message rev stamps and its in-memory
    changelog baseline are reset to the rebased state.

    Fails atomically: any error leaves the chain exactly as it was — including
    a still-staged in-memory changelog — since a half-rebased chain (no base,
    but a latest snapshot) reads as a healthy empty history, and a flushed but
    unrebased chain would have swallowed work the scene never saved. A refusal
    writes nothing at all.

    Args:
        scene: The scene whose chain to rebase

    Returns:
        dict: {"rebased_from_rev": int, "preserved_to": str (dirname)}

    Raises:
        ValueError: no changelog to rebase, or the chain is healthy
        ChangelogCorruptedError: the latest snapshot is missing or
            unreadable — there is no sound state to rebase onto
        Exception: any filesystem failure, after the chain was restored
    """
    base_path = _base_path(scene)
    if not os.path.exists(base_path):
        raise ValueError("No changelog exists for this scene — nothing to rebase")

    # Eligibility is decided before anything is written: staged deltas are
    # not on disk yet, so they cannot change the verdict, and a refusal must
    # leave the chain (and the staged work) exactly as it found it.
    try:
        divergent = await check_chain_divergence(scene)
        eligible = bool(divergent)
    except ChangelogCorruptedError:
        # unverifiable (e.g. quarantined segments) is eligible too
        eligible = True
    if not eligible:
        raise ValueError("The history chain is healthy — nothing to repair")

    changelog = getattr(scene, "_changelog", None)
    rollback_flush: Callable[[], None] | None = None
    if changelog is not None and changelog.pending_deltas:
        # Staged deltas were computed against the chain that is about to be
        # archived: committing them keeps their per-delta meta with it and
        # makes the latest snapshot the freshest state to rebase onto.
        restore_files = _snapshot_changelog_flush(scene)
        staged_deltas = list(changelog.pending_deltas)
        staged_rev = scene.rev

        def _undo_flush() -> None:
            restore_files()
            changelog.pending_deltas[:] = staged_deltas
            scene.rev = staged_rev

        rollback_flush = _undo_flush
        try:
            await changelog.commit(emit_message_revs=False)
        except Exception:
            rollback_flush()
            raise

    try:
        return await _rebase_onto_latest(scene, changelog)
    except Exception:
        if rollback_flush is not None:
            rollback_flush()
        raise


async def _rebase_onto_latest(
    scene: "Scene", changelog: "InMemoryChangelog | None"
) -> dict:
    """Install the latest snapshot as a fresh chain, archiving the old one.

    The write half of rebase_changelog_chain: eligibility and any staged-delta
    flush are the caller's, so a failure here only has to restore the files
    this function touches (the caller undoes the flush around it).
    """
    base_path = _base_path(scene)
    latest_data = _load_latest_scene_data(scene)
    if latest_data is None:
        raise ChangelogCorruptedError(
            "the latest snapshot is missing or unreadable — "
            "there is no sound state to rebase onto"
        )

    old_latest_rev = _get_overall_latest_revision(scene, strict=False)

    # Message revs name revisions of the chain being archived, and rev 0
    # already means "in the base, forks shallowly". Base and latest are
    # normalized together: normalizing only one would make the fresh
    # chain's very first divergence check report the rev stamps as drift.
    rebased_data = copy.deepcopy(latest_data)
    for entry in rebased_data.get("history") or []:
        if isinstance(entry, dict):
            entry["rev"] = 0

    # stage the new snapshots before anything moves, so an unwritable
    # directory fails while the chain is still untouched
    latest_path = _latest_path(scene)
    staged_base = f"{base_path}.rebasing.{os.getpid()}"
    staged_latest = f"{latest_path}.rebasing.{os.getpid()}"
    _write_json(staged_base, rebased_data)
    _write_json(staged_latest, rebased_data)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    attempt = 1
    while True:
        suffix = "" if attempt == 1 else f"-{attempt}"
        preserved_dirname = f"rebased-{ts}{suffix}"
        preserved_dir = os.path.join(scene.changelog_dir, preserved_dirname)
        try:
            os.makedirs(preserved_dir)
            break
        except FileExistsError:
            attempt += 1

    patterns = [
        f"{scene.filename}.base.json",
        f"{scene.filename}.latest.json",
        f"{scene.filename}.changelog.*.json",
        f"{scene.filename}.changelog.*.json.corrupted",
        f"{scene.filename}.quarantine.json",
        f"{scene.filename}.latest.json.corrupted",
    ]
    moved: list[tuple[str, str]] = []
    installed: list[str] = []
    try:
        for pattern in patterns:
            for path in glob.glob(os.path.join(scene.changelog_dir, pattern)):
                dst = os.path.join(preserved_dir, os.path.basename(path))
                os.replace(path, dst)
                moved.append((path, dst))

        os.replace(staged_base, base_path)
        installed.append(base_path)
        os.replace(staged_latest, latest_path)
        installed.append(latest_path)

        marker = read_rebase_marker(scene) or {}
        rebases = marker.get("rebases", [])
        rebases.append(
            {
                "ts": _utc_timestamp_now(),
                "rebased_from_rev": old_latest_rev,
                "preserved_to": preserved_dirname,
            }
        )
        _write_json(_rebase_marker_path(scene), {"rebases": rebases})
    except Exception as e:
        log.error("changelog_rebase_failed", error=e, preserved_to=preserved_dirname)
        for path in installed:
            try:
                os.remove(path)
            except OSError as rollback_error:
                log.error(
                    "changelog_rebase_rollback_failed",
                    path=path,
                    error=rollback_error,
                )
        for src, dst in reversed(moved):
            try:
                os.replace(dst, src)
            except OSError as rollback_error:
                log.error(
                    "changelog_rebase_rollback_failed", path=dst, error=rollback_error
                )
        for staged in (staged_base, staged_latest):
            try:
                if os.path.exists(staged):
                    os.remove(staged)
            except OSError:
                pass
        try:
            os.rmdir(preserved_dir)
        except OSError:
            pass
        raise

    _DIVERGENCE_CHECK_CACHE.pop(
        (os.path.abspath(scene.changelog_dir), scene.filename), None
    )

    # A load-screen scaffold has no live state to reconcile; a loaded scene
    # does, and leaving it on the archived namespace would number its next
    # delta above the revisions the fresh chain does not have.
    if not isinstance(scene, _SceneRef):
        for message in scene.history:
            message.rev = 0
        scene.rev = 0
        if changelog is not None:
            changelog.last_state = copy.deepcopy(rebased_data)
            changelog.initial_state = copy.deepcopy(rebased_data)

    log.info(
        "changelog_rebased",
        rebased_from_rev=old_latest_rev,
        preserved_to=preserved_dirname,
        preserved=[os.path.basename(src) for src, _ in moved],
    )
    return {"rebased_from_rev": old_latest_rev, "preserved_to": preserved_dirname}


async def fork_scene_at_revision(
    scene: "Scene",
    to_rev: int,
    save_name: str,
    expect_message_id: int | None = None,
) -> str:
    """
    Create a new scene file forked from the given revision.

    Writes the reconstructed scene state to ``<save_name>.json`` in the
    scene's save directory, cleared for independent use (mutable, visible in
    the scene browser, fresh memory id, no playthrough position).

    Message revs in the written fork are zeroed: a fork starts its own
    changelog chain at rev 0, so revs naming revisions of the source scene's
    chain would be meaningless in it.

    Args:
        scene: The scene object to fork
        to_rev: The revision to reconstruct and fork from
        save_name: Base name for the fork file
        expect_message_id: When given, the reconstructed history must contain
            a message with this id — raises ForkTargetMissingError otherwise,
            so a stale or never-materialized rev cannot silently produce a
            fork short of the message the user pointed at

    Returns:
        str: Path to the written fork file

    Raises:
        ForkTargetMissingError: expect_message_id not in the reconstructed
            history, or to_rev beyond the chain's latest revision (a rev that
            never materialized cannot reconstruct "at the message"). The
            beyond-latest guard does not apply when the chain is unverifiable
            (quarantined/corrupted) — that path already warns and proceeds.
        ChangelogDivergedError: the chain does not replay strictly — the
            fork would carry silently lost or fabricated data
    """
    corrupted = False
    try:
        divergent = await check_chain_divergence(scene)
    except ChangelogCorruptedError as e:
        log.warning(
            "fork_from_unverifiable_chain",
            rev=to_rev,
            detail=str(e),
        )
        divergent = None
        corrupted = True
    if divergent:
        log.warning(
            "fork_from_diverged_chain",
            rev=to_rev,
            paths=divergent[:20],
            detail="reconstruction may be missing or fabricating data",
        )

    latest_rev = _get_overall_latest_revision(scene, strict=False)
    if not corrupted and to_rev > latest_rev:
        raise ForkTargetMissingError(
            f"Revision {to_rev} does not exist (latest is {latest_rev})."
        )

    reconstructed = await reconstruct_scene_data(scene, to_rev=to_rev)

    if expect_message_id is not None and not any(
        entry.get("id") == expect_message_id
        for entry in reconstructed.get("history", [])
    ):
        raise ForkTargetMissingError(
            f"Reconstruction at rev {to_rev} does not contain message "
            f"{expect_message_id}."
        )

    return await write_reconstructed_scene(
        scene,
        to_rev,
        f"{save_name}.json",
        overrides={
            "immutable_save": False,
            "hidden": False,
            "deprecated": False,
            "memory_id": str(uuid.uuid4())[:10],
            "playthrough_progress": None,
        },
        precomputed_data=reconstructed,
        zero_message_revs=True,
    )


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
        self.initial_state: dict | None = None  # State before any pending changes
        self.committed = False
        self._rollback_failed = False

    def _raise_if_rollback_failed(self) -> None:
        if self._rollback_failed:
            raise RuntimeError(
                "This changelog cannot continue after an incomplete rollback; "
                "reload the scene before saving again"
            )

    async def __aenter__(self):
        """Initialize the in-memory changelog context."""
        # Baseline on the last committed snapshot when one exists, so deltas
        # always transform committed state -> new state and the delta chain
        # stays consistent with reconstructions. Baselining on the live scene
        # state instead would silently drop any mutations made since the last
        # commit (e.g. load-time message meta stamps) from the chain, which
        # breaks delta value verification during reconstruction.
        self.last_state = _load_latest_scene_data(self.scene)
        if self.last_state is None:
            self.last_state = _serialize_scene_plain(self.scene)
        self.initial_state = (
            self.last_state.copy()
        )  # Keep initial state for base snapshots
        self._backfill_message_revs()
        return self

    def _backfill_message_revs(self):
        # The scene file can lag the chain (a crash between commit and file
        # write, or a scene saved before the file carried revs); the latest
        # snapshot is the record of which revision a message entered at.
        snapshot_revs = {
            entry.get("id"): entry.get("rev")
            for entry in (self.last_state or {}).get("history", [])
        }
        for message in self.scene.history:
            if not message.rev and snapshot_revs.get(message.id):
                message.rev = snapshot_revs[message.id]

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def append_delta(self, meta: dict | None = None) -> int | None:
        """
        Append a delta for the current scene state to the in-memory list.

        History messages new to the chain are stamped with this delta's
        revision before serialization, so the stamp is part of the delta; the
        stamps are rolled back if the delta is not staged. Messages already
        recorded in the chain without a rev keep ``rev == 0`` and fork
        shallowly.

        Args:
            meta: Optional metadata to store with this revision

        Returns:
            int | None: The actual revision number this delta will have when committed, None if unchanged
        """
        self._raise_if_rollback_failed()
        next_real_rev = self.scene.rev + len(self.pending_deltas) + 1

        known_ids = {
            entry.get("id") for entry in (self.last_state or {}).get("history", [])
        }
        stamped = [
            message
            for message in self.scene.history
            if not message.rev and message.id not in known_ids
        ]
        for message in stamped:
            message.rev = next_real_rev

        try:
            curr_data = _serialize_scene_plain(self.scene)
            delta = _compute_delta(self.last_state, curr_data)
            staged = bool(delta) and _delta_reproduces_state(
                self.last_state, curr_data, delta
            )
        except Exception:
            for message in stamped:
                message.rev = 0
            raise

        if not staged:
            for message in stamped:
                message.rev = 0
            if delta:
                # last_state is left unchanged so the next append retries from
                # the same baseline instead of diverging the chain.
                log.error(
                    "delta_verification_failed",
                    detail="computed delta does not reproduce the scene state; delta not staged",
                )
            return None

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

    async def commit(self, emit_message_revs: bool = True) -> list[int]:
        """
        Commit all pending deltas to the persistent changelog files.
        After committing, the changelog can continue to accumulate new deltas.

        Args:
            emit_message_revs: announce committed message revisions. Rebase
                flushes disable this because those revisions are renumbered.

        Returns:
            list[int]: List of committed revision numbers

        Raises:
            Exception: any failure to persist or restore changelog files
        """
        self._raise_if_rollback_failed()
        if not self.pending_deltas:
            return []

        restore_files = _snapshot_changelog_flush(self.scene)
        committed_revs = []
        try:
            if not os.path.exists(_base_path(self.scene)):
                await save_changelog(self.scene)

            for entry in self.pending_deltas:
                start_rev, log_path = _get_latest_changelog_file(self.scene)
                log_data = _ensure_log_initialized(self.scene, start_rev)

                log.debug("commit_in_memory_deltas", real_delta_entry=entry)
                estimated_size = len(json.dumps(entry))
                current_size = _get_file_size(log_path)
                entry_rev = entry["rev"]
                if (
                    current_size > 0
                    and (current_size + estimated_size) > MAX_CHANGELOG_FILE_SIZE
                ):
                    start_rev = entry_rev
                    log_path = _changelog_log_path(self.scene, start_rev)
                    log_data = _ensure_log_initialized(self.scene, start_rev)
                    log.debug(
                        "changelog_file_split", new_file=log_path, start_rev=start_rev
                    )

                log_data["deltas"].append(entry)
                log_data["latest_rev"] = entry_rev
                _write_json(log_path, log_data)

                committed_revs.append(entry_rev)
                log.debug("committed_in_memory_delta", rev=entry_rev)

            _write_json(_latest_path(self.scene), self.last_state)
        except Exception as write_error:
            try:
                restore_files()
            except Exception as rollback_error:
                # The disk may already contain some pending entries. Retrying
                # this instance could append them twice, so only a scene reload
                # may establish a trustworthy in-memory baseline again.
                self._rollback_failed = True
                raise ExceptionGroup(
                    "Changelog commit failed and its rollback also failed",
                    [write_error, rollback_error],
                ) from write_error
            raise

        self.pending_deltas.clear()

        if committed_revs:
            self.scene.rev = max(committed_revs)

        if committed_revs and emit_message_revs:
            # Revs are emitted only once they exist on disk: with auto_save
            # off, appends stage deltas without committing, and the UI must
            # not learn a rev that the committed chain cannot reconstruct.
            committed_set = set(committed_revs)
            stamped = [
                m for m in self.scene.history if m.rev and m.rev in committed_set
            ]
            if stamped:
                # lazy import: changelog sits below the emit stack
                from talemate.emit import emit

                emit(
                    "message_revs",
                    data={"revs": [{"id": m.id, "rev": m.rev} for m in stamped]},
                    websocket_passthrough=True,
                )

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


async def ensure_changelogs_for_all_scenes(root: str | None = None) -> None:
    """
    Ensure base and latest changelog snapshots exist for all scene files.

    Scans the scenes directory, finds all scene JSON files, and for each scene:
    - Creates the base and latest files if the base is missing
    - Creates the latest file from base if latest is missing

    Args:
        root: Optional path to the root scenes directory. If None, uses the
              project's configured scenes directory.
    """
    # Resolve the scenes root directory
    scenes_root: Path = Path(root) if root else SCENES_DIR

    processed = 0

    try:
        if not scenes_root.is_dir():
            log.warning("scenes_root_not_found", root=str(scenes_root))
            return None

        for project_path in sorted(
            (p for p in scenes_root.iterdir() if p.is_dir()), key=lambda p: p.name
        ):
            # Consider only top-level scene JSON files in each project directory
            try:
                entries = [
                    p.name
                    for p in project_path.iterdir()
                    if p.is_file() and p.suffix == ".json"
                ]
            except Exception:
                continue

            for scene_file in sorted(entries):
                scene_path = project_path / scene_file
                base_path = project_path / "changelog" / f"{scene_file}.base.json"
                latest_path = project_path / "changelog" / f"{scene_file}.latest.json"

                processed += 1

                try:
                    # Load the scene data from disk (without instantiating a full Scene)
                    with open(scene_path, "r") as f:
                        data = json.load(f)
                except Exception as e:
                    log.warning("read_scene_failed", path=str(scene_path), error=e)
                    continue

                # Build a minimal scene reference and ensure artifacts exist
                scene_ref = _SceneRef(
                    filename=scene_file,
                    save_dir=str(project_path),
                    data=data,
                )

                try:
                    base_exists = base_path.exists()
                    latest_exists = latest_path.exists()

                    if not base_exists:
                        await save_changelog(scene_ref)  # creates base and latest
                    else:
                        if not latest_exists:
                            await _ensure_latest_initialized(scene_ref)
                except Exception as e:
                    log.warning(
                        "ensure_scene_changelog_failed", path=str(scene_path), error=e
                    )

    except Exception as e:  # pragma: no cover
        log.error("ensure_changelogs_for_all_scenes_failed", error=e)
    return None
