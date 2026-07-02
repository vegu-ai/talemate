from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

import talemate.emit.async_signals
from talemate.events import GameLoopEvent
from talemate.prompts import Prompt
from talemate.prompts.response import AnchorExtractor, ResponseSpec
from talemate.scene_message import ReinforcementMessage

from talemate.agents.base import AgentAction, set_processing

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger("talemate.agents.world_state")


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
        """

        for reinforcement in self.scene.world_state.reinforce:
            # Skip character reinforcements if require_active is True and character is not active
            if (
                reinforcement.require_active
                and reinforcement.character
                and not self.scene.character_is_active(reinforcement.character)
            ):
                continue

            if reinforcement.due <= 0 or force:
                await self.update_reinforcement(
                    reinforcement.question, reinforcement.character, reset=reset
                )
            else:
                reinforcement.due -= 1

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

        message = ReinforcementMessage(message="")
        message.set_source(
            "world_state",
            "update_reinforcement",
            question=question,
            character=character,
        )

        if reset and reinforcement.insert == "sequential":
            self.scene.pop_history(
                typ="reinforcement", meta_hash=message.meta_hash, all=True
            )

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

        answer = extracted["response"]

        reinforcement.answer = answer
        reinforcement.due = reinforcement.interval

        # remove any recent previous reinforcement message with same question
        # to avoid overloading the near history with reinforcement messages
        if not reset:
            self.scene.pop_history(
                typ="reinforcement", meta_hash=message.meta_hash, max_iterations=10
            )

        if reinforcement.insert == "sequential":
            # insert the reinforcement message at the current position
            message.message = answer
            log.debug("update_reinforcement", message=message, reset=reset)
            await self.scene.push_history(message)

        # if reinforcement has a character name set, update the character detail
        if reinforcement.character:
            character = self.scene.get_character(reinforcement.character)
            await character.set_detail(reinforcement.question, answer)

        else:
            # set world entry
            await self.scene.world_state_manager.save_world_entry(
                reinforcement.question,
                reinforcement.as_context_line,
                {},
            )

        self.scene.world_state.emit()

        return message
