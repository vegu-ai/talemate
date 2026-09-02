"""
Offscreen life: when a character returns after missing part of the story,
write what they did while away and store it as a fact only they know.
"""

from typing import TYPE_CHECKING

import structlog

import talemate.emit.async_signals as async_signals
import talemate.util as util
from talemate.agents.base import AgentAction, AgentActionConfig, set_processing
from talemate.events import ArchiveEvent, CharacterActivatedEvent
from talemate.knowledge.facts import facts_for_entry, store_offscreen_fact
from talemate.knowledge.schema import Fact
from talemate.prompts import Prompt

if TYPE_CHECKING:
    from talemate.tale_mate import Character

__all__ = ["OffscreenLifeMixin"]

log = structlog.get_logger("talemate.agents.narrator.offscreen")

OFFSCREEN_FACTS_LIMIT = 20


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
        # a return is written at once when the archive already holds the
        # missed span; otherwise it waits for the next archive entry, since
        # the span a character missed is cut only once a message after their
        # return is archived
        self.pending_returns: dict[str, int] = {}
        async_signals.get("character.activated").connect(self.on_character_activated)
        async_signals.get("archive_add").connect(self.on_archive_add_offscreen)

    def missed_entries(self, character: "Character") -> list[dict]:
        """
        The summarized history entries the character was absent for, up to
        their return: the tail of the archive whose presence is known and does
        not include them, oldest first.
        """
        missed: list[dict] = []
        for entry in reversed(self.scene.archived_history):
            present = entry.get("present")
            if present is None or character.name in present:
                break
            missed.append(entry)
        missed.reverse()
        return missed

    async def on_character_activated(self, event: CharacterActivatedEvent):
        if not self.offscreen_life_enabled or event.scene is not self.scene:
            return
        character = event.character
        pending = getattr(self, "pending_returns", None)
        if pending is None:
            pending = self.pending_returns = {}
        missed = self.missed_entries(character)
        if missed:
            pending.pop(character.name, None)
            await self._offscreen_life_if_enough(character, missed)
            return
        pending[character.name] = self.scene.ts
        log.debug("offscreen life pending", character=character.name)

    async def on_archive_add_offscreen(self, event: ArchiveEvent):
        pending = getattr(self, "pending_returns", None)
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

    @set_processing
    async def narrate_offscreen_life(
        self, character: "Character", missed: list[dict]
    ) -> Fact | None:
        """What the character did while away; stored as an offscreen fact."""
        scene = self.scene
        missed_facts: list[Fact] = []
        for entry in missed:
            if entry.get("id"):
                missed_facts.extend(facts_for_entry(scene, entry["id"]))
        missed_facts = missed_facts[-OFFSCREEN_FACTS_LIMIT:]

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
                "missed": missed,
                "missed_facts": missed_facts,
                "elapsed": elapsed or "a while",
                "extra_instructions": self.extra_instructions,
                "response_length": length,
            },
        )
        # plain prose: no dialogue fix-up and no narrative markers on a fact
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
