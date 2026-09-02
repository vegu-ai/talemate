"""
Offscreen life: when a character returns after missing part of the story,
write what they did while away and store it as a fact only they know.
"""

from typing import TYPE_CHECKING

import structlog

import talemate.emit.async_signals as async_signals
import talemate.util as util
from talemate.agents.base import AgentAction, AgentActionConfig
from talemate.events import ArchiveEvent, CharacterActivatedEvent
from talemate.knowledge.facts import store_offscreen_fact
from talemate.knowledge.schema import Fact
from talemate.prompts import Prompt

if TYPE_CHECKING:
    from talemate.tale_mate import Character

__all__ = ["OffscreenLifeMixin"]

log = structlog.get_logger("talemate.agents.narrator.offscreen")


class OffscreenLifeMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["offscreen_life"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            icon="mdi-account-clock-outline",
            label="Offscreen Life",
            description="When a character returns after missing part of the story, write what they did while away. The result is stored as a fact only that character knows; it is not added to the scene text. +1 request per return.",
            config={
                "min_entries": AgentActionConfig(
                    type="number",
                    label="Minimum missed entries",
                    description="Write the offscreen life only when the character missed at least this many summarized history entries.",
                    value=1,
                    min=1,
                    max=20,
                    step=1,
                ),
                "length": AgentActionConfig(
                    type="number",
                    label="Length",
                    description="Token length for the offscreen life narration.",
                    value=192,
                    min=32,
                    max=1024,
                    step=32,
                ),
            },
        )

    @property
    def offscreen_life_enabled(self) -> bool:
        return self.resolve_enabled("offscreen_life")

    @property
    def offscreen_life_min_entries(self) -> int:
        return int(self.resolve_config("offscreen_life", "min_entries"))

    @property
    def offscreen_life_length(self) -> int:
        return int(self.resolve_config("offscreen_life", "length"))

    def connect(self, scene):
        super().connect(scene)
        # returns whose absence is not fully archived yet, settled on archive_add
        self.pending_returns: dict[str, int] = {}
        async_signals.get("character.activated").connect(self.on_character_activated)
        async_signals.get("archive_add").connect(self.on_archive_add_offscreen)

    def missed_entries(self, character: "Character") -> list[dict]:
        """
        The summarized history entries the character was absent for, up to
        their return: the tail of the archive whose presence is known and does
        not include them, oldest first. A character the archive never saw
        present (or with unknown presence) was not away: nothing is missed.
        """
        missed: list[dict] = []
        anchored = False
        for entry in reversed(self.scene.archived_history):
            present = entry.get("present")
            if present is None or character.name in present:
                anchored = True
                break
            missed.append(entry)
        if not anchored:
            return []
        missed.reverse()
        return missed

    def absence_fully_archived(self) -> bool:
        """
        True when no message after the newest archived entry exists: the
        archive holds the whole absence. The presence cut archives the missed
        span only once a message after the return arrives, so a return with
        an unarchived tail waits for that cut.
        """
        history = self.scene.history
        if not history:
            return True
        last_end = -1
        for entry in reversed(self.scene.archived_history):
            if entry.get("end") is not None:
                last_end = entry["end"]
                break
        return last_end >= len(history) - 1

    def was_in_scene(self, character: "Character") -> bool:
        """Present on an archived entry (or one with unknown presence) or on a message."""
        name = character.name
        for entry in self.scene.archived_history:
            present = entry.get("present")
            if present is None or name in present:
                return True
        return any(
            getattr(message, "present", None) and name in message.present
            for message in self.scene.history
        )

    async def on_character_activated(self, event: CharacterActivatedEvent):
        if not self.offscreen_life_enabled or event.scene is not self.scene:
            return
        character = event.character
        if not self.was_in_scene(character):
            # a character new to the scene was not away
            log.debug("offscreen life: never in the scene", character=character.name)
            return
        missed = self.missed_entries(character)
        if missed and self.absence_fully_archived():
            self.pending_returns.pop(character.name, None)
            await self._offscreen_life_if_enough(character, missed)
            return
        # part of the absence is not archived yet: wait for the cut that
        # covers it, so the account spans the whole absence
        self.pending_returns[character.name] = self.scene.ts
        log.debug("offscreen life pending", character=character.name)

    async def on_archive_add_offscreen(self, event: ArchiveEvent):
        pending = self.pending_returns
        if not pending or event.scene is not self.scene:
            return
        for name in list(pending):
            character = self.scene.get_character(name)
            if character is None or name not in self.scene.active_characters:
                pending.pop(name, None)
                continue
            missed = self.missed_entries(character)
            if not missed:
                # the newest entry covers the character: nothing was missed
                if event.present is None or name in event.present:
                    pending.pop(name, None)
                continue
            pending.pop(name, None)
            if self.offscreen_life_enabled:
                await self._offscreen_life_if_enough(character, missed)

    async def _offscreen_life_if_enough(
        self, character: "Character", missed: list[dict]
    ):
        if len(missed) < self.offscreen_life_min_entries:
            log.debug(
                "offscreen life skipped",
                character=character.name,
                missed=len(missed),
                required=self.offscreen_life_min_entries,
            )
            return
        await self.narrate_offscreen_life(character, missed)

    async def narrate_offscreen_life(
        self, character: "Character", missed: list[dict]
    ) -> Fact | None:
        """
        What the character did while away; stored as an offscreen fact.

        The prompt renders from the character's own perspective (their
        bucket), so the span they missed is not in front of the model at all.
        """
        scene = self.scene
        first_ts = missed[0].get("ts") if missed else None
        try:
            elapsed = util.diff_to_human(util.coerce_ts(first_ts), scene.ts)
        except (TypeError, ValueError):
            elapsed = ""

        length = self.offscreen_life_length
        _, extracted = await Prompt.request(
            "narrator.offscreen-life",
            self.client,
            f"narrate_{length}",
            vars={
                "scene": scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "missed_count": len(missed),
                "elapsed": elapsed or "a while",
                "extra_instructions": self.extra_instructions,
                "response_length": length,
            },
        )
        text = self.clean_result(
            (extracted.get("response") or "").strip().strip("*"),
            ensure_dialog_format=False,
            force_narrative=False,
        )
        if not text:
            log.warning("offscreen life: empty response", character=character.name)
            return None
        fact = await store_offscreen_fact(scene, character.name, text)
        log.debug(
            "offscreen life",
            character=character.name,
            missed=len(missed),
            fact=fact.id,
        )
        return fact
