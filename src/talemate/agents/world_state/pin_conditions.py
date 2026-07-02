from __future__ import annotations

import json

import structlog

import talemate.emit.async_signals
from talemate.events import GameLoopEvent
from talemate.prompts import Prompt

from talemate.agents.base import AgentAction, AgentActionConfig, set_processing

log = structlog.get_logger("talemate.agents.world_state")


class WorldStatePinConditionsMixin:
    """
    World-state manager agent mixin that handles conditional context pins —
    evaluating each pin's condition via the LLM, toggling the pin accordingly,
    and ticking the decay countdown that auto-deactivates stale pins.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["check_pin_conditions"] = AgentAction(
            enabled=True,
            can_be_disabled=True,
            container=True,
            icon="mdi-pin",
            label="Update conditional context pins",
            description="Will evaluate context pins conditions and toggle those pins accordingly. Runs automatically every N turns.",
            config={
                "turns": AgentActionConfig(
                    type="number",
                    label="Turns",
                    description="Number of turns to wait before checking conditions.",
                    value=2,
                    min=1,
                    max=100,
                    step=1,
                )
            },
        )

    # config property helpers

    @property
    def check_pin_conditions_enabled(self) -> bool:
        return self.resolve_enabled("check_pin_conditions")

    @property
    def check_pin_conditions_turns(self):
        return self.resolve_config("check_pin_conditions", "turns")

    # signal connect

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop").connect(
            self.on_game_loop_check_pin_conditions
        )

    async def on_game_loop_check_pin_conditions(self, emission: GameLoopEvent):
        """
        Called once per scene-loop round.
        """
        if not self.enabled:
            return

        await self.auto_check_pin_conditions()

    # methods

    async def auto_check_pin_conditions(self):
        if not self.enabled:
            return

        if not self.check_pin_conditions_enabled:
            return

        if (
            self.next_pin_check % self.check_pin_conditions_turns != 0
            or self.next_pin_check == 0
        ):
            self.next_pin_check += 1
            return

        self.next_pin_check = 0

        await self.check_pin_conditions()

    @set_processing
    async def check_pin_conditions(
        self,
    ):
        """
        Checks if any context pin conditions
        """

        log.debug("check_pin_conditions", turns=self.check_pin_conditions_turns)

        world_state = self.scene.world_state

        state_change = False

        # Build list of pins to check, honoring decay semantics
        pins_to_check = {}
        for entry_id, pin in world_state.pins.items():
            # Skip game-state-controlled pins from the LLM loop
            if pin.gamestate_condition:
                continue
            # Initialize countdown if active with decay but no due set
            if pin.active and pin.decay and not pin.decay_due:
                pin.decay_due = pin.decay

            # Only pins with conditions are checked by the LLM
            if not pin.condition:
                continue

            # If pin is active and has decay, skip checks until it's about to decay (decay_due == 1)
            if (
                pin.active
                and pin.decay
                and (pin.decay_due is not None)
                and pin.decay_due > 1
            ):
                continue

            # Include pin for checking when it has no decay, is inactive, or is about to decay
            if (not pin.decay) or (not pin.active) or (pin.decay_due == 1):
                pins_to_check[entry_id] = {
                    "condition": pin.condition,
                    "state": pin.condition_state,
                }

        # Early return if nothing to check, but still tick decay
        if not pins_to_check:
            for entry_id, pin in world_state.pins.items():
                # Game-state-controlled pins do not decay
                if pin.gamestate_condition:
                    continue
                if pin.active and pin.decay:
                    if not pin.decay_due:
                        pin.decay_due = pin.decay
                    pin.decay_due -= self.check_pin_conditions_turns
                    log.debug("applying pin decay", pin=pin, decay_due=pin.decay_due)
                    if pin.decay_due <= 0:
                        log.debug("pin decay expired", pin=pin, decay_due=pin.decay_due)
                        pin.active = False
                        pin.decay_due = None
                        state_change = True
            if state_change:
                await self.scene.load_active_pins()
                self.scene.emit_status()
            return

        first_entry_id = list(pins_to_check.keys())[0]

        _, answers = await Prompt.request(
            "world_state.check-pin-conditions",
            self.client,
            "analyze",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "previous_states": json.dumps(pins_to_check, indent=2),
                "coercion": {first_entry_id: {"condition": ""}},
            },
        )

        # Apply LLM results
        for entry_id, answer in answers.items():
            if entry_id not in world_state.pins:
                log.debug(
                    "check_pin_conditions",
                    entry_id=entry_id,
                    answer=answer,
                    msg="entry_id not found in world_state.pins (LLM failed to produce a clean response)",
                )
                continue

            log.debug("check_pin_conditions", entry_id=entry_id, answer=answer)
            state = answer.get("state")
            pin = world_state.pins[entry_id]
            if state is True or (
                isinstance(state, str) and state.lower() in ["true", "yes", "y"]
            ):
                prev_state = pin.condition_state
                pin.condition_state = True
                if not pin.active:
                    state_change = True
                pin.active = True
                # Refresh decay countdown when condition is true and pin stays/turns active
                if pin.decay:
                    pin.decay_due = pin.decay
                if prev_state != pin.condition_state:
                    state_change = True
            else:
                if pin.condition_state is not False or pin.active:
                    pin.condition_state = False
                    pin.active = False
                    # Clear countdown when deactivated
                    pin.decay_due = None
                    state_change = True

        # Tick decay counters for all active pins with decay
        for entry_id, pin in world_state.pins.items():
            # Game-state-controlled pins do not decay
            if pin.gamestate_condition:
                continue
            if pin.active and pin.decay:
                if not pin.decay_due:
                    pin.decay_due = pin.decay
                # Decrement once per check cycle
                pin.decay_due -= 1
                if pin.decay_due <= 0:
                    # Auto-deactivate on expiry
                    pin.active = False
                    pin.decay_due = None
                    state_change = True

        if state_change:
            await self.scene.load_active_pins()
            self.scene.emit_status()
