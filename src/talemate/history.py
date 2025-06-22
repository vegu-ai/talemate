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

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.scene_message import SceneMessage
from talemate.util import iso8601_diff_to_human
from talemate.world_state.templates import GenerationOptions
from talemate.exceptions import GenerationCancelled
from talemate.context import handle_generation_cancelled
from talemate.events import ArchiveEvent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

__all__ = [
    "history_with_relative_time",
    "pop_history",
    "rebuild_history",
    "character_activity",
    "update_history_entry",
    "regenerate_history_entry",
    "collect_source_entries",
    "resolve_history_entry",
    "entry_contained",
    "emit_archive_add",
]

log = structlog.get_logger()


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

def emit_archive_add(scene: "Scene", entry: ArchiveEntry):
    """
    Emits the archive_add signal for an archive entry
    """
    scene.signals["archive_add"].send(
        ArchiveEvent(
            scene=scene, 
            event_type="archive_add", 
            text=entry.text, 
            ts=entry.ts, 
            memory_id=entry.id
        )
    )

def resolve_history_entry(scene: "Scene", entry: HistoryEntry) -> LayeredArchiveEntry | ArchiveEntry:
    """
    Resolves a history entry in the scene's archived history
    """
    
    if entry.layer == 0:
        return ArchiveEntry(**scene.archived_history[entry.index])
    else:
        return LayeredArchiveEntry(**scene.layered_history[entry.layer - 1][entry.index])

def entry_contained(scene: "Scene", entry_id: str, container: HistoryEntry | SourceEntry) -> bool:
    """
    Checks if entry_id is contained in container through source entries, checking all the way up to the base layer
    """

    messages = collect_source_entries(scene, container)
    
    for message in messages:
        if message.id == entry_id:
            return True
        if not isinstance(message, SceneMessage) and entry_contained(scene, entry_id, message):
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
            return message.typ not in ["director", "context_investigation", "reinforcement"]
        
        result = [
            SourceEntry(
                text=str(source), 
                layer=-1, 
                id=source.id,
                start=entry.start,
                end=entry.end,
                ts=source.ts,
                ts_start=source.ts_start,
                ts_end=source.ts_end) for source in filter(include_message, scene.history[entry.start:entry.end+1]
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
            ) for source in source_layer[entry.start:entry.end+1]
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


def history_with_relative_time(history: list[str], scene_time: str, layer: int = 0) -> list[dict]:
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
            time_start=iso8601_diff_to_human(scene_time, entry["ts_start"] if entry.get("ts_start") else None),
            time_end=iso8601_diff_to_human(scene_time, entry["ts_end"] if entry.get("ts_end") else None),
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

async def rebuild_history(
    scene: "Scene",
    callback: Callable | None = None,
    generation_options: GenerationOptions | None = None,
):
    """
    rebuilds all history for a scene
    """
    memory = get_agent("memory")
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
    except Exception as e:
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
    none_have_acted:bool
    characters:list

async def character_activity(scene: "Scene", since_time_passage: bool = False) -> CharacterActivity:
    """
    Returns a CharacterActivity object containing a list of all active characters sorted by which were last active
    
    The most recently active character is first in the list.
    
    If no characters have acted, the none_have_acted flag will be set to True.
    
    If since_time_passage is True, the search will stop when a TimePassageMessage is found.
    """
    
    activity:list = []
    
    character_names = scene.character_names
    
    for message in scene.collect_messages(typ="character", max_iterations=100, stop_on_time_passage=since_time_passage):
        if message.character_name not in activity and message.character_name in character_names:
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
        characters=[scene.get_character(character) for character in activity]
    )
    
    
async def update_history_entry(scene: "Scene", entry: HistoryEntry) -> LayeredArchiveEntry | ArchiveEntry:
    """
    Updates a history entry in the scene's archived history
    """
    
    if entry.layer == 0:
        # base layer
        archive_entry = ArchiveEntry(**entry.model_dump())
        scene.archived_history[entry.index] = archive_entry.model_dump(exclude_none=True)
        emit_archive_add(scene, archive_entry)
        return archive_entry
    else:
        # layered history
        layered_entry = LayeredArchiveEntry(**entry.model_dump())
        scene.layered_history[entry.layer - 1][entry.index] = layered_entry.model_dump(exclude_none=True)
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
        archive_entry: ArchiveEntry | LayeredArchiveEntry = resolve_history_entry(scene, entry)
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


async def validate_history(scene: "Scene") -> bool:
    
    archived_history = scene.archived_history
    layered_history = scene.layered_history
    
    # if archived_history does not have memory_id set, we need to ensure
    # they are set and reimport to the memory agent
    
    any_missing_memory_id = any(entry.get("id") is None for entry in archived_history)
    
    invalid = any_missing_memory_id
    
    if invalid:
        log.warning("History is invalid, fixing and reimporting", any_missing_memory_id=any_missing_memory_id)
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
    for entry in scene.archived_history:
        scene.signals["archive_add"].send(
            ArchiveEvent(
                scene=scene, event_type="archive_add", text=entry["text"], ts=entry["ts"], memory_id=entry["id"]
            )
        )
        
    for layer_index, layer in enumerate(layered_history):
        for entry_index, entry in enumerate(layer):
            if not entry.get("id"):
                log.warning("Layered history entry is missing id, generating one", layer=layer_index, index=entry_index)
                entry["id"] = str(uuid.uuid4())[:8]
                # these entries also have their `end` value incorrectly offset by -1 so we need to fix it
                if entry.get("end") is not None:
                    entry["end"] += 1
            
    return not invalid