"""
Baseline snapshot tests for narrator agent prompt templates (prompt caching enabled).

Inherits all tests from baselines/ — only the mock client and baseline directory differ.
"""

from ..test_narrator_templates import (  # noqa: F401
    mock_scene,
    mock_editor_agent,
    mock_conversation_agent,
    mock_narrator_agent_for_registry,
    narrator_agent,
    setup_agents,
    active_context,
)
from ..baselines.test_narrator_baselines import TestNarratorBaselines  # noqa: F401
