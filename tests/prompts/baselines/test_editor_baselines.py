"""
Baseline snapshot tests for editor agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from ..conftest import mock_llm_client  # noqa: F401
from ..test_editor_templates import (  # noqa: F401
    mock_scene,
    mock_memory_agent,
    mock_summarizer_agent,
    mock_narrator_agent_for_registry,
    mock_director_agent,
    editor_agent,
    setup_agents,
    active_context,
)
from .conftest import capture_prompt

AGENT = "editor"


def _force_repetition_match(
    mock_scene, mock_memory_agent, history_text="The forest was dark and mysterious."
):
    """Wire mocks so a single similarity match is reported for the draft text.

    Used by baseline tests that need to exercise the repetition-handling
    branches of the revision templates without involving real embeddings.
    """
    history_messages = [Mock(message=history_text, typ="narrator")]
    mock_scene.collect_messages = Mock(return_value=history_messages)
    mock_memory_agent.compare_string_lists = AsyncMock(
        return_value={
            "similarity_matches": [[0, 0, 0.9]],
            "cosine_similarity_matrix": [],
        }
    )


class TestEditorBaselines:
    """Baseline tests for editor agent methods."""

    @pytest.mark.asyncio
    async def test_add_detail(self, active_context, mock_scene, baseline_checker):
        editor = active_context
        character = mock_scene.get_character("Elena")
        editor.actions["add_detail"].enabled = True
        await editor.add_detail(content="Elena: Hello there.", character=character)
        baseline_checker(capture_prompt(editor), AGENT, "add_detail")

    @pytest.mark.asyncio
    async def test_revision_rewrite(
        self,
        active_context,
        mock_scene,
        mock_memory_agent,
        baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "rewrite"
        editor.actions["revision"].config["min_issues"].value = 1

        _force_repetition_match(mock_scene, mock_memory_agent)

        editor.client.send_prompt = AsyncMock(
            return_value="<REVISION>The forest was silent.</REVISION>"
        )

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="The forest was dark and mysterious.",
            character=None,
        )
        await editor.revision_rewrite(info)

        baseline_checker(capture_prompt(editor), AGENT, "revision_rewrite")

    @pytest.mark.asyncio
    async def test_revision_rewrite__rewrite_handling(
        self,
        active_context,
        mock_scene,
        mock_memory_agent,
        baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "rewrite"
        editor.actions["revision"].config["min_issues"].value = 1
        editor.actions["revision"].config["repetition_handling"].value = "rewrite"

        _force_repetition_match(mock_scene, mock_memory_agent)

        editor.client.send_prompt = AsyncMock(
            return_value="<REVISION>The forest was silent.</REVISION>"
        )

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="The forest was dark and mysterious.",
            character=None,
        )
        await editor.revision_rewrite(info)

        baseline_checker(
            capture_prompt(editor), AGENT, "revision_rewrite__rewrite_handling"
        )

    @pytest.mark.asyncio
    async def test_revision_unslop(
        self,
        active_context,
        mock_scene,
        mock_memory_agent,
        mock_summarizer_agent,
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
        self,
        active_context,
        mock_memory_agent,
        mock_summarizer_agent,
        baseline_checker,
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
        self,
        active_context,
        mock_memory_agent,
        mock_summarizer_agent,
        baseline_checker,
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

    @pytest.mark.asyncio
    async def test_revision_unslop__with_repetition(
        self,
        active_context,
        mock_scene,
        mock_memory_agent,
        mock_summarizer_agent,
        baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"
        # default: repetition_handling="remove"

        _force_repetition_match(mock_scene, mock_memory_agent)

        editor.client.send_prompt = AsyncMock(return_value="<FIX>Fixed text.</FIX>")

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="The forest was dark and mysterious.",
            character=None,
        )
        await editor.revision_unslop(info)
        baseline_checker(
            capture_prompt(editor), AGENT, "revision_unslop__with_repetition"
        )

    @pytest.mark.asyncio
    async def test_revision_unslop__with_repetition__rewrite_handling(
        self,
        active_context,
        mock_scene,
        mock_memory_agent,
        mock_summarizer_agent,
        baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"
        editor.actions["revision"].config["repetition_handling"].value = "rewrite"

        _force_repetition_match(mock_scene, mock_memory_agent)

        editor.client.send_prompt = AsyncMock(return_value="<FIX>Fixed text.</FIX>")

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="The forest was dark and mysterious.",
            character=None,
        )
        await editor.revision_unslop(info)
        baseline_checker(
            capture_prompt(editor),
            AGENT,
            "revision_unslop__with_repetition__rewrite_handling",
        )

    @pytest.mark.asyncio
    async def test_revision_unslop__summarization_with_repetition(
        self,
        active_context,
        mock_scene,
        mock_memory_agent,
        mock_summarizer_agent,
        baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"
        # default: repetition_handling="remove"

        _force_repetition_match(
            mock_scene,
            mock_memory_agent,
            history_text="The heroes journeyed through the treacherous mountain pass.",
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
            capture_prompt(editor),
            AGENT,
            "revision_unslop__summarization_with_repetition",
        )

    @pytest.mark.asyncio
    async def test_revision_unslop__summarization_with_repetition__rewrite_handling(
        self,
        active_context,
        mock_scene,
        mock_memory_agent,
        mock_summarizer_agent,
        baseline_checker,
    ):
        editor = active_context
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"
        editor.actions["revision"].config["repetition_handling"].value = "rewrite"

        _force_repetition_match(
            mock_scene,
            mock_memory_agent,
            history_text="The heroes journeyed through the treacherous mountain pass.",
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
            capture_prompt(editor),
            AGENT,
            "revision_unslop__summarization_with_repetition__rewrite_handling",
        )
