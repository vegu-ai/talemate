from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple

import structlog

import talemate.emit.async_signals
from talemate.events import GameLoopEvent
from talemate.decisions.budget import fit_list
from talemate.decisions.characters import short_description
from talemate.decisions.gate import decision_gate, decision_gate_enabled
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.reinforcements import (
    prepare_reinforcement_source,
    write_reinforcement_entry,
)
from talemate.prompts import Prompt
from talemate.agents.world_state.response_specs import REINFORCEMENT_ANSWER_SPEC
from talemate.scene_message import ReinforcementMessage
from talemate.util.async_tools import bounded_gather_apply
from talemate.util.prompt import condensed

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    set_processing,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Character
    from talemate.world_state import Reinforcement

REINFORCEMENT_HISTORY_TYPES = ("character", "narrator", "time")
REINFORCEMENT_LEAD_IN = 3
# fits the default interval's 23 messages at about 175 tokens each
REINFORCEMENT_HISTORY_CAP = 4096
REINFORCEMENT_PINS_CAP = 512

log = structlog.get_logger("talemate.agents.world_state")

talemate.emit.async_signals.register("agent.world_state.reinforcement.skipped")


def reinforcement_history_window(interval: int) -> int:
    """
    Story messages a tracked-state decision reads: about `interval` rounds of
    two messages, plus a lead-in from before the last update.
    """
    return 2 * max(interval, 1) + REINFORCEMENT_LEAD_IN


