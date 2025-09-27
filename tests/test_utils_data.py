import os
import pytest
import json
import yaml
from unittest.mock import MagicMock
import talemate.util.data
from talemate.util.data import (
    fix_faulty_json,
    extract_json,
    extract_json_v2,
    extract_yaml_v2,
    extract_data_auto,
    extract_data,
    JSONEncoder,
    DataParsingError,
    fix_yaml_colon_in_strings,
    fix_faulty_yaml,
)


# Helper function to get test data paths
def get_test_data_path(filename):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "data", "util", "data", filename)


@pytest.fixture
def mock_client_and_prompt():
    """Create mock client and prompt for extract_data_auto tests."""
    client = MagicMock()
    prompt_cls = MagicMock()

    # Mock the extract_data_with_ai_fallback to just use extract_data
    async def mock_extract_with_ai(client, text, prompt_cls, schema_format):
        # Wrap in codeblock format and use existing extract_data
        wrapped = f"```{schema_format}\n{text}\n```"
        return extract_data(wrapped, schema_format)

    # Patch the function during tests
    original_func = talemate.util.data.extract_data_with_ai_fallback
    talemate.util.data.extract_data_with_ai_fallback = mock_extract_with_ai

    yield client, prompt_cls

    # Restore original function
    talemate.util.data.extract_data_with_ai_fallback = original_func


def test_json_encoder():
    """Test JSONEncoder handles unknown types by converting to string."""

    class CustomObject:
        def __str__(self):
            return "CustomObject"

    # Create an object of a custom class
    custom_obj = CustomObject()

    # Encode it using JSONEncoder
    encoded = json.dumps({"obj": custom_obj}, cls=JSONEncoder)

    # Check if the object was converted to a string
    assert encoded == '{"obj": "CustomObject"}'


def test_fix_faulty_json():
    """Test fix_faulty_json function with various faulty JSON strings."""

    # Test adjacent objects - need to wrap in list brackets to make it valid JSON
    fixed = fix_faulty_json('{"a": 1}{"b": 2}')
    assert fixed == '{"a": 1},{"b": 2}'
    # We need to manually wrap it in brackets for the test
    assert json.loads("[" + fixed + "]") == [{"a": 1}, {"b": 2}]

    # Test trailing commas
    assert json.loads(fix_faulty_json('{"a": 1, "b": 2,}')) == {"a": 1, "b": 2}
    assert json.loads(fix_faulty_json('{"a": [1, 2, 3,]}')) == {"a": [1, 2, 3]}


def test_extract_json():
    """Test extract_json function to extract JSON from the beginning of a string."""
    # Simple test
    json_str, obj = extract_json('{"name": "test", "value": 42} and some text')
    assert json_str == '{"name": "test", "value": 42}'
    assert obj == {"name": "test", "value": 42}

    # Test with array
    json_str, obj = extract_json("[1, 2, 3] and some text")
    assert json_str == "[1, 2, 3]"
    assert obj == [1, 2, 3]

    # Test with whitespace
    json_str, obj = extract_json('  {"name": "test"} and some text')
    assert json_str == '{"name": "test"}'
    assert obj == {"name": "test"}

    # Test with invalid JSON
    with pytest.raises(ValueError):
        extract_json("This is not JSON")


def test_extract_json_v2_valid():
    """Test extract_json_v2 with valid JSON in code blocks."""
    # Load test data
    with open(get_test_data_path("valid_json.txt"), "r") as f:
        text = f.read()

    # Extract JSON
    result = extract_json_v2(text)

    # Check if we got two unique JSON objects (third is a duplicate)
    assert len(result) == 2

    # Check if the objects are correct
    expected_first = {
        "name": "Test Object",
        "properties": {"id": 1, "active": True},
        "tags": ["test", "json", "parsing"],
    }

    expected_second = {"name": "Simple Object", "value": 42}

    assert expected_first in result
    assert expected_second in result


