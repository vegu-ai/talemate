import structlog
from .core import Node, GraphState, PropertyField, InputValueError, UNRESOLVED
from .core.dynamic import DynamicSocketNodeBase
from .registry import register
from talemate.util.prompt import condensed
from talemate.prompts.base import Prompt

log = structlog.get_logger("talemate.game.engine.nodes.string")


@register("data/string/AsString")
class AsString(Node):
    """
    Converts a value to a string
    """

    def __init__(self, title="As String", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value", socket_type="any")
        self.add_output("value", socket_type="str")

    async def run(self, state: GraphState):
        value = self.normalized_input_value("value")
        self.set_output_values({"value": str(value)})


@register("data/string/Make")
class MakeString(Node):
    """Creates a string

    Creates a string with the specified value.

    Properties:

    - value: The string value to create

    Outputs:

    - value: The created string value
    """

    class Fields:
        value = PropertyField(
            name="value",
            description="The string value to create",
            type="str",
            default="",
        )

    def __init__(self, title="Make String", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("value", "")
        self.add_output("value", socket_type="str")

    async def run(self, state: GraphState):
        value = self.get_property("value")
        self.set_output_values({"value": value})


@register("data/string/MakeText")
class MakeText(MakeString):
    """
    Same as make string but will be rendered with a multiline text editor

    Properties:

    - value: The string value to create

    Outputs:

    - value: The created string value
    """

    class Fields:
        value = PropertyField(
            name="value",
            description="The string value to create",
            type="text",
            default="",
        )

    def __init__(self, title="Make Text", **kwargs):
        super().__init__(title=title, **kwargs)


@register("data/string/Split")
class Split(Node):
    """Splits a string into a list based on a delimiter

    Divides a string into multiple parts using a specified delimiter.

    Inputs:

    - string: The string to split
    - delimiter: Character(s) to use as the split point (optional)

    Properties:

    - delimiter: Default delimiter to use when not provided via input
    - max_splits: Maximum number of splits to perform (-1 for all possible splits)

    Outputs:

    - parts: List of string parts after splitting
    """

    class Fields:
        delimiter = PropertyField(
            name="delimiter",
            description="Character(s) to use as the split point",
            type="str",
            default=" ",
        )
        max_splits = PropertyField(
            name="max_splits",
            description="Maximum number of splits to perform (-1 for all possible splits)",
            type="int",
            default=-1,
        )

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("delimiter", socket_type="str", optional=True)
        self.add_output("parts", socket_type="list")

        self.set_property("delimiter", " ")
        self.set_property("max_splits", -1)

    async def run(self, state: GraphState):
        string: str = self.get_input_value("string")
        delimiter = self.get_input_value("delimiter")
        max_splits = self.get_property("max_splits")

        # handle escaped newline delimiter
        if delimiter == "\\n":
            delimiter = "\n"

        parts = string.split(delimiter, maxsplit=max_splits)
        self.set_output_values({"parts": parts})


@register("data/string/Join")
class Join(Node):
    """Joins a list of strings with a delimiter

    Combines a list of strings into a single string with a specified delimiter between each element.

    Inputs:

    - strings: List of strings to join
    - delimiter: Character(s) to insert between each string (optional)

    Properties:

    - delimiter: Default delimiter to use when not provided via input

    Outputs:

    - result: The joined string
    """

    class Fields:
        delimiter = PropertyField(
            name="delimiter",
            description="Character(s) to insert between each string",
            type="str",
            default=" ",
        )

    def setup(self):
        self.add_input("strings", socket_type="list")
        self.add_input("delimiter", socket_type="str", optional=True)
        self.add_output("result", socket_type="str")

        self.set_property("delimiter", " ")

    async def run(self, state: GraphState):
        strings = self.get_input_value("strings")
        delimiter = self.get_input_value("delimiter")

        # handle escaped newline delimiter
        if delimiter == "\\n":
            delimiter = "\n"

        if not all(isinstance(s, str) for s in strings):
            raise InputValueError(self, "strings", "All items must be strings")

        result = delimiter.join(strings)
        self.set_output_values({"result": result})


@register("data/string/Replace")
class Replace(Node):
    """Replaces occurrences of a substring with another

    Searches for all occurrences of a substring and replaces them with a new string.

    Inputs:

    - string: The original string
    - old: Substring to find and replace
    - new: Replacement string

    Properties:

    - count: Maximum number of replacements to make (-1 for all occurrences)

    Outputs:

    - result: The string after replacements
    """

    class Fields:
        count = PropertyField(
            name="count",
            description="Maximum number of replacements to make (-1 for all occurrences)",
            type="int",
            default=-1,
        )
        old = PropertyField(
            name="old",
            description="Substring to find and replace",
            type="str",
            default="",
        )
        new = PropertyField(
            name="new",
            description="Replacement string",
            type="str",
            default="",
        )

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("old", socket_type="str")
        self.add_input("new", socket_type="str")
        self.add_output("result", socket_type="str")

        self.set_property("old", "")
        self.set_property("new", "")
        self.set_property("count", -1)  # -1 means replace all

    async def run(self, state: GraphState):
        string = self.normalized_input_value("string") or ""
        old = self.normalized_input_value("old") or ""
        new = self.normalized_input_value("new") or ""
        count = self.get_property("count")

        result = string.replace(old, new, count)
        self.set_output_values({"result": result})


@register("data/string/Format")
class Format(Node):
    """Python-style string formatting with variables

    Formats a template string by replacing placeholders with values from a variables dictionary,
    using Python's format() string method.

    Inputs:

    - template: A format string with placeholders (e.g., "Hello, {name}")
    - variables: Dictionary of variable names and values to insert

    Outputs:

    - result: The formatted string
    """

    def setup(self):
        self.add_input("template", socket_type="str")
        self.add_input("variables", socket_type="dict")
        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        template = self.get_input_value("template")
        variables = self.get_input_value("variables")

        try:
            result = template.format(**variables)
            self.set_output_values({"result": result})
        except (KeyError, ValueError) as e:
            raise InputValueError(self, "variables", f"Format error: {str(e)}")


@register("data/string/AdvancedFormat")
class AdvancedFormat(DynamicSocketNodeBase):
    """
    Python-style string formatting with dynamic inputs.

    Behaves like Format but supports dynamic inputs similar to DictCollector.
    Dynamic inputs can be:
    - a tuple (key, value)
    - a scalar value, in which case the key is derived from the source
      socket/node using a best-effort heuristic.

    Inputs:
    - template: A format string with placeholders (e.g., "Hello, {name}")
    - variables: Optional base dictionary to merge into
      (dynamic inputs extend/override these)

    Dynamic inputs: item{i}

    Outputs:
    - result: The formatted string
    """

    # Frontend dynamic sockets configuration
    dynamic_input_label: str = "item{i}"
    supports_dynamic_sockets: bool = True
    dynamic_input_type: str = "any"

    class Fields:
        template = PropertyField(
            name="template",
            description='A format string with placeholders (e.g., "Hello, {name}")',
            type="text",
            default="",
        )

    def __init__(self, title="Advanced Format", **kwargs):
        super().__init__(title=title, **kwargs)

    def add_static_inputs(self):
        self.add_input("template", socket_type="str")
        self.set_property("template", "")
        self.add_input("variables", socket_type="dict", optional=True)

    def setup(self):
        super().setup()
        self.add_output("result", socket_type="str")

    async def format(self, template: str, variables: dict) -> str:
        return template.format(**variables)

    async def run(self, state: GraphState):
        template = self.normalized_input_value("template")
        base_vars = self.normalized_input_value("variables") or {}

        # Build variables from dynamic inputs
        variables = dict(base_vars)

        for socket in self.inputs:
            if socket.name in ["template", "variables"]:
                continue

            if socket.source and socket.value is not UNRESOLVED:
                value = socket.value
                # Treat (key, value) tuples specially
                if isinstance(value, tuple) and len(value) == 2:
                    key, val = value
                    variables[key] = val
                else:
                    key = self.best_key_name_for_socket(socket)
                    variables[key] = value
            elif socket.source and socket.value is UNRESOLVED:
                # any connected socket is no longer optional
                return

        try:
            result = await self.format(template, variables)
        except (KeyError, ValueError) as e:
            raise InputValueError(self, "variables", f"Format error: {str(e)}")

        self.set_output_values({"result": result})


@register("prompt/Jinja2Format")
class Jinja2Format(AdvancedFormat):
    """
    Formats a string using jinja2 with Prompt's template environment

    Uses a Prompt instance to render templates, providing access to all
    Prompt globals, filters, and template features.

    Inputs:
    - template: The template string to render
    - variables: Dictionary of variables for the template
    - scope: Optional agent scope (e.g., "director") for template includes
    """

    def __init__(self, title="Jinja2 Format", **kwargs):
        super().__init__(title=title, **kwargs)

    def add_static_inputs(self):
        super().add_static_inputs()
        self.add_input("scope", socket_type="str", optional=True)

    async def format(self, template: str, variables: dict) -> str:
        # Get the scope if provided
        scope = self.normalized_input_value("scope")

        # Determine agent_type from scope
        agent_type = ""
        if scope and scope != "scene":
            agent_type = scope

        # Create a Prompt instance from the template text with agent_type context
        prompt = Prompt.from_text(template, vars=variables, agent_type=agent_type)
        # Render the template using Prompt's render method
        return prompt.render()


@register("data/string/Case")
class Case(Node):
    """Changes string case (upper, lower, title, capitalize)

    Converts a string to a different case format, such as uppercase, lowercase,
    title case, or capitalized.

    Inputs:

    - string: The string to transform

    Properties:

    - operation: Case operation to perform (upper, lower, title, capitalize)

    Outputs:

    - result: The transformed string
    """

    class Fields:
        operation = PropertyField(
            name="operation",
            description="Case operation to perform",
            type="str",
            default="lower",
            choices=["upper", "lower", "title", "capitalize"],
        )

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_output("result", socket_type="str")

        self.set_property("operation", "lower")

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        operation = self.get_property("operation")

        if operation == "upper":
            result = string.upper()
        elif operation == "lower":
            result = string.lower()
        elif operation == "title":
            result = string.title()
        elif operation == "capitalize":
            result = string.capitalize()

        self.set_output_values({"result": result})


@register("data/string/Trim")
class Trim(Node):
    """Removes characters from start/end of string

    Removes specified characters from the beginning, end, or both ends of a string.
    By default, it removes whitespace if no specific characters are provided.

    Inputs:

    - string: The string to trim
    - chars: Character(s) to remove (optional, defaults to whitespace)

    Properties:

    - mode: Where to trim from (left, right, both)
    - chars: Default characters to remove when not provided via input

    Outputs:

    - result: The trimmed string
    """

    class Fields:
        mode = PropertyField(
            name="mode",
            description="Trim mode",
            type="str",
            default="both",
            choices=["left", "right", "both"],
        )

        chars = PropertyField(
            name="chars", description="Character(s) to remove", type="str", default=None
        )

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("chars", socket_type="str", optional=True)
        self.add_output("result", socket_type="str")

        self.set_property("mode", "both")
        self.set_property("chars", None)  # None means whitespace

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        chars = self.get_input_value("chars")
        mode = self.get_property("mode")

        # handle escaped newline chars
        if chars and "\\n" in chars:
            chars = chars.replace("\\n", "\n")

        if mode == "left":
            result = string.lstrip(chars)
        elif mode == "right":
            result = string.rstrip(chars)
        else:
            result = string.strip(chars)

        self.set_output_values({"result": result})


@register("data/string/Substring")
class Substring(Node):
    """Extracts a portion of a string using indices

    Extracts a substring from the original string using start and end indices.

    Inputs:

    - string: The source string
    - start: Starting index (optional)
    - end: Ending index (optional)

    Properties:

    - start: Default starting index (0-based)
    - end: Default ending index (None means until the end of the string)

    Outputs:

    - result: The extracted substring
    """

    class Fields:
        start = PropertyField(
            name="start",
            description="Starting index",
            type="int",
            default=0,
            min=0,
            step=1,
        )

        end = PropertyField(
            name="end",
            description="Ending index",
            type="int",
            default=None,
            min=0,
            step=1,
        )

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("start", socket_type="int", optional=True)
        self.add_input("end", socket_type="int", optional=True)
        self.add_output("result", socket_type="str")

        self.set_property("start", 0)
        self.set_property("end", None)

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        start = self.get_input_value("start")
        end = self.get_input_value("end")

        result = string[start:end]
        self.set_output_values({"result": result})


@register("data/string/Extract")
class Extract(Node):
    """
    Extracts a portion of a string using a left and right anchor

    Finds the first valid block between anchors (no nested left_anchor inside).
    Falls back to everything after the left_anchor if no complete block is found.

    Examples:
    - "<TAG>nested<TAG>value</TAG>" -> "value" (first clean block)
    - "<TAG>value</TAG> ... <TAG>other</TAG>" -> "value" (first valid block)
    - "<TAG>no closing tag" -> "no closing tag" (fallback)

    Inputs:

    - string: The string to extract from
    - left_anchor: The left anchor
    - right_anchor: The right anchor

    Properties:

    - left_anchor: The left anchor
    - right_anchor: The right anchor
    - trim: Whether to trim the result

    Outputs:

    - result: The extracted substring
    """

    class Fields:
        left_anchor = PropertyField(
            name="left_anchor", description="The left anchor", type="str", default=""
        )
        right_anchor = PropertyField(
            name="right_anchor", description="The right anchor", type="str", default=""
        )
        trim = PropertyField(
            name="trim",
            description="Whether to trim the result",
            type="bool",
            default=True,
        )

    def __init__(self, title="Extract", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("left_anchor", socket_type="str", optional=True)
        self.add_input("right_anchor", socket_type="str", optional=True)

        self.set_property("left_anchor", "")
        self.set_property("right_anchor", "")
        self.set_property("trim", True)

        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        left_anchor = self.normalized_input_value("left_anchor") or ""
        right_anchor = self.normalized_input_value("right_anchor") or ""
        trim = self.normalized_input_value("trim")

        result = None

        # Split by left anchor to get segments
        parts = string.split(left_anchor)

        if len(parts) > 1:
            # Try to find the first valid block (segment with right_anchor, meaning no nested left_anchor)
            for part in parts[1:]:
                if right_anchor in part:
                    result = part.split(right_anchor, 1)[0]
                    break

            # Fallback: if no valid block found, take everything after the last left_anchor
            if result is None:
                result = parts[-1]
        else:
            result = ""

        if trim:
            result = result.strip()

        self.set_output_values({"result": result})


@register("data/string/StringCheck")
class StringCheck(Node):
    """Checks if a string starts with, ends with, or contains a substring

    Tests whether a string starts with, ends with, contains, or exactly equals a substring,
    with optional case sensitivity.

    Inputs:

    - string: The string to check
    - substring: The substring to look for

    Properties:

    - mode: Check operation to perform (startswith, endswith, contains, exact)
    - case_sensitive: Whether the check should be case-sensitive
    - substring: Default substring to check for when not provided via input

    Outputs:

    - result: Boolean result of the check
    """

    class Fields:
        mode = PropertyField(
            name="mode",
            description="Check operation to perform",
            type="str",
            default="contains",
            choices=["startswith", "endswith", "contains", "exact"],
        )
        case_sensitive = PropertyField(
            name="case_sensitive",
            description="Whether the check should be case-sensitive",
            type="bool",
            default=True,
        )
        substring = PropertyField(
            name="substring",
            description="Default substring to check for",
            type="str",
            default="",
        )

    def __init__(self, title="String Check", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("substring", socket_type="str")
        self.add_output("result", socket_type="bool")

        self.set_property("substring", "")
        self.set_property("mode", "contains")
        self.set_property("case_sensitive", True)

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        substring = self.get_input_value("substring")
        mode = self.get_property("mode")
        case_sensitive = self.get_property("case_sensitive")

        if not string:
            self.set_output_values({"result": False})
            return

        if not case_sensitive:
            string = string.lower()
            substring = substring.lower()

        if mode == "startswith":
            result = string.startswith(substring)
        elif mode == "endswith":
            result = string.endswith(substring)
        elif mode == "exact":
            result = string == substring
        else:  # contains
            result = substring in string

        self.set_output_values({"result": result})


@register("data/string/Excerpt")
class Excerpt(Node):
    """
    Returns a excerpt of a string based on length.
    """

    class Fields:
        length = PropertyField(
            name="length",
            description="The length of the excerpt",
            type="int",
            default=100,
        )
        add_ellipsis = PropertyField(
            name="add_ellipsis",
            description="Whether to add an ellipsis to the end of the excerpt",
            type="bool",
            default=True,
        )

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_output("result", socket_type="str")

        self.set_property("length", 100)
        self.set_property("add_ellipsis", True)

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        length = self.get_property("length")
        add_ellipsis = self.get_property("add_ellipsis")

        result = string[:length]

        if add_ellipsis and len(string) > length:
            result = result + "..."

        self.set_output_values({"result": result})


@register("data/string/Condensed")
class Condensed(Node):
    """
    Condenses a string by removing line breaks and extra spaces.
    """

    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        result = condensed(string)
        self.set_output_values({"result": result})
