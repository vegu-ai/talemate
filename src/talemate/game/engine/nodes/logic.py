from typing import ClassVar
import structlog
import pydantic
from talemate.game.engine.nodes.core import (
    Node,
    register,
    GraphState,
    NodeVerbosity,
    UNRESOLVED,
    Socket,
    PropertyField,
    InputValueError,
    NodeStyle,
)

__all__ = [
    "Coallesce",
    "LogicalRouter",
    "ORRouter",
    "ANDRouter",
    "Invert",
    "Switch",
    "RSwitch",
    "RSwitchAdvanced",
    "Case",
    "CaseRouter",
    "MakeBool",
    "AsBool",
    "ApplyDefault",
]

log = structlog.get_logger("talemate.game.engine.nodes.core.logic")


def is_truthy(value):
    return value is not None and value is not False and value is not UNRESOLVED


class LogicalRouter(Node):
    """
    Base node class for logical routers
    """

    _op: ClassVar[str] = "and"

    def __init__(self, title="OR Router", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("a", socket_type="bool", group="flags")
        self.add_input("b", socket_type="bool", group="flags")
        self.add_input("c", socket_type="bool", group="flags")
        self.add_input("d", socket_type="bool", group="flags")
        self.add_input("value", optional=True)
        self.add_output("yes")
        self.add_output("no")

    async def run(self, state: GraphState):
        # Get all flag values
        a = self.get_input_value("a")
        b = self.get_input_value("b")
        c = self.get_input_value("c")
        d = self.get_input_value("d")
        value = self.get_input_value("value")

        a_connected = self.get_input_socket("a").source is not None
        b_connected = self.get_input_socket("b").source is not None
        c_connected = self.get_input_socket("c").source is not None
        d_connected = self.get_input_socket("d").source is not None

        # Initialize flags list with required flags
        active_flags = []

        if a_connected:
            active_flags.append(Socket.as_bool(a))
        if b_connected:
            active_flags.append(Socket.as_bool(b))
        if c_connected:
            active_flags.append(Socket.as_bool(c))
        if d_connected:
            active_flags.append(Socket.as_bool(d))

        # If no valid flags are provided, treat as False
        if not active_flags:
            result = False
        else:
            if self._op == "or":
                result = any(active_flags)
            elif self._op == "and":
                result = all(active_flags)
            else:
                raise ValueError(f"Unknown operation: {self._op}")

        # Set output deactivation
        self.outputs[0].deactivated = result is False  # yes
        self.outputs[1].deactivated = result is True  # no

        # return value should fall back to result if not provided
        if value is UNRESOLVED:
            value = True

        # Set output values
        self.set_output_values(
            {
                "yes": value if result else UNRESOLVED,
                "no": value if not result else UNRESOLVED,
            }
        )

        # expand socket sources for debugging
        if state.verbosity == NodeVerbosity.VERBOSE:
            log.debug(
                f"LogicalRouter {self.title} result: {result}",
                flags=active_flags,
                result=result,
                input_values=self.get_input_values(),
            )

            for socket in self.inputs:
                if socket.source:
                    log.debug(
                        f"LogicalRouter {self.title} Input {socket.name} source: {socket.source.node.title}.{socket.source.name} value: {socket.value} ! {socket.source.value}"
                    )
                else:
                    log.debug(
                        f"LogicalRouter {self.title} Input {socket.name} source: NOT CONNECTED"
                    )


@register("core/ORRouter")
class ORRouter(LogicalRouter):
    """
    Route a value based on OR logic where any of a - d is truthy (if connected)

    Truthy values are considered as True, False and None are considered as False

    If a value is provided, it will be returned if the result is True
    If no value is provided, True will be returned on the output activated through the result, the other output will be deactivated

    Inputs:

    - a: flag A
    - b: flag B
    - c: flag C
    - d: flag D

    Outputs:

    - yes: if the result is True
    - no: if the result is False
    """

    _op = "or"

    def __init__(self, title="OR Router", **kwargs):
        super().__init__(title=title, **kwargs)


@register("core/ANDRouter")
class ANDRouter(LogicalRouter):
    """
    Route a value based on AND logic where all of a - d are truthy (if connected)

    Truthy values are considered as True, False and None are considered as False

    If a value is provided, it will be returned if the result is True
    If no value is provided, True will be returned on the output activated through the result, the other output will be deactivated

    Inputs:

    - a: flag A
    - b: flag B
    - c: flag C
    - d: flag D

    Outputs:

    - yes: if the result is True
    - no: if the result is False
    """

    _op = "and"

    def __init__(self, title="AND Router", **kwargs):
        super().__init__(title=title, **kwargs)


@register("core/Invert")
class Invert(Node):
    """
    Takes a boolean input and inverts it

    Inputs:

    - value: boolean value

    Outputs:

    - value: inverted boolean value
    """

    def __init__(self, title="Invert", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value", socket_type="bool")
        self.add_output("value", socket_type="bool")

    async def run(self, state: GraphState):
        value = self.get_input_value("value")
        result = not Socket.as_bool(value)
        self.set_output_values({"value": result})


@register("core/Switch")
class Switch(Node):
    """
    Checks if the input value is not None or False

    If the value is truthy, the yes output is activated, otherwise the no output is activated

    Inputs:

    - value: value to check

    Properties:

    - pass_through: if True, the value will be passed through to the output, otherwise True will be passed through

    Outputs:

    - yes: if the value is truthy
    - no: if the value is not truthy
    """

    class Fields:
        pass_through = PropertyField(
            name="pass_through",
            type="bool",
            default=True,
            description="If True, the value will be passed through to the output, otherwise True will be passed through",
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            icon="F0641",
        )

    def __init__(self, title="Switch", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value")

        self.set_property("pass_through", True)

        self.add_output("yes")
        self.add_output("no")

    async def run(self, state: GraphState):
        value = self.get_input_value("value")
        pass_through = self.get_property("pass_through")

        result = is_truthy(value)

        if not pass_through:
            value = True

        self.set_output_values(
            {
                "yes": value if result else UNRESOLVED,
                "no": value if not result else UNRESOLVED,
            }
        )

        self.get_output_socket("yes").deactivated = not result
        self.get_output_socket("no").deactivated = result


@register("core/RSwitch")
class RSwitch(Node):
    """
    Checks if the a value is truthy

    If the value is truthy, the yes input is routed to the output, otherwise the no input is routed to the output

    Inputs:

    - check: value to check
    - yes: value to return if the check value is truthy
    - no: value to return if the check value is not truthy

    Outputs:

    - value: the value to return
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            icon="F0641",
        )

    def __init__(self, title="RSwitch", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("check", optional=True)
        self.add_input("yes", optional=True)
        self.add_input("no", optional=True)
        self.add_output("value")

    async def run(self, state: GraphState):
        check = self.get_input_value("check")
        yes = self.get_input_value("yes")
        no = self.get_input_value("no")

        check = is_truthy(check)

        result = yes if check else no

        self.set_output_values({"value": result})


@register("core/RSwitchAdvanced")
class RSwitchAdvanced(Node):
    """
    Checks if the a value is truthy

    If the value is truthy, the yes input is routed to yes output and the no output is deactivated, otherwise the no input is routed to the no output and the yes output is deactivated

    Inputs:

    - check: value to check
    - yes: value to return if the check value is truthy
    - no: value to return if the check value is not truthy

    Outputs:

    - yes: the value to return if the check value is truthy
    - no: the value to return if the check value is not truthy
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            icon="F0641",
        )

    def __init__(self, title="RSwitch Advanced", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("check", optional=True)
        self.add_input("yes", optional=True)
        self.add_input("no", optional=True)
        self.add_output("yes")
        self.add_output("no")

    async def run(self, state: GraphState):
        check = self.get_input_value("check")
        yes = self.get_input_value("yes")
        no = self.get_input_value("no")

        check = is_truthy(check)

        result = yes if check else no

        self.set_output_values(
            {
                "yes": result if check else UNRESOLVED,
                "no": result if not check else UNRESOLVED,
            }
        )


@register("core/Case")
class Case(Node):
    """
    Route a value based on attribute value check (exact match)
    like a switch / case statement.

    Inputs:

    - value: value to check

    Properties:

    - attribute_name: the attribute name to check for the value. If not provided, the value itself will be used.
    - case_a: the value to compare to for case A
    - case_b: the value to compare to for case B
    - case_c: the value to compare to for case C
    - case_d: the value to compare to for case D

    Outputs:

    - a: if the value matches case A
    - b: if the value matches case B
    - c: if the value matches case C
    - d: if the value matches case D
    """

    class Fields:
        attribute_name = PropertyField(
            name="attribute_name",
            type="str",
            default="",
            description="The attribute name to check for the value",
        )

        case_a = PropertyField(
            name="case_a",
            type="str",
            default="",
            description="The value to compare to for case A",
        )

        case_b = PropertyField(
            name="case_b",
            type="str",
            default="",
            description="The value to compare to for case B",
        )

        case_c = PropertyField(
            name="case_c",
            type="str",
            default="",
            description="The value to compare to for case C",
        )

        case_d = PropertyField(
            name="case_d",
            type="str",
            default="",
            description="The value to compare to for case D",
        )

    def __init__(self, title="Case", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value")

        self.set_property("attribute_name", "")

        self.set_property("case_a", "")
        self.set_property("case_b", "")
        self.set_property("case_c", "")
        self.set_property("case_d", "")

        self.add_output("a")
        self.add_output("b")
        self.add_output("c")
        self.add_output("d")
        self.add_output("none")

    async def run(self, state: GraphState):
        value = self.get_input_value("value")
        attribute_name = self.get_property("attribute_name")

        if is_truthy(attribute_name) and attribute_name.strip():
            compare_to = getattr(value, attribute_name)
        else:
            compare_to = str(value)

        case_a = self.get_property("case_a")
        case_b = self.get_property("case_b")
        case_c = self.get_property("case_c")
        case_d = self.get_property("case_d")

        if compare_to == case_a:
            self.set_output_values({"a": value})
        elif compare_to == case_b:
            self.set_output_values({"b": value})
        elif compare_to == case_c:
            self.set_output_values({"c": value})
        elif compare_to == case_d:
            self.set_output_values({"d": value})
        else:
            self.set_output_values({"none": value})

        if state.verbosity >= NodeVerbosity.NORMAL:
            log.debug(
                f"Case {self.title} value: {value} attribute_name: {attribute_name} cases: {case_a}, {case_b}, {case_c}, {case_d}",
                compare_to=compare_to,
            )


@register("core/CaseRouter")
class CaseRouter(Node):
    """
    Route specific input values based on a check value match.
    Only the matching input is routed to its corresponding output, others are deactivated.

    Inputs:

    - check: value to check
    - a: value to route for case A
    - b: value to route for case B
    - c: value to route for case C
    - d: value to route for case D
    - default: value to route if no match

    Properties:

    - attribute_name: the attribute name to check for the check value. If not provided, the value itself will be used.
    - case_a: the value to compare to for case A
    - case_b: the value to compare to for case B
    - case_c: the value to compare to for case C
    - case_d: the value to compare to for case D

    Outputs:

    - value: the value of the matching case or default
    """

    class Fields:
        attribute_name = PropertyField(
            name="attribute_name",
            type="str",
            default="",
            description="The attribute name to check for the check value",
        )

        case_a = PropertyField(
            name="case_a",
            type="str",
            default="",
            description="The value to compare to for case A",
        )

        case_b = PropertyField(
            name="case_b",
            type="str",
            default="",
            description="The value to compare to for case B",
        )

        case_c = PropertyField(
            name="case_c",
            type="str",
            default="",
            description="The value to compare to for case C",
        )

        case_d = PropertyField(
            name="case_d",
            type="str",
            default="",
            description="The value to compare to for case D",
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            icon="F0641",
        )

    def __init__(self, title="Case Router", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("check")
        self.add_input("a", optional=True)
        self.add_input("b", optional=True)
        self.add_input("c", optional=True)
        self.add_input("d", optional=True)
        self.add_input("default", optional=True)

        self.set_property("attribute_name", "")

        self.set_property("case_a", "")
        self.set_property("case_b", "")
        self.set_property("case_c", "")
        self.set_property("case_d", "")

        self.add_output("value")

    async def run(self, state: GraphState):
        check_val = self.get_input_value("check")
        attribute_name = self.get_property("attribute_name")

        if is_truthy(attribute_name) and attribute_name.strip():
            compare_to = getattr(check_val, attribute_name)
        else:
            compare_to = str(check_val)

        case_a = self.get_property("case_a")
        case_b = self.get_property("case_b")
        case_c = self.get_property("case_c")
        case_d = self.get_property("case_d")

        input_a = self.get_input_value("a")
        input_b = self.get_input_value("b")
        input_c = self.get_input_value("c")
        input_d = self.get_input_value("d")
        input_default = self.get_input_value("default")

        # Compare as strings if properties are strings
        compare_to_str = str(compare_to)

        if compare_to_str == case_a:
            result = input_a
        elif compare_to_str == case_b:
            result = input_b
        elif compare_to_str == case_c:
            result = input_c
        elif compare_to_str == case_d:
            result = input_d
        else:
            result = input_default

        self.set_output_values({"value": result})

        if state.verbosity >= NodeVerbosity.NORMAL:
            log.debug(
                f"CaseRouter {self.title} check: {check_val} compare_to: {compare_to} result: {result}",
            )


@register("core/Coallesce")
class Coallesce(Node):
    """
    Takes a list of values and returns the first non-UNRESOLVED value

    Inputs:

    - a: value A
    - b: value B
    - c: value C
    - d: value D

    Outputs:

    - value: the first non-UNRESOLVED value
    """

    def __init__(self, title="Coallesce", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("a", optional=True)
        self.add_input("b", optional=True)
        self.add_input("c", optional=True)
        self.add_input("d", optional=True)
        self.add_output("value")

    async def run(self, state: GraphState):
        a = self.get_input_value("a")
        b = self.get_input_value("b")
        c = self.get_input_value("c")
        d = self.get_input_value("d")

        result = UNRESOLVED

        if is_truthy(a):
            result = a
        elif is_truthy(b):
            result = b
        elif is_truthy(c):
            result = c
        elif is_truthy(d):
            result = d

        self.set_output_values({"value": result})


@register("core/MakeBool")
class MakeBool(Node):
    """
    Creates a boolean value

    Properties:

    - value: boolean value

    Outputs:

    - value: boolean value
    """

    class Fields:
        value = PropertyField(
            name="value", type="bool", default=True, description="The boolean value"
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            auto_title="{value}",
        )

    def __init__(self, title="Make Bool", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("value", True)
        self.add_output("value", socket_type="bool")

    async def run(self, state: GraphState):
        value = self.get_input_value("value")
        self.set_output_values({"value": value})


@register("core/AsBool")
class AsBool(Node):
    """
    Converts a value to a boolean

    This specfically handles UNRESOLVED by casting it to a default value

    Inputs:

    - value: value to convert

    Properties:

    - default: the default value to return if the value is UNRESOLVED

    Outputs:

    - value: boolean value
    """

    class Fields:
        default = PropertyField(
            name="default",
            type="bool",
            default=False,
            description="The default value to return if the value is UNRESOLVED",
        )

    def __init__(self, title="As Bool", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value", optional=True)
        self.set_property("default", False)
        self.add_output("value", socket_type="bool")

    async def run(self, state: GraphState):
        value = self.get_input_value("value")
        default = self.get_property("default")

        if value is UNRESOLVED:
            value = default

        if not isinstance(value, bool):
            try:
                value = bool(value)
            except Exception as e:
                raise InputValueError(f"Failed to convert value to bool: {e}")

        self.set_output_values({"value": value})


@register("core/ApplyDefault")
class ApplyDefault(Node):
    """
    Applies a default value if the input value is UNRESOLVED

    Inputs:

    - value: value to apply the default to
    - default: the default value to apply

    Properties:

    - apply_on_unresolved: if True, the default will be applied if the value is UNRESOLVED
    - apply_on_none: if True, the default will be applied if the value is None

    Outputs:

    - value: the value with the default applied
    """

    class Fields:
        apply_on_none = PropertyField(
            name="apply_on_none",
            type="bool",
            default=False,
            description="If True, the default will be applied if the value is None",
        )

        apply_on_unresolved = PropertyField(
            name="apply_on_unresolved",
            type="bool",
            default=True,
            description="If True, the default will be applied if the value is UNRESOLVED",
        )

    def __init__(self, title="Apply Default", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value", optional=True)
        self.add_input("default")
        self.set_property("apply_on_none", False)
        self.set_property("apply_on_unresolved", True)
        self.add_output("value")

    async def run(self, state: GraphState):
        value = self.get_input_value("value")
        default = self.require_input("default")
        apply_on_none = self.get_property("apply_on_none")
        apply_on_unresolved = self.get_property("apply_on_unresolved")

        if apply_on_unresolved and value is UNRESOLVED:
            value = default

        if apply_on_none and value is None:
            value = default

        self.set_output_values({"value": value})
