from typing import Callable, Any, Literal
import pydantic
import uuid
import json
import yaml

from talemate.prompts.base import Prompt

__all__ = [
    "Argument",
    "Call",
    "Callback",
    "State",
    "InvalidCallbackArguments",
    "ExampleCallbackArguments",
]

YAML_OPTIONS = {
    "default_flow_style": False,
    "allow_unicode": True,
    "indent": 2,
    "sort_keys": False,
    "width": 100,
}

YAML_PRESERVE_NEWLINES = (
    "If there are newlines, they should be preserved by using | style."
)


class InvalidCallbackArguments(ValueError):
    pass


class ExampleCallbackArguments(InvalidCallbackArguments):
    pass


class State(pydantic.BaseModel):
    calls: list["Call"] = pydantic.Field(default_factory=list)
    schema_format: Literal["json", "yaml"] = "json"


class Argument(pydantic.BaseModel):
    name: str
    type: str
    preserve_newlines: bool = False

    def extra_instructions(self, state: State) -> str:
        if state.schema_format == "yaml" and self.preserve_newlines:
            return f" {YAML_PRESERVE_NEWLINES}"
        return ""


class Call(pydantic.BaseModel):
    name: str = pydantic.Field(
        validation_alias=pydantic.AliasChoices("name", "function")
    )
    arguments: dict[str, Any] = pydantic.Field(default_factory=dict)
    result: str | int | float | bool | dict | list | None = None
    uid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    called: bool = False
    error: str | None = None

    @pydantic.field_validator("arguments")
    def check_for_schema_examples(cls, v: dict[str, Any]) -> dict[str, str]:
        valid_types = ["str", "int", "float", "bool", "dict", "list"]
        for key, value in v.items():
            if isinstance(value, str):
                for type_name in valid_types:
                    if value.startswith(f"{type_name} - "):
                        raise ExampleCallbackArguments(
                            f"Argument '{key}' contains schema example: '{value}'. AI repeated the schema format."
                        )
        return v

    @pydantic.field_validator("arguments")
    def join_string_lists(cls, v: dict[str, Any]) -> dict[str, str]:
        return {
            key: "\n".join(str(item) for item in value)
            if isinstance(value, list)
            else value
            for key, value in v.items()
        }

    @property
    def payload(self) -> dict:
        return {
            "function": self.name,
            "arguments": {
                k: v for k, v in self.arguments.items() if not k.startswith("_")
            },
        }


class Callback(pydantic.BaseModel):
    name: str
    arguments: list[Argument] = pydantic.Field(default_factory=list)
    fn: Callable
    state: State = State()
    multiple: bool = True

    examples: list[dict] = pydantic.Field(default_factory=list)
    argument_instructions: dict[str, str | None] = pydantic.Field(default_factory=dict)
    instructions: str | None = ""

    @property
    def pretty_name(self) -> str:
        return self.name.replace("_", " ").title()

    def render(self, usage: str, examples: list[dict] = None, **argument_usage) -> str:
        prompt = Prompt.get(
            "focal.callback",
            {
                "callback": self,
                "name": self.name,
                "usage": usage,
                "argument_usage": argument_usage or {},
                "arguments": self.arguments,
                "state": self.state,
                "examples": examples or [],
            },
        )

        return prompt.render()

    ## schema

    def _usage(self, argument_usage) -> dict:
        return {
            "function": self.name,
            "arguments": {
                argument.name: f"{argument.type} - {argument_usage.get(argument.name, '')}{argument.extra_instructions(self.state)}"
                for argument in self.arguments
            },
        }

    def _example(self, example: dict) -> dict:
        return {
            "function": self.name,
            "arguments": {k: v for k, v in example.items() if not k.startswith("_")},
        }

    def usage(self, argument_usage) -> str:
        fmt: str = self.state.schema_format
        text = getattr(self, f"{fmt}_usage")(argument_usage)
        text = text.rstrip()
        return f"```{fmt}\n{text}\n```"

    def example(self, example: dict) -> str:
        fmt: str = self.state.schema_format
        text = getattr(self, f"{fmt}_example")(example)
        text = text.rstrip()
        return f"```{fmt}\n{text}\n```"

    ## JSON

    def json_usage(self, argument_usage) -> str:
        return json.dumps(self._usage(argument_usage), indent=2)

    def json_example(self, example: dict) -> str:
        return json.dumps(self._example(example), indent=2)

    ## YAML

    def yaml_usage(self, argument_usage) -> str:
        return yaml.dump(self._usage(argument_usage), **YAML_OPTIONS)

    def yaml_example(self, example: dict) -> str:
        return yaml.dump(self._example(example), **YAML_OPTIONS)
