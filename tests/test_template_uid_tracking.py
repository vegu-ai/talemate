"""
Unit tests for template_uid tracking in PromptData.

Tests that when a Prompt is sent via Prompt.send(), the template_uid is correctly
passed through to the PromptData emitted via the prompt_sent signal.
"""

import pytest
from unittest.mock import AsyncMock, patch

from talemate.client.base import PromptData
from talemate.prompts.base import Prompt, active_template_uid


class TestPromptDataTemplateUid:
    """Tests for the template_uid field in PromptData."""

    def test_prompt_data_has_template_uid_field(self):
        """Verify PromptData model includes template_uid field."""
        data = PromptData(
            kind="test",
            prompt="test prompt",
            response="test response",
            prompt_tokens=10,
            response_tokens=5,
            client_name="test-client",
            client_type="test",
            time=1.0,
            template_uid="narrator.narrate-scene",
        )
        assert data.template_uid == "narrator.narrate-scene"

    def test_prompt_data_template_uid_defaults_to_none(self):
        """Verify template_uid defaults to None when not provided."""
        data = PromptData(
            kind="test",
            prompt="test prompt",
            response="test response",
            prompt_tokens=10,
            response_tokens=5,
            client_name="test-client",
            client_type="test",
            time=1.0,
        )
        assert data.template_uid is None

    def test_prompt_data_serializes_template_uid(self):
        """Verify template_uid is included in model_dump() output."""
        data = PromptData(
            kind="test",
            prompt="test prompt",
            response="test response",
            prompt_tokens=10,
            response_tokens=5,
            client_name="test-client",
            client_type="test",
            time=1.0,
            template_uid="director.guide-scene",
        )
        dumped = data.model_dump()
        assert "template_uid" in dumped
        assert dumped["template_uid"] == "director.guide-scene"


class TestActiveTemplateUidContext:
    """Tests for the active_template_uid context variable."""

    def test_active_template_uid_defaults_to_none(self):
        """Verify active_template_uid defaults to None."""
        assert active_template_uid.get() is None

    def test_active_template_uid_can_be_set_and_reset(self):
        """Verify context variable can be set and properly reset."""
        assert active_template_uid.get() is None

        token = active_template_uid.set("narrator.test")
        assert active_template_uid.get() == "narrator.test"

        active_template_uid.reset(token)
        assert active_template_uid.get() is None

    def test_active_template_uid_nested_contexts(self):
        """Verify nested context variable handling."""
        assert active_template_uid.get() is None

        token1 = active_template_uid.set("outer.template")
        assert active_template_uid.get() == "outer.template"

        token2 = active_template_uid.set("inner.template")
        assert active_template_uid.get() == "inner.template"

        active_template_uid.reset(token2)
        assert active_template_uid.get() == "outer.template"

        active_template_uid.reset(token1)
        assert active_template_uid.get() is None


class TestPromptSendSetsTemplateUid:
    """Tests that Prompt.send() properly sets the active_template_uid context."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock LLM client."""
        client = AsyncMock()
        client.send_prompt = AsyncMock(return_value="test response")
        client.can_be_coerced = True
        client.data_format = "json"
        return client

    @pytest.mark.asyncio
    async def test_prompt_send_sets_context_variable(self, mock_client):
        """Verify Prompt.send() sets active_template_uid during client call."""
        captured_uid = None

        async def capture_uid(*args, **kwargs):
            nonlocal captured_uid
            captured_uid = active_template_uid.get()
            return "test response"

        mock_client.send_prompt = capture_uid

        prompt = Prompt(
            uid="narrator.test-template",
            agent_type="narrator",
            name="test-template",
            template="Test prompt content",
        )

        await prompt.send(mock_client, kind="test")

        assert captured_uid == "narrator.test-template"

    @pytest.mark.asyncio
    async def test_prompt_send_resets_context_after_completion(self, mock_client):
        """Verify context is reset after Prompt.send() completes."""
        assert active_template_uid.get() is None

        prompt = Prompt(
            uid="narrator.test",
            agent_type="narrator",
            name="test",
            template="Test prompt",
        )

        await prompt.send(mock_client, kind="test")

        # Context should be reset after send completes
        assert active_template_uid.get() is None

    @pytest.mark.asyncio
    async def test_prompt_send_resets_context_on_exception(self, mock_client):
        """Verify context is reset even if client.send_prompt raises."""
        mock_client.send_prompt = AsyncMock(side_effect=Exception("Test error"))

        prompt = Prompt(
            uid="narrator.test",
            agent_type="narrator",
            name="test",
            template="Test prompt",
        )

        with pytest.raises(Exception, match="Test error"):
            await prompt.send(mock_client, kind="test")

        # Context should still be reset
        assert active_template_uid.get() is None

    @pytest.mark.asyncio
    async def test_prompt_send_with_empty_uid(self, mock_client):
        """Verify empty uid is handled gracefully."""
        captured_uid = None

        async def capture_uid(*args, **kwargs):
            nonlocal captured_uid
            captured_uid = active_template_uid.get()
            return "test response"

        mock_client.send_prompt = capture_uid

        prompt = Prompt(
            uid="",
            agent_type="",
            name="",
            template="Test prompt",
        )

        await prompt.send(mock_client, kind="test")

        # Empty string should be converted to None
        assert captured_uid is None

    @pytest.mark.asyncio
    async def test_prompt_from_text_has_no_uid(self, mock_client):
        """Verify Prompt.from_text() results in None template_uid."""
        captured_uid = None

        async def capture_uid(*args, **kwargs):
            nonlocal captured_uid
            captured_uid = active_template_uid.get()
            return "test response"

        mock_client.send_prompt = capture_uid

        prompt = Prompt.from_text("Some raw prompt text")

        await prompt.send(mock_client, kind="test")

        # from_text creates a prompt with empty uid
        assert captured_uid is None
