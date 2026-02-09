"""
Baseline snapshot tests for editor agent prompt templates (prompt caching enabled).

Mirrors tests in baselines/ but with optimize_prompt_caching=True.
"""

import pytest
from unittest.mock import AsyncMock

from ..test_editor_templates import (
    mock_scene,
    mock_memory_agent,
    mock_summarizer_agent,
    mock_narrator_agent_for_registry,
    mock_director_agent,
    editor_agent,
    setup_agents,
    active_context,
)
from ..baselines.conftest import capture_prompt

AGENT = "editor"


class TestEditorBaselines:
    """Baseline tests for editor agent methods (prompt caching enabled)."""

    @pytest.mark.asyncio
    async def test_add_detail(self, active_context, mock_scene, baseline_checker):
        editor = active_context
        character = mock_scene.get_character("Elena")
        editor.actions["add_detail"].enabled = True
        await editor.add_detail(content="Elena: Hello there.", character=character)
        baseline_checker(capture_prompt(editor), AGENT, "add_detail")

    @pytest.mark.asyncio
    async def test_revision_unslop(
        self, active_context, mock_scene, mock_memory_agent, mock_summarizer_agent,
        baseline_checker,
    ):
        editor = active_context
        character = mock_scene.get_character("Elena")
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={"similarity_matches": [], "cosine_similarity_matrix": []}
        )
        editor.client.send_prompt = AsyncMock(return_value="<FIX>Fixed text.</FIX>")

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text='Elena: "The forest is ethereally luminescent," she breathed softly.',
            character=character,
        )
        await editor.revision_unslop(info)
        baseline_checker(capture_prompt(editor), AGENT, "revision_unslop")

    @pytest.mark.asyncio
    async def test_revision_unslop__contextual_generation(
        self, active_context, mock_memory_agent, mock_summarizer_agent, baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={"similarity_matches": [], "cosine_similarity_matrix": []}
        )
        editor.client.send_prompt = AsyncMock(return_value="<FIX>Fixed text.</FIX>")

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="A warrior with the strength of a thousand suns.",
            character=None,
            context_type="character attribute",
            context_name="abilities",
        )
        await editor.revision_unslop(info)
        baseline_checker(
            capture_prompt(editor), AGENT, "revision_unslop__contextual_generation"
        )

    @pytest.mark.asyncio
    async def test_revision_unslop__summarization(
        self, active_context, mock_memory_agent, mock_summarizer_agent, baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={"similarity_matches": [], "cosine_similarity_matrix": []}
        )
        editor.client.send_prompt = AsyncMock(return_value="<FIX>Fixed text.</FIX>")

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="The heroes journeyed through the treacherous mountain pass.",
            character=None,
            summarization_history=["Chapter 1: The journey began."],
        )
        await editor.revision_unslop(info)
        baseline_checker(
            capture_prompt(editor), AGENT, "revision_unslop__summarization"
        )
