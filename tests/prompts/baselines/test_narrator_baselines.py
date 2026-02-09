"""
Baseline snapshot tests for narrator agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.
"""

import pytest

from ..conftest import mock_llm_client  # noqa: F401
from ..test_narrator_templates import (  # noqa: F401
    mock_scene,
    mock_editor_agent,
    mock_conversation_agent,
    mock_narrator_agent_for_registry,
    narrator_agent,
    setup_agents,
    active_context,
)
from .conftest import capture_prompt

AGENT = "narrator"


class TestNarratorBaselines:
    """Baseline tests for narrator agent methods."""

    @pytest.mark.asyncio
    async def test_narrate_scene(self, active_context, baseline_checker):
        narrator = active_context
        await narrator.narrate_scene(narrative_direction="Describe the forest clearing")
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_scene")

    @pytest.mark.asyncio
    async def test_progress_story(self, active_context, baseline_checker):
        narrator = active_context
        await narrator.progress_story(narrative_direction="Move the story forward")
        baseline_checker(capture_prompt(narrator), AGENT, "progress_story")

    @pytest.mark.asyncio
    async def test_progress_story__default(self, active_context, baseline_checker):
        narrator = active_context
        await narrator.progress_story()
        baseline_checker(capture_prompt(narrator), AGENT, "progress_story__default")

    @pytest.mark.asyncio
    async def test_narrate_query(self, active_context, baseline_checker):
        narrator = active_context
        await narrator.narrate_query(query="What is the current state of the forest?")
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_query")

    @pytest.mark.asyncio
    async def test_narrate_query__with_extra_context(
        self, active_context, baseline_checker
    ):
        narrator = active_context
        await narrator.narrate_query(
            query="Describe the atmosphere",
            extra_context="The scene is set at midnight",
        )
        baseline_checker(
            capture_prompt(narrator), AGENT, "narrate_query__with_extra_context"
        )

    @pytest.mark.asyncio
    async def test_narrate_character(
        self, active_context, mock_scene, baseline_checker
    ):
        narrator = active_context
        character = mock_scene.get_character("Elena")
        await narrator.narrate_character(
            character=character, narrative_direction="Describe her appearance"
        )
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_character")

    @pytest.mark.asyncio
    async def test_paraphrase(self, active_context, baseline_checker):
        narrator = active_context
        await narrator.paraphrase(
            narration="The warrior drew his sword and prepared for battle."
        )
        baseline_checker(capture_prompt(narrator), AGENT, "paraphrase")

    @pytest.mark.asyncio
    async def test_narrate_time_passage(self, active_context, baseline_checker):
        narrator = active_context
        await narrator.narrate_time_passage(
            duration="PT2H",
            time_passed="Two hours later",
            narrative_direction="The sun has set",
        )
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_time_passage")

    @pytest.mark.asyncio
    async def test_narrate_after_dialogue(
        self, active_context, mock_scene, baseline_checker
    ):
        narrator = active_context
        character = mock_scene.get_character("Elena")
        await narrator.narrate_after_dialogue(
            character=character, narrative_direction="Describe her reaction"
        )
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_after_dialogue")

    @pytest.mark.asyncio
    async def test_narrate_character_entry(
        self, active_context, mock_scene, baseline_checker
    ):
        narrator = active_context
        character = mock_scene.get_character("Elena")
        await narrator.narrate_character_entry(
            character=character, narrative_direction="She enters dramatically"
        )
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_character_entry")

    @pytest.mark.asyncio
    async def test_narrate_character_exit(
        self, active_context, mock_scene, baseline_checker
    ):
        narrator = active_context
        character = mock_scene.get_character("Elena")
        await narrator.narrate_character_exit(
            character=character, narrative_direction="She leaves quietly"
        )
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_character_exit")

    @pytest.mark.asyncio
    async def test_narrate_environment(self, active_context, baseline_checker):
        narrator = active_context
        await narrator.narrate_environment(
            narrative_direction="Describe the ambient sounds"
        )
        baseline_checker(capture_prompt(narrator), AGENT, "narrate_environment")
