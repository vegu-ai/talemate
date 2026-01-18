from talemate.game.engine.ux.schema import UXChoice
from talemate.util.ux import json_load_maybe, normalize_choices


def test_json_load_maybe_valid_json():
    """Test json_load_maybe with valid JSON strings."""
    # Test with a JSON object
    result = json_load_maybe('{"name": "test", "value": 42}')
    assert result == {"name": "test", "value": 42}

    # Test with a JSON array
    result = json_load_maybe('[1, 2, 3, "four"]')
    assert result == [1, 2, 3, "four"]

    # Test with a JSON string
    result = json_load_maybe('"hello world"')
    assert result == "hello world"

    # Test with a JSON number
    result = json_load_maybe("123")
    assert result == 123

    # Test with a JSON boolean
    result = json_load_maybe("true")
    assert result is True

    result = json_load_maybe("false")
    assert result is False

    # Test with null
    result = json_load_maybe("null")
    assert result is None


def test_json_load_maybe_invalid_json():
    """Test json_load_maybe with invalid JSON strings returns the original string."""
    # Invalid JSON should return the original string
    invalid_json = '{"name": "test", "value":'
    result = json_load_maybe(invalid_json)
    assert result == invalid_json

    # Plain text should return as-is
    plain_text = "This is not JSON"
    result = json_load_maybe(plain_text)
    assert result == plain_text

    # Empty string
    result = json_load_maybe("")
    assert result == ""

    # String with special characters
    special = "Hello {world} [test]"
    result = json_load_maybe(special)
    assert result == special


def test_normalize_choices_none():
    """Test normalize_choices with None returns empty list."""
    result = normalize_choices(None)
    assert result == []


def test_normalize_choices_list_of_strings():
    """Test normalize_choices with a list of strings."""
    choices = ["Option 1", "Option 2", "Option 3"]
    result = normalize_choices(choices)

    assert len(result) == 3
    assert result[0].id == "choice_0"
    assert result[0].label == "Option 1"
    assert result[0].value == "Option 1"
    assert result[1].id == "choice_1"
    assert result[1].label == "Option 2"
    assert result[1].value == "Option 2"
    assert result[2].id == "choice_2"
    assert result[2].label == "Option 3"
    assert result[2].value == "Option 3"


def test_normalize_choices_list_of_dicts():
    """Test normalize_choices with a list of dictionaries."""
    choices = [
        {"id": "opt1", "label": "Option 1", "value": "val1"},
        {"id": "opt2", "label": "Option 2", "value": "val2"},
    ]
    result = normalize_choices(choices)

    assert len(result) == 2
    assert result[0].id == "opt1"
    assert result[0].label == "Option 1"
    assert result[0].value == "val1"
    assert result[1].id == "opt2"
    assert result[1].label == "Option 2"
    assert result[1].value == "val2"


def test_normalize_choices_list_of_dicts_minimal():
    """Test normalize_choices with minimal dictionaries (missing id)."""
    choices = [
        {"label": "Option 1", "value": "val1"},
        {"label": "Option 2", "value": "val2"},
    ]
    result = normalize_choices(choices)

    assert len(result) == 2
    assert result[0].id == "choice_0"
    assert result[0].label == "Option 1"
    assert result[0].value == "val1"
    assert result[1].id == "choice_1"
    assert result[1].label == "Option 2"
    assert result[1].value == "val2"


def test_normalize_choices_list_of_dicts_embedded_label():
    """Test normalize_choices with dicts where label is a key."""
    choices = [
        {"id": "opt1", "Option 1": "val1"},
        {"id": "opt2", "Option 2": "val2"},
    ]
    result = normalize_choices(choices)

    assert len(result) == 2
    assert result[0].id == "opt1"
    assert result[0].label == "Option 1"
    assert result[0].value == "val1"
    assert result[1].id == "opt2"
    assert result[1].label == "Option 2"
    assert result[1].value == "val2"


def test_normalize_choices_list_of_uxchoice():
    """Test normalize_choices with a list of UXChoice objects."""
    choices = [
        UXChoice(id="opt1", label="Option 1", value="val1"),
        UXChoice(id="opt2", label="Option 2", value="val2"),
    ]
    result = normalize_choices(choices)

    assert len(result) == 2
    assert result[0].id == "opt1"
    assert result[0].label == "Option 1"
    assert result[0].value == "val1"
    assert result[1].id == "opt2"
    assert result[1].label == "Option 2"
    assert result[1].value == "val2"


def test_normalize_choices_dict_label_to_value():
    """Test normalize_choices with a dictionary mapping labels to values."""
    choices = {
        "Option 1": "val1",
        "Option 2": "val2",
        "Option 3": "val3",
    }
    result = normalize_choices(choices)

    assert len(result) == 3
    # Order may vary, so check by label
    labels = {choice.label: choice for choice in result}
    assert "Option 1" in labels
    assert labels["Option 1"].value == "val1"
    assert "Option 2" in labels
    assert labels["Option 2"].value == "val2"
    assert "Option 3" in labels
    assert labels["Option 3"].value == "val3"


