"""
Baseline snapshot tests for director agent prompt templates (prompt caching enabled).

Mirrors tests in baselines/ but with optimize_prompt_caching=True.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from ..test_director_templates import (
    mock_scene,
    mock_summarizer_agent,
    mock_narrator_agent,
    mock_conversation_agent,
    mock_world_state_agent,
    mock_creator_agent,
    mock_memory_agent,
    mock_tts_agent,
    director_agent,
    setup_agents,
    active_context,
    MockCharacter,
)
from ..baselines.conftest import capture_prompt

AGENT = "director"


class TestDirectorBaselines:
    """Baseline tests for director agent methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_guide_actor_off_of_scene_analysis(self, active_context, baseline_checker):
        director = active_context
        character = director.scene.get_character("Elena")
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><GUIDANCE>Guidance text.</GUIDANCE>"
        )
        await director.guide_actor_off_of_scene_analysis(
            analysis="The scene is tense and dramatic.",
            character=character,
            response_length=256,
        )
        baseline_checker(capture_prompt(director), AGENT, "guide_actor_off_of_scene_analysis")

    @pytest.mark.asyncio
    async def test_guide_narrator_off_of_scene_analysis(self, active_context, baseline_checker):
        director = active_context
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><GUIDANCE>Guidance text.</GUIDANCE>"
        )
        await director.guide_narrator_off_of_scene_analysis(
            analysis="The scene needs more description.",
            response_length=256,
        )
        baseline_checker(capture_prompt(director), AGENT, "guide_narrator_off_of_scene_analysis")

    @pytest.mark.asyncio
    async def test_generate_choices(self, active_context, baseline_checker):
        director = active_context
        director.client.send_prompt = AsyncMock(
            return_value='Analysis.\nACTIONS:\n- "Go to the forest"'
        )
        await director.generate_choices(
            instructions="Generate choices for the player",
        )
        baseline_checker(capture_prompt(director), AGENT, "generate_choices")

    @pytest.mark.asyncio
    async def test_generate_choices__with_character(self, active_context, baseline_checker):
        director = active_context
        character = director.scene.get_character("Elena")
        director.client.send_prompt = AsyncMock(
            return_value='Analysis.\nACTIONS:\n- "Ask about the herbs"'
        )
        await director.generate_choices(
            character=character,
            instructions="Generate choices for Elena",
        )
        baseline_checker(capture_prompt(director), AGENT, "generate_choices__with_character")

    @pytest.mark.asyncio
    async def test_chat_send(self, active_context, baseline_checker):
        director = active_context
        chat = director.chat_create()
        chat_id = chat.id
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><MESSAGE>Response message.</MESSAGE>"
        )
        with patch(
            "talemate.agents.director.action_core.utils.get_available_actions"
        ) as mock_actions, patch(
            "talemate.agents.director.action_core.utils.get_meta_groups"
        ) as mock_meta:
            mock_actions.return_value = []
            mock_meta.return_value = []
            await director.chat_send(
                chat_id=chat_id,
                message="What should happen next in the scene?",
            )
        baseline_checker(capture_prompt(director), AGENT, "chat_send")

    @pytest.mark.asyncio
    async def test_direction_execute_turn(self, active_context, baseline_checker):
        director = active_context
        director.actions["scene_direction"].enabled = True
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><DECISION>Decision text.</DECISION>"
        )
        with patch(
            "talemate.agents.director.action_core.utils.get_available_actions"
        ) as mock_actions, patch(
            "talemate.agents.director.action_core.utils.get_meta_groups"
        ) as mock_meta:
            mock_actions.return_value = []
            mock_meta.return_value = []
            await director.direction_execute_turn(always_on=True)
        baseline_checker(capture_prompt(director), AGENT, "direction_execute_turn")

    @pytest.mark.asyncio
    async def test_auto_direct_set_scene_intent(self, active_context, baseline_checker):
        director = active_context
        director.scene.intent_state.scene_types = {
            "exploration": Mock(id="exploration", name="Exploration"),
            "combat": Mock(id="combat", name="Combat"),
        }
        director.client.send_prompt = AsyncMock(
            return_value='{"function": "do_nothing"}'
        )
        await director.auto_direct_set_scene_intent(require=False)
        baseline_checker(capture_prompt(director), AGENT, "auto_direct_set_scene_intent")

    @pytest.mark.asyncio
    async def test_detect_characters_from_texts(self, active_context, baseline_checker):
        director = active_context
        texts = [
            "Alice said: 'Hello there!'",
            "Bob replied: 'Nice to meet you.'",
        ]
        director.client.send_prompt = AsyncMock(
            return_value='{"function": "add_detected_character", "character_name": "Alice"}'
        )
        with patch(
            "talemate.agents.director.character_management.ClientContext"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = Mock()
            mock_ctx.return_value.__exit__ = Mock()
            await director.detect_characters_from_texts(texts=texts)
        baseline_checker(capture_prompt(director), AGENT, "detect_characters_from_texts")
