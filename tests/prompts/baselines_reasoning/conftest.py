"""
Baseline snapshot testing infrastructure for prompt templates with reasoning enabled.

Mirrors the tests in baselines/ but with reason_enabled=True on the mock client.
Baselines are stored separately in tests/data/prompts/baselines_reasoning/.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from ..baselines.conftest import make_baseline_checker


BASELINES_DIR = (
    Path(__file__).parent.parent.parent / "data" / "prompts" / "baselines_reasoning"
)


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client with reason_enabled=True.

    Overrides the default mock_llm_client fixture so that all agents
    created in these tests will have reasoning enabled.

    When reasoning is enabled, can_be_coerced is False (matching real
    ClientBase behavior where reasoning prevents prompt coercion).
    """
    client = AsyncMock()
    client.send_prompt = AsyncMock(return_value="Mock LLM response")
    client.max_token_length = 4096
    client.decensor_enabled = False
    client.can_be_coerced = False
    client.model_name = "test-model"
    client.data_format = "json"
    client.optimize_prompt_caching = False
    client.reason_enabled = True
    client.double_coercion = None
    client.name = "test-client"
    return client


@pytest.fixture
def baseline_checker(update_baselines):
    """Fixture providing a bound baseline checker for reasoning baselines."""
    return make_baseline_checker(update_baselines, BASELINES_DIR)