class ReinforcementSkippedEmission(AgentEmission):
    """
    The decision model found a tracked state unchanged, so no update request
    ran and the state keeps its answer until its next interval.
    """

    question: str
    character: str | None = None
    answer: str | None = None
    interval: int


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
            config={
                "decision_model": AgentActionConfig(
                    type="bool",
                    label="Use Decision Model",
                    description="Skip a scheduled update when the decision model is sure the tracked state has not changed. A wrong answer can delay an update; manual updates always run.",
                    value=True,
                ),
            },
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
        queried and applied one at a time. With a decision gate, batch clients
        retain that generation/application boundary but requests run sequentially.
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

        use_decision = (
            not force
            and not reset
            and decision_gate_enabled(
                self.resolve_config("update_reinforcements", "decision_model")
            )
        )

        supports_concurrent = bool(
            self.client and self.client.supports_concurrent_inference
        )

        # reset pops each item's prior history in _prepare_reinforcement,
        # before any answer exists - run it one item at a time so a
        # mid-batch failure cannot have wiped history it never replaced
        if not supports_concurrent or reset or len(due) < 2:
            for reinforcement in due:
                await self.update_reinforcement(
                    reinforcement.question,
                    reinforcement.character,
                    reset=reset,
                    decision_model=use_decision,
                )
            return

        prepared = [
            PreparedReinforcement(
                reinforcement, self._prepare_reinforcement(reinforcement, reset)
            )
            for reinforcement in due
        ]

        async def generate(item: PreparedReinforcement) -> str | Literal[False]:
            return await self.generate_reinforcement(
                item.reinforcement, reset, decision_model=use_decision
            )

        async def apply(item: PreparedReinforcement, answer: str | Literal[False]):
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

        await bounded_gather_apply(
            prepared,
            generate,
            apply,
            max_concurrent=1 if use_decision else 3,
            on_error=on_error,
        )

    @set_processing
    async def update_reinforcement(
        self,
        question: str,
        character: "str | Character" = None,
        reset: bool = False,
        *,
        decision_model: bool = False,
    ) -> ReinforcementMessage | None:
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
        answer = await self.generate_reinforcement(
            reinforcement, reset, decision_model=decision_model
        )
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

    def reinforcement_decision_history(
        self, reinforcement: "Reinforcement"
    ) -> list[str]:
        window = reinforcement_history_window(reinforcement.interval)
        history = []
        for message in reversed(self.scene.history):
            if message.typ not in REINFORCEMENT_HISTORY_TYPES or message.hidden:
                continue
            history.insert(0, str(message))
            if len(history) >= window:
                break
        return history

    def reinforcement_decision_state(
        self, reinforcement: "Reinforcement", budget: int | None
    ) -> dict:
        scene = self.scene
        character = (
            scene.get_character(reinforcement.character)
            if reinforcement.character
            else None
        )
        pins = [
            f"{pin.title}: {condensed(pin.time_aware_text)}"
            for pin in scene.active_pins
        ]
        state = {
            "question": reinforcement.question,
            "character": reinforcement.character,
            "character_description": short_description(character)
            if character
            else None,
            "instructions": reinforcement.instructions,
            "previous_answer": reinforcement.answer,
            "last_updated_ts": reinforcement.updated_ts,
            "current_ts": scene.ts,
            "pins": fit_list({}, "pins", pins, REINFORCEMENT_PINS_CAP)["pins"],
            # the window messages the caps left out; fitted with the largest
            # count so the real one cannot push the state past the budget
            "history_left_out": 0,
            "history": [],
        }
        window = self.reinforcement_decision_history(reinforcement)
        capped = fit_list({}, "history", window, REINFORCEMENT_HISTORY_CAP)["history"]
        fitted = fit_list(
            {**state, "history_left_out": len(window)}, "history", capped, budget
        )
        return {**fitted, "history_left_out": len(window) - len(fitted["history"])}

    @set_processing
    async def generate_reinforcement(
        self,
        reinforcement: "Reinforcement",
        reset: bool,
        *,
        decision_model: bool = False,
    ) -> str | Literal[False]:
        if reinforcement.insert == "sequential":
            kind = "analyze_freeform_medium_short"
        else:
            kind = "analyze_freeform"

        scene = self.scene
        variables = {
            "scene": scene,
            "max_tokens": self.client.max_token_length,
            "question": reinforcement.question,
            "instructions": reinforcement.instructions or "",
            "character": (
                scene.get_character(reinforcement.character)
                if reinforcement.character
                else None
            ),
            "answer": (reinforcement.answer if not reset else None) or "",
            "reinforcement": reinforcement,
        }

        async def request_update() -> str:
            _, extracted = await Prompt.request(
                "world_state.update-reinforcements",
                self.client,
                kind,
                vars=variables,
                response_spec=REINFORCEMENT_ANSWER_SPEC,
            )
            return extracted["response"]

        if not decision_gate_enabled(decision_model) or not reinforcement.answer:
            return await request_update()

        async def fallback(ids):
            return {"state": await request_update()}

        result = await decision_gate(
            "world_state.decision-reinforcement",
            enabled=True,
            candidates={"state": [False]},
            variables=lambda: {
                "state": lambda budget: self.reinforcement_decision_state(
                    reinforcement, budget
                )
            },
            fallback=fallback,
            is_current=lambda: self.scene is scene
            and reinforcement in scene.world_state.reinforce,
        )
        return result["state"]

    async def _apply_reinforcement(
        self,
        reinforcement: "Reinforcement",
        message: ReinforcementMessage,
        answer: str | Literal[False],
        reset: bool,
    ) -> ReinforcementMessage | None:
        if answer is False:
            reinforcement.due = reinforcement.interval
            self.scene.world_state.emit()
            await talemate.emit.async_signals.get(
                "agent.world_state.reinforcement.skipped"
            ).send(
                ReinforcementSkippedEmission(
                    agent=self,
                    question=reinforcement.question,
                    character=reinforcement.character,
                    answer=reinforcement.answer,
                    interval=reinforcement.interval,
                )
            )
            return None

        changed = answer != reinforcement.answer
        reinforcement.set_answer(self.scene, answer)
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
            await self.scene.push_history(message, emit_message=True)

        if not perception:
            await self.scene.world_state.store_reinforcement_answer(reinforcement)
        self.scene.world_state.emit()

        return message
