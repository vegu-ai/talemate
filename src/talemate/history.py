"""
Utilities for managing the scene history.

Most of these currently exist as mehtods on the Scene object, but i am in the process of moving them here.
"""

import pydantic
import asyncio
from typing import TYPE_CHECKING, Callable

import structlog
import traceback
import uuid
import datetime
import isodate

from talemate.emit import emit
import talemate.emit.async_signals as async_signals
from talemate.instance import get_agent
from talemate.scene_message import SceneMessage
from talemate.util import (
    iso8601_diff_to_human,
    iso8601_add,
    duration_to_timedelta,
)
from talemate.world_state.templates import GenerationOptions
from talemate.exceptions import GenerationCancelled
from talemate.context import handle_generation_cancelled
from talemate.events import ArchiveEvent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "history_with_relative_time",
    "pop_history",
    "count_message_types_at_tail",
    "rebuild_history",
    "character_activity",
    "update_history_entry",
    "regenerate_history_entry",
    "collect_source_entries",
    "resolve_history_entry",
    "entry_contained",
    "emit_archive_add",
    "add_history_entry",
    "delete_history_entry",
    "reimport_history",
]

log = structlog.get_logger()


async_signals.register("archive_add")


class UnregeneratableEntryError(Exception):
    pass


class ArchiveEntry(pydantic.BaseModel):
    text: str
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:8])
    start: int | None = None
    end: int | None = None
    ts: str = pydantic.Field(default_factory=lambda: "PT1S")


class LayeredArchiveEntry(ArchiveEntry):
    ts_start: str | None = None
    ts_end: str | None = None


class HistoryEntry(pydantic.BaseModel):
    text: str
    ts: str
    index: int
    layer: int
    id: str | None = None
    ts_start: str | None = None
    ts_end: str | None = None
    time: str | None = None
    time_start: str | None = None
    time_end: str | None = None
    start: int | None = None
    end: int | None = None

    @property
    def is_static(self) -> bool:
        return self.layer == 0 and self.start is None and self.end is None


class SourceEntry(pydantic.BaseModel):
    text: str
    layer: int
    id: str | int
    start: int | None = None
    end: int | None = None
    ts: str | None = None
    ts_start: str | None = None
    ts_end: str | None = None

    def __str__(self):
        return self.text


async def emit_archive_add(scene: "Scene", entry: ArchiveEntry):
    """
    Emits the archive_add signal for an archive entry
    """
    await async_signals.get("archive_add").send(
        ArchiveEvent(
            scene=scene,
            event_type="archive_add",
            text=entry.text,
            ts=entry.ts,
            memory_id=entry.id,
        )
    )


def resolve_history_entry(
    scene: "Scene", entry: HistoryEntry
) -> LayeredArchiveEntry | ArchiveEntry:
    """
    Resolves a history entry in the scene's archived history
    """

    if entry.layer == 0:
        return ArchiveEntry(**scene.archived_history[entry.index])
    else:
        return LayeredArchiveEntry(
            **scene.layered_history[entry.layer - 1][entry.index]
        )


def entry_contained(
    scene: "Scene", entry_id: str, container: HistoryEntry | SourceEntry
) -> bool:
    """
    Checks if entry_id is contained in container through source entries, checking all the way up to the base layer
    """

    messages = collect_source_entries(scene, container)

    for message in messages:
        if message.id == entry_id:
            return True
        if not isinstance(message, SceneMessage) and entry_contained(
            scene, entry_id, message
        ):
            return True

    return False


def collect_source_entries(scene: "Scene", entry: HistoryEntry) -> list[SourceEntry]:
    """
    Collects the source entries for a history entry
    """

    if entry.start is None or entry.end is None:
        # entries that dont defien a start and end are not regeneratable
        return []

    if entry.layer == 0:
        # base layer
        def include_message(message: SceneMessage) -> bool:
            return message.typ not in [
                "director",
                "context_investigation",
                "reinforcement",
            ]

        result = [
            SourceEntry(
                text=str(source),
                layer=-1,
                id=source.id,
                start=getattr(source, "start", None),
                end=getattr(source, "end", None),
                ts=getattr(source, "ts", None),
                ts_start=getattr(source, "ts_start", None),
                ts_end=getattr(source, "ts_end", None),
            )
            for source in filter(
                include_message, scene.history[entry.start : entry.end + 1]
            )
        ]

        return result

    else:
        # layered history
        if entry.layer == 1:
            source_layer = scene.archived_history
            source_layer_index = 0
        else:
            source_layer_index = entry.layer - 1
            source_layer = scene.layered_history[source_layer_index]

        return [
            SourceEntry(
                text=source["text"],
                layer=source_layer_index,
                id=source["id"],
                start=source.get("start", None),
                end=source.get("end", None),
                ts=source.get("ts", None),
                ts_start=source.get("ts_start", None),
                ts_end=source.get("ts_end", None),
            )
            for source in source_layer[entry.start : entry.end + 1]
        ]


