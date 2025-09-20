from .core import (
    Node,
    register,
    GraphState,
    UNRESOLVED,
    InputValueError,
    PropertyField,
)

from talemate.util.diff import dmp_inline_diff, plain_text_diff
from talemate.util.response import extract_list


@register("util/Counter")
class Counter(Node):
    """
    Counter node that increments a numeric value inside a
    dict and returns the new value.

    Inputs:
    - state: The graph state
    - dict: The dict containing the value to increment
    - key: The key to the value to increment
    - reset: If true, the value will be reset to 0

    Properties:
    - increment: The amount to increment the value by
    - key: The key to the value to increment
    - reset: If true, the value will be reset to 0

    Outputs:
    - value: The new value
    - dict: The dict with the new value
    """

    class Fields:
        increment = PropertyField(
            name="increment",
            type="number",
            default=1,
            step=1,
            min=1,
            description="The amount to increment the value by",
        )

        key = PropertyField(
            name="key",
            type="str",
            default="counter",
            description="The key to the value to increment",
        )

        reset = PropertyField(
            name="reset",
            type="bool",
            default=False,
            description="If true, the value will be reset to 0",
        )

    def __init__(self, title="Counter", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("dict", socket_type="dict")
        self.add_input("key", socket_type="str", optional=True)
        self.add_input("reset", socket_type="bool", optional=True)

        self.set_property("increment", 1)
        self.set_property("key", "counter")
        self.set_property("reset", False)

        self.add_output("value")
        self.add_output("dict", socket_type="dict")

    async def run(self, state: GraphState):
        dict_ = self.get_input_value("dict")
        key = self.get_input_value("key")
        reset = self.get_input_value("reset")
        increment = self.get_property("increment")

        if increment is UNRESOLVED:
            raise InputValueError(self, "increment", "Increment value is required")

        if reset:
            dict_[key] = 0
        else:
            dict_[key] = dict_.get(key, 0) + increment

        self.set_output_values({"value": dict_[key], "dict": dict_})


@register("util/Diff")
class Diff(Node):
    """
    Diff node that returns the diff between two strings.
    """

    def __init__(self, title="Diff", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("a", socket_type="str")
        self.add_input("b", socket_type="str")
        self.add_output("diff_plain", socket_type="str")
        self.add_output("diff_html", socket_type="str")
        self.add_output("a", socket_type="str")
        self.add_output("b", socket_type="str")

    async def run(self, state: GraphState):
        a = self.normalized_input_value("a") or ""
        b = self.normalized_input_value("b") or ""
        diff_plain = plain_text_diff(a, b)
        diff_html = dmp_inline_diff(a, b)
        self.set_output_values(
            {"diff_plain": diff_plain, "diff_html": diff_html, "a": a, "b": b}
        )


@register("util/ExtractList")
class ExtractList(Node):
    """
    Extracts a list from a string.
    """

    def __init__(self, title="Extract List", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_output("string", socket_type="str")
        self.add_output("list", socket_type="list")
        self.add_output("is_empty", socket_type="bool")

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        list = extract_list(string)
        is_empty = len(list) == 0
        self.set_output_values({"string": string, "list": list, "is_empty": is_empty})
