import json
import re
import structlog
import yaml
from typing import TYPE_CHECKING
from datetime import date, datetime

__all__ = [
    "fix_faulty_json",
    "extract_data",
    "extract_data_with_ai_fallback",
    "extract_json",
    "extract_json_v2",
    "extract_yaml_v2",
    "JSONEncoder",
    "DataParsingError",
    "fix_yaml_colon_in_strings",
    "fix_faulty_yaml",
]

log = structlog.get_logger("talemate.util.dedupe")


if TYPE_CHECKING:
    from talemate.client.base import ClientBase
    from talemate.prompts.base import Prompt


class JSONEncoder(json.JSONEncoder):
    """
    Default to str() on unknown types
    """

    def default(self, obj):
        try:
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            return super().default(obj)
        except TypeError:
            return str(obj)


class DataParsingError(Exception):
    """
    Custom error class for data parsing errors (JSON, YAML, etc).
    """

    def __init__(self, message, data=None):
        self.message = message
        self.data = data
        super().__init__(self.message)


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


def extract_json_v2(text):
    """
    Extracts JSON structures from code blocks in a text string.

    Parameters:
        text (str): The input text containing code blocks with JSON.

    Returns:
        list: A list of unique parsed JSON objects.

    Raises:
        DataParsingError: If invalid JSON is encountered in code blocks.
    """
    unique_jsons = []
    seen = set()

    # Split by code block markers
    parts = text.split("```")

    # Process every code block (odd indices after split)
    for i in range(1, len(parts), 2):
        if i >= len(parts):
            break

        block = parts[i].strip()

        # Skip empty blocks
        if not block:
            continue

        # Remove language identifier if present
        if block.startswith("json"):
            block = block[4:].strip()

        # Try to parse the block as a single JSON object first
        try:
            fixed_block = fix_faulty_json(block)
            json_obj = json.loads(fixed_block)

            # Convert to string for deduplication check
            json_str = json.dumps(json_obj, sort_keys=True)

            # Only add if we haven't seen this object before
            if json_str not in seen:
                seen.add(json_str)
                unique_jsons.append(json_obj)
        except json.JSONDecodeError:
            # If it fails, try to split and parse multiple JSON objects
            try:
                # Add commas between adjacent objects if needed
                fixed_block = fix_faulty_json(block)

                # Check for multiple JSON objects by looking for patterns like }{ or }[
                # Replace with },{ or },[
                fixed_block = re.sub(r"}\s*{", "},{", fixed_block)
                fixed_block = re.sub(r"]\s*{", "],[", fixed_block)
                fixed_block = re.sub(r"}\s*\[", "},[", fixed_block)
                fixed_block = re.sub(r"]\s*\[", "],[", fixed_block)

                # Wrap in array brackets if not already an array
                if not (fixed_block.startswith("[") and fixed_block.endswith("]")):
                    fixed_block = "[" + fixed_block + "]"

                # Parse as array
                json_array = json.loads(fixed_block)

                # Process each object in the array
                for json_obj in json_array:
                    json_str = json.dumps(json_obj, sort_keys=True)
                    if json_str not in seen:
                        seen.add(json_str)
                        unique_jsons.append(json_obj)
            except json.JSONDecodeError as e:
                raise DataParsingError(f"Invalid JSON in code block: {str(e)}", block)

    return unique_jsons


def extract_yaml_v2(text):
    """
    Extracts YAML structures from code blocks in a text string.

    Parameters:
        text (str): The input text containing code blocks with YAML.

    Returns:
        list: A list of unique parsed YAML objects.

    Raises:
        DataParsingError: If invalid YAML is encountered in code blocks.
    """
    unique_yamls = []
    seen = set()

    # Split by code block markers
    parts = text.split("```")

    # Process every code block (odd indices after split)
    for i in range(1, len(parts), 2):
        if i >= len(parts):
            break

        block = parts[i].strip()

        # Skip empty blocks
        if not block:
            continue

        # Remove language identifier if present
        if block.startswith("yaml") or block.startswith("yml"):
            block = block[block.find("\n") :].strip()

        # Parse YAML (supporting multiple documents with ---)
        try:
            # First try to parse the YAML as-is
            yaml_docs = list(yaml.safe_load_all(block))
        except yaml.YAMLError as e:
            # If parsing fails, try to fix the YAML and parse again
            try:
                # Apply fixes to YAML before parsing
                fixed_block = fix_faulty_yaml(block)

                # Use safe_load_all to get all YAML documents in the block
                yaml_docs = list(yaml.safe_load_all(fixed_block))
            except yaml.YAMLError:
                # If it still fails, raise the original error
                raise DataParsingError(f"Invalid YAML in code block: {str(e)}", block)

        # If we only have one document and it's a dict, check if we should split it into multiple documents
        if len(yaml_docs) == 1 and isinstance(yaml_docs[0], dict) and yaml_docs[0]:
            # Check if the document has a nested structure where first level keys represent separate documents
            root_doc = yaml_docs[0]

            # If the first level keys all have dict values, treat them as separate documents
            if all(isinstance(root_doc[key], dict) for key in root_doc):
                # Replace yaml_docs with separate documents
                yaml_docs = [root_doc[key] for key in root_doc]

        # Process each YAML document
        for yaml_obj in yaml_docs:
            # Skip if None (empty YAML)
            if yaml_obj is None:
                continue

            # Convert to JSON string for deduplication check
            json_str = json.dumps(yaml_obj, sort_keys=True, cls=JSONEncoder)

            # Only add if we haven't seen this object before
            if json_str not in seen:
                seen.add(json_str)
                unique_yamls.append(yaml_obj)

    return unique_yamls


