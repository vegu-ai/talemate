"""
Baseline snapshot tests for conversation agent prompt templates (prompt caching enabled).

Inherits all tests from baselines/ — only the mock client and baseline directory differ.
"""

from ..test_conversation_templates import (  # noqa: F401
    mock_scene,
    mock_conversation_agent_for_registry,
    conversation_agent,
    setup_agents,
    active_context,
    MockActor,
)
from ..baselines.test_conversation_baselines import TestConversationBaselines  # noqa: F401