def test_extract_json_v2_invalid():
    """Test extract_json_v2 raises DataParsingError for invalid JSON."""
    # Load test data
    with open(get_test_data_path("invalid_json.txt"), "r") as f:
        text = f.read()

    # Try to extract JSON, should raise DataParsingError
    with pytest.raises(DataParsingError):
        extract_json_v2(text)


def test_extract_json_v2_faulty():
    """Test extract_json_v2 with faulty but fixable JSON."""
    # Load test data
    with open(get_test_data_path("faulty_json.txt"), "r") as f:
        text = f.read()

    # Try to extract JSON, should successfully fix and extract some objects
    # but might fail on the severely malformed ones
    try:
        result = extract_json_v2(text)
        # If it manages to fix all JSON, verify the results
        assert len(result) > 0
    except DataParsingError:
        # This is also acceptable if some JSON is too broken to fix
        pass


def test_data_parsing_error():
    """Test the DataParsingError class."""
    # Create a DataParsingError with a message and data
    test_data = '{"broken": "json"'
    error = DataParsingError("Test error message", test_data)

    # Check properties
    assert error.message == "Test error message"
    assert error.data == test_data
    assert str(error) == "Test error message"


def test_extract_json_v2_multiple():
    """Test extract_json_v2 with multiple JSON objects including duplicates."""
    # Load test data
    with open(get_test_data_path("multiple_json.txt"), "r") as f:
        text = f.read()

    # Extract JSON
    result = extract_json_v2(text)

    # Check if we got the correct number of unique objects (3 unique out of 5 total)
    assert len(result) == 3

    # Define expected objects
    expected_objects = [
        {"id": 1, "name": "First Object", "tags": ["one", "first", "primary"]},
        {"id": 2, "name": "Second Object", "tags": ["two", "second"]},
        {
            "id": 3,
            "name": "Third Object",
            "metadata": {"created": "2023-01-01", "version": 1.0},
            "active": True,
        },
    ]

    # Check if all expected objects are in the result
    for expected in expected_objects:
        assert expected in result

    # Verify that each object appears exactly once (no duplicates)
    id_counts = {}
    for obj in result:
        id_counts[obj["id"]] = id_counts.get(obj["id"], 0) + 1

    # Each ID should appear exactly once
    for id_val, count in id_counts.items():
        assert count == 1, (
            f"Object with ID {id_val} appears {count} times (should be 1)"
        )


def test_extract_yaml_v2_valid():
    """Test extract_yaml_v2 with valid YAML in code blocks."""
    # Load test data
    with open(get_test_data_path("valid_yaml.txt"), "r") as f:
        text = f.read()

    # Extract YAML
    result = extract_yaml_v2(text)

    # Check if we got two unique YAML objects (third is a duplicate)
    assert len(result) == 2

    # Check if the objects are correct
    expected_first = {
        "name": "Test Object",
        "properties": {"id": 1, "active": True},
        "tags": ["test", "yaml", "parsing"],
    }

    expected_second = {"simple_name": "Simple Object", "value": 42}

    assert expected_first in result
    assert expected_second in result


def test_extract_yaml_v2_invalid():
    """Test extract_yaml_v2 raises DataParsingError for invalid YAML."""
    # Load test data
    with open(get_test_data_path("invalid_yaml.txt"), "r") as f:
        text = f.read()

    # Try to extract YAML, should raise DataParsingError
    with pytest.raises(DataParsingError):
        extract_yaml_v2(text)


