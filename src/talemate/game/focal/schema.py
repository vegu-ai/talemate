from typing import Callable, Any, Literal
import pydantic
import uuid
import json
import yaml

from talemate.prompts.base import Prompt

__all__ = ["Argument", "Call", "Callback", "State"]

YAML_OPTIONS = {
    "default_flow_style": False,
    "allow_unicode": True,
    "indent": 2,
    "sort_keys": False,
    "width": 100,
}

class State(pydantic.BaseModel):
    calls:list["Call"] = pydantic.Field(default_factory=list)
    schema_format: Literal["json", "yaml"] = "json"

class Argument(pydantic.BaseModel):
    name: str
    type: str
    
class Call(pydantic.BaseModel):
    name: str = pydantic.Field(validation_alias=pydantic.AliasChoices('name', 'function'))
    arguments: dict[str, Any] = pydantic.Field(default_factory=dict)
    result: str | int | float | bool | dict | list | None = None
    uid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    called: bool = False

    @pydantic.field_validator('arguments')
    def join_string_lists(cls, v: dict[str, Any]) -> dict[str, str]:
        return {
            key: '\n'.join(str(item) for item in value) if isinstance(value, list) else str(value)
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
    
    ## schema
    
    def _usage(self, argument_usage) -> dict:
        return {
            "function": self.name,
            "arguments": {
                argument.name: f"{argument.type} - {argument_usage.get(argument.name, '')}"
                for argument in self.arguments
            }
        } 
        
    def _example(self, example:dict) -> dict:
        return {
            "function": self.name,
            "arguments": {k:v for k,v in example.items() if not k.startswith("_")},
        }
        
    def usage(self, argument_usage) -> str:
        fmt:str = self.state.schema_format
        text = getattr(self, f"{fmt}_usage")(argument_usage)
        text = text.rstrip()
        return f"```{fmt}\n{text}\n```"
    
    def example(self, example:dict) -> str:
        fmt:str = self.state.schema_format
        text = getattr(self, f"{fmt}_example")(example)
        text = text.rstrip()
        return f"```{fmt}\n{text}\n```"
    
    ## JSON
    
    def json_usage(self, argument_usage) -> str:
        return json.dumps(self._usage(argument_usage), indent=2)
    
    def json_example(self, example:dict) -> str:
        return json.dumps(self._example(example), indent=2)
    
    ## YAML
    
    def yaml_usage(self, argument_usage) -> str:
        return yaml.dump(self._usage(argument_usage), **YAML_OPTIONS)
    
    def yaml_example(self, example:dict) -> str:
        return yaml.dump(self._example(example), **YAML_OPTIONS)