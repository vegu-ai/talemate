"""
Baseline snapshot tests for conversation agent prompt templates (reasoning enabled).

Mirrors tests in baselines/ but with reason_enabled=True.
"""

import pytest
from unittest.mock import AsyncMock

from ..test_conversation_templates import (  # noqa: F401
    mock_scene,
    mock_conversation_agent_for_registry,
    conversation_agent,
    setup_agents,
    active_context,
    MockActor,
)
from ..baselines.conftest import capture_prompt

AGENT = "conversation"


class TestConversationBaselines:
    """Baseline tests for conversation agent methods (reasoning enabled)."""

    @pytest.mark.asyncio
    async def test_converse__movie_script(
        self, active_context, mock_scene, baseline_checker
    ):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)
        agent.actions["generation_override"].config["format"].value = "movie_script"
        await agent.converse(actor)
        baseline_checker(capture_prompt(agent), AGENT, "converse__movie_script")

    @pytest.mark.asyncio
    async def test_converse__chat(self, active_context, mock_scene, baseline_checker):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)
        agent.actions["generation_override"].config["format"].value = "chat"
        agent.client.send_prompt = AsyncMock(
            return_value='Elena: *nods thoughtfully* "Yes, I agree."\nEND-OF-LINE'
        )
        await agent.converse(actor)
        baseline_checker(capture_prompt(agent), AGENT, "converse__chat")

    @pytest.mark.asyncio
    async def test_converse__narrative(
        self, active_context, mock_scene, baseline_checker
    ):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)
        agent.actions["generation_override"].config["format"].value = "narrative"
        agent.client.send_prompt = AsyncMock(
            return_value='She paused. "The view is breathtaking."'
        )
        await agent.converse(actor)
        baseline_checker(capture_prompt(agent), AGENT, "converse__narrative")

    @pytest.mark.asyncio
    async def test_converse__with_instruction(
        self, active_context, mock_scene, baseline_checker
    ):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)
        await agent.converse(actor, instruction="Express surprise about the weather")
        baseline_checker(capture_prompt(agent), AGENT, "converse__with_instruction")

    @pytest.mark.asyncio
    async def test_converse__with_decensor(
        self, active_context, mock_scene, mock_llm_client, baseline_checker
    ):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)
        mock_llm_client.decensor_enabled = True
        await agent.converse(actor)
        baseline_checker(capture_prompt(agent), AGENT, "converse__with_decensor")
