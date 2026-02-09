"""
Baseline snapshot tests for world_state agent prompt templates (prompt caching enabled).

Mirrors tests in baselines/ but with optimize_prompt_caching=True.
"""

import pytest
from unittest.mock import Mock, AsyncMock

from talemate.world_state import Reinforcement, ContextPin
from ..test_world_state_templates import (
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
from ..baselines.conftest import capture_prompt, capture_all_prompts

AGENT = "world_state"


class TestWorldStateAnalyzeBaselines:
    """Baseline tests for world_state analyze methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_analyze_and_follow_instruction(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="Analysis result.")
        await agent.analyze_and_follow_instruction(
            text="The hero discovered a hidden passage behind the waterfall.",
            instruction="Identify all locations mentioned in the text.",
        )
        baseline_checker(
            capture_prompt(agent), AGENT, "analyze_and_follow_instruction"
        )

    @pytest.mark.asyncio
    async def test_analyze_and_follow_instruction__short(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="Brief summary.")
        await agent.analyze_and_follow_instruction(
            text="Short text.", instruction="Summarize.", short=True
        )
        baseline_checker(
            capture_prompt(agent), AGENT, "analyze_and_follow_instruction__short"
        )

    @pytest.mark.asyncio
    async def test_analyze_text_and_answer_question(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="Elena is using an ancient sword.")
        await agent.analyze_text_and_answer_question(
            text="Elena wielded the ancient sword with great skill.",
            query="What weapon is Elena using?",
        )
        baseline_checker(
            capture_prompt(agent), AGENT, "analyze_text_and_answer_question"
        )

    @pytest.mark.asyncio
    async def test_analyze_text_and_extract_context(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="Political turmoil context.")
        await agent.analyze_text_and_extract_context(
            text="The kingdom has been at war for a decade.",
            goal="Understanding the political situation",
            num_queries=3,
        )
        # This method may make multiple calls; capture the last one
        baseline_checker(capture_prompt(agent), AGENT, "analyze_text_and_extract_context")

    @pytest.mark.asyncio
    async def test_analyze_text_and_extract_context_via_queries(
        self, active_context, mock_memory_agent, baseline_checker
    ):
        agent = active_context
        agent.client.send_prompt = AsyncMock(
            return_value="1. What is the history?\n2. Who are the factions?"
        )
        await agent.analyze_text_and_extract_context_via_queries(
            text="The sorcerer's tower loomed over the ancient forest.",
            goal="Gather information about the sorcerer.",
            num_queries=2,
        )
        baseline_checker(
            capture_prompt(agent), AGENT, "analyze_text_and_extract_context_via_queries"
        )

    @pytest.mark.asyncio
    async def test_analyze_history_and_follow_instructions(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="History analysis.")
        entries = [
            {"ts": "PT1H", "text": "The hero arrived at the village."},
            {"ts": "PT2H", "text": "The hero met with the village elder."},
        ]
        await agent.analyze_history_and_follow_instructions(
            entries=entries,
            instructions="Summarize the hero's journey so far.",
            response_length=256,
        )
        baseline_checker(
            capture_prompt(agent), AGENT, "analyze_history_and_follow_instructions"
        )


class TestWorldStateIdentifyBaselines:
    """Baseline tests for world_state identify methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_identify_characters(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(
            return_value='{"characters": [{"name": "Elena", "description": "A healer"}]}'
        )
        await agent.identify_characters(
            text="Elena spoke to the village elder, while Marcus stood guard."
        )
        baseline_checker(capture_prompt(agent), AGENT, "identify_characters")


class TestWorldStateExtractBaselines:
    """Baseline tests for world_state extract methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_extract_character_sheet(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(
            return_value="name: Elena\nage: 25\noccupation: Healer"
        )
        await agent.extract_character_sheet(
            name="Elena", text="A skilled healer with gentle manners."
        )
        baseline_checker(capture_prompt(agent), AGENT, "extract_character_sheet")

    @pytest.mark.asyncio
    async def test_extract_character_sheet__with_alteration(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="name: Elena\nage: 30")
        await agent.extract_character_sheet(
            name="Elena",
            text="",
            alteration_instructions="Update age to reflect time passing.",
        )
        baseline_checker(
            capture_prompt(agent), AGENT, "extract_character_sheet__with_alteration"
        )


class TestWorldStateRequestBaselines:
    """Baseline tests for world_state request methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_request_world_state(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(
            return_value='{"characters": {"Hero": {"emotion": "determined"}}, "items": {}}'
        )
        await agent.request_world_state()
        baseline_checker(capture_prompt(agent), AGENT, "request_world_state")


class TestWorldStateReinforcementBaselines:
    """Baseline tests for world_state reinforcement methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_update_reinforcement(self, active_context, mock_scene, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="The hero feels determined.")
        reinforcement = Reinforcement(
            question="What is the hero's mood?",
            answer="", interval=10, due=0, character=None,
            instructions="", insert="sequential",
        )
        mock_scene.world_state.find_reinforcement = AsyncMock(
            return_value=(0, reinforcement)
        )
        mock_scene.world_state.reinforce = [reinforcement]
        await agent.update_reinforcement(
            question="What is the hero's mood?", character=None
        )
        baseline_checker(capture_prompt(agent), AGENT, "update_reinforcement")

    @pytest.mark.asyncio
    async def test_update_reinforcement__with_character(
        self, active_context, mock_scene, baseline_checker
    ):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="Elena appears calm.")
        reinforcement = Reinforcement(
            question="current mood", answer="", interval=10, due=0,
            character="Elena", instructions="", insert="conversation-context",
        )
        mock_scene.world_state.find_reinforcement = AsyncMock(
            return_value=(0, reinforcement)
        )
        mock_scene.world_state.reinforce = [reinforcement]
        await agent.update_reinforcement(question="current mood", character="Elena")
        baseline_checker(
            capture_prompt(agent), AGENT, "update_reinforcement__with_character"
        )


class TestWorldStatePinBaselines:
    """Baseline tests for world_state pin condition methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_check_pin_conditions(self, active_context, mock_scene, baseline_checker):
        agent = active_context
        pin = ContextPin(
            entry_id="test_pin",
            condition="The hero is in danger",
            condition_state=False,
            active=False,
        )
        mock_scene.world_state.pins = {"test_pin": pin}
        agent.client.send_prompt = AsyncMock(
            return_value='{"test_pin": {"condition": "The hero is in danger", "state": true}}'
        )
        await agent.check_pin_conditions()
        baseline_checker(capture_prompt(agent), AGENT, "check_pin_conditions")


class TestWorldStatePresenceBaselines:
    """Baseline tests for world_state character presence methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_is_character_present(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="yes")
        await agent.is_character_present("Elena")
        baseline_checker(capture_prompt(agent), AGENT, "is_character_present")

    @pytest.mark.asyncio
    async def test_is_character_leaving(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="yes")
        await agent.is_character_leaving("Elena")
        baseline_checker(capture_prompt(agent), AGENT, "is_character_leaving")


class TestWorldStateQueryBaselines:
    """Baseline tests for world_state query methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_answer_query_true_or_false(self, active_context, baseline_checker):
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="yes")
        await agent.answer_query_true_or_false(
            query="Is the door open?", text="The door stood ajar."
        )
        baseline_checker(
            capture_prompt(agent), AGENT, "answer_query_true_or_false"
        )


class TestWorldStateCharacterProgressionBaselines:
    """Baseline tests for world_state character progression methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_determine_character_development(
        self, active_context, mock_scene, baseline_checker
    ):
        agent = active_context
        character = mock_scene.get_character("Elena")
        agent.client.send_prompt = AsyncMock(return_value="[]")
        await agent.determine_character_development(character=character)
        baseline_checker(
            capture_prompt(agent), AGENT, "determine_character_development"
        )

    @pytest.mark.asyncio
    async def test_determine_character_development__with_instructions(
        self, active_context, mock_scene, baseline_checker
    ):
        agent = active_context
        character = mock_scene.get_character("Elena")
        agent.client.send_prompt = AsyncMock(return_value="[]")
        await agent.determine_character_development(
            character=character, instructions="Focus on combat improvements."
        )
        baseline_checker(
            capture_prompt(agent),
            AGENT,
            "determine_character_development__with_instructions",
        )
