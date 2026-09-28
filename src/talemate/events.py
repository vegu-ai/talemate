from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pydantic
import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Scene, Character, SceneMessage
    from talemate.scene_message import CharacterTransitionMessage

__all__ = [
    "Event",
    "HistoryEvent",
    "ArchiveEvent",
    "CharacterStateEvent",
    "CharacterActivatedEvent",
    "CharacterDeactivatedEvent",
    "GameStateChangedEvent",
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
    ts: int | None = None
    present: list[str] | None = None


class CharacterActivatedEvent(Event):
    """
    Sent by `activate_character` once the character is back in the scene.
    `transition` is the arrival entry in the history; None when none was
    recorded, as during a scene load.
    """

    character: "Character"
    transition: "CharacterTransitionMessage | None" = None


class CharacterDeactivatedEvent(Event):
    """
    Sent by `deactivate_character` once the character has left the scene.
    `transition` is the departure entry in the history; None when none was
    recorded, as during a scene load.
    """

    character: "Character"
    transition: "CharacterTransitionMessage | None" = None


class GameStateChangedEvent(Event):
    """
    Sent for each game state value that changes, from any writer (see
    talemate.game.state); a removed value has value None.
    """

    path: str
    value: Any = None
    previous_value: Any = None


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
