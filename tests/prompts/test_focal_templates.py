"""
Unit tests for focal agent templates.

Tests template rendering without requiring an LLM connection.
"""

import pytest
from unittest.mock import Mock
from .helpers import (
    create_mock_agent,
    create_base_context,
    render_template,
    assert_template_renders,
)


@pytest.fixture
def focal_context():
    """Base context for focal templates."""
    return create_base_context()


@pytest.fixture
def active_context(focal_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="focal")
    scene_token = active_scene.set(focal_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield focal_context

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


def create_mock_focal_state(schema_format: str = "json"):
    """Create a mock focal state."""
    state = Mock()
    state.schema_format = schema_format
    state.calls = []
    return state


def create_mock_argument(name: str, arg_type: str = "str", preserve_newlines: bool = False):
    """Create a mock argument for callbacks."""
    arg = Mock()
    arg.name = name
    arg.type = arg_type
    arg.preserve_newlines = preserve_newlines

    def extra_instructions(state):
        if state.schema_format == "yaml" and preserve_newlines:
            return " If there are newlines, they should be preserved by using | style."
        return ""

    arg.extra_instructions = extra_instructions
    return arg


def create_mock_callback(
    name: str = "test_callback",
    arguments: list = None,
    multiple: bool = True,
    schema_format: str = "json",
):
    """Create a mock callback for focal templates."""
    callback = Mock()
    callback.name = name
    callback.pretty_name = name.replace("_", " ").title()
    callback.multiple = multiple

    # Create state
    callback.state = create_mock_focal_state(schema_format)

    # Default arguments if none provided
    if arguments is None:
        arguments = [
            create_mock_argument("text", "str"),
            create_mock_argument("reason", "str"),
        ]
    callback.arguments = arguments

    # Mock the usage method to return formatted schema
    def mock_usage(argument_usage):
        if schema_format == "json":
            args_str = ", ".join(
                f'"{arg.name}": "{arg.type} - {argument_usage.get(arg.name, "")}"'
                for arg in arguments
            )
            return f'```json\n{{"function": "{name}", "arguments": {{{args_str}}}}}\n```'
        else:
            args_str = "\n  ".join(
                f'{arg.name}: "{arg.type} - {argument_usage.get(arg.name, "")}"'
                for arg in arguments
            )
            return f"```yaml\nfunction: {name}\narguments:\n  {args_str}\n```"

    callback.usage = mock_usage

    # Mock the example method
    def mock_example(example):
        if schema_format == "json":
            import json
            payload = {"function": name, "arguments": {k: v for k, v in example.items() if not k.startswith("_")}}
            return f"```json\n{json.dumps(payload, indent=2)}\n```"
        else:
            import yaml
            payload = {"function": name, "arguments": {k: v for k, v in example.items() if not k.startswith("_")}}
            return f"```yaml\n{yaml.dump(payload)}\n```"

    callback.example = mock_example

    return callback


def create_mock_focal(schema_format: str = "json", max_calls: int = 5):
    """Create a mock Focal instance for focal templates."""
    focal = Mock()
    focal.state = create_mock_focal_state(schema_format)
    focal.max_calls = max_calls
    focal.render_instructions = Mock(return_value="Mock focal instructions")

    # Mock callbacks
    focal.callbacks = Mock()
    focal.callbacks.rewrite_text = create_mock_callback("rewrite_text")

    return focal


class TestFocalCallbackTemplate:
    """Tests for callback.jinja2 template."""

    def test_callback_renders(self, active_context):
        """Test callback.jinja2 renders with basic callback."""
        context = active_context.copy()
        context["callback"] = create_mock_callback("edit_text")
        context["usage"] = "Use this function to edit text in the scene."
        context["argument_usage"] = {
            "text": "The text to edit",
            "reason": "Why this edit is needed",
        }
        context["examples"] = []

        result = render_template("focal.callback", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the callback name
        assert "edit_text" in result.lower() or "Edit Text" in result
        # Template should include usage description
        assert "edit text" in result.lower()

    def test_callback_with_multiple_true(self, active_context):
        """Test callback.jinja2 indicates multiple calls allowed."""
        context = active_context.copy()
        callback = create_mock_callback("add_detail", multiple=True)
        context["callback"] = callback
        context["usage"] = "Add details to the scene."
        context["argument_usage"] = {"text": "Detail text", "reason": "Purpose"}
        context["examples"] = []

        result = render_template("focal.callback", context)
        assert result is not None
        assert len(result) > 0
        # Template should indicate multiple calls allowed
        assert "multiple times" in result.lower()

    def test_callback_with_multiple_false(self, active_context):
        """Test callback.jinja2 indicates single call only."""
        context = active_context.copy()
        callback = create_mock_callback("finalize", multiple=False)
        context["callback"] = callback
        context["usage"] = "Finalize the changes."
        context["argument_usage"] = {"text": "Final text", "reason": "Completion"}
        context["examples"] = []

        result = render_template("focal.callback", context)
        assert result is not None
        assert len(result) > 0
        # Template should indicate only one call
        assert "only call this function once" in result.lower()

    def test_callback_with_examples(self, active_context):
        """Test callback.jinja2 includes examples when provided."""
        context = active_context.copy()
        callback = create_mock_callback("rewrite_text")
        context["callback"] = callback
        context["usage"] = "Rewrite text to improve quality."
        context["argument_usage"] = {
            "text": "Text to rewrite",
            "reason": "Reason for rewriting",
        }
        context["examples"] = [
            {"text": "The quick brown fox.", "reason": "Improve clarity"},
            {"_comment": "This shows a typical use case", "text": "Hello world.", "reason": "Fix grammar"},
        ]

        result = render_template("focal.callback", context)
        assert result is not None
        assert len(result) > 0
        # Template should include examples section
        assert "example" in result.lower()
        # Should include the comment
        assert "typical use case" in result.lower()

    def test_callback_yaml_format(self, active_context):
        """Test callback.jinja2 with YAML schema format."""
        context = active_context.copy()
        callback = create_mock_callback("update_scene", schema_format="yaml")
        context["callback"] = callback
        context["usage"] = "Update the scene description."
        context["argument_usage"] = {
            "text": "New scene text",
            "reason": "Update purpose",
        }
        context["examples"] = []

        result = render_template("focal.callback", context)
        assert result is not None
        assert len(result) > 0
        # Template should use YAML format
        assert "yaml" in result.lower()


class TestFocalExtractCallsTemplate:
    """Tests for extract_calls.jinja2 template."""

    def test_extract_calls_renders_json(self, active_context):
        """Test extract_calls.jinja2 renders with JSON format."""
        context = active_context.copy()
        context["text"] = "Please edit this text. ```json\n{\"function\": \"edit\", \"arguments\": {}}\n```"
        context["focal"] = create_mock_focal(schema_format="json")

        result = render_template("focal.extract_calls", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text
        assert "edit this text" in result.lower()
        # Template should mention function calls
        assert "function call" in result.lower()
        # Template should reference json format
        assert "json" in result.lower()

    def test_extract_calls_renders_yaml(self, active_context):
        """Test extract_calls.jinja2 renders with YAML format."""
        context = active_context.copy()
        context["text"] = "Update the scene.\n```yaml\nfunction: update\narguments: {}\n```"
        context["focal"] = create_mock_focal(schema_format="yaml")

        result = render_template("focal.extract_calls", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text
        assert "update the scene" in result.lower()
        # Template should reference yaml format
        assert "yaml" in result.lower()

    def test_extract_calls_no_function_calls(self, active_context):
        """Test extract_calls.jinja2 handles text without function calls."""
        context = active_context.copy()
        context["text"] = "This is just plain text without any function calls."
        context["focal"] = create_mock_focal(schema_format="json")

        result = render_template("focal.extract_calls", context)
        assert result is not None
        assert len(result) > 0
        # Template should mention empty list case
        assert "empty" in result.lower()

    def test_extract_calls_task_section(self, active_context):
        """Test extract_calls.jinja2 includes proper task instructions."""
        context = active_context.copy()
        context["text"] = "Some text with a ```json\n{}\n``` code block."
        context["focal"] = create_mock_focal(schema_format="json")

        result = render_template("focal.extract_calls", context)
        assert result is not None
        assert len(result) > 0
        # Template should include task section
        assert "task" in result.lower()
        # Should mention extracting calls
        assert "extract" in result.lower()


class TestFocalFixDataTemplate:
    """Tests for fix-data.jinja2 template."""

    def test_fix_data_renders_json(self, active_context):
        """Test fix-data.jinja2 renders for JSON format."""
        context = active_context.copy()
        context["text"] = '{"key": "value" "missing": "comma"}'

        # Need to mock the client with json data_format
        mock_client = Mock()
        mock_client.data_format = "json"
        mock_client.max_token_length = 4096
        mock_client.decensor_enabled = False
        mock_client.can_be_coerced = True

        result = render_template("focal.fix-data", context, client=mock_client)
        assert result is not None
        assert len(result) > 0
        # Template should mention JSON
        assert "json" in result.lower()
        # Template should include the broken text
        assert "value" in result.lower()
        # Template should mention fixing syntax
        assert "fix" in result.lower()

    def test_fix_data_renders_yaml(self, active_context):
        """Test fix-data.jinja2 renders for YAML format."""
        context = active_context.copy()
        context["text"] = "key: value\n  bad_indent: broken"

        # Need to mock the client with yaml data_format
        mock_client = Mock()
        mock_client.data_format = "yaml"
        mock_client.max_token_length = 4096
        mock_client.decensor_enabled = False
        mock_client.can_be_coerced = True

        result = render_template("focal.fix-data", context, client=mock_client)
        assert result is not None
        assert len(result) > 0
        # Template should mention YAML
        assert "yaml" in result.lower()
        # Template should include the broken text
        assert "value" in result.lower()

    def test_fix_data_preserves_structure(self, active_context):
        """Test fix-data.jinja2 instructs to preserve structure."""
        context = active_context.copy()
        context["text"] = '{"nested": {"data": "here"}}'

        mock_client = Mock()
        mock_client.data_format = "json"
        mock_client.max_token_length = 4096
        mock_client.decensor_enabled = False
        mock_client.can_be_coerced = True

        result = render_template("focal.fix-data", context, client=mock_client)
        assert result is not None
        assert len(result) > 0
        # Template should mention not changing structure
        assert "structure" in result.lower()


class TestFocalInstructionsTemplate:
    """Tests for instructions.jinja2 template."""

    def test_instructions_renders(self, active_context):
        """Test instructions.jinja2 renders with basic focal state."""
        context = active_context.copy()
        context["state"] = create_mock_focal_state(schema_format="json")
        context["max_calls"] = 5

        result = render_template("focal.instructions", context)
        assert result is not None
        assert len(result) > 0
        # Template should mention functions
        assert "function" in result.lower()
        # Template should include max calls
        assert "5" in result

    def test_instructions_json_format(self, active_context):
        """Test instructions.jinja2 specifies JSON format."""
        context = active_context.copy()
        context["state"] = create_mock_focal_state(schema_format="json")
        context["max_calls"] = 3

        result = render_template("focal.instructions", context)
        assert result is not None
        assert len(result) > 0
        # Template should mention json code blocks
        assert "json" in result.lower()
        # Should mention code blocks
        assert "code block" in result.lower()

    def test_instructions_yaml_format(self, active_context):
        """Test instructions.jinja2 specifies YAML format."""
        context = active_context.copy()
        context["state"] = create_mock_focal_state(schema_format="yaml")
        context["max_calls"] = 3

        result = render_template("focal.instructions", context)
        assert result is not None
        assert len(result) > 0
        # Template should mention yaml code blocks
        assert "yaml" in result.lower()

    def test_instructions_max_calls_limit(self, active_context):
        """Test instructions.jinja2 enforces max calls limit."""
        context = active_context.copy()
        context["state"] = create_mock_focal_state(schema_format="json")
        context["max_calls"] = 1

        result = render_template("focal.instructions", context)
        assert result is not None
        assert len(result) > 0
        # Template should mention the call limit
        assert "1" in result
        # With max_calls > 1, should mention using fewer calls recommendation
        # With max_calls = 1, won't have that recommendation

    def test_instructions_multiple_calls_recommendation(self, active_context):
        """Test instructions.jinja2 recommends fewer calls when max > 1."""
        context = active_context.copy()
        context["state"] = create_mock_focal_state(schema_format="json")
        context["max_calls"] = 10

        result = render_template("focal.instructions", context)
        assert result is not None
        assert len(result) > 0
        # Template should recommend fewer calls when max is greater than 1
        assert "fewer" in result.lower() or "recommend" in result.lower()

    def test_instructions_no_max_calls(self, active_context):
        """Test instructions.jinja2 handles no max_calls (None/0)."""
        context = active_context.copy()
        context["state"] = create_mock_focal_state(schema_format="json")
        context["max_calls"] = None

        result = render_template("focal.instructions", context)
        assert result is not None
        # Template should still render even without max_calls
        assert "function" in result.lower()

    def test_instructions_code_block_format(self, active_context):
        """Test instructions.jinja2 specifies code block format."""
        context = active_context.copy()
        context["state"] = create_mock_focal_state(schema_format="json")
        context["max_calls"] = 5

        result = render_template("focal.instructions", context)
        assert result is not None
        assert len(result) > 0
        # Template should explain how to call functions
        assert "code block" in result.lower() or "```" in result
        # Should mention defining functions in code blocks
        assert "call" in result.lower()
