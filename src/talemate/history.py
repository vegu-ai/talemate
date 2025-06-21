"""
Utilities for managing the scene history.

Most of these currently exist as mehtods on the Scene object, but i am in the process of moving them here.
"""

import pydantic
import asyncio
from typing import TYPE_CHECKING, Callable

import structlog
import traceback

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.scene_message import SceneMessage
from talemate.util import iso8601_diff_to_human
from talemate.world_state.templates import GenerationOptions
from talemate.exceptions import GenerationCancelled
from talemate.context import handle_generation_cancelled

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

__all__ = [
    "history_with_relative_time",
    "pop_history",
    "rebuild_history",
    "character_activity",
]

log = structlog.get_logger()


class ArchiveEntry(pydantic.BaseModel):
    text: str
    start: int | None = None
    end: int | None = None
    ts: str | None = None
    
class LayeredArchiveEntry(ArchiveEntry):
    ts_start: str | None = None
    ts_end: str | None = None
    
class HistoryEntry(pydantic.BaseModel):
    text: str
    ts: str
    index: int
    layer: int
    ts_start: str | None = None
    ts_end: str | None = None
    time: str | None = None
    time_start: str | None = None
    time_end: str | None = None
    start: int | None = None
    end: int | None = None


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


async def rebuild_history(
    scene: "Scene",
    callback: Callable | None = None,
    generation_options: GenerationOptions | None = None,
):
    """
    rebuilds all history for a scene
    """

    # clear out archived history, but keep pre-established history
    scene.archived_history = [
        ah for ah in scene.archived_history if ah.get("end") is None
    ]
    
    scene.layered_history = []

    scene.saved = False

    scene.sync_time()

    summarizer = get_agent("summarizer")

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
        return archive_entry
    else:
        # layered history
        layered_entry = LayeredArchiveEntry(**entry.model_dump())
        scene.layered_history[entry.layer - 1][entry.index] = layered_entry.model_dump(exclude_none=True)
        return layered_entry