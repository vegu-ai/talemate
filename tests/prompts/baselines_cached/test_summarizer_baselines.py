"""
Baseline snapshot tests for summarizer agent prompt templates (prompt caching enabled).

Inherits all tests from baselines/ — only the mock client and baseline directory differ.
"""

from ..test_summarizer_templates import (  # noqa: F401
    mock_scene,
    mock_conversation_agent,
    mock_summarizer_agent_for_registry,
    summarizer_agent,
    setup_agents,
    active_context,
    MockCharacter,
)
from ..baselines.test_summarizer_baselines import TestSummarizerBaselines  # noqa: F401
