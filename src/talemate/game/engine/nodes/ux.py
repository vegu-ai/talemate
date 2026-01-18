from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pydantic
import structlog

from talemate.context import active_scene
from talemate.emit import emit
from talemate.game.engine.nodes.core import (
    GraphState,
    InputValueError,
    Node,
    NodeStyle,
    PropertyField,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.ux.schema import (
    UXChoiceElement,
    UXElement,
    UXSelection,
    UXTextInputElement,
)
from talemate.util.colors import ALL_COLOR_NAMES
from talemate.util.ux import normalize_choices

__all__ = [
    "BuildChoiceElement",
    "BuildTextInputElement",
    "StyleElement",
    "EmitElement",
]

log = structlog.get_logger("talemate.game.engine.nodes.ux")


class _UxBuildCommonFields:
    """
    Shared PropertyField definitions for build-* UX element nodes.
    """

    closable = PropertyField(
        name="closable",
        description="Whether the user can dismiss the element (dismissal cancels waiting)",
        type="bool",
        default=True,
    )
    timeout_seconds = PropertyField(
        name="timeout_seconds",
        description="Optional timeout for the interaction (0 = no timeout)",
        type="int",
        default=0,
        min=0,
    )
    element_title = PropertyField(
        name="element_title",
        description="Title for the element",
        type="str",
        default="",
    )
    element_body = PropertyField(
        name="element_body",
        description="Body/description for the element",
        type="text",
        default="",
    )


class _BuildUxElementMixin:
    """
    Mixin with shared sockets + value-resolution for build-* UX element nodes.
    """

    def _ux_build_setup_common(self):
        self.add_input("state")
        self.add_input("id", socket_type="str", optional=True)
        self.add_input("closable", socket_type="bool", optional=True)
        self.add_input("timeout_seconds", socket_type="int", optional=True)
        self.add_input("title", socket_type="str", optional=True)
        self.add_input("body", socket_type="str", optional=True)

        self.set_property("closable", True)
        self.set_property("timeout_seconds", 0)
        self.set_property("element_title", "")
        self.set_property("element_body", "")

        # input passthrough outputs (resolved values)
        self.add_output("state", socket_type="any")
        self.add_output("id", socket_type="str")
        self.add_output("closable", socket_type="bool")
        self.add_output("timeout_seconds", socket_type="int")
        self.add_output("title", socket_type="str")
        self.add_output("body", socket_type="str")

    def _ux_build_setup_tail_outputs(self):
        # These should remain last so graphs read nicely.
        self.add_output("ux_id", socket_type="str")
        self.add_output("ux_element", socket_type="ux_element")

    def _ux_build_resolve_common(self) -> tuple[str, bool, int, str | None, str | None]:
        ux_id = self.normalized_input_value("id") or str(uuid.uuid4())
        closable = (
            self.normalized_input_value("closable")
            if self.get_input_socket("closable").source
            else self.get_property("closable")
        )
        timeout_seconds = (
            self.normalized_input_value("timeout_seconds")
            if self.get_input_socket("timeout_seconds").source
            else self.get_property("timeout_seconds")
        )
        try:
            timeout_seconds = int(timeout_seconds or 0)
        except Exception:
            timeout_seconds = int(self.get_property("timeout_seconds") or 0)
        timeout_seconds = max(0, timeout_seconds)

        title = (
            self.normalized_input_value("title")
            or self.get_property("element_title")
            or None
        )
        body = (
            self.normalized_input_value("body")
            or self.get_property("element_body")
            or None
        )

        return ux_id, bool(closable), timeout_seconds, title, body


def _parse_ux_element(raw: Any) -> UXElement:
    if isinstance(raw, (UXChoiceElement, UXTextInputElement)):
        return raw
    return pydantic.TypeAdapter(UXElement).validate_python(raw)


@register("ux/BuildChoiceElement")
class BuildChoiceElement(_BuildUxElementMixin, Node):
    """
    Builds a choice UX element payload.

    Inputs:
    - state: any
    - id: str (optional)
    - title: str (optional)
    - body: str (optional)
    - choices: list (required)
    - multi_select: bool (optional)
    - default: str|list[str] (optional)

    Outputs:
    - state: any
    - ux_id: str
    - ux_element: dict
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2d3a38",
            title_color="#3a4d4a",
            icon="F1B4F",
        )

    def __init__(self, title="Build Choice Element", **kwargs):
        super().__init__(title=title, **kwargs)

    class Fields:
        closable = _UxBuildCommonFields.closable
        timeout_seconds = _UxBuildCommonFields.timeout_seconds
        element_title = _UxBuildCommonFields.element_title
        element_body = _UxBuildCommonFields.element_body
        multi_select = PropertyField(
            name="multi_select",
            description="Allow selecting multiple choices",
            type="bool",
            default=False,
        )
        default = PropertyField(
            name="default",
            description="Default selection (string or list of strings)",
            type="any",
            default=None,
        )

    def setup(self):
        self._ux_build_setup_common()
        self.add_input("choices", socket_type="list")
        self.add_input("multi_select", socket_type="bool", optional=True)
        self.add_input("default", socket_type="any", optional=True)

        self.set_property("multi_select", False)
        self.set_property("default", None)

        self.add_output("choices", socket_type="list")
        self.add_output("multi_select", socket_type="bool")
        self.add_output("default", socket_type="any")
        self._ux_build_setup_tail_outputs()

    async def run(self, state: GraphState):
        state_value = self.get_input_value("state")
        ux_id, closable, timeout_seconds, title, body = self._ux_build_resolve_common()
        raw_choices = self.get_input_value("choices")
        multi_select = (
            self.normalized_input_value("multi_select")
            if self.get_input_socket("multi_select").source
            else self.get_property("multi_select")
        )
        default = (
            self.normalized_input_value("default")
            if self.get_input_socket("default").source
            else self.get_property("default")
        )

        choices = normalize_choices(raw_choices)
        if not choices:
            raise InputValueError(self, "choices", "Must provide at least one choice")

        element = UXChoiceElement(
            id=ux_id,
            closable=closable,
            title=title,
            body=body,
            choices=choices,
            multi_select=bool(multi_select),
            default=default,
            timeout_seconds=timeout_seconds,
        )

        self.set_output_values(
            {
                "state": state_value,
                "id": element.id,
                "closable": element.closable,
                "timeout_seconds": element.timeout_seconds,
                "title": element.title or "",
                "body": element.body or "",
                "choices": raw_choices if isinstance(raw_choices, list) else [],
                "multi_select": element.multi_select,
                "default": element.default,
                "ux_id": element.id,
                "ux_element": element.model_dump(),
            }
        )


@register("ux/BuildTextInputElement")
class BuildTextInputElement(_BuildUxElementMixin, Node):
    """
    Builds a text input UX element payload.

    Inputs:
    - state: any
    - id: str (optional)
    - title: str (optional)
    - body: str (optional)
    - multiline: bool (optional)
    - rows: int (optional)
    - placeholder: str (optional)
    - default: str (optional)
    - trim: bool (optional)

    Outputs:
    - state: any
    - ux_id: str
    - ux_element: dict
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2d3a38",
            title_color="#3a4d4a",
            icon="F1B4F",
        )

    def __init__(self, title="Build Text Input Element", **kwargs):
        super().__init__(title=title, **kwargs)

    class Fields:
        closable = _UxBuildCommonFields.closable
        timeout_seconds = _UxBuildCommonFields.timeout_seconds
        element_title = _UxBuildCommonFields.element_title
        element_body = _UxBuildCommonFields.element_body
        multiline = PropertyField(
            name="multiline",
            description="Render as textarea (true) or single-line input (false)",
            type="bool",
            default=False,
        )
        rows = PropertyField(
            name="rows",
            description="Textarea rows (only used when multiline)",
            type="int",
            default=0,
            min=0,
        )
        placeholder = PropertyField(
            name="placeholder",
            description="Input placeholder text",
            type="str",
            default="",
        )
        default = PropertyField(
            name="default",
            description="Default input value",
            type="str",
            default="",
        )
        trim = PropertyField(
            name="trim",
            description="Whether to trim input before submission",
            type="bool",
            default=True,
        )

    def setup(self):
        self._ux_build_setup_common()
        self.add_input("multiline", socket_type="bool", optional=True)
        self.add_input("rows", socket_type="int", optional=True)
        self.add_input("placeholder", socket_type="str", optional=True)
        self.add_input("default", socket_type="str", optional=True)
        self.add_input("trim", socket_type="bool", optional=True)

        self.set_property("multiline", False)
        self.set_property("rows", 0)
        self.set_property("placeholder", "")
        self.set_property("default", "")
        self.set_property("trim", True)

        self.add_output("multiline", socket_type="bool")
        self.add_output("rows", socket_type="int")
        self.add_output("placeholder", socket_type="str")
        self.add_output("default", socket_type="str")
        self.add_output("trim", socket_type="bool")
        self._ux_build_setup_tail_outputs()

    async def run(self, state: GraphState):
        state_value = self.get_input_value("state")
        ux_id, closable, timeout_seconds, title, body = self._ux_build_resolve_common()

        multiline = (
            self.normalized_input_value("multiline")
            if self.get_input_socket("multiline").source
            else self.get_property("multiline")
        )
        rows = (
            self.normalized_input_value("rows")
            if self.get_input_socket("rows").source
            else self.get_property("rows")
        )
        placeholder = (
            self.normalized_input_value("placeholder")
            if self.get_input_socket("placeholder").source
            else self.get_property("placeholder")
        )
        default = (
            self.normalized_input_value("default")
            if self.get_input_socket("default").source
            else self.get_property("default")
        )
        trim = (
            self.normalized_input_value("trim")
            if self.get_input_socket("trim").source
            else self.get_property("trim")
        )

        try:
            rows_int = int(rows or 0)
        except Exception:
            rows_int = int(self.get_property("rows") or 0)
        rows_int = max(0, rows_int)

        placeholder = (
            str(placeholder).strip() if placeholder is not None else ""
        ) or None
        default = str(default) if default is not None else None
        if default is not None and default == "":
            default = None

        element = UXTextInputElement(
            id=ux_id,
            closable=closable,
            title=title,
            body=body,
            multiline=bool(multiline),
            rows=rows_int or None,
            placeholder=placeholder,
            default=default,
            trim=bool(trim),
            timeout_seconds=timeout_seconds,
        )

        self.set_output_values(
            {
                "state": state_value,
                "id": element.id,
                "closable": element.closable,
                "timeout_seconds": element.timeout_seconds,
                "title": element.title or "",
                "body": element.body or "",
                "multiline": element.multiline,
                "rows": element.rows or 0,
                "placeholder": element.placeholder or "",
                "default": element.default or "",
                "trim": element.trim,
                "ux_id": element.id,
                "ux_element": element.model_dump(),
            }
        )


