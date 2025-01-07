from typing import Callable, Any
import pydantic
import uuid
import json

from talemate.prompts.base import Prompt

__all__ = ["Argument", "Call", "Callback", "State"]

class State(pydantic.BaseModel):
    calls:list["Call"] = pydantic.Field(default_factory=list)

class Argument(pydantic.BaseModel):
    name: str
    type: str
    
class Call(pydantic.BaseModel):
    name: str = pydantic.Field(validation_alias=pydantic.AliasChoices('name', 'function'))
    arguments: dict[str, str] = pydantic.Field(default_factory=dict)
    result: str | int | float | bool | None = None
    uid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    called: bool = False

    @pydantic.field_validator('arguments')
    def join_string_lists(cls, v: dict[str, Any]) -> dict[str, str]:
        return {
            key: '\n'.join(str(item) for item in value) if isinstance(value, list) else value
            for key, value in v.items()
        }

class Callback(pydantic.BaseModel):
    name: str
    arguments: list[Argument] = pydantic.Field(default_factory=list)
    fn: Callable
    state: State = State()
    multiple: bool = True
    
    @property
    def pretty_name(self) -> str:
        return self.name.replace("_", " ").title()
    
    def render(self, usage:str, examples:list[dict]=None, **argument_usage) -> str:
        prompt = Prompt.get(
            "focal.callback",
            {
                "callback": self,
                "name": self.name,
                "usage": usage,
                "argument_usage": argument_usage or {},
                "arguments": self.arguments,
                "state": self.state,
                "examples": examples or []
            }
        )
        
        return prompt.render()
    
    def json_usage(self, argument_usage) -> str:
        return json.dumps({
            "function": self.name,
            "arguments": {
                argument.name: f"{argument.type} - {argument_usage.get(argument.name, '')}"
                for argument in self.arguments
            }
        }, indent=2)
    
    def json_example(self, example:dict) -> str:
        return json.dumps({
            "function": self.name,
            "arguments": example
        }, indent=2)