"""
Baseline snapshot tests for summarizer agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.
"""

import pytest
from unittest.mock import Mock, AsyncMock

import talemate.instance as instance
from tests.prompts.test_summarizer_templates import (
    mock_llm_client,
    mock_scene,
    mock_conversation_agent,
    mock_summarizer_agent_for_registry,
    summarizer_agent,
    setup_agents,
    active_context,
    MockCharacter,
)
from .conftest import capture_prompt

AGENT = "summarizer"


class TestSummarizerBaselines:
    """Baseline tests for summarizer agent methods."""

    @pytest.mark.asyncio
    async def test_analyze_dialoge(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="The scene concludes at the denouement point."
        )
        dialogue = [
            "Elena: Hello there, traveler.",
            "Hero: Good to meet you.",
            "The sun was setting in the west.",
        ]
        await summarizer.analyze_dialoge(dialogue)
        baseline_checker(capture_prompt(summarizer), AGENT, "analyze_dialoge")

    @pytest.mark.asyncio
    async def test_find_natural_scene_termination(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="- Progress 2\n- Progress 5"
        )
        event_chunks = [
            "The party gathered at the inn.",
            "They discussed their plan.",
            "The leader gave a rousing speech.",
            "Everyone headed to their rooms for the night.",
            "Morning came swiftly.",
            "The journey began anew.",
        ]
        await summarizer.find_natural_scene_termination(event_chunks)
        baseline_checker(
            capture_prompt(summarizer), AGENT, "find_natural_scene_termination"
        )

    @pytest.mark.asyncio
    async def test_summarize(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="Analysis.\nSUMMARY: Summary text."
        )
        text = "Elena walked through the forest. She met a stranger on the path."
        await summarizer.summarize(text)
        baseline_checker(capture_prompt(summarizer), AGENT, "summarize")

    @pytest.mark.asyncio
    async def test_summarize__with_extra_context(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="Context.\nSUMMARY: Summary with context."
        )
        text = "The battle raged on through the night."
        extra_context = ["Previously: The heroes arrived at the fortress."]
        await summarizer.summarize(text, extra_context=extra_context)
        baseline_checker(
            capture_prompt(summarizer), AGENT, "summarize__with_extra_context"
        )

    @pytest.mark.asyncio
    async def test_summarize_events(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="CHUNK 1: Summary of events."
        )
        text = "The hero began the journey. The hero crossed the river."
        await summarizer.summarize_events(text)
        baseline_checker(capture_prompt(summarizer), AGENT, "summarize_events")

    @pytest.mark.asyncio
    async def test_summarize_events__with_extra_context(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="CHAPTER 2: Events with context."
        )
        text = "The hero found the treasure."
        extra_context = "Previously: The hero entered the dungeon."
        await summarizer.summarize_events(text, extra_context=extra_context)
        baseline_checker(
            capture_prompt(summarizer), AGENT, "summarize_events__with_extra_context"
        )

    @pytest.mark.asyncio
    async def test_summarize_director_chat(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="Summary of chat."
        )
        history = [
            {"type": "message", "source": "user", "message": "Update the character."},
            {"type": "message", "source": "director", "message": "I'll update now."},
            {
                "type": "action_result",
                "source": "director",
                "name": "update_character",
                "instructions": "Make them brave",
                "result": {"success": True},
            },
        ]
        await summarizer.summarize_director_chat(history)
        baseline_checker(
            capture_prompt(summarizer), AGENT, "summarize_director_chat"
        )

    @pytest.mark.asyncio
    async def test_analyze_scene_for_conversation(
        self, active_context, mock_scene, baseline_checker
    ):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="Scene analysis for conversation."
        )
        character = MockCharacter(name="TestChar")
        await summarizer.analyze_scene_for_next_action(
            typ="conversation", character=character, length=512
        )
        baseline_checker(
            capture_prompt(summarizer), AGENT, "analyze_scene_for_conversation"
        )

    @pytest.mark.asyncio
    async def test_analyze_scene_for_narration(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="Scene analysis for narration."
        )
        await summarizer.analyze_scene_for_next_action(
            typ="narration", character=None, length=1024
        )
        baseline_checker(
            capture_prompt(summarizer), AGENT, "analyze_scene_for_narration"
        )

    @pytest.mark.asyncio
    async def test_suggest_context_investigations__conversation(
        self, active_context, mock_scene, baseline_checker
    ):
        summarizer = active_context
        mock_scene.layered_history = [
            [{"text": "Chapter 1 events", "start": 0, "end": 5,
              "ts_start": "PT0S", "ts_end": "PT1H"}]
        ]
        summarizer.client.send_prompt = AsyncMock(
            return_value="Investigate chapter 1.1."
        )
        character = MockCharacter(name="ConvoChar")
        await summarizer.suggest_context_investigations(
            analysis="Tension between characters.",
            analysis_type="conversation",
            character=character,
        )
        baseline_checker(
            capture_prompt(summarizer),
            AGENT,
            "suggest_context_investigations__conversation",
        )

    @pytest.mark.asyncio
    async def test_suggest_context_investigations__narration_progress(
        self, active_context, mock_scene, baseline_checker
    ):
        summarizer = active_context
        mock_scene.layered_history = [
            [{"text": "Chapter 1 events", "start": 0, "end": 5,
              "ts_start": "PT0S", "ts_end": "PT1H"}]
        ]
        summarizer.client.send_prompt = AsyncMock(
            return_value="Investigate chapter 1.1."
        )
        await summarizer.suggest_context_investigations(
            analysis="The story is progressing toward the climax.",
            analysis_type="narration",
            analysis_sub_type="progress",
        )
        baseline_checker(
            capture_prompt(summarizer),
            AGENT,
            "suggest_context_investigations__narration_progress",
        )

    @pytest.mark.asyncio
    async def test_update_context_investigation(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value="Updated investigation."
        )
        await summarizer.update_context_investigation(
            current_context_investigation="The hero was tired from the journey.",
            new_context_investigation="The hero had rested the night before.",
            analysis="The scene shows a confrontation.",
        )
        baseline_checker(
            capture_prompt(summarizer), AGENT, "update_context_investigation"
        )

    @pytest.mark.asyncio
    async def test_markup_context_for_tts(self, active_context, baseline_checker):
        summarizer = active_context
        summarizer.client.send_prompt = AsyncMock(
            return_value='<MARKUP>[1] "Hello," said Elena. [SPEAKER: Elena]</MARKUP>'
        )
        text = '"Hello there," said Elena. Marcus nodded.'
        await summarizer.markup_context_for_tts(text)
        baseline_checker(
            capture_prompt(summarizer), AGENT, "markup_context_for_tts"
        )
