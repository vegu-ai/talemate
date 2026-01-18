import pydantic
from typing import Literal, Any
import uuid

__all__ = [
    "ActionCoreBudgets",
    "ActionCoreMessage",
    "ActionCoreResultMessage",
    "ActionCoreFunctionAvailable",
    "ActionCoreCallbackGroup",
]


class ActionCoreBudgets(pydantic.BaseModel):
    """
    Base budgets model for director action features.
    Tracks token allocation between scene context and history.
    """

    max_tokens: int = 0
    reserved: int = 0
    scene_context_ratio: float = 0.0
    max_gamestate_tokens: int = 1024

    def set_reserved(self, reserved: int):
        self.reserved = reserved

    @pydantic.computed_field(description="The number of available tokens")
    @property
    def available(self) -> int:
        remaining = self.max_tokens - self.reserved
        return remaining if remaining > 0 else 0

    @pydantic.computed_field(description="The number of tokens for scene context")
    @property
    def scene_context(self) -> int:
        return int(self.scene_context_ratio * self.available)

    @pydantic.computed_field(description="The number of tokens for history")
    @property
    def history_budget(self) -> int:
        return int((1 - self.scene_context_ratio) * self.available)


class ActionCoreMessage(pydantic.BaseModel):
    """
    Base message model for director action features.
    Represents a text message from the director.
    """

    message: str
    source: Literal["director"] = "director"
    type: Literal["text", "action_result", "summary"] = "text"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])


class ActionCoreResultMessage(pydantic.BaseModel):
    """
    Base action result message model.
    Holds the result of an executed action.
    """

    type: Literal["action_result"] = "action_result"
    source: Literal["director"] = "director"
    name: str
    arguments: dict[str, Any] = pydantic.Field(default_factory=dict)
    result: Any = None
    instructions: str | None = None
    status: Literal["success", "error"] = "success"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])


class ActionCoreCallbackGroup(pydantic.BaseModel):
    """
    Represents a group of callbacks/sub-actions for an action.
    """

    group_name: str
    callbacks: list[dict[str, Any]] = pydantic.Field(
        default_factory=list,
        description="List of callback descriptors with title, description, and examples",
    )


class ActionCoreFunctionAvailable(pydantic.BaseModel):
    """
    Describes an action that is available to the director.
    """

    name: str
    description: str
    callback_groups: list[ActionCoreCallbackGroup] = pydantic.Field(
        default_factory=list,
        description="Structured callback groups for this action",
    )
