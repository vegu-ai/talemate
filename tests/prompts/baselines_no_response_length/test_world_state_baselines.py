"""
Baseline snapshot tests for world_state agent prompt templates (no response length enforcement).

Inherits all tests from baselines/ — only the mock client and baseline directory differ.
"""

from ..test_world_state_templates import (  # noqa: F401
    mock_scene,
    mock_memory_agent,
    mock_creator_agent,
    mock_summarizer_agent,
    mock_director_agent,
    world_state_agent,
    setup_agents,
    active_context,
    MockCharacter,
)
from ..baselines.test_world_state_baselines import (  # noqa: F401
    TestWorldStateAnalyzeBaselines,
    TestWorldStateIdentifyBaselines,
    TestWorldStateExtractBaselines,
    TestWorldStateRequestBaselines,
    TestWorldStateReinforcementBaselines,
    TestWorldStatePinBaselines,
    TestWorldStatePresenceBaselines,
    TestWorldStateQueryBaselines,
    TestWorldStateCharacterProgressionBaselines,
)
