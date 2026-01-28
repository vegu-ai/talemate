"""
Unit tests for focal system methods.

Tests that focal methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from method
to prompt rendering to LLM call, without making actual API calls.

The Focal system is a utility used by other agents for structured function calling.
It is NOT an agent itself. The methods that call Prompt.request() are:
- Focal._extract() - uses focal.extract_calls template
- extract_data_with_ai_fallback() - uses focal.fix-data template
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from talemate.game.focal import Focal, Callback, Argument
from talemate.util.data import extract_data_with_ai_fallback
from talemate.prompts.base import Prompt
from .helpers import create_mock_scene


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that returns predictable responses."""
    client = AsyncMock()
    client.send_prompt = AsyncMock(return_value='{"calls": []}')
    client.max_token_length = 4096
    client.decensor_enabled = False
    client.can_be_coerced = True
    client.model_name = "test-model"
    client.data_format = "json"
    return client


@pytest.fixture
def mock_scene():
    """Create a rich mock scene for testing."""
    return create_mock_scene()


@pytest.fixture
def mock_director_agent():
    """Create a mock director agent for focal context."""
    director = Mock()
    director.log_function_call = AsyncMock()
    return director


@pytest.fixture
def setup_agents(mock_director_agent):
    """Set up the agent registry with mocked agents."""
    import talemate.instance as instance

    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Set up mock agents in the registry
    instance.AGENTS["director"] = mock_director_agent

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(mock_scene, setup_agents):
    """Set up active scene context for tests."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = Mock()
    mock_agent.agent_type = "focal"
    mock_agent.client = Mock()
    mock_agent.client.max_token_length = 4096
    mock_agent.client.decensor_enabled = False
    mock_agent.client.can_be_coerced = True

    scene_token = active_scene.set(mock_scene)
    agent_token = active_agent.set(mock_agent)

    yield

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


def create_test_callback(name: str = "test_callback"):
    """Create a test callback for focal tests."""

    async def callback_fn(**kwargs):
        return f"Called {name} with {kwargs}"

    return Callback(
        name=name,
        arguments=[
            Argument(name="text", type="str"),
            Argument(name="reason", type="str"),
        ],
        fn=callback_fn,
    )


class TestFocalExtractCalls:
    """Tests for Focal._extract() which uses the focal.extract_calls template."""

    @pytest.mark.asyncio
    async def test_extract_calls_client(self, mock_llm_client, active_context):
        """Test that _extract calls the LLM client when extraction is needed."""
        # Create a Focal instance
        callback = create_test_callback("edit_text")
        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=5,
        )

        # Set up response that needs AI extraction (has code blocks but not valid JSON)
        # The mock will return a properly formatted response with "calls" array
        mock_llm_client.send_prompt = AsyncMock(
            return_value='{"calls": [{"function": "edit_text", "arguments": {"text": "hello", "reason": "test"}}]}'
        )

        # Call _extract with text that will trigger AI extraction
        # (the first extraction attempt will fail, then AI will be used)
        with patch.object(focal, "_extract", wraps=focal._extract):
            # Use a malformed response that will trigger AI extraction
            malformed_response = """Here's my function call:
