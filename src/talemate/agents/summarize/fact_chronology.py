from talemate.agents.base import AgentAction, AgentActionConfig
from talemate.knowledge.chronology import DEFAULTS


class FactChronologyMixin:
    @classmethod
    def add_actions(cls, actions):
        labels = {
            "milestone_half_life": "Milestone half-life (days)",
            "state_half_life": "State half-life (days)",
            "routine_half_life": "Routine half-life (days)",
            "recent_window": "Recent facts window (days)",
            "score_floor": "Older facts score floor",
        }
        descriptions = {
            "milestone_half_life": "Days until a milestone's importance score halves without a restatement.",
            "state_half_life": "Days until a durable state's importance score halves without a restatement.",
            "routine_half_life": "Days until a routine detail's importance score halves without a restatement.",
            "recent_window": "Facts newer than this remain eligible in full. Older facts need a sufficient score or a mention of a present character.",
            "score_floor": "Older facts must score above this, unless they mention a present character. Higher values keep fewer old facts in prompts.",
        }
        actions["fact_chronology"] = AgentAction(
            container=True,
            label="Fact chronology",
            icon="mdi-clock-outline",
            description="Rank facts by importance and time since they were established or restated. Changes prompt selection without changing what characters know or making extra AI requests.",
            config={
                key: AgentActionConfig(
                    type="number",
                    label=labels[key],
                    description=descriptions[key],
                    value=value,
                    min=0.1 if "half_life" in key else 0,
                    max=3 if key == "score_floor" else 3650,
                    step=0.1 if key == "score_floor" or "half_life" in key else 1,
                )
                for key, value in DEFAULTS.items()
            },
        )
