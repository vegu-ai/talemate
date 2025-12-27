import pydantic
from typing import Literal
import uuid

from talemate.agents.director.action_core.schema import (
    ActionCoreBudgets,
    ActionCoreMessage,
    ActionCoreResultMessage,
)

__all__ = [
    "SceneDirectionMessage",
    "SceneDirectionActionResultMessage",
    "SceneDirection",
    "SceneDirectionBudgets",
    "SceneDirectionTurnBalance",
]


class SceneDirectionBudgets(ActionCoreBudgets):
    """
    Direction-specific budgets with direction_history alias.
    """

    @pydantic.computed_field(description="The number of tokens for direction history")
    @property
    def direction_history(self) -> int:
        return self.history_budget


class SceneDirectionMessage(ActionCoreMessage):
    """
    Direction message - adds summary type.
    Unlike chat messages, these are always from the director.
    """

    type: Literal["text", "action_result", "summary"] = "text"


class SceneDirectionActionResultMessage(ActionCoreResultMessage):
    """
    Direction action result - same as base, no rejected status needed.
    """

    pass


class SceneDirection(pydantic.BaseModel):
    """
    State container for autonomous scene direction.
    Tracks the history of director decisions and actions across turns.
    """

    messages: list["SceneDirectionMessage | SceneDirectionActionResultMessage"] = (
        pydantic.Field(default_factory=list)
    )
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])
    turn_count: int = 0


class SceneDirectionTurnBalance(pydantic.BaseModel):
    """
    Lightweight metrics used to encourage yielding to the user and avoiding
    multiple autonomous narration turns in a row.

    These counters are computed over recent `scene.history` entries, walking
    backwards until the most recent user-controlled action (or a time passage).
    """

    narrator_turns_since_user: int = 0
    non_user_character_turns_since_user: int = 0
    non_user_character_distinct_since_user: int = 0
    non_user_character_names_since_user: list[str] = pydantic.Field(
        default_factory=list
    )
    turns_since_user: int = 0
    found_user_turn: bool = False