def pop_history(
    history: list[SceneMessage],
    typ: str,
    source: str = None,
    all: bool = False,
    max_iterations: int = None,
    reverse: bool = False,
):
    """
    Pops the last message from the scene history
    """

    iterations = 0

    if not reverse:
        iter_range = range(len(history) - 1, -1, -1)
    else:
        iter_range = range(len(history))

    to_remove = []

    for idx in iter_range:
        if history[idx].typ == typ and (
            history[idx].source == source or source is None
        ):
            to_remove.append(history[idx])
            if not all:
                break
        iterations += 1
        if max_iterations and iterations >= max_iterations:
            break

    for message in to_remove:
        history.remove(message)


def count_message_types_at_tail(
    history: list[SceneMessage],
    target_types: list[str],
    ignore_types: list[str] | None = None,
) -> int:
    """
    Counts consecutive messages of target_types at the tail of the history.

    Stops counting when it encounters a message that is:
    - NOT in target_types
    - NOT in ignore_types (if provided)

    Args:
        history: The scene history
        target_types: Message types to count (e.g., ["narrator"])
        ignore_types: Message types that don't break the count (e.g., ["director", "reinforcement"])

    Returns:
        int: Number of consecutive target_type messages at the tail
    """
    if not history:
        return 0

    if ignore_types is None:
        ignore_types = []

    count = 0

    for idx in range(len(history) - 1, -1, -1):
        message = history[idx]

        if message.typ in target_types:
            count += 1
        elif message.typ not in ignore_types:
            # Hit a message that's not in target_types and not in ignore_types
            break
        # If in ignore_types, continue without incrementing count

    return count


def history_with_relative_time(
    history: list[dict], scene_time: str, layer: int = 0
) -> list[dict]:
    """
    Cycles through a list of Archived History entries and runs iso8601_diff_to_human

    Will return a list of dictionaries with the following keys

    - text `str`: the history text
    - ts `str `: the original timestamp
    - time `str`: the human readable time
    """

    return [
        HistoryEntry(
            text=entry["text"],
            ts=entry["ts"],
            id=entry.get("id", None),
            index=index,
            layer=layer,
            ts_start=entry.get("ts_start", None),
            ts_end=entry.get("ts_end", None),
            time=iso8601_diff_to_human(scene_time, entry["ts"]),
            time_start=iso8601_diff_to_human(
                scene_time, entry["ts_start"] if entry.get("ts_start") else None
            ),
            time_end=iso8601_diff_to_human(
                scene_time, entry["ts_end"] if entry.get("ts_end") else None
            ),
            start=entry.get("start", None),
            end=entry.get("end", None),
        ).model_dump()
        for index, entry in enumerate(history)
    ]


async def purge_all_history_from_memory():
    """
    Removes all history from the memory agent
    """
    memory = get_agent("memory")
    await memory.delete({"typ": "history"})


async def static_history(scene: "Scene") -> list[ArchiveEntry]:
    """
    Returns the static history for a scene
    """
    return [
        ArchiveEntry(**entry)
        for entry in scene.archived_history
        if entry.get("end") is None
    ]


async def rebuild_history(
    scene: "Scene",
    callback: Callable | None = None,
    generation_options: GenerationOptions | None = None,
):
    """
    rebuilds all history for a scene
    """
    summarizer = get_agent("summarizer")

    # clear out archived history, but keep pre-established history
    scene.archived_history = [
        ah for ah in scene.archived_history if ah.get("end") is None
    ]

    scene.layered_history = []

    await purge_all_history_from_memory()

    scene.saved = False

    scene.sync_time()

    entries = 0
    total_entries = summarizer.estimated_entry_count

    try:
        while True:
            await asyncio.sleep(0.1)

            if not scene.active:
                # scene is no longer active
                log.warning("Scene is no longer active, aborting rebuild of history")
                emit("status", message="Rebuilding of archive aborted", status="info")
                return

            emit(
                "status",
                message=f"Rebuilding historical archive... {entries}/~{total_entries}",
                status="busy",
                data={"cancellable": True},
            )

            more = await summarizer.build_archive(
                scene, generation_options=generation_options
            )

            scene.sync_time()

            if callback:
                await callback()

            entries += 1
            if not more:
                break
    except GenerationCancelled as e:
        log.info("Generation cancelled, stopping rebuild of historical archive")
        emit("status", message="Rebuilding of archive cancelled", status="info")
        handle_generation_cancelled(e)
        return
    except Exception:
        log.error("Error rebuilding historical archive", error=traceback.format_exc())
        emit("status", message="Error rebuilding historical archive", status="error")
        return

    scene.sync_time()
    await scene.commit_to_memory()

    if summarizer.layered_history_enabled:
        emit("status", message="Rebuilding layered history...", status="busy")
        await summarizer.summarize_to_layered_history()

    emit("status", message="Historical archive rebuilt", status="success")


