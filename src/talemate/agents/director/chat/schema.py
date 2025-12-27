import pydantic
from typing import Literal
import uuid

from talemate.agents.director.action_core.schema import (
    ActionCoreBudgets,
    ActionCoreMessage,
    ActionCoreResultMessage,
)

__all__ = [
    "DirectorChatMessage",
    "DirectorChatFunctionSelected",
    "DirectorChat",
    "DirectorChatActionResultMessage",
    "DirectorChatBudgets",
    "DirectorChatResponse",
]


class DirectorChatBudgets(ActionCoreBudgets):
    """
    Chat-specific budgets with director_chat alias for backward compatibility.
    """

    @pydantic.computed_field(description="The number of tokens for director chat")
    @property
    def director_chat(self) -> int:
        return self.history_budget


class DirectorChatResponse(pydantic.BaseModel):
    """
    A response from the director
    """

    parsed_response: str
    raw_response: str
    budgets: DirectorChatBudgets
    actions_selected: list[dict] = pydantic.Field(default_factory=list)


class DirectorChatMessage(ActionCoreMessage):
    """
    Chat message - extends base with user source and asset support.
    """

    source: Literal["director", "user"]
    type: Literal["text", "action_result", "asset_view"] = "text"
    asset_id: str | None = None


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


class DirectorChatActionResultMessage(ActionCoreResultMessage):
    """
    Chat action result - extends base with 'rejected' status.
    """

    status: Literal["success", "error", "rejected"] = "success"
