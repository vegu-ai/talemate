"""
Baseline snapshot testing infrastructure for prompt templates with prompt caching enabled.

Mirrors the tests in baselines/ but with optimize_prompt_caching=True on the mock client.
Baselines are stored separately in tests/data/prompts/baselines_cached/.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock


BASELINES_DIR = (
    Path(__file__).parent.parent.parent / "data" / "prompts" / "baselines_cached"
)


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client with optimize_prompt_caching=True.

    Overrides the default mock_llm_client fixture so that all agents
    created in these tests will have prompt caching enabled.
    """
    client = AsyncMock()
    client.send_prompt = AsyncMock(return_value="Mock LLM response")
    client.max_token_length = 4096
    client.decensor_enabled = False
    client.can_be_coerced = True
    client.model_name = "test-model"
    client.data_format = "json"
    client.optimize_prompt_caching = True
    client.name = "test-client"
    return client


@pytest.fixture
def baseline_checker(update_baselines):
    """Fixture providing a bound baseline checker for cached baselines."""

    def check(prompt_text: str, agent_name: str, test_name: str):
        baseline_dir = BASELINES_DIR / agent_name
        baseline_file = baseline_dir / f"{test_name}.txt"

        if update_baselines:
            baseline_dir.mkdir(parents=True, exist_ok=True)
            baseline_file.write_text(prompt_text, encoding="utf-8")
            return

        if not baseline_file.exists():
            raise FileNotFoundError(
                f"Baseline file not found: {baseline_file}\n"
                f"Run with --update-baselines to create it."
            )

        expected = baseline_file.read_text(encoding="utf-8")
        assert prompt_text == expected, (
            f"Prompt output does not match baseline: {baseline_file}\n"
            f"Run with --update-baselines to update."
        )

    return check
