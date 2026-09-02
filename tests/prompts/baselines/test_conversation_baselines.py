"""
Baseline snapshot tests for conversation agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.
"""

import pytest
from unittest.mock import AsyncMock

from ..conftest import mock_llm_client  # noqa: F401
from ..test_conversation_templates import (  # noqa: F401
    mock_scene,
    mock_conversation_agent_for_registry,
    conversation_agent,
    setup_agents,
    active_context,
)
from .conftest import capture_prompt

AGENT = "conversation"


class TestConversationBaselines:
    """Baseline tests for conversation agent methods."""

    @pytest.mark.asyncio
    async def test_converse__movie_script(
        self, active_context, mock_scene, baseline_checker
    ):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = npc.actor
        agent.actions["generation_override"].config["format"].value = "movie_script"
        await agent.converse(actor)
        baseline_checker(capture_prompt(agent), AGENT, "converse__movie_script")

    @pytest.mark.asyncio
    async def test_converse__chat(self, active_context, mock_scene, baseline_checker):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = npc.actor
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
        actor = npc.actor
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
        actor = npc.actor
        await agent.converse(actor, instruction="Express surprise about the weather")
        baseline_checker(capture_prompt(agent), AGENT, "converse__with_instruction")

    @pytest.mark.asyncio
    async def test_converse__with_decensor(
        self, active_context, mock_scene, mock_llm_client, baseline_checker
    ):
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = npc.actor
        mock_llm_client.decensor_enabled = True
        await agent.converse(actor)
        baseline_checker(capture_prompt(agent), AGENT, "converse__with_decensor")

    @pytest.mark.asyncio
    async def test_converse__with_absence_block(
        self, active_context, mock_scene, baseline_checker
    ):
        from talemate import instance

        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = npc.actor
        # the registry mock answers the template's agent_action call
        instance.AGENTS["conversation"].absence_block = AsyncMock(
            return_value=[
                "Marcus found the letter under the floorboard.",
                "The bridge to the east collapsed last night.",
            ]
        )
        await agent.converse(actor)
        prompt = capture_prompt(agent)
        # the section name renders as a heading or, in the xml variant, a tag
        assert "does not know" in prompt.lower().replace("_", " ")
        assert "- Marcus found the letter under the floorboard." in prompt
        baseline_checker(prompt, AGENT, "converse__with_absence_block")

    @pytest.mark.asyncio
    async def test_converse__with_awareness_line(
        self, active_context, mock_scene, baseline_checker
    ):
        from talemate import instance

        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = npc.actor
        instance.AGENTS["conversation"].awareness_line = AsyncMock(
            return_value="Elena knows all of the bridge, some of the letter, nothing of the mine"
        )
        await agent.converse(actor)
        prompt = capture_prompt(agent)
        assert "is aware of" in prompt.lower().replace("_", " ")
        assert (
            "Elena knows all of the bridge, some of the letter, nothing of the mine."
            in prompt
        )
        baseline_checker(prompt, AGENT, "converse__with_awareness_line")
