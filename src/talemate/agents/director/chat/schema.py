import time

import pydantic
from typing import Literal
import uuid

from talemate.agents.director.action_core.schema import (
    ActionCoreBudgets,
    ActionCoreMessage,
    ActionCoreResultMessage,
)
from talemate.agents.director.chat.settings import ChatModeSettings

__all__ = [
    "DirectorChatMessage",
    "DirectorChatBatchResultMessage",
    "DirectorChatFunctionSelected",
    "DirectorChat",
    "DirectorChatActionResultMessage",
    "DirectorChatBudgets",
    "DirectorChatResponse",
    "DirectorChatListEntry",
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


class DirectorChatBatchResultMessage(DirectorChatMessage):
    """Batch details with counts of all proposed calls, including nested calls."""

    type: Literal["batch_result"] = "batch_result"
    source: Literal["director"] = "director"
    applied_count: int = pydantic.Field(ge=0)
    not_applied_count: int = pydantic.Field(ge=0)


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

    messages: list[
        "DirectorChatMessage | DirectorChatBatchResultMessage | DirectorChatActionResultMessage"
    ]
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])
    title: str | None = None
    mode: Literal[
        "normal", "decisive", "nospoilers", "generate_arc", "generate_arc_expand"
    ] = "normal"
    confirm_write_actions: bool = True
    created_at: float = pydantic.Field(default_factory=time.time)
    plan_id: str | None = None
    modes: ChatModeSettings = pydantic.Field(default_factory=ChatModeSettings)


class DirectorChatListEntry(pydantic.BaseModel):
    """
    Lightweight chat entry for listing chats without full message history.
    """

    id: str
    title: str | None = None
    mode: Literal[
        "normal", "decisive", "nospoilers", "generate_arc", "generate_arc_expand"
    ] = "normal"
    created_at: float = 0.0


class DirectorChatActionResultMessage(ActionCoreResultMessage):
    """
    Chat action result - extends base with 'rejected' status.
    """

    status: Literal["success", "error", "rejected"] = "success"
