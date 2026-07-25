"""
Baseline snapshot tests for creator agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.
"""

import pytest
from unittest.mock import AsyncMock

from talemate.agents.creator.assistant import ContentGenerationContext
from talemate.agents.creator.character import CharacterGenerationRequest
from talemate.world_state.templates.content import WritingStyle
from ..conftest import mock_llm_client  # noqa: F401
from ..test_creator_templates import (  # noqa: F401
    mock_scene,
    mock_editor_agent,
    mock_creator_agent_for_registry,
    mock_director_agent,
    mock_memory_agent,
    mock_world_state_agent,
    creator_agent,
    setup_agents,
    active_context,
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
            capture_prompt(creator),
            AGENT,
            "determine_character_name__with_allowed_names",
        )

    @pytest.mark.asyncio
    async def test_determine_character_name__group(
        self, active_context, baseline_checker
    ):
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
        creator.client.send_prompt.return_value = "Elena wants to find a cure."
        await creator.determine_character_goals(
            character=character, goal_instructions="Focus on character growth."
        )
        baseline_checker(capture_prompt(creator), AGENT, "determine_character_goals")

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
    async def test_determine_scenario_description(
        self, active_context, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = "A dark fantasy world."
        await creator.determine_scenario_description(
            text="A dark fantasy world where magic is forbidden."
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "determine_scenario_description"
        )


class TestCreatorGenerateCharacterBaselines:
    """Baseline tests for the consolidated character generation one-shot."""

    @pytest.mark.asyncio
    async def test_generate_character__all_aspects(
        self, active_context, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = "\n".join(
            [
                "<NAME>Elena</NAME>",
                "<DESCRIPTION>Elena is a skilled healer.</DESCRIPTION>",
                "<ATTRIBUTES>Age: early 30s\nOccupation: healer</ATTRIBUTES>",
                "<DIALOGUE_INSTRUCTIONS>Speaks softly.</DIALOGUE_INSTRUCTIONS>",
                '<EXAMPLE_DIALOGUE>Elena: "Oh dear!"</EXAMPLE_DIALOGUE>',
            ]
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=[
                    "name",
                    "description",
                    "attributes",
                    "dialogue_instructions",
                    "example_dialogue",
                ],
                name="the tall woman with dark hair",
                content="A mysterious healer arrives at the forest clearing.",
            )
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "generate_character__all_aspects"
        )

    @pytest.mark.asyncio
    async def test_generate_character__subset(self, active_context, baseline_checker):
        creator = active_context
        creator.client.send_prompt.return_value = "\n".join(
            [
                "<DESCRIPTION>Elena is a skilled healer.</DESCRIPTION>",
                "<DIALOGUE_INSTRUCTIONS>Speaks softly.</DIALOGUE_INSTRUCTIONS>",
            ]
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description", "dialogue_instructions"],
                name="Elena",
                content="A mysterious healer arrives at the forest clearing.",
            )
        )
        baseline_checker(capture_prompt(creator), AGENT, "generate_character__subset")

    @pytest.mark.asyncio
    async def test_generate_character__existing_character(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "\n".join(
            [
                "<DESCRIPTION>Elena is a skilled healer.</DESCRIPTION>",
                "<ATTRIBUTES>Age: early 30s\nOccupation: healer</ATTRIBUTES>",
                '<EXAMPLE_DIALOGUE>Elena: "Oh dear!"</EXAMPLE_DIALOGUE>',
            ]
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description", "attributes", "example_dialogue"],
                name="Elena",
                character=character,
            )
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "generate_character__existing_character"
        )

    @pytest.mark.asyncio
    async def test_generate_character__writing_style(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        mock_scene.writing_style = WritingStyle(
            name="Terse", instructions="Write in terse, Hemingway-esque prose."
        )
        creator.client.send_prompt.return_value = (
            "<DESCRIPTION>Elena is a skilled healer.</DESCRIPTION>"
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Elena",
                content="A mysterious healer arrives at the forest clearing.",
            )
        )
        baseline_checker(
            capture_prompt(creator), AGENT, "generate_character__writing_style"
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
        baseline_checker(capture_prompt(creator), AGENT, "contextual_generate__general")

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

    @pytest.mark.asyncio
    async def test_contextual_generate__character_attribute_with_instructions(
        self, active_context, mock_scene, baseline_checker
    ):
        from unittest.mock import Mock
        import talemate.instance as instance

        creator = active_context
        creator.client.send_prompt.return_value = "<ATTRIBUTE>healer</ATTRIBUTE>"

        # Mock rag_build on the registry agent (used by agent_action in templates)
        mock_memory = Mock(name="mock.memory.herbalism_skill")
        mock_memory.text = "Elena is skilled in herbalism and natural remedies."
        mock_memory.context_id = "memory_001"
        instance.AGENTS["creator"].rag_build = AsyncMock(return_value=[mock_memory])

        generation_context = ContentGenerationContext(
            context="character attribute:occupation",
            character="Elena",
            instructions="Make sure the occupation fits the fantasy setting",
            length=192,
        )
        await creator.contextual_generate(generation_context)
        baseline_checker(
            capture_prompt(creator),
            AGENT,
            "contextual_generate__character_attribute_with_instructions",
        )

    @pytest.mark.asyncio
    async def test_contextual_generate__list(
        self, active_context, mock_scene, baseline_checker
    ):
        creator = active_context
        creator.client.send_prompt.return_value = '["sword", "shield", "potion"]'
        generation_context = ContentGenerationContext(
            context="list:Items in inventory",
            instructions="Generate inventory items",
            length=256,
        )
        await creator.contextual_generate(generation_context)
        baseline_checker(capture_prompt(creator), AGENT, "contextual_generate__list")


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