class CharacterActivity(pydantic.BaseModel):
    none_have_acted: bool
    characters: list


async def character_activity(
    scene: "Scene", since_time_passage: bool = False
) -> CharacterActivity:
    """
    Returns a CharacterActivity object containing a list of all active characters sorted by which were last active

    The most recently active character is first in the list.

    If no characters have acted, the none_have_acted flag will be set to True.

    If since_time_passage is True, the search will stop when a TimePassageMessage is found.
    """

    activity: list = []

    character_names = scene.character_names

    for message in scene.collect_messages(
        typ="character", max_iterations=100, stop_on_time_passage=since_time_passage
    ):
        if (
            message.character_name not in activity
            and message.character_name in character_names
        ):
            activity.append(message.character_name)

        # if all characters have been added, break
        if len(activity) == len(character_names):
            break

    none_have_acted = not activity

    # any characters in the activity list at this point have not spoken
    # and should be appended to the list
    for character in character_names:
        if character not in activity:
            activity.append(character)

    return CharacterActivity(
        none_have_acted=none_have_acted,
        characters=[scene.get_character(character) for character in activity],
    )


async def update_history_entry(
    scene: "Scene", entry: HistoryEntry
) -> LayeredArchiveEntry | ArchiveEntry:
    """
    Updates a history entry in the scene's archived history
    """

    if entry.layer == 0:
        # base layer
        archive_entry = ArchiveEntry(**entry.model_dump())
        scene.archived_history[entry.index] = archive_entry.model_dump(
            exclude_none=True
        )
        await emit_archive_add(scene, archive_entry)
        return archive_entry
    else:
        # layered history
        layered_entry = LayeredArchiveEntry(**entry.model_dump())
        scene.layered_history[entry.layer - 1][entry.index] = layered_entry.model_dump(
            exclude_none=True
        )
        return layered_entry


async def regenerate_history_entry(
    scene: "Scene",
    entry: HistoryEntry,
    generation_options: GenerationOptions | None = None,
) -> LayeredArchiveEntry | ArchiveEntry:
    """
    Regenerates a history entry in the scene's archived history
    """

    summarizer = get_agent("summarizer")
    if entry.start is None or entry.end is None:
        # entries that dont defien a start and end are not regeneratable
        raise UnregeneratableEntryError("No start or end")

    entries = collect_source_entries(scene, entry)

    if not entries:
        raise UnregeneratableEntryError("No entries")

    try:
        archive_entry: ArchiveEntry | LayeredArchiveEntry = resolve_history_entry(
            scene, entry
        )
    except IndexError:
        raise UnregeneratableEntryError("Entry not found")

    summarized = entry.text

    if isinstance(archive_entry, LayeredArchiveEntry):
        new_archive_entries = await summarizer.summarize_entries_to_layered_history(
            [entry.model_dump() for entry in entries],
            entry.layer,
            entry.start,
            entry.end,
            generation_options=generation_options,
        )

        if not new_archive_entries:
            raise UnregeneratableEntryError("Summarization produced no output")

        # if there is more than one entry, merge into first entry
        summarized = "\n\n".join(entry.text for entry in new_archive_entries)

    elif isinstance(archive_entry, ArchiveEntry):
        summarized = await summarizer.summarize(
            "\n".join(map(str, entries)),
            extra_context=await summarizer.previous_summaries(archive_entry),
            generation_options=generation_options,
        )

    entry.text = summarized

    await update_history_entry(scene, entry)

    return entry


async def reimport_history(scene: "Scene", emit_status: bool = True):
    """
    Reimports the history from the memory agent
    """
    try:
        if emit_status:
            emit("status", message="Reimporting history...", status="busy")
        await purge_all_history_from_memory()
        await validate_history(scene)
    except Exception as e:
        log.error("Error reimporting history", error=e)
        if emit_status:
            emit("status", message="Error reimporting history", status="error")
        return
    finally:
        if emit_status:
            emit("status", message="History reimported", status="success")


