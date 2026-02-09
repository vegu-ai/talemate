"""
Baseline snapshot tests for creator agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.
"""

import pytest
from unittest.mock import AsyncMock

from talemate.agents.creator.assistant import ContentGenerationContext
from tests.prompts.test_creator_templates import (
    mock_llm_client,
    mock_scene,
    mock_editor_agent,
    mock_creator_agent_for_registry,
    mock_director_agent,
    mock_memory_agent,
    mock_world_state_agent,
    creator_agent,
    setup_agents,
    active_context,
    MockCharacter,
)
from .conftest import capture_prompt

AGENT = "creator"


class TestCreatorTitleBaselines:
    """Baseline tests for creator title methods."""

    @pytest.mark.asyncio
    async def test_generate_title(self, active_context, baseline_checker):
        creator = active_context
        creator.client.send_prompt.return_value = "<TITLE>The Dark Forest Quest</TITLE>"
        await creator.generate_title(
            text="A hero ventures into the dark forest to save the kingdom."
        )
        baseline_checker(capture_prompt(creator), AGENT, "generate_title")


class TestCreatorContentContextBaselines:
    """Baseline tests for creator content context methods."""

    @pytest.mark.asyncio
    async def test_determine_content_context_for_character(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "fantasy adventure"
        await creator.determine_content_context_for_character(character=character)
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_content_context_for_character"
        )

    @pytest.mark.asyncio
    async def test_determine_content_context_for_description(
        self, active_context, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = "post-apocalyptic survival"
        await creator.determine_content_context_for_description(
            description="A post-apocalyptic world overrun by zombies."
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_content_context_for_description"
        )


class TestCreatorCharacterBaselines:
    """Baseline tests for creator character methods."""

    @pytest.mark.asyncio
    async def test_determine_character_attributes(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = '{"age": "early 30s"}'
        await creator.determine_character_attributes(character=character)
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_character_attributes"
        )

    @pytest.mark.asyncio
    async def test_determine_character_name(self, active_context, baseline_checker):
        creator = active_context
        creator.client.send_prompt.return_value = "<NAME>Elena</NAME>"
        await creator.determine_character_name(
            character_name="the tall woman with dark hair"
        )
        baseline_checker(capture_prompt(creator), AGENT, "determine_character_name")

    @pytest.mark.asyncio
    async def test_determine_character_name__with_allowed_names(
        self, active_context, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = "<NAME>Marcus</NAME>"
        await creator.determine_character_name(
            character_name="the mysterious stranger",
            allowed_names=["John", "Marcus", "Elena"],
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_character_name__with_allowed_names"
        )

    @pytest.mark.asyncio
    async def test_determine_character_name__group(self, active_context, baseline_checker):
        creator = active_context
        creator.client.send_prompt.return_value = "<NAME>The Guards</NAME>"
        await creator.determine_character_name(
            character_name="the guards standing at the gate", group=True
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_character_name__group"
        )

    @pytest.mark.asyncio
    async def test_determine_character_description(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "Elena is a skilled healer."
        await creator.determine_character_description(character=character)
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_character_description"
        )

    @pytest.mark.asyncio
    async def test_determine_character_goals(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        character = mock_scene.get_character("Elena")
        character.set_detail = AsyncMock()
        creator.client.send_prompt.return_value = "Elena wants to find a cure."
        await creator.determine_character_goals(
            character=character, goal_instructions="Focus on character growth."
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_character_goals"
        )

    @pytest.mark.asyncio
    async def test_determine_character_dialogue_instructions(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "Speaks softly with a gentle tone."
        await creator.determine_character_dialogue_instructions(character=character)
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_character_dialogue_instructions"
        )

    @pytest.mark.asyncio
    async def test_determine_scenario_description(self, active_context, baseline_checker):
        creator = active_context
        creator.client.send_prompt.return_value = "A dark fantasy world."
        await creator.determine_scenario_description(
            text="A dark fantasy world where magic is forbidden."
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_scenario_description"
        )


class TestCreatorContextualGenerateBaselines:
    """Baseline tests for creator contextual_generate methods."""

    @pytest.mark.asyncio
    async def test_contextual_generate__general(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = (
            "<CONTENT>A detailed description.</CONTENT>"
        )
        generation_context = ContentGenerationContext(
            context="general:World History",
            instructions="Describe the world's history",
            length=100,
        )
        await creator.contextual_generate(generation_context)
        baseline_checker(
            capture_prompt(creator), AGENT, "contextual_generate__general"
        )

    @pytest.mark.asyncio
    async def test_contextual_generate__character_attribute(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = "<ATTRIBUTE>healer</ATTRIBUTE>"
        generation_context = ContentGenerationContext(
            context="character attribute:occupation",
            character="Elena",
            instructions="",
            length=192,
        )
        await creator.contextual_generate(generation_context)
        baseline_checker(
            capture_prompt(creator), AGENT, "contextual_generate__character_attribute"
        )


class TestCreatorAutocompleteBaselines:
    """Baseline tests for creator autocomplete methods."""

    @pytest.mark.asyncio
    async def test_autocomplete_dialogue(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = (
            "<COMPLETION>that you are here</COMPLETION>"
        )
        await creator.autocomplete_dialogue(
            input="I am so glad", character=character, emit_signal=False
        )
        baseline_checker(capture_prompt(creator), AGENT, "autocomplete_dialogue")

    @pytest.mark.asyncio
    async def test_autocomplete_narrative(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = (
            "<COMPLETION>and the wind howled</COMPLETION>"
        )
        await creator.autocomplete_narrative(
            input="The forest was dark", emit_signal=False
        )
        baseline_checker(capture_prompt(creator), AGENT, "autocomplete_narrative")