def test_normalize_choices_json_string_list():
    """Test normalize_choices with a JSON string containing a list."""
    json_str = '["Option 1", "Option 2", "Option 3"]'
    result = normalize_choices(json_str)

    assert len(result) == 3
    assert result[0].label == "Option 1"
    assert result[1].label == "Option 2"
    assert result[2].label == "Option 3"


def test_normalize_choices_json_string_dict():
    """Test normalize_choices with a JSON string containing a dictionary."""
    json_str = '{"Option 1": "val1", "Option 2": "val2"}'
    result = normalize_choices(json_str)

    assert len(result) == 2
    labels = {choice.label: choice for choice in result}
    assert "Option 1" in labels
    assert labels["Option 1"].value == "val1"
    assert "Option 2" in labels
    assert labels["Option 2"].value == "val2"


def test_normalize_choices_newline_separated_string():
    """Test normalize_choices with a newline-separated string."""
    choices = "Option 1\nOption 2\nOption 3"
    result = normalize_choices(choices)

    assert len(result) == 3
    assert result[0].label == "Option 1"
    assert result[0].value == "Option 1"
    assert result[1].label == "Option 2"
    assert result[1].value == "Option 2"
    assert result[2].label == "Option 3"
    assert result[2].value == "Option 3"


def test_normalize_choices_newline_separated_with_whitespace():
    """Test normalize_choices with newline-separated string containing whitespace."""
    choices = "  Option 1  \n  Option 2  \n  Option 3  "
    result = normalize_choices(choices)

    assert len(result) == 3
    assert result[0].label == "Option 1"
    assert result[1].label == "Option 2"
    assert result[2].label == "Option 3"


def test_normalize_choices_newline_separated_empty_lines():
    """Test normalize_choices with newline-separated string containing empty lines."""
    choices = "Option 1\n\nOption 2\n  \nOption 3"
    result = normalize_choices(choices)

    assert len(result) == 3
    assert result[0].label == "Option 1"
    assert result[1].label == "Option 2"
    assert result[2].label == "Option 3"


def test_normalize_choices_single_value():
    """Test normalize_choices with a single value (fallback)."""
    result = normalize_choices("Single Option")
    assert len(result) == 1
    assert result[0].id == "choice_0"
    assert result[0].label == "Single Option"
    assert result[0].value == "Single Option"

    # Test with a number
    result = normalize_choices(42)
    assert len(result) == 1
    assert result[0].label == "42"
    assert result[0].value == 42


def test_normalize_choices_list_with_mixed_types():
    """Test normalize_choices with a list containing mixed types."""
    choices = [
        "String option",
        {"id": "dict1", "label": "Dict option", "value": "dict_val"},
        UXChoice(id="ux1", label="UXChoice option", value="ux_val"),
        123,  # Will be stringified
    ]
    result = normalize_choices(choices)

    assert len(result) == 4
    assert result[0].label == "String option"
    assert result[1].id == "dict1"
    assert result[1].label == "Dict option"
    assert result[2].id == "ux1"
    assert result[2].label == "UXChoice option"
    assert result[3].label == "123"
    assert result[3].value == 123


def test_normalize_choices_empty_list():
    """Test normalize_choices with an empty list."""
    result = normalize_choices([])
    assert result == []


def test_normalize_choices_empty_dict():
    """Test normalize_choices with an empty dictionary."""
    result = normalize_choices({})
    assert result == []


def test_normalize_choices_empty_string():
    """Test normalize_choices with an empty string."""
    result = normalize_choices("")
    assert result == []


def test_normalize_choices_json_string_list_of_dicts():
    """Test normalize_choices with JSON string containing list of dicts."""
    json_str = '[{"id": "opt1", "label": "Option 1", "value": "val1"}, {"id": "opt2", "label": "Option 2", "value": "val2"}]'
    result = normalize_choices(json_str)

    assert len(result) == 2
    assert result[0].id == "opt1"
    assert result[0].label == "Option 1"
    assert result[0].value == "val1"
    assert result[1].id == "opt2"
    assert result[1].label == "Option 2"
    assert result[1].value == "val2"


def test_normalize_choices_dict_with_non_string_keys():
    """Test normalize_choices with dictionary having non-string keys."""
    # Note: In Python, True == 1, so True and 1 would collide in a dict
    # We'll test with distinct non-string keys
    choices = {
        1: "value1",
        "two": "value2",
        3.14: "value3",
    }
    result = normalize_choices(choices)

    assert len(result) == 3
    labels = {choice.label: choice for choice in result}
    assert "1" in labels
    assert labels["1"].value == "value1"
    assert "two" in labels
    assert labels["two"].value == "value2"
    assert "3.14" in labels
    assert labels["3.14"].value == "value3"
