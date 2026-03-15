"""
Baseline snapshot tests for director agent prompt templates (non-coercible client).

Inherits all tests from baselines/ — only the mock client and baseline directory differ.
"""

from ..test_director_templates import (  # noqa: F401
    mock_scene,
    mock_summarizer_agent,
    mock_narrator_agent,
    mock_conversation_agent,
    mock_world_state_agent,
    mock_creator_agent,
    mock_memory_agent,
    mock_tts_agent,
    director_agent,
    setup_agents,
    active_context,
    MockCharacter,
)
from ..baselines.test_director_baselines import TestDirectorBaselines  # noqa: F401
