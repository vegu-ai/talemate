from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Scene, SceneMessage

__all__ = [
    "Event",
    "HistoryEvent",
]


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
    memory_id: str = None
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
class GameLoopNewMessageEvent(GameLoopBase):
    message: SceneMessage
