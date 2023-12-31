from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Actor, SceneMessage

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
class GameLoopEvent(Event):
    pass

@dataclass
class GameLoopStartEvent(GameLoopEvent):
    pass

@dataclass
class GameLoopActorIterEvent(GameLoopEvent):
    actor: Actor
    
@dataclass
class GameLoopNewMessageEvent(GameLoopEvent):
    message: SceneMessage