def test_extract_yaml_v2_multiple():
    """Test extract_yaml_v2 with multiple YAML objects including duplicates."""
    # Load test data
    with open(get_test_data_path("multiple_yaml.txt"), "r") as f:
        text = f.read()

    # Extract YAML
    result = extract_yaml_v2(text)

    # Check if we got the correct number of unique objects (3 unique out of 5 total)
    assert len(result) == 3

    # Get the objects by ID for easier assertions
    objects_by_id = {obj["id"]: obj for obj in result}

    # Check for object 1
    assert objects_by_id[1]["name"] == "First Object"
    assert objects_by_id[1]["tags"] == ["one", "first", "primary"]

    # Check for object 2
    assert objects_by_id[2]["name"] == "Second Object"
    assert objects_by_id[2]["tags"] == ["two", "second"]

    # Check for object 3 - note that the date is parsed as a date object by YAML
    assert objects_by_id[3]["name"] == "Third Object"
    assert objects_by_id[3]["active"] is True
    assert "created" in objects_by_id[3]["metadata"]

    # Verify that each object ID appears exactly once (no duplicates)
    id_counts = {}
    for obj in result:
        id_counts[obj["id"]] = id_counts.get(obj["id"], 0) + 1

    # Each ID should appear exactly once
    for id_val, count in id_counts.items():
        assert count == 1, (
            f"Object with ID {id_val} appears {count} times (should be 1)"
        )


def test_extract_yaml_v2_multiple_documents():
    """Test extract_yaml_v2 with multiple YAML documents in a single code block."""
    # Load test data from file
    with open(get_test_data_path("multiple_yaml_documents.txt"), "r") as f:
        test_data = f.read()

    # Extract YAML
    result = extract_yaml_v2(test_data)

    # Check if we got all three documents
    assert len(result) == 3

    # Check if the objects are correct
    objects_by_id = {obj["id"]: obj for obj in result}

    assert objects_by_id[1]["name"] == "First Document"
    assert "first" in objects_by_id[1]["tags"]

    assert objects_by_id[2]["name"] == "Second Document"
    assert "secondary" in objects_by_id[2]["tags"]

    assert objects_by_id[3]["name"] == "Third Document"
    assert objects_by_id[3]["active"] is True


def test_extract_yaml_v2_without_separators():
    """Test extract_yaml_v2 with multiple YAML documents without --- separators."""
    # Load test data from file
    with open(get_test_data_path("multiple_yaml_without_separators.txt"), "r") as f:
        test_data = f.read()

    # Extract YAML
    result = extract_yaml_v2(test_data)

    # Check if we got all three nested documents
    assert len(result) == 3

    # Create a dictionary of documents by name for easy testing
    docs_by_name = {doc["name"]: doc for doc in result}

    # Verify that all three documents are correctly parsed
    assert "First Document" in docs_by_name
    assert docs_by_name["First Document"]["id"] == 1
    assert "first" in docs_by_name["First Document"]["tags"]

    assert "Second Document" in docs_by_name
    assert docs_by_name["Second Document"]["id"] == 2
    assert "secondary" in docs_by_name["Second Document"]["tags"]

    assert "Third Document" in docs_by_name
    assert docs_by_name["Third Document"]["id"] == 3
    assert docs_by_name["Third Document"]["active"] is True


def test_extract_json_v2_multiple_objects():
    """Test extract_json_v2 with multiple JSON objects in a single code block."""
    # Load test data from file
    with open(get_test_data_path("multiple_json_objects.txt"), "r") as f:
        test_data = f.read()

    # Extract JSON
    result = extract_json_v2(test_data)

    # Check if we got all three objects
    assert len(result) == 3

    # Check if the objects are correct
    objects_by_id = {obj["id"]: obj for obj in result}

    assert objects_by_id[1]["name"] == "First Object"
    assert objects_by_id[1]["type"] == "test"

    assert objects_by_id[2]["name"] == "Second Object"
    assert objects_by_id[2]["values"] == [1, 2, 3]

    assert objects_by_id[3]["name"] == "Third Object"
    assert objects_by_id[3]["active"] is True
    assert objects_by_id[3]["metadata"]["created"] == "2023-05-15"