```json
{function: edit_text, arguments: {text: "hello", reason: test}}
```
"""
            calls = await focal._extract(malformed_response)

            # The method should have attempted to extract and used AI fallback
            # Verify extraction returned a list of Call objects
            assert isinstance(calls, list)
            assert len(calls) == 1

            # Verify the extracted call has correct structure
            assert calls[0].name == "edit_text"
            assert calls[0].arguments["text"] == "hello"
            assert calls[0].arguments["reason"] == "test"

            # Verify AI fallback was called since JSON was malformed
            # Note: send_prompt may be called twice - once for extract_calls template
            # and once for fix-data fallback
            assert mock_llm_client.send_prompt.call_count >= 1

    @pytest.mark.asyncio
    async def test_extract_no_calls_for_plain_text(
        self, mock_llm_client, active_context
    ):
        """Test that _extract returns empty list for text without code blocks."""
        callback = create_test_callback("edit_text")
        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=5,
        )

        # Plain text without any code blocks
        plain_text = "This is just regular text without any function calls."

        calls = await focal._extract(plain_text)

        # Should return empty list without calling LLM
        assert calls == []
        # LLM should not be called for plain text
        mock_llm_client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_valid_json_no_ai(self, mock_llm_client, active_context):
        """Test that valid JSON is extracted without AI fallback."""
        callback = create_test_callback("edit_text")
        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=5,
        )

        # Valid JSON response
        valid_response = """```json
{"function": "edit_text", "arguments": {"text": "hello", "reason": "test"}}
```"""

        calls = await focal._extract(valid_response)

        # Should extract call without AI
        assert len(calls) == 1
        assert calls[0].name == "edit_text"
        assert calls[0].arguments["text"] == "hello"
        assert calls[0].arguments["reason"] == "test"

        # Verify this is a Call object with proper structure
        from talemate.game.focal import Call
        assert isinstance(calls[0], Call)
        assert calls[0].called is False  # Not yet executed
        assert calls[0].error is None

        # LLM should not be called when JSON is valid
        mock_llm_client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_multiple_calls_json(self, mock_llm_client, active_context):
        """Test extraction of multiple function calls from a single response."""
        callback1 = create_test_callback("edit_text")
        callback2 = Callback(
            name="save_file",
            arguments=[Argument(name="filename", type="str")],
            fn=lambda **kwargs: None,
        )
        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback1, callback2],
            max_calls=5,
        )

        # Valid JSON response with multiple calls
        valid_response = """```json
{"function": "edit_text", "arguments": {"text": "content", "reason": "improve"}}
```
```json
{"function": "save_file", "arguments": {"filename": "output.txt"}}
```"""

        calls = await focal._extract(valid_response)

        # Should extract both calls without AI
        assert len(calls) == 2

        # Verify first call
        assert calls[0].name == "edit_text"
        assert calls[0].arguments["text"] == "content"
        assert calls[0].arguments["reason"] == "improve"

        # Verify second call
        assert calls[1].name == "save_file"
        assert calls[1].arguments["filename"] == "output.txt"

        # LLM should not be called when JSON is valid
        mock_llm_client.send_prompt.assert_not_called()


class TestFocalRequest:
    """Tests for Focal.request() which calls Prompt.request()."""

    @pytest.mark.asyncio
    async def test_request_with_template_calls_client(
        self, mock_llm_client, active_context, mock_director_agent
    ):
        """Test that Focal.request() calls the LLM client with rendered prompt."""
        # Set up callback
        call_count = 0
        received_args = {}

        async def test_fn(**kwargs):
            nonlocal call_count, received_args
            call_count += 1
            received_args = kwargs.copy()
            return "done"

        callback = Callback(
            name="test_action",
            arguments=[Argument(name="text", type="str")],
            fn=test_fn,
        )

        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=5,
        )

        # Mock the LLM to return a valid function call
        mock_llm_client.send_prompt = AsyncMock(
            return_value='```json\n{"function": "test_action", "arguments": {"text": "hello"}}\n```'
        )

        # Create a simple test template that includes focal instructions
        # We'll use a patched version to avoid needing actual template
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            # Prompt.request now returns a tuple (response, extracted)
            mock_response = '```json\n{"function": "test_action", "arguments": {"text": "hello"}}\n```'
            mock_request.return_value = (
                mock_response,
                {"response": mock_response},
            )

            # Call request with a template name
            # Since we're mocking Prompt.request, we need to simulate the template behavior
            await focal.request(template_name="focal.extract_calls")

            # Verify Prompt.request was called
            mock_request.assert_called_once()

            # Verify the callback was executed with correct arguments
            assert call_count == 1
            assert received_args["text"] == "hello"

            # Verify the call was recorded in focal state
            assert len(focal.state.calls) == 1
            assert focal.state.calls[0].name == "test_action"
            assert focal.state.calls[0].called is True
            assert focal.state.calls[0].arguments["text"] == "hello"

    @pytest.mark.asyncio
    async def test_request_executes_callbacks(
        self, mock_llm_client, active_context, mock_director_agent
    ):
        """Test that Focal.request() executes extracted callbacks."""
        call_args = []

        async def test_fn(text: str):
            call_args.append(text)
            return "done"

        callback = Callback(
            name="save_text",
            arguments=[Argument(name="text", type="str")],
            fn=test_fn,
        )

        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=5,
        )

        # Mock to return a valid function call
        mock_llm_client.send_prompt = AsyncMock(
            return_value='```json\n{"function": "save_text", "arguments": {"text": "saved content"}}\n```'
        )

        # Patch Prompt.request to return the mock response
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            # Prompt.request now returns a tuple (response, extracted)
            mock_response = '```json\n{"function": "save_text", "arguments": {"text": "saved content"}}\n```'
            mock_request.return_value = (
                mock_response,
                {"response": mock_response},
            )

            await focal.request(template_name="focal.extract_calls")

            # Verify the callback was executed with correct argument
            assert len(call_args) == 1
            assert call_args[0] == "saved content"

            # Verify the call was recorded in focal state with result
            assert len(focal.state.calls) == 1
            assert focal.state.calls[0].name == "save_text"
            assert focal.state.calls[0].called is True
            assert focal.state.calls[0].result == "done"
            assert focal.state.calls[0].error is None

    @pytest.mark.asyncio
    async def test_request_executes_multiple_callbacks(
        self, mock_llm_client, active_context, mock_director_agent
    ):
        """Test that Focal.request() executes multiple extracted callbacks in order."""
        execution_order = []

        async def save_fn(text: str):
            execution_order.append(("save", text))
            return "saved"

        async def publish_fn(target: str):
            execution_order.append(("publish", target))
            return "published"

        callback_save = Callback(
            name="save_text",
            arguments=[Argument(name="text", type="str")],
            fn=save_fn,
        )
        callback_publish = Callback(
            name="publish",
            arguments=[Argument(name="target", type="str")],
            fn=publish_fn,
        )

        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback_save, callback_publish],
            max_calls=5,
        )

        # Patch Prompt.request to return multiple function calls
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_response = """```json
{"function": "save_text", "arguments": {"text": "content A"}}
```
```json
{"function": "publish", "arguments": {"target": "production"}}
```"""
            mock_request.return_value = (
                mock_response,
                {"response": mock_response},
            )

            await focal.request(template_name="focal.extract_calls")

            # Verify both callbacks were executed in order
            assert len(execution_order) == 2
            assert execution_order[0] == ("save", "content A")
            assert execution_order[1] == ("publish", "production")

            # Verify both calls were recorded in focal state
            assert len(focal.state.calls) == 2
            assert focal.state.calls[0].name == "save_text"
            assert focal.state.calls[0].result == "saved"
            assert focal.state.calls[1].name == "publish"
            assert focal.state.calls[1].result == "published"

    @pytest.mark.asyncio
    async def test_request_respects_max_calls(
        self, mock_llm_client, active_context, mock_director_agent
    ):
        """Test that Focal.request() respects max_calls limit."""
        call_count = 0

        async def test_fn(text: str):
            nonlocal call_count
            call_count += 1
            return "done"

        callback = Callback(
            name="action",
            arguments=[Argument(name="text", type="str")],
            fn=test_fn,
        )

        # Set max_calls to 2
        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=2,
        )

        # Patch Prompt.request to return 5 function calls
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_response = """```json
{"function": "action", "arguments": {"text": "call1"}}
```
```json
{"function": "action", "arguments": {"text": "call2"}}
```
```json
{"function": "action", "arguments": {"text": "call3"}}
```
```json
{"function": "action", "arguments": {"text": "call4"}}
```
```json
{"function": "action", "arguments": {"text": "call5"}}
```"""
            mock_request.return_value = (
                mock_response,
                {"response": mock_response},
            )

            await focal.request(template_name="focal.extract_calls")

            # Only 2 callbacks should have been executed due to max_calls
            assert call_count == 2
            assert len(focal.state.calls) == 2


class TestExtractDataWithAIFallback:
    """Tests for extract_data_with_ai_fallback() which uses focal.fix-data template."""

    @pytest.mark.asyncio
    async def test_extract_valid_json_no_ai(self, mock_llm_client, active_context):
        """Test that valid JSON is extracted without AI fallback."""
        valid_json = '{"key": "value", "number": 42}'

        result = await extract_data_with_ai_fallback(
            mock_llm_client, valid_json, Prompt, schema_format="json"
        )

        # Should extract without calling AI
        assert len(result) == 1
        assert result[0]["key"] == "value"
        assert result[0]["number"] == 42
        # LLM should not be called for valid JSON
        mock_llm_client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_invalid_json_uses_ai_fallback(
        self, mock_llm_client, active_context
    ):
        """Test that invalid JSON triggers AI fallback using focal.fix-data template."""
        invalid_json = '{"key": "value" "missing": "comma"}'

        # Set up mock to return fixed JSON
        mock_llm_client.send_prompt = AsyncMock(
            return_value='```json\n{"key": "value", "missing": "comma"}\n```'
        )

        result = await extract_data_with_ai_fallback(
            mock_llm_client, invalid_json, Prompt, schema_format="json"
        )

        # Should have used AI fallback
        assert mock_llm_client.send_prompt.called

        # Verify the extraction result contains the fixed data
        assert len(result) == 1
        assert result[0]["key"] == "value"
        assert result[0]["missing"] == "comma"

        # Get the prompt that was sent
        call_args = mock_llm_client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify the prompt contains the text to fix
        assert "value" in prompt_text.lower() or "fix" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_extract_valid_yaml_no_ai(self, mock_llm_client, active_context):
        """Test that valid YAML is extracted without AI fallback."""
        mock_llm_client.data_format = "yaml"
        valid_yaml = "key: value\nnumber: 42"

        result = await extract_data_with_ai_fallback(
            mock_llm_client, valid_yaml, Prompt, schema_format="yaml"
        )

        # Should extract without calling AI
        assert len(result) == 1
        assert result[0]["key"] == "value"
        assert result[0]["number"] == 42
        # LLM should not be called for valid YAML
        mock_llm_client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_invalid_yaml_uses_ai_fallback(
        self, mock_llm_client, active_context
    ):
        """Test that invalid YAML triggers AI fallback using focal.fix-data template."""
        mock_llm_client.data_format = "yaml"
        invalid_yaml = "key: value\n  bad_indent: broken"

        # Set up mock to return fixed YAML
        mock_llm_client.send_prompt = AsyncMock(
            return_value="```yaml\nkey: value\nbad_indent: broken\n```"
        )

        result = await extract_data_with_ai_fallback(
            mock_llm_client, invalid_yaml, Prompt, schema_format="yaml"
        )

        # Should have used AI fallback
        assert mock_llm_client.send_prompt.called

        # Verify the extraction result contains the fixed data
        assert len(result) == 1
        assert result[0]["key"] == "value"
        assert result[0]["bad_indent"] == "broken"

    @pytest.mark.asyncio
    async def test_extract_json_with_nested_structure(
        self, mock_llm_client, active_context
    ):
        """Test that nested JSON structures are extracted correctly."""
        nested_json = '{"outer": {"inner": "value"}, "list": [1, 2, 3]}'

        result = await extract_data_with_ai_fallback(
            mock_llm_client, nested_json, Prompt, schema_format="json"
        )

        # Should extract without calling AI
        assert len(result) == 1
        assert result[0]["outer"]["inner"] == "value"
        assert result[0]["list"] == [1, 2, 3]
        mock_llm_client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_yaml_with_nested_structure(
        self, mock_llm_client, active_context
    ):
        """Test that nested YAML structures are extracted correctly."""
        mock_llm_client.data_format = "yaml"
        nested_yaml = "outer:\n  inner: value\nlist:\n  - 1\n  - 2\n  - 3"

        result = await extract_data_with_ai_fallback(
            mock_llm_client, nested_yaml, Prompt, schema_format="yaml"
        )

        # Should extract without calling AI
        assert len(result) == 1
        assert result[0]["outer"]["inner"] == "value"
        assert result[0]["list"] == [1, 2, 3]
        mock_llm_client.send_prompt.assert_not_called()


class TestFocalRenderMethods:
    """Tests for Focal rendering methods (these use Prompt.get, not Prompt.request).

    These tests verify that rendering works correctly, even though they don't
    call the LLM. They're included for completeness since they're part of the
    focal system's core functionality.
    """

    def test_render_instructions_json(self, mock_llm_client, active_context):
        """Test that render_instructions produces valid output for JSON format."""
        callback = create_test_callback("edit_text")
        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=5,
            schema_format="json",
        )

        instructions = focal.render_instructions()

        # Should contain function calling instructions
        assert "function" in instructions.lower()
        assert "json" in instructions.lower()
        assert "5" in instructions  # max_calls

    def test_render_instructions_yaml(self, mock_llm_client, active_context):
        """Test that render_instructions produces valid output for YAML format."""
        callback = create_test_callback("edit_text")
        focal = Focal(
            client=mock_llm_client,
            callbacks=[callback],
            max_calls=3,
            schema_format="yaml",
        )

        instructions = focal.render_instructions()

        # Should contain function calling instructions for YAML
        assert "function" in instructions.lower()
        assert "yaml" in instructions.lower()
        assert "3" in instructions  # max_calls

    def test_callback_render(self, active_context):
        """Test that Callback.render() produces valid output."""
        callback = Callback(
            name="edit_text",
            arguments=[
                Argument(name="text", type="str"),
                Argument(name="reason", type="str"),
            ],
            fn=lambda: None,
        )

        rendered = callback.render(
            usage="Edit the provided text to improve quality.",
            text="The text content to edit",
            reason="Why this edit is needed",
        )

        # Should contain callback information
        assert "edit_text" in rendered.lower() or "Edit Text" in rendered
        assert "text" in rendered.lower()
        assert "reason" in rendered.lower()

    def test_callback_render_with_examples(self, active_context):
        """Test that Callback.render() includes examples when provided."""
        callback = Callback(
            name="rewrite",
            arguments=[
                Argument(name="content", type="str"),
            ],
            fn=lambda: None,
        )

        rendered = callback.render(
            usage="Rewrite the content.",
            content="The content to rewrite",
            examples=[
                {"content": "Example text", "_comment": "A simple example"},
            ],
        )

        # Should contain example
        assert "example" in rendered.lower()
