from typing import Callable
import pydantic
import uuid

from talemate.prompts.base import Prompt

__all__ = ["Argument", "Call", "Callback", "State"]

class State(pydantic.BaseModel):
    argument_delimiter: str = "|"
    callback_prefix: str = "START"
    callback_suffix: str = "COMMIT"
    
    calls:list["Call"] = pydantic.Field(default_factory=list)
    
    def set(self, name:str, value:str):
        
        if name not in ["argument_delimiter", "callback_prefix", "callback_suffix"]:
            raise ValueError(f"Invalid state attribute: {name}")
        
        setattr(self, name, value)

class Argument(pydantic.BaseModel):
    name: str
    type: str
    
class Call(pydantic.BaseModel):
    name: str
    arguments: dict[str, str] = pydantic.Field(default_factory=dict)
    result: str | int | float | bool | None = None
    uid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    called: bool = False

class Callback(pydantic.BaseModel):
    name: str
    arguments: list[Argument] = pydantic.Field(default_factory=list)
    fn: Callable
    state: State = State()
    
    @property
    def pretty_name(self) -> str:
        return self.name.replace("_", " ").title()
    
    def render(self, usage:str, **argument_usage) -> str:
        prompt = Prompt.get(
            "focal.callback",
            {
                "callback": self,
                "name": self.name,
                "usage": usage,
                "argument_usage": argument_usage or {},
                "arguments": self.arguments,
                "state": self.state,
            }
        )
        
        return prompt.render()