@register("ux/StyleElement")
class StyleElement(Node):
    """
    Pass-through node for styling UX elements.

    Intended usage: connect between `ux/Build*Element` nodes and `ux/EmitElement`.

    Inputs:
    - state: any
    - ux_element: dict
    - tint: str (optional) - Vuetify color name
    - icon: str (optional) - mdi-* icon name

    Outputs:
    - state: any
    - ux_id: str
    - ux_element: dict
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2d3a38",
            title_color="#3a4d4a",
            icon="F1B4F",
        )

    def __init__(self, title="Style UX Element", **kwargs):
        super().__init__(title=title, **kwargs)

    class Fields:
        tint = PropertyField(
            name="tint",
            description="Color tint (Vuetify color name)",
            type="str",
            default="muted",
            generate_choices=lambda: ALL_COLOR_NAMES,
        )
        icon = PropertyField(
            name="icon",
            description="Material Design Icon name (e.g., 'mdi-help-circle-outline', 'mdi-information'). Leave blank for no icon.",
            type="str",
            default="",
        )

    def setup(self):
        self.add_input("state")
        self.add_input("ux_element", socket_type="ux_element")
        self.add_input("tint", socket_type="str", optional=True)
        self.add_input("icon", socket_type="str", optional=True)

        self.set_property("tint", "muted")
        self.set_property("icon", "")

        self.add_output("state", socket_type="any")
        self.add_output("ux_id", socket_type="str")
        self.add_output("ux_element", socket_type="ux_element")

    async def run(self, state: GraphState):
        state_value = self.get_input_value("state")
        raw = self.require_input("ux_element", none_is_set=True)

        try:
            element = _parse_ux_element(raw)
        except Exception as exc:
            raise InputValueError(self, "ux_element", f"Invalid UX element: {exc}")

        tint = (
            self.normalized_input_value("tint")
            if self.get_input_socket("tint").source
            else self.get_property("tint")
        )
        icon = (
            self.normalized_input_value("icon")
            if self.get_input_socket("icon").source
            else self.get_property("icon")
        )

        color = (str(tint).strip() if tint is not None else "") or None
        icon = (str(icon).strip() if icon is not None else "") or None

        element.color = color
        element.icon = icon

        # Always sync to meta for backward compatibility
        if element.color is None:
            element.meta.pop("color", None)
        else:
            element.meta["color"] = element.color

        if element.icon is None:
            element.meta.pop("icon", None)
        else:
            element.meta["icon"] = element.icon

        self.set_output_values(
            {
                "state": state_value,
                "ux_id": element.id,
                "ux_element": element.model_dump(),
            }
        )


@register("ux/EmitElement")
class EmitElement(Node):
    """
    Emits a UX element to the frontend (websocket passthrough).

    Choice elements are awaitable by design: emitting a choice element will wait
    for the user to select/cancel (with optional element-defined timeout),
    then close the UX element and return the captured interaction values.

    Inputs:
    - state: any
    - ux_element: dict

    Outputs:
    - state: any
    - ux_id: str
    - ux_element: dict
    - value: any
    - values: dict
    - cancelled: bool
    - timed_out: bool
    """

    _ux_shared_prefix: str = "_ux_"
    _wait_sleep_seconds: float = 0.25

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2d3a38",
            title_color="#3a4d4a",
            icon="F1B4F",
        )

    def __init__(self, title="Emit UX Element", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("ux_element", socket_type="ux_element")
        self.add_output("state", socket_type="any")
        self.add_output("ux_id", socket_type="str")
        self.add_output("ux_element", socket_type="ux_element")
        self.add_output("value", socket_type="any")
        self.add_output("values", socket_type="any")
        self.add_output("cancelled", socket_type="bool")
        self.add_output("timed_out", socket_type="bool")

    def ux_shared_key(self, ux_id: str) -> str:
        return f"{self._ux_shared_prefix}{ux_id}"

    def shared_container(self, state: GraphState, scene) -> tuple[dict, str]:
        """
        Returns (shared_dict, label).

        UX selections are written by the websocket router into
        scene.nodegraph_state.shared. If this node is running in an isolated
        GraphState, state.shared may not be the same dict. Prefer the scene's
        nodegraph shared-state when available.
        """
        try:
            graph_state = getattr(scene, "nodegraph_state", None)
            if graph_state and getattr(graph_state, "shared", None) is not None:
                return graph_state.shared, "scene.nodegraph_state.shared"
        except Exception:
            pass
        return state.shared, "state.shared"

    def parse_selection_payload(
        self, ux_id: str, selection_payload: Any
    ) -> UXSelection:
        if isinstance(selection_payload, UXSelection):
            return selection_payload

        if isinstance(selection_payload, dict):
            try:
                return UXSelection(**selection_payload)
            except Exception:
                return UXSelection(
                    ux_id=ux_id,
                    kind=selection_payload.get("kind") or "choice",
                    selected=selection_payload.get("selected"),
                    cancelled=bool(selection_payload.get("cancelled") or False),
                    raw=selection_payload,
                )

        return UXSelection(ux_id=ux_id, kind="choice", selected=selection_payload)

    async def wait_for_interaction(
        self,
        state: GraphState,
        ux_id: str,
        scene,
        timeout_seconds: int,
        start_time: float,
    ) -> tuple[UXSelection | None, bool, bool]:
        """
        Returns (selection, timed_out, aborted).
        - timed_out: only true when the configured timeout expires
        - aborted: true when the scene becomes inactive mid-wait
        """

        shared, shared_label = self.shared_container(state, scene)
        key = self.ux_shared_key(ux_id)

        existing_value = shared.get(key)
        log.debug(
            "ux.wait.start",
            ux_id=ux_id,
            key=key,
            shared=shared_label,
            timeout_seconds=timeout_seconds,
            existing_type=type(existing_value).__name__
            if existing_value is not None
            else None,
        )

        # If selection is already present, do not overwrite it with waiting marker.
        if existing_value is None:
            shared[key] = "waiting"

        selection_payload: Any | None = None
        timed_out = False
        aborted = False
        last_seen = None

        while True:
            current = shared.get(key)
            if current is None:
                shared[key] = "waiting"
                current = "waiting"

            if current != "waiting":
                selection_payload = current
                break

            if not getattr(scene, "active", True):
                aborted = True
                log.debug(
                    "ux.wait.abort_scene_inactive",
                    ux_id=ux_id,
                    key=key,
                    shared=shared_label,
                )
                break

            if timeout_seconds > 0 and time.time() - start_time > timeout_seconds:
                timed_out = True
                log.debug("ux.wait.timeout", ux_id=ux_id, key=key, shared=shared_label)
                break

            if current is not last_seen:
                last_seen = current
                log.debug(
                    "ux.wait.poll",
                    ux_id=ux_id,
                    key=key,
                    shared=shared_label,
                    current_type=type(current).__name__
                    if current is not None
                    else None,
                )

            await asyncio.sleep(self._wait_sleep_seconds)

        # cleanup marker/value
        try:
            shared.pop(key, None)
        except Exception:
            pass

        if selection_payload is None:
            return None, timed_out, aborted

        return self.parse_selection_payload(ux_id, selection_payload), False, False

    async def run(self, state: GraphState):
        state_value = self.get_input_value("state")
        raw = self.require_input("ux_element", none_is_set=True)
        try:
            element = _parse_ux_element(raw)
        except Exception as exc:
            raise InputValueError(self, "ux_element", f"Invalid UX element: {exc}")

        # Normalize timeout from element (0 = no timeout)
        try:
            timeout_seconds = int(getattr(element, "timeout_seconds", 0) or 0)
        except Exception:
            timeout_seconds = 0
        timeout_seconds = max(0, timeout_seconds)

        start_time = time.time()
        if hasattr(element, "timeout_started_at_ms"):
            if timeout_seconds > 0:
                element.timeout_started_at_ms = int(start_time * 1000)
            else:
                element.timeout_started_at_ms = None

        emit(
            "ux",
            message="",
            id=element.id,
            data={
                "action": "present",
                "element": element.model_dump(),
            },
            websocket_passthrough=True,
        )

        # Default outputs for non-awaitable elements (future kinds)
        value: Any | None = None
        values: dict[str, Any] = {
            "ux_id": element.id,
            "kind": element.kind,
            "value": None,
            "text": None,
            "choice_id": None,
            "label": None,
            "cancelled": False,
            "timed_out": False,
            "raw": {},
        }
        cancelled = False
        timed_out = False

        if element.kind in ("choice", "text_input"):
            scene = active_scene.get()
            selection, timed_out, aborted = await self.wait_for_interaction(
                state=state,
                ux_id=element.id,
                scene=scene,
                timeout_seconds=timeout_seconds,
                start_time=start_time,
            )

            if timed_out:
                # Timeout is treated as cancelled (per UX contract)
                cancelled = True
                value = None
                values["cancelled"] = True
                values["timed_out"] = True
                values["raw"] = {"reason": "timeout"}
            elif aborted:
                cancelled = True
                value = None
                values["cancelled"] = True
                values["raw"] = {"reason": "scene_inactive"}
            elif selection is not None:
                cancelled = bool(selection.cancelled)
                value = selection.selected
                if (
                    element.kind == "text_input"
                    and getattr(element, "trim", False)
                    and isinstance(value, str)
                ):
                    value = value.strip()
                values["value"] = value
                values["text"] = value if element.kind == "text_input" else None
                values["choice_id"] = selection.choice_id
                values["label"] = selection.label
                values["cancelled"] = cancelled
                values["timed_out"] = False
                values["raw"] = selection.raw or selection.model_dump()
            else:
                cancelled = True
                values["cancelled"] = True
                values["raw"] = {"reason": "no_selection"}

            # Always emit close when the interaction finishes
            emit(
                "ux",
                message="",
                id=element.id,
                data={
                    "action": "close",
                    "ux_id": element.id,
                },
                websocket_passthrough=True,
            )

        self.set_output_values(
            {
                "state": state_value,
                "ux_id": element.id,
                "ux_element": element.model_dump(),
                "value": value,
                "values": values,
                "cancelled": cancelled,
                "timed_out": timed_out,
            }
        )