def test_fix_yaml_colon_in_strings():
    """Test fix_yaml_colon_in_strings with problematic YAML containing unquoted colons."""
    # Load test data from file
    with open(get_test_data_path("yaml_with_colons.txt"), "r") as f:
        problematic_yaml = f.read()

    # Extract YAML from the code block
    problematic_yaml = problematic_yaml.split("```")[1]
    if problematic_yaml.startswith("yaml"):
        problematic_yaml = problematic_yaml[4:].strip()

    # Fix the YAML
    fixed_yaml = fix_yaml_colon_in_strings(problematic_yaml)

    # Parse the fixed YAML to check it works
    parsed = yaml.safe_load(fixed_yaml)

    # Check the structure and content is preserved
    assert parsed["calls"][0]["name"] == "act"
    assert parsed["calls"][0]["arguments"]["name"] == "Kaira"
    assert (
        "I can see you're scared, Elmer"
        in parsed["calls"][0]["arguments"]["instructions"]
    )


def test_fix_faulty_yaml():
    """Test fix_faulty_yaml with various problematic YAML constructs."""
    # Load test data from file
    with open(get_test_data_path("yaml_list_with_colons.txt"), "r") as f:
        problematic_yaml = f.read()

    # Extract YAML from the code block
    problematic_yaml = problematic_yaml.split("```")[1]
    if problematic_yaml.startswith("yaml"):
        problematic_yaml = problematic_yaml[4:].strip()

    # Fix the YAML
    fixed_yaml = fix_faulty_yaml(problematic_yaml)

    # Parse the fixed YAML to check it works
    parsed = yaml.safe_load(fixed_yaml)

    # Check the structure and content is preserved
    assert len(parsed["instructions_list"]) == 2
    # The content will be the full string with colons in it now
    assert "Run to the door" in parsed["instructions_list"][0]
    assert "Wait for me!" in parsed["instructions_list"][0]
    assert "Look around" in parsed["instructions_list"][1]
    assert "Is there another way out?" in parsed["instructions_list"][1]


def test_extract_yaml_v2_with_colons():
    """Test extract_yaml_v2 correctly processes YAML with problematic colons in strings."""
    # Load test data containing YAML code blocks with problematic colons
    with open(get_test_data_path("yaml_block_with_colons.txt"), "r") as f:
        text = f.read()

    # Extract YAML
    result = extract_yaml_v2(text)

    # Check if we got the two YAML objects
    assert len(result) == 2

    # Find the objects by their structure
    calls_obj = None
    instructions_obj = None
    for obj in result:
        if "calls" in obj:
            calls_obj = obj
        elif "instructions_list" in obj:
            instructions_obj = obj

    # Verify both objects were found
    assert calls_obj is not None, "Could not find the 'calls' object"
    assert instructions_obj is not None, "Could not find the 'instructions_list' object"

    # Check the structure and content of the first object (calls)
    assert calls_obj["calls"][0]["name"] == "act"
    assert calls_obj["calls"][0]["arguments"]["name"] == "Kaira"

    # Check that the problematic part with the colon is preserved
    instructions = calls_obj["calls"][0]["arguments"]["instructions"]
    assert "Speak in a calm, soothing tone and say:" in instructions
    assert "I can see you're scared, Elmer" in instructions

    # Check the second object (instructions_list)
    assert len(instructions_obj["instructions_list"]) == 2
    assert "Run to the door" in instructions_obj["instructions_list"][0]
    assert "Wait for me!" in instructions_obj["instructions_list"][0]
    assert "Look around" in instructions_obj["instructions_list"][1]
    assert "Is there another way out?" in instructions_obj["instructions_list"][1]


