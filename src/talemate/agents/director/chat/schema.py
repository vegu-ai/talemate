import pydantic
from typing import Literal, Any
import uuid

__all__ = [
    "DirectorChatMessage",
    "DirectorChatFunctionAvailable",
    "DirectorChatFunctionSelected",
    "DirectorChat",
    "DirectorChatActionResultMessage",
    "DirectorChatBudgets",
    "DirectorChatResponse",
]


class DirectorChatBudgets(pydantic.BaseModel):
    """
    The budgets for the director chat
    """

    max_tokens: int = 0
    reserved: int = 0
    scene_context_ratio: float = 0.0

    def set_reserved(self, reserved: int):
        self.reserved = reserved

    @pydantic.computed_field(description="The number of available tokens")
    @property
    def available(self) -> int:
        # Ensure we never return negative available tokens
        remaining = self.max_tokens - self.reserved
        return remaining if remaining > 0 else 0

    @pydantic.computed_field(description="The number of tokens for scene context")
    @property
    def scene_context(self) -> int:
        return int(self.scene_context_ratio * self.available)

    @pydantic.computed_field(description="The number of tokens for director chat")
    @property
    def director_chat(self) -> int:
        return int((1 - self.scene_context_ratio) * self.available)


class DirectorChatResponse(pydantic.BaseModel):
    """
    A response from the director
    """

    parsed_response: str
    raw_response: str
    budgets: DirectorChatBudgets
    actions_selected: list[dict] = pydantic.Field(default_factory=list)


class DirectorChatMessage(pydantic.BaseModel):
    """
    A message from the user or the director
    """

    message: str
    source: Literal["director", "user"]
    type: Literal["text", "action_result", "asset_view"] = "text"
    asset_id: str | None = None
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])


class DirectorChatFunctionAvailable(pydantic.BaseModel):
    """
    A function that is available to the director
    """

    name: str
    description: str


class DirectorChatFunctionSelected(pydantic.BaseModel):
    """
    A function that has been selected by the director
    """

    name: str
    instructions: str


class DirectorChat(pydantic.BaseModel):
    """
    A history of messages from the user or the director
    """

    messages: list["DirectorChatMessage | DirectorChatActionResultMessage"]
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])
    mode: Literal["normal", "decisive", "nospoilers"] = "normal"
    confirm_write_actions: bool = True


class DirectorChatActionResultMessage(pydantic.BaseModel):
    """
    A structured message that holds the result of an executed action.
    Always originates from the director side.
    """

    type: Literal["action_result"] = "action_result"
    source: Literal["director"] = "director"
    name: str
    arguments: dict[str, Any] = pydantic.Field(default_factory=dict)
    result: Any = None
    instructions: str | None = None
    status: Literal["success", "error", "rejected"] = "success"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])
