from __future__ import annotations

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


class Event(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    scene: "Scene"
    event_type: str


class HistoryEvent(Event):
    messages: list["SceneMessage"]


class ArchiveEvent(Event):
    text: str
    memory_id: str
    ts: str | None = None


class CharacterStateEvent(Event):
    state: str
    character_name: str


class SceneStateEvent(Event):
    pass


class GameLoopBase(Event):
    pass


class GameLoopEvent(GameLoopBase):
    had_passive_narration: bool = False


class GameLoopStartEvent(GameLoopBase):
    pass


class GameLoopActorIterEvent(GameLoopBase):
    actor: "Actor"
    game_loop: GameLoopEvent


class GameLoopCharacterIterEvent(GameLoopBase):
    character: "Character"
    game_loop: GameLoopEvent


class GameLoopNewMessageEvent(GameLoopBase):
    message: "SceneMessage"


class PlayerTurnStartEvent(Event):
    pass


class RegenerateGeneration(Event):
    message: "SceneMessage"
    character: "Character | None" = None


async_signals.register(
    "regenerate.msg.character",
    "regenerate.msg.narrator",
    "regenerate.msg.reinforcement",
    "regenerate.msg.context_investigation",
    "game_loop_player_character_iter",
    "game_loop_ai_character_iter",
)
