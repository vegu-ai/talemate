import re
import structlog
from .core import Node, GraphState, UNRESOLVED, PropertyField, InputValueError
from .registry import register

log = structlog.get_logger("talemate.game.engine.nodes.string")

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
            default=""
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
            default=""
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
            default=" "
        )
        max_splits = PropertyField(
            name="max_splits",
            description="Maximum number of splits to perform (-1 for all possible splits)",
            type="int",
            default=-1
        )
    
    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("delimiter", socket_type="str", optional=True)
        self.add_output("parts", socket_type="list")
        
        self.set_property("delimiter", " ")
        self.set_property("max_splits", -1)
        
    async def run(self, state: GraphState):
        string:str = self.get_input_value("string")
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
            default=" "
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
            default=-1
        )
    
    def setup(self):
        self.add_input("string", socket_type="str")
        self.add_input("old", socket_type="str")
        self.add_input("new", socket_type="str")
        self.add_output("result", socket_type="str")
        
        self.set_property("count", -1)  # -1 means replace all
        
    async def run(self, state: GraphState):
        string = self.get_input_value("string")
        old = self.get_input_value("old")
        new = self.get_input_value("new")
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
            choices=["upper", "lower", "title", "capitalize"]
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
            choices=["left", "right", "both"]
        )
        
        chars = PropertyField(
            name="chars",
            description="Character(s) to remove",
            type="str",
            default=None
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
            step=1
        )
        
        end = PropertyField(
            name="end",
            description="Ending index",
            type="int",
            default=None,
            min=0,
            step=1
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
    
    Whatever is between the left and right anchors will be extracted.
    
    The first occurrence of the left anchor will be used.
    
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
            name="left_anchor",
            description="The left anchor",
            type="str",
            default=""
        )
        right_anchor = PropertyField(
            name="right_anchor",
            description="The right anchor",
            type="str",
            default=""
        )
        trim = PropertyField(
            name="trim",
            description="Whether to trim the result",
            type="bool",
            default=True
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
        
        parts = string.split(left_anchor, 1)
        if len(parts) > 1:
            result = parts[1].split(right_anchor, 1)[0]
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
            choices=["startswith", "endswith", "contains", "exact"]
        )
        case_sensitive = PropertyField(
            name="case_sensitive",
            description="Whether the check should be case-sensitive",
            type="bool",
            default=True
        )
        substring = PropertyField(
            name="substring",
            description="Default substring to check for",
            type="str",
            default=""
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