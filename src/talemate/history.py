"""
Utilities for managing the scene history.

Most of these currently exist as mehtods on the Scene object, but i am in the process of moving them here.
"""

import asyncio
from typing import TYPE_CHECKING, Callable

import structlog

from talemate.emit import emit
from talemate.instance import get_agent
from talemate.scene_message import SceneMessage
from talemate.util import iso8601_diff_to_human
from talemate.world_state.templates import GenerationOptions

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "history_with_relative_time",
    "pop_history",
    "rebuild_history",
]

log = structlog.get_logger()


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


def history_with_relative_time(history: list[str], scene_time: str) -> list[dict]:
    """
    Cycles through a list of Archived History entries and runs iso8601_diff_to_human

    Will return a list of dictionaries with the following keys

    - text `str`: the history text
    - ts `str `: the original timestamp
    - time `str`: the human readable time
    """

    return [
        {
            "text": entry["text"],
            "ts": entry["ts"],
            "ts_start": entry.get("ts_start", None),
            "ts_end": entry.get("ts_end", None),
            "time": iso8601_diff_to_human(scene_time, entry["ts"]),
            "time_start": iso8601_diff_to_human(scene_time, entry["ts_start"] if entry.get("ts_start") else None),
            "time_end": iso8601_diff_to_human(scene_time, entry["ts_end"] if entry.get("ts_end") else None),
        }
        for entry in history
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

    scene.ts = scene.archived_history[-1].ts if scene.archived_history else "PT0S"

    summarizer = get_agent("summarizer")

    entries = 0
    total_entries = summarizer.estimated_entry_count

    try:
        while True:

            if not scene.active:
                # scene is no longer active
                log.warning("Scene is no longer active, aborting rebuild of history")
                emit("status", message="Rebuilding of archive aborted", status="info")
                return

            emit(
                "status",
                message=f"Rebuilding historical archive... {entries}/~{total_entries}",
                status="busy",
            )

            more = await summarizer.build_archive(
                scene, generation_options=generation_options
            )

            scene.ts = scene.archived_history[-1]["ts"]

            if callback:
                callback()

            entries += 1
            if not more:
                break
    except Exception as e:
        log.exception("Error rebuilding historical archive", error=e)
        emit("status", message="Error rebuilding historical archive", status="error")
        return

    scene.sync_time()
    await scene.commit_to_memory()
    
    if summarizer.layered_history_enabled:
        emit("status", message="Rebuilding layered history...", status="busy")
        await summarizer.summarize_to_layered_history()
    
    emit("status", message="Historical archive rebuilt", status="success")
