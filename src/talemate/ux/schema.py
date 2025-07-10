import pydantic

__all__ = [
    "Note",
    "Field",
    "Column",
]


class Note(pydantic.BaseModel):
    text: str
    title: str = None
    color: str = "muted"
    icon: str = "mdi-information-outline"


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


class Column(Field):
    pass
