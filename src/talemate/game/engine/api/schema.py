from enum import Enum
from typing import TYPE_CHECKING

import pydantic

from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
    TimePassageMessage,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Character


__all__ = [
    "CharacterSchema",
    "CharacterMessageSchema",
    "NarratorMessageSchema",
    "DirectorMessageSchema",
    "TimePassageMessageSchema",
    "ReinforcementMessageSchema",
    "VariableSchema",
    "StatusEnum",
    "StatusEmission",
    "MessageTypes",
]


### Scene


class CharacterSchema(pydantic.BaseModel):
    """
    Describes a character in the scene

    Properties:

    - name: str = The name of the character
    - base_attributes: dict[str, str | int | float | bool] = The base attributes of the character
    - details: dict[str, str] 0 The details of the character
    - gender: str - free form gender dewscription
    - color: str - name color in the scene message
    - is_player: bool - Whether the character is controlled by the user
    """

    name: str
    base_attributes: dict[str, str | int | float | bool]
    details: dict[str, str]
    gender: str
    color: str
    is_player: bool = False

    @classmethod
    def from_character(cls, character: "Character") -> "CharacterSchema":
        from talemate.tale_mate import Character

        assert isinstance(character, Character), (
            f"Expected Character, got {type(character)}"
        )

        return cls(
            name=character.name,
            base_attributes=character.base_attributes,
            details=character.details,
            gender=character.gender,
            color=character.color,
            is_player=character.is_player,
        )


### Messages


class MessageTypes(str, Enum):
    character = "character"
    narrator = "narrator"
    director = "director"
    time_passage = "time_passage"
    reinforcement = "reinforcement"


class CharacterMessageSchema(pydantic.BaseModel):
    """
    Describes a scene message for a player controlled character

    Properties

    - message: str - The message content
    - raw: str - The raw message content
    - id: int - The unique message id
    - source: str - The source of the message (character name)
    - hidden: bool - Whether the message is hidden
    """

    message: str
    raw: str
    id: int
    source: str
    hidden: bool

    @classmethod
    def from_message(cls, message: "CharacterMessage") -> "CharacterMessageSchema":
        assert isinstance(message, CharacterMessage), (
            f"Expected CharacterMessage, got {type(message)}"
        )

        return cls(
            message=message.message,
            raw=message.raw,
            id=message.id,
            source=message.source,
            hidden=message.hidden,
        )


class NarratorMessageSchema(pydantic.BaseModel):
    """
    Describes a scene message for the narrator

    Properties

    - message: str - The message content
    - raw: str - The raw message content
    - id: int - The unique message id
    - hidden: bool - Whether the message is hidden
    """

    message: str
    raw: str
    id: int
    hidden: bool

    @classmethod
    def from_message(cls, message: "NarratorMessage") -> "NarratorMessageSchema":
        assert isinstance(message, NarratorMessage), (
            f"Expected NarratorMessage, got {type(message)}"
        )

        return cls(
            message=message.message,
            raw=message.raw,
            id=message.id,
            hidden=message.hidden,
        )


class DirectorMessageSchema(pydantic.BaseModel):
    """
    Describes a scene message for the director

    Properties
    - message: str - The message content
    - raw: str - The raw message content
    - id: int - The unique message id
    - hidden: bool - Whether the message is hidden
    """

    message: str
    raw: str
    id: int
    hidden: bool

    @classmethod
    def from_message(cls, message: "DirectorMessage") -> "DirectorMessageSchema":
        assert isinstance(message, DirectorMessage), (
            f"Expected DirectorMessage, got {type(message)}"
        )

        return cls(
            message=message.message,
            raw=message.raw,
            id=message.id,
            hidden=message.hidden,
        )


class TimePassageMessageSchema(pydantic.BaseModel):
    """
    Desccribes a scene message for a time passage

    Properties

    - message: str - The message content
    - raw: str - The raw message content
    - id: int - The unique message id
    - source: str - The source of the message
    - ts: str - The time passage (iso8601 duration)
    - hidden: bool - Whether the message is hidden
    """

    message: str
    raw: str
    id: int
    source: str
    ts: str
    hidden: bool

    @classmethod
    def from_message(cls, message: "TimePassageMessage") -> "TimePassageMessageSchema":
        assert isinstance(message, TimePassageMessage), (
            f"Expected TimePassageMessage, got {type(message)}"
        )

        return cls(
            message=message.message,
            raw=message.raw,
            id=message.id,
            source=message.source,
            ts=message.ts,
            hidden=message.hidden,
        )


class ReinforcementMessageSchema(pydantic.BaseModel):
    """
    Describes a scene message for a state reinforcement

    Properties

    - message: str - The message content
    - raw: str - The raw message content
    - id: int - The unique message id
    - source: str - The source of the message
    - hidden: bool - Whether the message is hidden
    """

    message: str
    raw: str
    id: int
    source: str
    hidden: bool

    @classmethod
    def from_message(
        cls, message: "ReinforcementMessage"
    ) -> "ReinforcementMessageSchema":
        assert isinstance(message, ReinforcementMessage), (
            f"Expected ReinforcementMessage, got {type(message)}"
        )

        return cls(
            message=message.message,
            raw=message.raw,
            id=message.id,
            source=message.source,
            meta=message.meta,
            hidden=message.hidden,
        )


### Game State


class VariableSchema(pydantic.BaseModel):
    key: str
    value: str | int | float | bool | None = None


### Events


class StatusEnum(str, Enum):
    success = "success"
    error = "error"
    warning = "warning"
    info = "info"
    busy = "busy"


class StatusEmission(pydantic.BaseModel):
    status: StatusEnum
    message: str
    as_scene_message: bool = False
