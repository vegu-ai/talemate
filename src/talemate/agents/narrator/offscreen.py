"""
Offscreen life: when a character returns after missing part of the story,
write what they did while away and store it as a fact only they know.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

import talemate.emit.async_signals as async_signals
import talemate.util as util
from talemate.agents.base import AgentAction, AgentActionConfig
from talemate.context import scene_is_loading
from talemate.events import ArchiveEvent, CharacterActivatedEvent
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.facts import store_offscreen_fact
from talemate.knowledge.schema import Fact
from talemate.prompts import Prompt
from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Character

__all__ = ["EntryBriefingCoordination", "OffscreenLifeMixin"]

log = structlog.get_logger("talemate.agents.narrator.offscreen")


@dataclass(frozen=True)
class EntryBriefingCoordination:
    """Narrator's explicit offscreen contribution to one entry request."""

    deferred: bool = False
    missed: tuple[dict, ...] = ()
    elapsed: str = ""


@dataclass(frozen=True)
class PendingReturn:
    return_scene_time: int
    entry_boundary_message_id: int = 0
    combined_entry_briefing: bool = False


class OffscreenLifeMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["offscreen_life"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            icon="mdi-account-clock-outline",
            label="Offscreen Life",
            description="When a character returns after missing part of the story, write what they did while away. The result is stored as a fact only that character knows; it is not added to the scene text. Normally +1 request per return; a combined entry briefing may add one retry if its account section is unreadable.",
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
        self.pending_returns: dict[str, PendingReturn] = {}
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

    def absence_fully_archived(self, character: "Character") -> bool:
        """
        True when no unarchived message belongs to the absence: nothing after
        the newest archived entry's `end` has a known presence that excludes
        the character. The newest messages are never archived, so this looks
        at what they are, not at whether they exist.
        """
        last_end = -1
        for entry in reversed(self.scene.archived_history):
            if entry.get("end") is not None:
                last_end = entry["end"]
                break
        name = character.name
        for message in self.scene.history[last_end + 1 :]:
            present = getattr(message, "present", None)
            if present is not None and name not in present:
                return False
        return True

    def was_in_scene(self, character: "Character") -> bool:
        """
        Known prior presence on an archived entry or a message. Unknown
        presence governs what the filter hides, not what spends a request:
        a scene without presence data produces no account.
        """
        name = character.name
        if any(
            name in (entry.get("present") or [])
            for entry in self.scene.archived_history
        ):
            return True
        return any(
            name in (getattr(message, "present", None) or [])
            for message in self.scene.history
        )

    def _elapsed(self, missed: list[dict]) -> str:
        first_ts = missed[0].get("ts") if missed else None
        try:
            away_scene_time = util.coerce_ts(first_ts)
            return util.duration_to_human(
                abs(away_scene_time - self.scene.ts), suffix=""
            )
        except (TypeError, ValueError):
            return ""

    def away_scene_time(self, character: "Character") -> int | None:
        """Best known scene time at which a returning character was away."""

        missed = self.missed_entries(character)
        candidates = missed
        if not candidates and self.was_in_scene(character):
            candidates = [
                entry
                for entry in self.scene.archived_history
                if character.name in (entry.get("present") or ())
            ][-1:]
        if not candidates:
            return None
        try:
            return util.coerce_ts(candidates[0].get("ts"))
        except (TypeError, ValueError):
            return None

    def coordinate_entry_briefing(
        self, character: "Character"
    ) -> EntryBriefingCoordination:
        """Plan a briefing-only, combined, or archive-deferred entry request."""

        if not self.offscreen_life_enabled or not self.was_in_scene(character):
            return EntryBriefingCoordination()
        missed = self.missed_entries(character)
        if not self.absence_fully_archived(character):
            self.pending_returns[character.name] = PendingReturn(
                return_scene_time=self.scene.ts,
                entry_boundary_message_id=(
                    self.scene.history[-1].id if self.scene.history else 0
                ),
                combined_entry_briefing=True,
            )
            log.debug("combined entry briefing pending", character=character.name)
            return EntryBriefingCoordination(deferred=True)
        if len(missed) < self.offscreen_life_min_entries:
            return EntryBriefingCoordination()
        return EntryBriefingCoordination(
            missed=tuple(missed),
            elapsed=self._elapsed(missed),
        )

    async def on_character_activated(self, event: CharacterActivatedEvent):
        if not self.offscreen_life_enabled or event.scene is not self.scene:
            return
        if scene_is_loading.get() is event.scene:
            # a load activates the scene's own characters; an offscreen account
            # is a turn the player asks for, never a side effect of opening a
            # scene
            return
        character = event.character
        conversation = get_agent("conversation")
        if (
            conversation.knowledge_brief_characters_on_entry
            and conversation.character_knowledge_enabled
            and not character.is_player
        ):
            # Conversation owns the explicit combined/deferred request. This
            # branch is independent of signal receiver order.
            return
        if not self.was_in_scene(character):
            # a character new to the scene was not away
            log.debug("offscreen life: never in the scene", character=character.name)
            return
        missed = self.missed_entries(character)
        if missed and self.absence_fully_archived(character):
            self.pending_returns.pop(character.name, None)
            await self._offscreen_life_if_enough(character, missed)
            return
        # part of the absence is not archived yet: wait for the cut that
        # covers it, so the account spans the whole absence
        self.pending_returns[character.name] = PendingReturn(
            return_scene_time=self.scene.ts
        )
        log.debug("offscreen life pending", character=character.name)

    async def on_archive_add_offscreen(self, event: ArchiveEvent):
        pending = self.pending_returns
        if not pending or event.scene is not self.scene:
            return
        for name in list(pending):
            pending_return = pending[name]
            character = self.scene.get_character(name)
            if character is None or name not in self.scene.active_characters:
                pending.pop(name, None)
                continue
            if not self.absence_fully_archived(character):
                # a long absence is cut into several entries: wait for the last
                continue
            missed = self.missed_entries(character)
            pending.pop(name, None)
            if getattr(pending_return, "combined_entry_briefing", False):
                conversation = get_agent("conversation")
                eligible = (
                    missed if len(missed) >= self.offscreen_life_min_entries else []
                )
                from talemate.agents.conversation.entry_context import (
                    entry_windows,
                    save_entry_windows,
                )

                windows = entry_windows(conversation)
                window = windows.get(character.name)

                briefing_enabled = (
                    conversation.character_knowledge_enabled
                    and conversation.knowledge_brief_characters_on_entry
                    and window is not None
                )
                if briefing_enabled:
                    if window.away_scene_time is None and eligible:
                        try:
                            window.away_scene_time = util.coerce_ts(
                                eligible[0].get("ts")
                            )
                        except (TypeError, ValueError):
                            pass
                        else:
                            save_entry_windows(conversation, windows)
                    await conversation.generate_entry_briefing(
                        character,
                        missed=eligible if self.offscreen_life_enabled else [],
                    )
                elif self.offscreen_life_enabled and eligible:
                    await self._offscreen_life_if_enough(character, eligible)
            elif missed and self.offscreen_life_enabled:
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
        elapsed = self._elapsed(missed)

        length = self.offscreen_life_length
        _, extracted = await Prompt.request(
            "narrator.offscreen-life",
            self.client,
            f"narrate_{length}",
            vars={
                "scene": scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "knowledge_index": KnowledgeIndex.from_scene(scene),
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
        return await self.store_offscreen_life(character, text, missed)

    async def store_offscreen_life(
        self, character: "Character", text: str, missed: list[dict]
    ) -> Fact | None:
        """Store a validated standalone or combined offscreen-life result."""

        if not text:
            log.warning("offscreen life: empty response", character=character.name)
            return None
        scene = self.scene
        fact = await store_offscreen_fact(scene, character.name, text)
        log.debug(
            "offscreen life",
            character=character.name,
            missed=len(missed),
            fact=fact.id,
        )
        return fact