async def validate_history(scene: "Scene", commit_to_memory: bool = True) -> bool:
    archived_history = scene.archived_history
    layered_history = scene.layered_history

    # if archived_history does not have memory_id set, we need to ensure
    # they are set and reimport to the memory agent

    any_missing_memory_id = any(entry.get("id") is None for entry in archived_history)

    invalid = any_missing_memory_id

    if invalid:
        log.warning(
            "History is invalid, fixing and reimporting",
            any_missing_memory_id=any_missing_memory_id,
        )
        await purge_all_history_from_memory()

        _archived_history = []

        for entry in archived_history:
            try:
                _archived_history.append(
                    ArchiveEntry(**entry).model_dump(exclude_none=True)
                )
            except Exception as e:
                log.error("Error validating history entry", error=e)
                log.error("Invalid entry", entry=entry)
                continue

        scene.archived_history = _archived_history

    # always send the archive_add signal for all entries
    # this ensures the entries are up to date in the memory database
    if commit_to_memory:
        for entry in scene.archived_history:
            await emit_archive_add(scene, ArchiveEntry(**entry))

    for layer_index, layer in enumerate(layered_history):
        for entry_index, entry in enumerate(layer):
            if not entry.get("id"):
                log.warning(
                    "Layered history entry is missing id, generating one",
                    layer=layer_index,
                    index=entry_index,
                )
                entry["id"] = str(uuid.uuid4())[:8]
                # these entries also have their `end` value incorrectly offset by -1 so we need to fix it
                if entry.get("end") is not None:
                    entry["end"] += 1

    return not invalid


async def add_history_entry(scene: "Scene", text: str, offset: str) -> ArchiveEntry:
    """
    Inserts a manual history entry into the base (archived) history.

    Args:
        scene: The active Scene instance.
        text: Human-provided text for the entry.
        offset: ISO-8601 duration representing how long **before the current scene time** the entry occurred.

    Returns:
        The created ArchiveEntry dataclass instance.

    Raises:
        ValueError: If the entry would not be older than the first summarized archive entry or if no summarized entry exists.
    """

    is_first_entry = len(scene.archived_history) == 0

    if is_first_entry:
        # first entry we can just push it to the front of the history
        entry = ArchiveEntry(
            text=text,
            ts="PT0S",
            id=str(uuid.uuid4())[:8],
        ).model_dump(exclude_none=True)
        scene.archived_history.append(entry)
        scene.ts = offset
        await reimport_history(scene)
        return entry

    # Find the first archive entry that originated from summarisation (has start & end)
    first_summary: dict | None = None
    for entry in scene.archived_history:
        if entry.get("start") is not None and entry.get("end") is not None:
            first_summary = entry
            break

    # Parse and convert to timedelta for arithmetic
    scene_td = duration_to_timedelta(isodate.parse_duration(scene.ts))
    offset_td = duration_to_timedelta(isodate.parse_duration(offset))

    new_ts_td: datetime.timedelta = scene_td - offset_td

    log.debug(
        "add_history_entry",
        is_first_entry=is_first_entry,
        scene_ts=scene.ts,
        offset=offset,
        scene_td=scene_td,
        offset_td=offset_td,
        new_ts_td=new_ts_td,
    )

    # If offset predates the current scene start, shift timeline earlier so
    # that the *relative* distance between existing events is preserved.
    if new_ts_td.total_seconds() < 0:
        log.debug(
            "offset is before scene start, shifting timeline", new_ts_td=new_ts_td
        )
        # Amount we must shift the whole timeline forward so that the new
        # entry can be placed at PT0S.  This is the *earliness* gap between
        # the requested offset and the current earliest timestamp.
        # We need to shift by: offset - scene.ts (which is positive since offset > scene.ts)
        # Since we already have the timedeltas, we can compute this directly
        shift_td = offset_td - scene_td  # This will be positive
        shift_iso = isodate.duration_isoformat(shift_td)

        log.debug("shift_iso", shift_iso=shift_iso)

        # Shift everything forward by the calculated amount so that the
        # timeline can accommodate the earlier entry at PT0S.
        shift_scene_timeline(scene, shift_iso)

        # After shifting, the new entry will sit at PT0S
        new_ts_td = datetime.timedelta(seconds=0)

    if first_summary is not None:
        first_summary_td = duration_to_timedelta(
            isodate.parse_duration(first_summary["ts"])
        )

        # New entry must be OLDER (i.e. smaller duration) than the first summary entry.
        if new_ts_td >= first_summary_td:
            raise ValueError(
                "New entry must be older than the first summarized history entry."
            )

    # Build ArchiveEntry
    new_ts_str = isodate.duration_isoformat(new_ts_td)
    archive_entry = ArchiveEntry(text=text, ts=new_ts_str)

    # Insert maintaining chronological order (ascending by duration)
    inserted = False
    for idx, existing in enumerate(scene.archived_history):
        try:
            existing_ts_td = duration_to_timedelta(
                isodate.parse_duration(existing.get("ts", "PT0S"))
            )
        except Exception:
            continue

        if new_ts_td < existing_ts_td:
            scene.archived_history.insert(
                idx, archive_entry.model_dump(exclude_none=True)
            )
            inserted = True
            break

    if not inserted:
        scene.archived_history.append(archive_entry.model_dump(exclude_none=True))

    # Recalculate scene time based on updated history/archives
    try:
        if first_summary is not None:
            scene.sync_time()
    except Exception as e:
        log.error("add_history_entry.sync_time", error=e)

    await reimport_history(scene)

    return archive_entry


