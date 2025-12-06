import pydantic

__all__ = [
    "Note",
    "Field",
    "Column",
]


class Action(pydantic.BaseModel):
    action_name: str
    arguments: list[str | int | float | bool] = pydantic.Field(default_factory=list)
    label: str = None
    icon: str = None


class Note(pydantic.BaseModel):
    text: str
    title: str | None = None
    color: str | None = None
    icon: str | None = None

    actions: list[Action] = pydantic.Field(default_factory=list)


class Field(pydantic.BaseModel):
    name: str
    label: str
    type: str
    value: int | float | str | bool | list | None = None
    choices: list[dict[str, str | int | float | bool]] = pydantic.Field(
        default_factory=list
    )
    max: int | float | None = None
    min: int | float | None = None
    step: int | float | None = None
    description: str = ""

    required: bool = False


class Column(Field):
    pass