def fix_yaml_colon_in_strings(yaml_text):
    """
    Fixes YAML issues with unquoted strings containing colons.

    Parameters:
        yaml_text (str): The input YAML text to fix

    Returns:
        str: Fixed YAML text
    """
    # Split the YAML text into lines
    lines = yaml_text.split("\n")
    result_lines = []

    for line in lines:
        # Look for lines with key-value pairs where value has a colon
        if ":" in line and line.count(":") > 1:
            # Check if this is a list item with a colon
            list_item_match = re.match(r"^(\s*)-\s+(.+)$", line)
            if list_item_match:
                indent, content = list_item_match.groups()
                if ":" in content and not (
                    content.startswith('"')
                    or content.startswith("'")
                    or content.startswith(">")
                    or content.startswith("|")
                ):
                    # Convert to block scalar notation for list item
                    result_lines.append(f"{indent}- |-")
                    # Add the content indented on the next line
                    result_lines.append(f"{indent}  {content}")
                    continue

            # Check if this looks like a key: value line with an unquoted value containing a colon
            key_match = re.match(r"^(\s*)([^:]+):\s+(.+)$", line)
            if key_match:
                indent, key, value = key_match.groups()
                # If value has a colon and isn't already properly quoted/formatted
                if ":" in value and not (
                    value.startswith('"')
                    or value.startswith("'")
                    or value.startswith(">")
                    or value.startswith("|")
                ):
                    # Convert to block scalar notation
                    result_lines.append(f"{indent}{key}: |-")
                    # Add the value indented on the next line
                    result_lines.append(f"{indent}  {value}")
                    continue

        # If no processing needed, keep the original line
        result_lines.append(line)

    return "\n".join(result_lines)


def fix_faulty_yaml(yaml_text):
    """
    Fixes common YAML syntax issues by applying a series of fixers.

    Parameters:
        yaml_text (str): The input YAML text to fix

    Returns:
        str: Fixed YAML text
    """
    # Apply specific fixers in sequence
    fixed_text = fix_yaml_colon_in_strings(yaml_text)

    # Add more fixers here as needed

    return fixed_text


def extract_data(text, schema_format: str = "json"):
    """
    Extracts data from text based on the schema format.
    """
    if schema_format == "json":
        return extract_json_v2(text)
    elif schema_format == "yaml":
        return extract_yaml_v2(text)
    else:
        raise ValueError(f"Unsupported schema format: {schema_format}")


async def extract_data_with_ai_fallback(
    client: "ClientBase", text: str, prompt_cls: "Prompt", schema_format: str = "json"
):
    """
    Try util.extract_data first. If it fails, ask the provided client to fix the
    malformed data like prompts/base.py does, then parse again. The data type
    (json|yaml) should be set by the client (client.data_format) and can be overridden
    via schema_format.
    """
    fmt = (getattr(client, "data_format", None) or schema_format or "json").lower()

    log.debug(
        "extract_data_with_ai_fallback", text=text, schema_format=schema_format, fmt=fmt
    )

    # First attempt: strict parse using our extractors with a fenced block
    try:
        fenced = f"```{fmt}\n{text}\n```"
        parsed = extract_data(fenced, fmt)
        log.debug("extract_data_with_ai_fallback", parsed=parsed)
        if parsed:
            return parsed
    except Exception as e:
        log.error("extract_data_with_ai_fallback", error=e)
        # ignore and proceed to AI repair
        pass

    # Second attempt: ask the model to repair and parse again
    try:
        log.debug("extract_data_with_ai_fallback", fmt=fmt, payload=text)
        if fmt == "json":
            fixed = await prompt_cls.request(
                "focal.fix-data",
                client,
                "analyze_long",
                vars={
                    "text": text,
                },
                dedupe_enabled=False,
            )
            try:
                return extract_json_v2(fixed)
            except Exception:
                return json.loads(fixed)
        elif fmt == "yaml":
            fixed = await prompt_cls.request(
                "focal.fix-data",
                client,
                "analyze_long",
                vars={
                    "text": text,
                },
                dedupe_enabled=False,
            )
            return extract_yaml_v2(fixed)
        else:
            raise ValueError(f"Unsupported schema format: {fmt}")
    except Exception as e:
        log.error("extract_data_with_ai_fallback", error=e)
        raise DataParsingError(f"AI-assisted {fmt.upper()} extraction failed: {e}")