async def delete_history_entry(scene: "Scene", entry: HistoryEntry) -> ArchiveEntry:
    """
    Deletes a manual base-layer history entry from the scene archives and removes it from the memory store.

    Args:
        scene: The Scene object whose history will be modified.
        entry: The HistoryEntry to remove (must be layer 0 and have no start/end indices).

    Returns:
        The ArchiveEntry that was removed.

    Raises:
        ValueError: If the entry is not a base-layer manual entry or cannot be found.
    """

    # Validation – only base layer and manual (start/end are None)
    if entry.layer != 0 or entry.start is not None or entry.end is not None:
        raise ValueError("Only manual base-layer entries can be deleted.")

    remove_idx: int | None = None
    for idx, existing in enumerate(scene.archived_history):
        if existing.get("id") == entry.id:
            remove_idx = idx
            break

    is_oldest_entry = remove_idx == 0

    if remove_idx is None:
        raise ValueError("Entry not found.")

    removed_raw = scene.archived_history.pop(remove_idx)
    removed_entry = ArchiveEntry(**removed_raw)

    if is_oldest_entry:
        # The removed first entry is always at 0s.  We therefore need to shift
        # the timeline by the timestamp of **what is now** the first entry so
        # that it becomes ``PT0S``.
        shift_iso = (
            (scene.archived_history[0].get("ts") or "PT0S")
            if scene.archived_history
            else "PT0S"
        )
        # Apply the negative shift to the entire scene timeline.
        shift_scene_timeline(scene, f"-{shift_iso}")

    # Ensure scene time remains consistent
    try:
        scene.sync_time()
    except Exception as e:
        log.error("delete_history_entry.sync_time", error=e)

    await reimport_history(scene)

    return removed_entry


def _shift_entry_ts(entry: dict, shift_iso: str):
    """Shift *in-place* the ts/ts_start/ts_end fields of a raw archive entry, clamping to >= 0."""
    for key in ["ts", "ts_start", "ts_end"]:
        if entry.get(key):
            try:
                entry[key] = iso8601_add(entry[key], shift_iso, clamp_non_negative=True)
            except Exception as e:  # pragma: no cover – defensive only
                log.error(
                    "shift_entry_ts",
                    error=e,
                    key=key,
                    value=entry.get(key),
                    shift_iso=shift_iso,
                )


def shift_scene_timeline(scene: "Scene", shift_iso: str):
    """Shift *every* timeline reference in the scene by the provided ISO-8601 duration.

    The function mutates the scene in place:

    1. ``scene.ts`` – overall scene time
    2. ``ts``, ``ts_start``, ``ts_end`` of every entry in ``scene.archived_history``
    3. Same fields for every entry in every layer in ``scene.layered_history``

    ``shift_iso`` can be positive (move forward in time) or negative (move backward).
    """

    if shift_iso in ["PT0S", "P0D", "PT0H", "P0M", "P0S", "-PT0S", "-P0D"]:
        # No-op
        return

    # 1) shift scene timestamp
    try:
        scene.ts = iso8601_add(scene.ts, shift_iso, clamp_non_negative=True)
    except Exception as e:  # pragma: no cover – defensive only
        log.error(
            "shift_scene_timeline.scene_ts",
            error=e,
            scene_ts=scene.ts,
            shift_iso=shift_iso,
        )

    # 2) shift archived_history entries
    for entry in scene.archived_history:
        _shift_entry_ts(entry, shift_iso)

    # 3) shift layered history entries
    for layer in scene.layered_history:
        for entry in layer:
            _shift_entry_ts(entry, shift_iso)