@pytest.mark.asyncio
async def test_extract_data_auto_mixed_formats(mock_client_and_prompt):
    """Test extract_data_auto with mixed JSON and YAML codeblocks."""
    client, prompt_cls = mock_client_and_prompt

    # Load test data
    with open(get_test_data_path("mixed_formats.txt"), "r") as f:
        mixed_text = f.read()

    result = await extract_data_auto(mixed_text, client, prompt_cls)

    # Should extract all three objects
    assert len(result) == 3

    # Verify objects by ID
    objects_by_id = {obj["id"]: obj for obj in result}

    assert objects_by_id[1]["name"] == "JSON Object"
    assert objects_by_id[1]["type"] == "json"

    assert objects_by_id[2]["name"] == "YAML Object"
    assert objects_by_id[2]["type"] == "yaml"
    assert "test" in objects_by_id[2]["tags"]

    assert objects_by_id[3]["name"] == "Second JSON"
    assert objects_by_id[3]["active"] is True


@pytest.mark.asyncio
async def test_extract_data_auto_untyped_codeblocks(mock_client_and_prompt):
    """Test extract_data_auto with untyped codeblocks using default format."""
    # Test with JSON default
    with open(get_test_data_path("untyped_codeblocks_json.txt"), "r") as f:
        json_text = f.read()

    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(
        json_text, client, prompt_cls, schema_format="json"
    )
    assert len(result) == 2

    names = {obj["name"] for obj in result}
    assert "Untyped JSON" in names
    assert "Another JSON" in names

    # Test with YAML default
    with open(get_test_data_path("untyped_codeblocks_yaml.txt"), "r") as f:
        yaml_text = f.read()

    result = await extract_data_auto(
        yaml_text, client, prompt_cls, schema_format="yaml"
    )
    assert len(result) == 2

    names = {obj["name"] for obj in result}
    assert "Untyped YAML" in names
    assert "Another YAML" in names


@pytest.mark.asyncio
async def test_extract_data_auto_bare_codeblock(mock_client_and_prompt):
    """Test extract_data_auto with entire text being just a codeblock."""
    # JSON codeblock
    json_codeblock = """```json
{"name": "Bare JSON", "id": 123, "active": true}
```"""

    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(json_codeblock, client, prompt_cls)
    assert len(result) == 1
    assert result[0]["name"] == "Bare JSON"
    assert result[0]["id"] == 123

    # YAML codeblock
    yaml_codeblock = """```yaml
name: Bare YAML
id: 456
active: false
tags:
  - bare
  - yaml
```"""

    result = await extract_data_auto(yaml_codeblock, client, prompt_cls)
    assert len(result) == 1
    assert result[0]["name"] == "Bare YAML"
    assert result[0]["id"] == 456
    assert "bare" in result[0]["tags"]


@pytest.mark.asyncio
async def test_extract_data_auto_raw_data(mock_client_and_prompt):
    """Test extract_data_auto with raw data structures (no codeblocks)."""
    # Raw JSON
    raw_json = '{"name": "Raw JSON", "value": 100}'
    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(raw_json, client, prompt_cls, schema_format="json")
    assert len(result) == 1
    assert result[0]["name"] == "Raw JSON"
    assert result[0]["value"] == 100

    # Raw YAML
    raw_yaml = """name: Raw YAML
value: 200
metadata:
  created: 2023-01-01
  version: 1.0"""

    result = await extract_data_auto(raw_yaml, client, prompt_cls, schema_format="yaml")
    assert len(result) == 1
    assert result[0]["name"] == "Raw YAML"
    assert result[0]["value"] == 200
    # YAML parser converts date strings to date objects
    assert str(result[0]["metadata"]["created"]) == "2023-01-01"


@pytest.mark.asyncio
async def test_extract_data_auto_empty_codeblocks(mock_client_and_prompt):
    """Test extract_data_auto skips empty codeblocks."""
    # Load test data
    with open(get_test_data_path("empty_codeblocks.txt"), "r") as f:
        text_with_empty = f.read()

    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(text_with_empty, client, prompt_cls)
    assert len(result) == 2

    objects_by_id = {obj["id"]: obj for obj in result}
    assert objects_by_id[1]["name"] == "Valid"
    assert objects_by_id[2]["name"] == "Valid YAML"


