from typing import Awaitable, Callable
from weakref import WeakKeyDictionary

import structlog

from talemate.context import handle_generation_cancelled
from talemate.exceptions import GenerationCancelled
from talemate.history import ArchiveEntry, HistoryEntry
from talemate.knowledge.facts import facts_for_entry

log = structlog.get_logger(__name__)

MissingFactsProgress = Callable[[dict], Awaitable[None]]


class MissingFactsRefused(Exception):
    """A run that cannot start; nothing was changed."""


class MissingFactsMixin:
    """Generate facts, entry by entry, for the base entries that have none."""

    def init_missing_facts(self):
        self._missing_facts_runs = WeakKeyDictionary()

    def entry_needs_facts(self, scene, stored: dict) -> bool:
        """
        A base entry that never had facts extracted: no facts, no facts status
        and nothing that makes extraction unavailable.
        """
        return (
            bool(stored.get("id"))
            and not stored.get("facts_status")
            and not facts_for_entry(scene, stored["id"])
            and not self.fact_source_unavailable_reason(scene, ArchiveEntry(**stored))
        )

    def entries_missing_facts(self, scene) -> list[HistoryEntry]:
        return [
            HistoryEntry(**stored, index=index, layer=0)
            for index, stored in enumerate(scene.archived_history)
            if self.entry_needs_facts(scene, stored)
        ]

    def missing_facts_running(self, scene) -> bool:
        return scene in self._missing_facts_runs

    def stop_missing_facts(self, scene) -> bool:
        """Stop the run after the entry in progress. False when none runs."""
        run = self._missing_facts_runs.get(scene)
        if run is None:
            return False
        run["stop"] = True
        return True

    def _missing_entry(self, scene, identity: str) -> HistoryEntry | None:
        # the history can change between entries: find the entry again by id
        for index, stored in enumerate(scene.archived_history):
            if stored.get("id") == identity:
                if not self.entry_needs_facts(scene, stored):
                    return None
                return HistoryEntry(**stored, index=index, layer=0)
        return None

    async def generate_missing_facts(
        self, scene, progress: MissingFactsProgress | None = None
    ) -> dict:
        """
        Run the facts extraction of each entry that needs facts, oldest first,
        so that each entry sees the facts of the entries before it. The run
        stops between entries on `stop_missing_facts`, on a user interrupt,
        when the scene changes or when Extract facts is turned off.
        """
        if not self.archive_extract_facts:
            raise MissingFactsRefused(
                "Extract facts is off in the Summarizer settings."
            )
        if self.missing_facts_running(scene):
            raise MissingFactsRefused("Missing facts are already being generated.")

        planned = [entry.id for entry in self.entries_missing_facts(scene)]
        run = {"stop": False}
        self._missing_facts_runs[scene] = run
        cancel_sequence = scene.cancel_sequence
        state = {
            "total": len(planned),
            "done": 0,
            "ok": 0,
            "failed": 0,
            "skipped": 0,
            "stopped": False,
        }
        try:
            if progress:
                await progress({**state, "entry_id": None})
            for identity in planned:
                scene.continue_actions()
                # an incoming websocket message can clear cancel_requested,
                # the cancel sequence still records the interrupt
                if (
                    run["stop"]
                    or scene.cancel_sequence != cancel_sequence
                    or self.scene is not scene
                    or not self.archive_extract_facts
                ):
                    state["stopped"] = True
                    break
                entry = self._missing_entry(scene, identity)
                status = await self.regenerate_facts(entry) if entry else None
                if status == "ok":
                    state["ok"] += 1
                elif status == "failed":
                    state["failed"] += 1
                else:
                    state["skipped"] += 1
                state["done"] += 1
                if progress:
                    await progress({**state, "entry_id": identity})
        except GenerationCancelled as exc:
            handle_generation_cancelled(exc)
            state["stopped"] = True
        finally:
            self._missing_facts_runs.pop(scene, None)
        log.debug("generate_missing_facts", **state)
        return state
