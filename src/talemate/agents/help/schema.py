import time
import uuid
from typing import Any, Literal

import pydantic

__all__ = [
    "HelpChat",
    "HelpChatMessage",
    "HelpChatDocResultMessage",
    "HelpChatListEntry",
    "HelpChatStore",
]


class HelpChatMessage(pydantic.BaseModel):
    """
    A conversational message in a help chat.
    """

    message: str = ""
    source: Literal["help", "user"]
    type: Literal["text"] = "text"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.message


class HelpChatDocResultMessage(pydantic.BaseModel):
    """
    The result of a documentation tool call made by the help agent.
    """

    name: str
    arguments: dict[str, Any] = pydantic.Field(default_factory=dict)
    result: Any = None
    type: Literal["doc_result"] = "doc_result"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))

    def __str__(self) -> str:
        return f"{self.name}({self.arguments}) -> {self.result}"


class HelpChat(pydantic.BaseModel):
    """
    A multi-turn conversation with the help agent.
    """

    messages: list[HelpChatMessage | HelpChatDocResultMessage] = pydantic.Field(
        default_factory=list
    )
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:10])
    title: str | None = None
    scene_aware: bool = False
    created_at: float = pydantic.Field(default_factory=time.time)


class HelpChatListEntry(pydantic.BaseModel):
    """
    Lightweight chat entry for listing chats without full message history.
    """

    id: str
    title: str | None = None
    created_at: float = 0.0


class HelpChatStore(pydantic.BaseModel):
    """
    On-disk store for help chats. Help chats are application level (not tied
    to a scene), so they persist to their own file rather than scene state.
    """

    chats: dict[str, HelpChat] = pydantic.Field(default_factory=dict)
    last_active_chat_id: str | None = None
