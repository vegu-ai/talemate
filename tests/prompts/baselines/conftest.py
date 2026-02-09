"""
Baseline snapshot testing infrastructure for prompt templates.

Provides utilities to capture rendered prompt text from agent method calls
and compare it against stored baseline files. Run with --update-baselines
to create or update baseline files.
"""

import re

import pytest
from pathlib import Path


BASELINES_DIR = Path(__file__).parent.parent.parent / "data" / "prompts" / "baselines"

PROMPT_CALL_BOUNDARY = "\n\n=== PROMPT CALL BOUNDARY ===\n\n"

# Pattern to normalize Mock object repr strings whose id changes between runs.
_MOCK_ID_RE = re.compile(r"<Mock (name='[^']*' )?id='\d+'>")
_MOCK_ID_REPLACEMENT = "<Mock \\1id='NORMALIZED'>"


def normalize_prompt(text: str) -> str:
    """Normalize non-deterministic fragments so baselines are stable across runs."""
    return _MOCK_ID_RE.sub(_MOCK_ID_REPLACEMENT, text)


def capture_prompt(agent):
    """Extract the rendered prompt text from the last send_prompt call.

    The text is normalized to remove non-deterministic fragments
    (e.g. Mock object ids) so baselines stay stable across runs.

    Args:
        agent: Agent instance whose mock client recorded the call.

    Returns:
        The normalized prompt string.
    """
    call_args = agent.client.send_prompt.call_args
    assert call_args is not None, "send_prompt was not called"
    return normalize_prompt(call_args[0][0])


def capture_all_prompts(agent):
    """Extract all rendered prompt texts from every send_prompt call.

    Useful for agent methods that make multiple LLM calls.
    Each prompt is normalized before joining.

    Args:
        agent: Agent instance whose mock client recorded the calls.

    Returns:
        All normalized prompt strings joined with a boundary separator.
    """
    call_args_list = agent.client.send_prompt.call_args_list
    assert len(call_args_list) > 0, "send_prompt was never called"
    prompts = [normalize_prompt(call[0][0]) for call in call_args_list]
    return PROMPT_CALL_BOUNDARY.join(prompts)


def assert_or_update_baseline(
    prompt_text: str,
    agent_name: str,
    test_name: str,
    update: bool,
):
    """Compare prompt_text against a baseline file, or update it.

    Args:
        prompt_text: The rendered prompt text captured from send_prompt.
        agent_name: Agent name for subdirectory (e.g., "narrator").
        test_name: Baseline filename stem (e.g., "narrate_scene").
        update: If True, write/overwrite the baseline file.

    Raises:
        AssertionError: If prompt_text does not exactly match the baseline.
        FileNotFoundError: If baseline doesn't exist and update is False.
    """
    baseline_dir = BASELINES_DIR / agent_name
    baseline_file = baseline_dir / f"{test_name}.txt"

    if update:
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


@pytest.fixture
def baseline_checker(update_baselines):
    """Fixture providing a bound baseline checker with the update flag."""

    def check(prompt_text: str, agent_name: str, test_name: str):
        assert_or_update_baseline(prompt_text, agent_name, test_name, update_baselines)

    return check
