from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pydantic
import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Scene, Character, SceneMessage

__all__ = [
    "Event",
    "HistoryEvent",
    "ArchiveEvent",
    "CharacterStateEvent",
    "SceneStateEvent",
    "GameLoopBase",
    "GameLoopEvent",
    "GameLoopStartEvent",
    "GameLoopActorIterEvent",
    "GameLoopCharacterIterEvent",
    "GameLoopNewMessageEvent",
    "PlayerTurnStartEvent",
    "RegenerateGeneration",
    "UserInteractionEvent",
]


class UserInteractionEvent(pydantic.BaseModel):
    """
    Emission model for user interaction signal.

    Attributes:
        message: The user's input message
        character: Optional character related to the interaction
    """

    message: str


# TODO: Convert these to pydantic models


@dataclass
class Event:
    scene: Scene
    event_type: str


@dataclass
class HistoryEvent(Event):
    messages: list[str]


@dataclass
class ArchiveEvent(Event):
    text: str
    memory_id: str
    ts: str = None


@dataclass
class CharacterStateEvent(Event):
    state: str
    character_name: str


@dataclass
class SceneStateEvent(Event):
    pass


@dataclass
class GameLoopBase(Event):
    pass


@dataclass
class GameLoopEvent(GameLoopBase):
    had_passive_narration: bool = False


@dataclass
class GameLoopStartEvent(GameLoopBase):
    pass


@dataclass
class GameLoopActorIterEvent(GameLoopBase):
    actor: Actor
    game_loop: GameLoopEvent


@dataclass
class GameLoopCharacterIterEvent(GameLoopBase):
    character: Character
    game_loop: GameLoopEvent


@dataclass
class GameLoopNewMessageEvent(GameLoopBase):
    message: SceneMessage


@dataclass
class PlayerTurnStartEvent(Event):
    pass


@dataclass
class RegenerateGeneration(Event):
    message: "SceneMessage"
    character: "Character" = None


async_signals.register(
    "regenerate.msg.character",
    "regenerate.msg.narrator",
    "regenerate.msg.reinforcement",
    "regenerate.msg.context_investigation",
    "game_loop_player_character_iter",
    "game_loop_ai_character_iter",
)