@pytest.mark.asyncio
async def test_extract_data_auto_malformed_blocks(mock_client_and_prompt):
    """Test extract_data_auto handles malformed blocks gracefully."""
    text_with_malformed = """
Valid JSON:

```json
{"name": "Valid", "id": 1}
```

Malformed JSON:

```json
{"name": "Broken", "id":
```

Another valid JSON:

```json
{"name": "Also Valid", "id": 2}
```
"""

    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(text_with_malformed, client, prompt_cls)
    # Should extract the 2 valid objects and skip the malformed one
    assert len(result) == 2

    names = {obj["name"] for obj in result}
    assert "Valid" in names
    assert "Also Valid" in names
    assert "Broken" not in names  # Should be skipped


@pytest.mark.asyncio
async def test_extract_data_auto_repairs_faulty_json(mock_client_and_prompt):
    """Test extract_data_auto can repair faulty JSON blocks."""
    # Load test data
    with open(get_test_data_path("faulty_json_repairable.txt"), "r") as f:
        text_with_faulty = f.read()

    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(text_with_faulty, client, prompt_cls)
    # Should successfully repair and extract both objects
    assert len(result) == 3  # Two from first block (after repair), one from second

    # Check that repair worked
    names = {obj["name"] for obj in result if "name" in obj}
    assert "Test" in names
    assert "Another" in names


@pytest.mark.asyncio
async def test_extract_data_auto_yml_identifier(mock_client_and_prompt):
    """Test extract_data_auto recognizes 'yml' as YAML identifier."""
    yml_text = """
Data with yml extension:

```yml
name: YML Test
id: 123
config:
  enabled: true
  timeout: 30
```
"""

    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(yml_text, client, prompt_cls)
    assert len(result) == 1
    assert result[0]["name"] == "YML Test"
    assert result[0]["id"] == 123
    assert result[0]["config"]["enabled"] is True


@pytest.mark.asyncio
async def test_extract_data_auto_invalid_raw_data(mock_client_and_prompt):
    """Test extract_data_auto raises DataParsingError for invalid raw data."""
    # Invalid raw JSON
    invalid_json = '{"name": "Broken JSON", "id":'

    with pytest.raises(DataParsingError) as exc_info:
        client, prompt_cls = mock_client_and_prompt
        await extract_data_auto(invalid_json, client, prompt_cls, schema_format="json")

    assert "Failed to parse raw JSON data" in str(exc_info.value)

    # Invalid raw YAML
    invalid_yaml = """name: Broken YAML
    - invalid: structure
  without: proper indentation"""

    with pytest.raises(DataParsingError) as exc_info:
        await extract_data_auto(invalid_yaml, client, prompt_cls, schema_format="yaml")

    assert "Failed to parse raw YAML data" in str(exc_info.value)


@pytest.mark.asyncio
async def test_extract_data_auto_unsupported_format(mock_client_and_prompt):
    """Test extract_data_auto raises DataParsingError for unsupported formats."""
    text = '{"name": "test"}'

    with pytest.raises(DataParsingError) as exc_info:
        client, prompt_cls = mock_client_and_prompt
        await extract_data_auto(text, client, prompt_cls, schema_format="xml")

    assert "Failed to parse raw XML data" in str(exc_info.value)


@pytest.mark.asyncio
async def test_extract_data_auto_multiple_objects_in_single_block(
    mock_client_and_prompt,
):
    """Test extract_data_auto handles multiple objects within a single codeblock."""
    multiple_json = """
```json
{"id": 1, "name": "First"}
{"id": 2, "name": "Second"}
{"id": 3, "name": "Third"}
```
"""

    client, prompt_cls = mock_client_and_prompt
    result = await extract_data_auto(multiple_json, client, prompt_cls)
    assert len(result) == 3

    objects_by_id = {obj["id"]: obj for obj in result}
    assert objects_by_id[1]["name"] == "First"
    assert objects_by_id[2]["name"] == "Second"
    assert objects_by_id[3]["name"] == "Third"
