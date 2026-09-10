from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import structlog

import talemate.emit.async_signals
from talemate.events import GameLoopEvent
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.reinforcements import (
    prepare_reinforcement_source,
    write_reinforcement_entry,
)
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.prompts.response import AnchorExtractor, ResponseSpec
from talemate.scene_message import ReinforcementMessage
from talemate.util.async_tools import bounded_gather_apply

from talemate.agents.base import AgentAction, set_processing

if TYPE_CHECKING:
    from talemate.tale_mate import Character
    from talemate.world_state import Reinforcement

log = structlog.get_logger("talemate.agents.world_state")


class PreparedReinforcement(NamedTuple):
    reinforcement: "Reinforcement"
    message: ReinforcementMessage


class WorldStateReinforcementsMixin:
    """
    World-state manager agent mixin that handles state reinforcements — the
    periodic re-querying of tracked world/character questions and writing the
    answers back into the scene (as detail, world entry, and/or inline message).
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["update_reinforcements"] = AgentAction(
            enabled=True,
            can_be_disabled=True,
            container=True,
            icon="mdi-image-auto-adjust",
            label="Update state reinforcements",
            description="Will attempt to update any due state reinforcements.",
            config={},
        )

    # config property helpers

    @property
    def update_reinforcements_enabled(self) -> bool:
        return self.resolve_enabled("update_reinforcements")

    # signal connect

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop").connect(
            self.on_game_loop_update_reinforcements
        )

    async def on_game_loop_update_reinforcements(self, emission: GameLoopEvent):
        """
        Called once per scene-loop round.
        """
        if not self.enabled:
            return

        await self.auto_update_reinforcments()

    # methods

    async def auto_update_reinforcments(self):
        if not self.enabled:
            return

        if not self.update_reinforcements_enabled:
            return

        await self.update_reinforcements()

    @set_processing
    async def update_reinforcements(self, force: bool = False, reset: bool = False):
        """
        Queries due worldstate re-inforcements

        When the client supports concurrent inference, the LLM queries for all
        due reinforcements run concurrently against the same scene snapshot
        and their results apply sequentially in list order afterwards (history
        pushes and state writes stay ordered); otherwise each reinforcement is
        queried and applied one at a time.
        """

        due = []

        for reinforcement in self.scene.world_state.reinforce:
            # Skip character reinforcements if require_active is True and character is not active
            if (
                reinforcement.require_active
                and reinforcement.character
                and not self.scene.character_is_active(reinforcement.character)
            ):
                continue

            if reinforcement.due <= 0 or force:
                due.append(reinforcement)
            else:
                reinforcement.due -= 1

        supports_concurrent = bool(
            self.client and self.client.supports_concurrent_inference
        )

        # reset pops each item's prior history in _prepare_reinforcement,
        # before any answer exists - run it one item at a time so a
        # mid-batch failure cannot have wiped history it never replaced
        if not supports_concurrent or reset or len(due) < 2:
            for reinforcement in due:
                await self.update_reinforcement(
                    reinforcement.question, reinforcement.character, reset=reset
                )
            return

        prepared = [
            PreparedReinforcement(
                reinforcement, self._prepare_reinforcement(reinforcement, reset)
            )
            for reinforcement in due
        ]

        async def generate(item: PreparedReinforcement) -> str:
            return await self.generate_reinforcement(item.reinforcement, reset)

        async def apply(item: PreparedReinforcement, answer: str):
            await self._apply_reinforcement(
                item.reinforcement, item.message, answer, reset
            )

        def on_error(item: PreparedReinforcement, error: BaseException):
            log.error(
                "update_reinforcements",
                question=item.reinforcement.question,
                character=item.reinforcement.character,
                error=str(error),
                exc_info=error,
            )

        await bounded_gather_apply(prepared, generate, apply, on_error=on_error)

    @set_processing
    async def update_reinforcement(
        self, question: str, character: "str | Character" = None, reset: bool = False
    ) -> str:
        """
        Queries a single re-inforcement
        """

        if isinstance(character, self.scene.Character):
            character = character.name

        message = None
        idx, reinforcement = await self.scene.world_state.find_reinforcement(
            question, character
        )

        if not reinforcement:
            log.warning(
                "Reinforcement not found", question=question, character=character
            )
            return

        message = self._prepare_reinforcement(reinforcement, reset)
        answer = await self.generate_reinforcement(reinforcement, reset)
        return await self._apply_reinforcement(reinforcement, message, answer, reset)

    def _prepare_reinforcement(
        self, reinforcement: "Reinforcement", reset: bool
    ) -> ReinforcementMessage:
        message = ReinforcementMessage(message="")
        message.set_source(
            "world_state",
            "update_reinforcement",
            question=reinforcement.question,
            character=reinforcement.character,
        )

        if reset and reinforcement.insert == "sequential":
            self.scene.pop_history(
                typ="reinforcement", meta_hash=message.meta_hash, all=True
            )

        return message

    @set_processing
    async def generate_reinforcement(
        self, reinforcement: "Reinforcement", reset: bool
    ) -> str:
        if reinforcement.insert == "sequential":
            kind = "analyze_freeform_medium_short"
        else:
            kind = "analyze_freeform"

        response, extracted = await Prompt.request(
            "world_state.update-reinforcements",
            self.client,
            kind,
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "question": reinforcement.question,
                "instructions": reinforcement.instructions or "",
                "character": (
                    self.scene.get_character(reinforcement.character)
                    if reinforcement.character
                    else None
                ),
                "answer": (reinforcement.answer if not reset else None) or "",
                "reinforcement": reinforcement,
            },
            response_spec=ResponseSpec(
                extractors={
                    "response": AnchorExtractor(
                        left="<ANSWER>",
                        right="</ANSWER>",
                        fallback_to_full=True,
                    ),
                },
            ),
        )

        return extracted["response"]

    async def _apply_reinforcement(
        self,
        reinforcement: "Reinforcement",
        message: ReinforcementMessage,
        answer: str,
        reset: bool,
    ) -> ReinforcementMessage:
        changed = answer != reinforcement.answer
        reinforcement.answer = answer
        reinforcement.due = reinforcement.interval

        # remove any recent previous reinforcement message with same question
        # to avoid overloading the near history with reinforcement messages
        if not reset:
            self.scene.pop_history(
                typ="reinforcement", meta_hash=message.meta_hash, max_iterations=10
            )

        perception = character_knowledge_enabled(self.scene)
        if reinforcement.insert == "sequential":
            message.message = answer
        if perception:
            source = (
                message
                if reinforcement.insert == "sequential"
                else prepare_reinforcement_source(
                    self.scene, reinforcement, new_answer=changed
                )
            )
            await write_reinforcement_entry(self.scene, reinforcement, source)

        self.scene.world_state.emit()
        if reinforcement.insert == "sequential":
            await self.scene.push_history(message)
        elif perception:
            await get_agent("summarizer").finalize_perceptions(self.scene, [])

        if not perception:
            if reinforcement.character:
                character = self.scene.get_character(reinforcement.character)
                await character.set_detail(reinforcement.question, answer)
            else:
                await self.scene.world_state_manager.save_world_entry(
                    reinforcement.question, reinforcement.as_context_line, {}
                )
        self.scene.world_state.emit()

        return message
