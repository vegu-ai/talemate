"""
Baseline snapshot testing infrastructure for prompt templates.

Provides utilities to capture rendered prompt text from agent method calls
and compare it against stored baseline files. Run with --update-baselines
to create or update baseline files.
"""

import re

import pytest
from pathlib import Path

from talemate.client.base import (
    ClientBase,
    INDIRECT_COERCION_PROMPT,
    INDIRECT_COERCION_PROMPT_REASONING,
)


BASELINES_DIR = Path(__file__).parent.parent.parent / "data" / "prompts" / "baselines"

PROMPT_CALL_BOUNDARY = "\n\n=== PROMPT CALL BOUNDARY ===\n\n"

# Fixed response length for baseline tests. The real value is computed from
# model presets in _send_prompt; we use a small fixed value here so baselines
# are deterministic.
TEST_RESPONSE_LENGTH = 512

# Pattern to normalize Mock object repr strings whose id changes between runs.
_MOCK_ID_RE = re.compile(r"<Mock (name='[^']*' )?id='\d+'>")
_MOCK_ID_REPLACEMENT = "<Mock \\1id='NORMALIZED'>"


def normalize_prompt(text: str) -> str:
    """Normalize non-deterministic fragments so baselines are stable across runs."""
    return _MOCK_ID_RE.sub(_MOCK_ID_REPLACEMENT, text)


def _apply_client_processing(
    client, prompt: str, call_kwargs: dict, has_response_length: bool = False
) -> str:
    """Apply client-side prompt transforms that _send_prompt would normally do.

    When send_prompt is mocked, the processing in _send_prompt is bypassed.
    This function replicates the prompt-transforming steps so baselines
    capture what the LLM would actually receive.
    """

    data_expected = call_kwargs.get("data_expected", False)
    reason_enabled = getattr(client, "reason_enabled", False)
    can_be_coerced = getattr(client, "can_be_coerced", True)
    enforce_response_length = getattr(client, "enforce_response_length", "cap_tokens_and_instructions")

    # attach_response_length_instruction (when mode includes instructions + not data_expected + not already set)
    if enforce_response_length in ("cap_tokens_and_instructions", "instructions") and not data_expected and not has_response_length:
        prompt = ClientBase.attach_response_length_instruction(
            client, prompt, TEST_RESPONSE_LENGTH
        )

    # split_prompt_for_coercion (when not coercible)
    if not can_be_coerced:
        prompt, coercion_prompt = ClientBase.split_prompt_for_coercion(client, prompt)
        if coercion_prompt:
            coercion_instruction = (
                INDIRECT_COERCION_PROMPT_REASONING
                if reason_enabled
                else INDIRECT_COERCION_PROMPT
            )
            prompt += f"{coercion_instruction}{coercion_prompt}"

    return prompt


def _capture_single(client, call_args) -> str:
    """Capture and process a single send_prompt call."""
    prompt_obj = call_args[0][0]
    has_response_length = getattr(prompt_obj, "response_length_instructions", False)
    prompt = _apply_client_processing(
        client, str(prompt_obj), call_args[1] or {}, has_response_length
    )
    return normalize_prompt(prompt)


def capture_prompt(agent):
    """Extract the rendered prompt text from the last send_prompt call.

    Applies client-side processing (response length instruction, coercion
    splitting) that _send_prompt would normally perform, then normalizes
    non-deterministic fragments (e.g. Mock object ids) for stable baselines.

    Args:
        agent: Agent instance whose mock client recorded the call.

    Returns:
        The normalized prompt string.
    """
    call_args = agent.client.send_prompt.call_args
    assert call_args is not None, "send_prompt was not called"
    return _capture_single(agent.client, call_args)


def capture_all_prompts(agent):
    """Extract all rendered prompt texts from every send_prompt call.

    Useful for agent methods that make multiple LLM calls.
    Each prompt has client-side processing applied and is normalized
    before joining.

    Args:
        agent: Agent instance whose mock client recorded the calls.

    Returns:
        All normalized prompt strings joined with a boundary separator.
    """
    call_args_list = agent.client.send_prompt.call_args_list
    assert len(call_args_list) > 0, "send_prompt was never called"
    prompts = [_capture_single(agent.client, call) for call in call_args_list]
    return PROMPT_CALL_BOUNDARY.join(prompts)


def assert_or_update_baseline(
    prompt_text: str,
    agent_name: str,
    test_name: str,
    update: bool,
    baselines_dir: Path = None,
):
    """Compare prompt_text against a baseline file, or update it.

    Args:
        prompt_text: The rendered prompt text captured from send_prompt.
        agent_name: Agent name for subdirectory (e.g., "narrator").
        test_name: Baseline filename stem (e.g., "narrate_scene").
        update: If True, write/overwrite the baseline file.
        baselines_dir: Directory for baseline files. Defaults to BASELINES_DIR.

    Raises:
        AssertionError: If prompt_text does not exactly match the baseline.
        FileNotFoundError: If baseline doesn't exist and update is False.
    """
    baselines_dir = baselines_dir or BASELINES_DIR
    baseline_dir = baselines_dir / agent_name
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


def make_baseline_checker(update_baselines: bool, baselines_dir: Path = None):
    """Create a baseline checker function for the given baselines directory.

    Args:
        update_baselines: If True, write/overwrite baseline files.
        baselines_dir: Directory for baseline files. Defaults to BASELINES_DIR.
    """

    def check(prompt_text: str, agent_name: str, test_name: str):
        assert_or_update_baseline(
            prompt_text, agent_name, test_name, update_baselines, baselines_dir
        )

    return check


@pytest.fixture
def baseline_checker(update_baselines):
    """Fixture providing a bound baseline checker with the update flag."""
    return make_baseline_checker(update_baselines)
