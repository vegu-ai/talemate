from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import pydantic

__all__ = [
    "UXElementBase",
    "UXAwaitableElementBase",
    "UXChoice",
    "UXChoiceElement",
    "UXTextInputElement",
    "UXElement",
    "UXSelection",
    "UXPresentPayload",
    "UXSelectPayload",
    "UXCancelPayload",
]


class UXElementBase(pydantic.BaseModel):
    """
    Base UX element payload that can be rendered by the frontend.
    """

    id: str
    kind: str

    # Whether the UX element may be dismissed by the user. If dismissed, any
    # waiting node should be resumed as cancelled.
    closable: bool = True

    title: str | None = None
    body: str | None = None

    # Presentation hints for the frontend (Vuetify-style).
    # Kept optional for backward compatibility; frontend may also read these from `meta`.
    icon: str | None = None
    color: str | None = None

    meta: dict[str, Any] = pydantic.Field(default_factory=dict)


class UXAwaitableElementBase(UXElementBase):
    """
    Base for UX elements that are awaitable and may timeout.
    """

    # Timeout behavior for awaitable elements.
    # 0 means no timeout (wait forever until user selects/cancels).
    timeout_seconds: int = 0

    # When timeout_seconds > 0, the backend can stamp the start time so the frontend
    # can show a countdown without needing any follow-up events.
    timeout_started_at_ms: int | None = None


class UXChoice(pydantic.BaseModel):
    """
    A single selectable option within a choice UX element.
    """

    id: str
    label: str
    value: Any | None = None
    disabled: bool = False


class UXChoiceElement(UXAwaitableElementBase):
    kind: Literal["choice"] = "choice"
    choices: list[UXChoice] = pydantic.Field(default_factory=list)
    multi_select: bool = False
    default: str | list[str] | None = None


class UXTextInputElement(UXAwaitableElementBase):
    kind: Literal["text_input"] = "text_input"

    # Render as textarea when true, single-line input when false.
    multiline: bool = False

    # Optional presentation hints for multiline input.
    rows: int | None = None

    placeholder: str | None = None
    default: str | None = None

    # Whether the frontend should trim input before submission.
    trim: bool = True


UXElement = Annotated[
    Union[UXChoiceElement, UXTextInputElement],
    pydantic.Field(discriminator="kind"),
]


class UXSelection(pydantic.BaseModel):
    """
    Selection returned from the frontend for a UX element.
    """

    ux_id: str
    kind: str

    # The selected value(s). For single-select this should be a scalar (often str).
    selected: Any | list[Any] | None = None

    # Optional details for choice-based UX
    choice_id: str | None = None
    value: Any | None = None
    label: str | None = None

    # Whether the UX interaction was cancelled/dismissed by the user.
    cancelled: bool = False

    # Original incoming payload (passthrough for debugging/extensibility).
    raw: dict[str, Any] = pydantic.Field(default_factory=dict)


class UXPresentPayload(pydantic.BaseModel):
    action: Literal["present"] = "present"
    element: UXElement


class UXSelectPayload(pydantic.BaseModel):
    action: Literal["select"] = "select"

    ux_id: str
    kind: str | None = None
    choice_id: str | None = None

    # Selected value (or label). Frontend should include this.
    selected: Any | list[Any] | None = None

    # Additional optional fields for convenience.
    value: Any | None = None
    label: str | None = None


class UXCancelPayload(pydantic.BaseModel):
    action: Literal["cancel"] = "cancel"
    ux_id: str
    kind: str | None = None
