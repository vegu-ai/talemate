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
    "UserInteractionMessage",
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


class UserInteractionMessage(pydantic.BaseModel):
    """
    User interaction message for scene direction history.
    Records when and what the user interacted with.
    """

    type: Literal["user_interaction"] = "user_interaction"
    user_input: str

    @pydantic.computed_field
    @property
    def preview(self) -> str:
        """First 50 characters of user input for display."""
        if not self.user_input:
            return ""
        stripped = self.user_input.strip()
        if len(stripped) > 50:
            return stripped[:50] + "..."
        return stripped


class SceneDirection(pydantic.BaseModel):
    """
    State container for autonomous scene direction.
    Tracks the history of director decisions and actions across turns.
    """

    messages: list[
        "SceneDirectionMessage | SceneDirectionActionResultMessage | UserInteractionMessage"
    ] = pydantic.Field(default_factory=list)
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])
    turn_count: int = 0


class SceneDirectionTurnBalance(pydantic.BaseModel):
    """
    Metrics tracking recent turn participation across the narrator and active characters.

    These metrics are computed over the last N messages in scene.history to identify
    which participants (narrator, characters) have been active or neglected.
    """

    # Total messages analyzed
    total_messages_analyzed: int = 0

    # Narrator activity
    narrator_message_count: int = 0
    narrator_percentage: float = 0.0
    narrator_overused: bool = False
    narrator_neglected: bool = False

    # Character activity tracking
    character_message_counts: dict[str, int] = pydantic.Field(default_factory=dict)
    character_percentages: dict[str, float] = pydantic.Field(default_factory=dict)
    neglected_characters: list[str] = pydantic.Field(default_factory=list)

    # Active characters in scene (for comparison)
    active_character_names: list[str] = pydantic.Field(default_factory=list)
