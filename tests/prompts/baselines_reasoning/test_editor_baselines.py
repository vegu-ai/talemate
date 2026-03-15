"""
Baseline snapshot tests for editor agent prompt templates (reasoning enabled).

Inherits all tests from baselines/ — only the mock client and baseline directory differ.
"""

from ..test_editor_templates import (  # noqa: F401
    mock_scene,
    mock_memory_agent,
    mock_summarizer_agent,
    mock_narrator_agent_for_registry,
    mock_director_agent,
    editor_agent,
    setup_agents,
    active_context,
)
from ..baselines.test_editor_baselines import TestEditorBaselines  # noqa: F401
