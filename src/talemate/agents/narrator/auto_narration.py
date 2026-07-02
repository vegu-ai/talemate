from __future__ import annotations

import random

import structlog
from talemate.instance import get_agent

from talemate.agents.base import AgentAction, AgentActionConfig

__all__ = ["AutoNarrationMixin"]

log = structlog.get_logger("talemate.agents.narrator.auto_narration")


class AutoNarrationMixin:
    """
    Adds the `auto_narration` agent action and the helpers that drive it.

    The mixin is consumed by `NarratorAgent` via `AutoNarrationMixin.add_actions(actions)`
    in `init_actions`, mirroring `MemoryRAGMixin`.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["auto_narration"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            label="Auto Narration",
            icon="mdi-script-text-play",
            quick_toggle=True,
            description=(
                "Automatically trigger narration during the scene loop. Master chance "
                "gates whether auto narration fires; weights determine which action is "
                "picked when it does."
            ),
            config={
                "chance": AgentActionConfig(
                    type="number",
                    label="Chance",
                    description="Master chance for auto narration to fire on a tick. 1 = always, 0 = never.",
                    value=0.3,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                ),
                "weights": AgentActionConfig(
                    type="weights",
                    label="Action Weights",
                    description="Relative likelihood of each action when auto narration fires. Always sums to 1.0.",
                    value={
                        "progress_story": 0.5,
                        "narrate_scene": 0.25,
                        "narrate_after_dialogue": 0.25,
                    },
                    choices=[
                        {"value": "progress_story", "label": "Progress Story"},
                        {"value": "narrate_scene", "label": "Narrate Scene"},
                        {
                            "value": "narrate_after_dialogue",
                            "label": "Narrate Environment",
                        },
                    ],
                ),
                "disable_during_scene_direction": AgentActionConfig(
                    type="bool",
                    label="Disable during scene direction",
                    description="Suppress auto narration while scene direction is enabled.",
                    value=True,
                ),
            },
        )

    @property
    def auto_narration_enabled(self) -> bool:
        return self.resolve_enabled("auto_narration")

    @property
    def auto_narration_chance(self) -> float:
        """Master chance (0.0–1.0) that auto narration fires on a tick."""
        return self.resolve_config("auto_narration", "chance")

    @property
    def auto_narration_weights(self) -> dict[str, float]:
        """Relative weights of each candidate action. Sums to ~1.0."""
        return dict(self.resolve_config("auto_narration", "weights"))

    def auto_narration_weight(self, action_name: str) -> float:
        return self.auto_narration_weights.get(action_name, 0.0)

    @property
    def auto_narration_disable_during_scene_direction(self) -> bool:
        return self.resolve_config("auto_narration", "disable_during_scene_direction")

    @property
    def auto_narration_enabled_actions(self) -> list[str]:
        """Names of actions currently eligible to fire under auto narration (weight > 0).

        Honors the same gates as `auto_narration_action` except for the chance roll —
        the answer reflects what *could* fire, not what *will* fire on this tick.
        """
        if not self.auto_narration_enabled or self.auto_narration_chance <= 0.0:
            return []
        if self.auto_narration_disable_during_scene_direction:
            director = get_agent("director")
            if director.direction_enabled_with_override:
                return []
        return [
            name for name, weight in self.auto_narration_weights.items() if weight > 0.0
        ]

    @property
    def auto_narration_action(self) -> str | None:
        """The action to perform on this tick, or None.

        Performs every gate in order: feature toggle, scene-direction suppression,
        master chance roll, weighted action selection over actions with weight > 0.
        """
        if not self.auto_narration_enabled:
            log.debug("auto_narration_action", skip="disabled")
            return None
        if self.auto_narration_disable_during_scene_direction:
            director = get_agent("director")
            if director.direction_enabled_with_override:
                log.debug("auto_narration_action", skip="scene_direction")
                return None
        chance = self.auto_narration_chance
        if chance <= 0.0:
            log.debug("auto_narration_action", skip="chance_zero", chance=chance)
            return None
        roll = random.random()
        if roll >= chance:
            log.debug(
                "auto_narration_action", skip="chance_roll", roll=roll, chance=chance
            )
            return None
        candidates = [
            (name, weight)
            for name, weight in self.auto_narration_weights.items()
            if weight > 0.0
        ]
        if not candidates:
            log.debug("auto_narration_action", skip="no_candidates")
            return None
        names, weights = zip(*candidates)
        chosen = random.choices(names, weights=weights, k=1)[0]
        log.debug(
            "auto_narration_action",
            chosen=chosen,
            roll=roll,
            chance=chance,
            weights=dict(zip(names, weights)),
        )
        return chosen
