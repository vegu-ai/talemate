import asyncio
from typing import TYPE_CHECKING, Any

import pydantic
import structlog

from talemate.agents.memory import MemoryAgent
from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.agents.director import DirectorAgent

log = structlog.get_logger("game_state")


class Goal(pydantic.BaseModel):
    description: str
    id: int
    status: bool = False


class Instructions(pydantic.BaseModel):
    character: dict[str, str] = pydantic.Field(default_factory=dict)


class Ops(pydantic.BaseModel):
    run_on_start: bool = False
    always_direct: bool = False


class GameState(pydantic.BaseModel):
    ops: Ops = Ops()
    variables: dict[str, Any] = pydantic.Field(default_factory=dict)
    goals: list[Goal] = pydantic.Field(default_factory=list)
    instructions: Instructions = pydantic.Field(default_factory=Instructions)

    @property
    def director(self) -> "DirectorAgent":
        return get_agent("director")

    @property
    def memory(self) -> MemoryAgent:
        return get_agent("memory")

    @property
    def scene(self) -> "Scene":
        return self.director.scene

    @property
    def game_won(self) -> bool:
        return self.variables.get("__game_won__") is True

    def __getitem__(self, key: str) -> Any:
        return self.get_var(key)

    def __setitem__(self, key: str, value: Any):
        self.set_var(key, value)

    def __delitem__(self, key: str):
        return self.unset_var(key)

    def __contains__(self, key: str) -> bool:
        return self.has_var(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.get_var(key, default=default)

    def pop(self, key: str, default: Any = None) -> Any:
        value = self.get_var(key, default=default)
        self.unset_var(key)
        return value

    def set_var(self, key: str, value: Any, commit: bool = False):
        self.variables[key] = value
        if commit:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.memory.add(value, uid=f"game_state.{key}"))

    def has_var(self, key: str) -> bool:
        return key in self.variables

    def get_var(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)

    def get_or_set_var(self, key: str, value: Any, commit: bool = False) -> Any:
        if not self.has_var(key):
            self.set_var(key, value, commit=commit)
        return self.get_var(key)

    def unset_var(self, key: str):
        self.variables.pop(key, None)
