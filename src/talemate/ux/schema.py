from typing import Literal

import pydantic

__all__ = [
    "Action",
    "Note",
    "Condition",
    "DynamicLabel",
    "DynamicSpan",
    "FieldGroup",
    "FieldType",
    "Field",
    "Column",
]

# Widget types understood by the shared frontend field renderer
# (talemate_frontend/src/components/UxField.vue).
FieldType = Literal[
    "autocomplete",
    "blob",
    "bool",
    "flags",
    "number",
    "table",
    "text",
    "vector2",
    "weights",
    "wstemplate",
    "password",
    "unified_api_key",
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


class Condition(pydantic.BaseModel):
    """
    Conditional visibility for a field (or a container of fields): the
    frontend only renders the item when the referenced attribute holds the
    given value (or one of the given values when `value` is a list).

    How `attribute` is resolved depends on the context the field is rendered
    in — agent settings resolve it against the agent's action config values,
    client settings resolve it against the client's field values.
    """

    attribute: str
    value: int | float | str | bool | list[int | float | str | bool] | None = None


class FieldGroup(pydantic.BaseModel):
    """
    Groups related fields together — the frontend renders one section/tab per
    group.
    """

    name: str
    label: str
    description: str = ""
    icon: str = "mdi-cog"


class Field(pydantic.BaseModel):
    """
    Uniform UX field definition.

    This is the shared schema for user-configurable settings rendered by the
    frontend — agent action configs (talemate.agents.base.AgentActionConfig)
    and client extra fields (talemate.client.base.ExtraField) both extend it.
    The frontend renders any of these through the shared UxField component.
    """

    # Field identifier. Optional because some containers (e.g. agent action
    # config dicts) key their fields externally.
    name: str = ""
    type: FieldType
    label: str
    description: str = ""

    value: int | float | str | bool | list | dict | None = None
    default_value: int | float | str | bool | None = None

    # number widgets
    min: int | float | None = None
    max: int | float | None = None
    step: int | float | None = None
    graduations: list[dict[str, int | float]] | None = None

    # blob widgets — initial textarea height and whether it grows with
    # content (up to max_rows when set)
    rows: int | None = None
    max_rows: int | None = None
    auto_grow: bool = False

    # choice widgets — always a list of {"label": ..., "value": ...} dicts;
    # scalar shorthand entries are normalized by the validator below.
    choices: (
        list[dict[str, str | int | float | bool | list[int | float | bool]]] | None
    ) = None

    # table widgets
    columns: list["Column"] | None = None

    note: Note | None = None
    note_on_value: dict[str | int | float | bool, Note] = pydantic.Field(
        default_factory=dict
    )

    condition: Condition | None = None
    group: FieldGroup | None = None

    required: bool = False
    # marks settings that can cause many additional prompts when enabled
    expensive: bool = False
    # value changes should be saved immediately rather than on dialog save
    save_on_change: bool = False

    @pydantic.field_validator("choices", mode="before")
    @classmethod
    def normalize_choices(cls, v):
        if v is None:
            return v
        return [
            choice
            if isinstance(choice, dict)
            else {"label": str(choice), "value": choice}
            for choice in v
        ]

    @pydantic.field_validator("note", mode="before")
    @classmethod
    def coerce_note(cls, v):
        if isinstance(v, str):
            return Note(text=v)
        return v

    @pydantic.field_validator("note_on_value", mode="before")
    @classmethod
    def coerce_note_on_value(cls, v):
        if isinstance(v, dict):
            return {
                key: Note(text=note) if isinstance(note, str) else note
                for key, note in v.items()
            }
        return v

    # notes can also be assigned as plain strings after construction
    # (assignment bypasses validation), so coerce again at dump time
    @pydantic.field_serializer("note")
    def serialize_note(self, v):
        if isinstance(v, str):
            return Note(text=v)
        return v


class DynamicLabel(pydantic.BaseModel):
    """
    Per-row label override for a table column: when the row's value for
    `attribute` (a sibling column) matches a key in `labels`, that label is
    shown instead of the column's static label.
    """

    attribute: str
    labels: dict[str, str]


class DynamicSpan(pydantic.BaseModel):
    """
    Per-row span override for a table column: when the row's value for
    `attribute` (a sibling column) matches a key in `spans`, that span is
    used instead of the column's static span.
    """

    attribute: str
    spans: dict[str, int]


class Column(Field):
    # grid width (out of 12) in the table widget's stacked row layout;
    # the frontend falls back to a per-type default when unset
    span: int | None = None

    # render in the row's control rail (with the move/delete buttons)
    # instead of the fields grid — bool columns only
    rail: bool = False

    # marks a rail bool column as the row's enable toggle — the table widget
    # dims the row's fields while it is off
    disables_row: bool = False

    dynamic_label: DynamicLabel | None = None
    dynamic_span: DynamicSpan | None = None


# resolve the "Column" forward reference in Field.columns
Field.model_rebuild()
