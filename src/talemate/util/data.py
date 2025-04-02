import json
import re
import json
import structlog

__all__ = [
    "fix_faulty_json",
    "extract_json",
    'JSONEncoder',
]

log = structlog.get_logger("talemate.util.dedupe")

class JSONEncoder(json.JSONEncoder):
    """
    Default to str() on unknown types
    """
    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)
        


def fix_faulty_json(data: str) -> str:
    # Fix missing commas
    data = re.sub(r"}\s*{", "},{", data)
    data = re.sub(r"]\s*{", "],{", data)
    data = re.sub(r"}\s*\[", "},{", data)
    data = re.sub(r"]\s*\[", "],[", data)

    # Fix trailing commas
    data = re.sub(r",\s*}", "}", data)
    data = re.sub(r",\s*]", "]", data)

    try:
        json.loads(data)
    except json.JSONDecodeError:
        try:
            json.loads(data + "}")
            return data + "}"
        except json.JSONDecodeError:
            try:
                json.loads(data + "]")
                return data + "]"
            except json.JSONDecodeError:
                return data

    return data


def extract_json(s):
    """
    Extracts a JSON string from the beginning of the input string `s`.

    Parameters:
        s (str): The input string containing a JSON string at the beginning.

    Returns:
        str: The extracted JSON string.
        dict: The parsed JSON object.

    Raises:
        ValueError: If a valid JSON string is not found.
    """
    open_brackets = 0
    close_brackets = 0
    bracket_stack = []
    json_string_start = None
    s = s.lstrip()  # Strip white spaces and line breaks from the beginning
    i = 0

    log.debug("extract_json", s=s)

    # Iterate through the string.
    while i < len(s):
        # Count the opening and closing curly brackets.
        if s[i] == "{" or s[i] == "[":
            bracket_stack.append(s[i])
            open_brackets += 1
            if json_string_start is None:
                json_string_start = i
        elif s[i] == "}" or s[i] == "]":
            bracket_stack
            close_brackets += 1
            # Check if the brackets match, indicating a complete JSON string.
            if open_brackets == close_brackets:
                json_string = s[json_string_start : i + 1]
                # Try to parse the JSON string.
                return json_string, json.loads(json_string)
        i += 1

    if json_string_start is None:
        raise ValueError("No JSON string found.")

    json_string = s[json_string_start:]
    while bracket_stack:
        char = bracket_stack.pop()
        if char == "{":
            json_string += "}"
        elif char == "[":
            json_string += "]"

    json_object = json.loads(json_string)
    return json_string, json_object