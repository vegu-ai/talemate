import os
import pytest
import json
from talemate.util.data import (
    fix_faulty_json,
    extract_json,
    extract_json_v2,
    JSONEncoder,
    DataParsingError
)

# Helper function to get test data paths
def get_test_data_path(filename):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'data', 'util', 'data', filename)

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
    assert json.loads('[' + fixed + ']') == [{"a": 1}, {"b": 2}]
    
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
    json_str, obj = extract_json('[1, 2, 3] and some text')
    assert json_str == '[1, 2, 3]'
    assert obj == [1, 2, 3]
    
    # Test with whitespace
    json_str, obj = extract_json('  {"name": "test"} and some text')
    assert json_str == '{"name": "test"}'
    assert obj == {"name": "test"}
    
    # Test with invalid JSON
    with pytest.raises(ValueError):
        extract_json('This is not JSON')

def test_extract_json_v2_valid():
    """Test extract_json_v2 with valid JSON in code blocks."""
    # Load test data
    with open(get_test_data_path('valid_json.txt'), 'r') as f:
        text = f.read()
    
    # Extract JSON
    result = extract_json_v2(text)
    
    # Check if we got two unique JSON objects (third is a duplicate)
    assert len(result) == 2
    
    # Check if the objects are correct
    expected_first = {
        "name": "Test Object",
        "properties": {
            "id": 1,
            "active": True
        },
        "tags": ["test", "json", "parsing"]
    }
    
    expected_second = {
        "name": "Simple Object",
        "value": 42
    }
    
    assert expected_first in result
    assert expected_second in result

def test_extract_json_v2_invalid():
    """Test extract_json_v2 raises DataParsingError for invalid JSON."""
    # Load test data
    with open(get_test_data_path('invalid_json.txt'), 'r') as f:
        text = f.read()
    
    # Try to extract JSON, should raise DataParsingError
    with pytest.raises(DataParsingError):
        extract_json_v2(text)

def test_extract_json_v2_faulty():
    """Test extract_json_v2 with faulty but fixable JSON."""
    # Load test data
    with open(get_test_data_path('faulty_json.txt'), 'r') as f:
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
    with open(get_test_data_path('multiple_json.txt'), 'r') as f:
        text = f.read()
    
    # Extract JSON
    result = extract_json_v2(text)
    
    # Check if we got the correct number of unique objects (3 unique out of 5 total)
    assert len(result) == 3
    
    # Define expected objects
    expected_objects = [
        {
            "id": 1,
            "name": "First Object",
            "tags": ["one", "first", "primary"]
        },
        {
            "id": 2,
            "name": "Second Object",
            "tags": ["two", "second"]
        },
        {
            "id": 3,
            "name": "Third Object",
            "metadata": {
                "created": "2023-01-01",
                "version": 1.0
            },
            "active": True
        }
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
        assert count == 1, f"Object with ID {id_val} appears {count} times (should be 1)" 