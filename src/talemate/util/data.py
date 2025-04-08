import json
import re
import json
import structlog
import yaml
from datetime import date, datetime

__all__ = [
    "fix_faulty_json",
    "extract_json",
    "extract_json_v2",
    "extract_yaml_v2",
    'JSONEncoder',
    'DataParsingError',
]

log = structlog.get_logger("talemate.util.dedupe")

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
        
        # Fix and parse JSON
        fixed_block = fix_faulty_json(block)
        try:
            json_obj = json.loads(fixed_block)
            
            # Convert to string for deduplication check
            json_str = json.dumps(json_obj, sort_keys=True)
            
            # Only add if we haven't seen this object before
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
            block = block[block.find("\n"):].strip()
        
        # Parse YAML
        try:
            yaml_obj = yaml.safe_load(block)
            
            # Skip if None (empty YAML)
            if yaml_obj is None:
                continue
                
            # Convert to JSON string for deduplication check
            # This works because YAML is a superset of JSON
            json_str = json.dumps(yaml_obj, sort_keys=True, cls=JSONEncoder)
            
            # Only add if we haven't seen this object before
            if json_str not in seen:
                seen.add(json_str)
                unique_yamls.append(yaml_obj)
        except yaml.YAMLError as e:
            raise DataParsingError(f"Invalid YAML in code block: {str(e)}", block)
            
    return unique_yamls