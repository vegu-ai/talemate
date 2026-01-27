"""
Unit tests for narrator agent templates.

Tests template rendering without requiring an LLM connection.
"""

import pytest
from .helpers import (
    create_mock_agent,
    create_mock_character,
    create_base_context,
    render_template,
    assert_template_renders,
)


@pytest.fixture
def narrator_context():
    """Base context for narrator templates."""
    return create_base_context()


@pytest.fixture
def active_context(narrator_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="narrator")
    scene_token = active_scene.set(narrator_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield narrator_context

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


class TestNarratorSystemTemplates:
    """Tests for narrator system templates."""

    def test_system_no_decensor_renders(self, active_context):
        """Test system-no-decensor.jinja2 renders."""
        result = render_template("narrator.system-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        assert "narrator" in result.lower()

    def test_system_renders(self, active_context):
        """Test system.jinja2 renders (includes system-no-decensor)."""
        result = render_template("narrator.system", active_context)
        assert result is not None
        assert len(result) > 0
        assert "narrator" in result.lower()
        # system.jinja2 adds extra text about explicit imagery
        assert "explicit" in result.lower() or "imagery" in result.lower()


class TestNarratorNarrationTemplates:
    """Tests for narrator narration templates."""

    def test_narrate_scene_renders(self, active_context, patch_rag_build):
        """Test narrate-scene.jinja2 renders."""
        result = render_template("narrator.narrate-scene", active_context)
        assert result is not None
        assert len(result) > 0
        # Template should include task instructions about visual details
        assert "visual" in result.lower()

    def test_narrate_progress_renders(self, active_context, patch_rag_build):
        """Test narrate-progress.jinja2 renders."""
        result = render_template("narrator.narrate-progress", active_context)
        assert result is not None
        assert len(result) > 0
        # Template should include task instructions about moving story forward
        assert "forward" in result.lower() or "progress" in result.lower()

    def test_narrate_query_renders(self, active_context, patch_rag_build):
        """Test narrate-query.jinja2 renders with a query."""
        context = active_context.copy()
        context["query"] = "What is the current state of the scene?"
        result = render_template("narrator.narrate-query", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the query
        assert "current state" in result.lower()

    def test_narrate_query_with_instruction_renders(self, active_context, patch_rag_build):
        """Test narrate-query.jinja2 renders with a non-question instruction."""
        context = active_context.copy()
        context["query"] = "Describe the atmosphere of the scene"
        result = render_template("narrator.narrate-query", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the instruction
        assert "atmosphere" in result.lower()

    def test_narrate_character_renders(self, active_context, patch_rag_build):
        """Test narrate-character.jinja2 renders with a character."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Marcus")
        result = render_template("narrator.narrate-character", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character name
        assert "Marcus" in result

    def test_narrate_character_entry_renders(self, active_context, patch_rag_build):
        """Test narrate-character-entry.jinja2 renders with a character."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Aria")
        result = render_template("narrator.narrate-character-entry", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character name and entrance
        assert "Aria" in result
        assert "entrance" in result.lower() or "enters" in result.lower()

    def test_narrate_character_entry_with_narrative_direction(self, active_context, patch_rag_build):
        """Test narrate-character-entry.jinja2 with narrative direction."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Aria")
        context["narrative_direction"] = "Aria enters dramatically through the main door."
        result = render_template("narrator.narrate-character-entry", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the narrative direction
        assert "Aria" in result

    def test_narrate_character_exit_renders(self, active_context, patch_rag_build):
        """Test narrate-character-exit.jinja2 renders with a character."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Roland")
        result = render_template("narrator.narrate-character-exit", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character name and exit
        assert "Roland" in result
        assert "exit" in result.lower() or "leaves" in result.lower()

    def test_narrate_character_exit_with_narrative_direction(self, active_context, patch_rag_build):
        """Test narrate-character-exit.jinja2 with narrative direction."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Roland")
        context["narrative_direction"] = "Roland exits silently into the night."
        result = render_template("narrator.narrate-character-exit", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the character name
        assert "Roland" in result

    def test_narrate_after_dialogue_renders(self, active_context, patch_rag_build):
        """Test narrate-after-dialogue.jinja2 renders."""
        result = render_template("narrator.narrate-after-dialogue", active_context)
        assert result is not None
        assert len(result) > 0
        # Template should include sensory details instruction
        assert "sensory" in result.lower()
        # Template should include the last message from scene context
        assert "current moment" in result.lower()

    def test_narrate_time_passage_renders(self, active_context, patch_rag_build):
        """Test narrate-time-passage.jinja2 renders with time passed."""
        context = active_context.copy()
        context["time_passed"] = "Two hours later"
        context["bot_token"] = "<|BOT|>"
        result = render_template("narrator.narrate-time-passage", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference time passage
        assert "time" in result.lower() or "passage" in result.lower()
        # Template should include the time_passed value in the bot token section
        assert "Two hours later" in result


class TestNarratorUtilityTemplates:
    """Tests for narrator utility templates."""

    def test_paraphrase_renders(self, active_context):
        """Test paraphrase.jinja2 renders with text to paraphrase."""
        context = active_context.copy()
        context["text"] = "The warrior drew his sword and prepared for battle."
        result = render_template("narrator.paraphrase", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text to paraphrase
        assert "warrior" in result.lower() or "sword" in result.lower()
        # Template should include paraphrase instructions
        assert "paraphrase" in result.lower()

    def test_paraphrase_with_extra_instructions(self, active_context):
        """Test paraphrase.jinja2 renders with extra instructions."""
        context = active_context.copy()
        context["text"] = "The mage cast a powerful spell."
        context["extra_instructions"] = "Maintain a formal tone."
        result = render_template("narrator.paraphrase", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the extra instructions
        assert "formal" in result.lower()

    def test_narrative_direction_renders(self, active_context):
        """Test narrative-direction.jinja2 renders with narrative direction."""
        context = active_context.copy()
        context["narrative_direction"] = "The hero discovers a hidden passage."
        result = render_template("narrator.narrative-direction", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the narrative direction
        assert "hidden passage" in result.lower()
        # Template should indicate these are directions for new narration
        assert "direction" in result.lower()

    def test_narrative_direction_without_direction(self, active_context):
        """Test narrative-direction.jinja2 renders without narrative direction (fallback)."""
        context = active_context.copy()
        context["narrative_direction"] = ""
        result = render_template("narrator.narrative-direction", context)
        assert result is not None
        # Should still render (includes regenerate-context as fallback)

    def test_narrative_direction_with_regeneration_context(self, active_context):
        """Test narrative-direction.jinja2 with regeneration context."""
        from unittest.mock import Mock
        context = active_context.copy()
        context["narrative_direction"] = "The hero speaks."
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Make it more dramatic."
        context["regeneration_context"].method = "edit"
        context["regeneration_context"].message = "The hero speaks softly."
        result = render_template("narrator.narrative-direction", context)
        assert result is not None
        assert len(result) > 0
        # Should include the editorial instructions
        assert "dramatic" in result.lower()


class TestNarratorContextTemplates:
    """Tests for narrator context templates."""

    def test_extra_context_renders(self, active_context):
        """Test extra-context.jinja2 renders with scene data."""
        result = render_template("narrator.extra-context", active_context)
        assert result is not None
        assert len(result) > 0
        # Template should include content classification section
        assert "classification" in result.lower() or "context" in result.lower()

    def test_extra_context_with_skip_characters(self, active_context):
        """Test extra-context.jinja2 with skip_characters."""
        context = active_context.copy()
        context["skip_characters"] = ["Elena"]
        result = render_template("narrator.extra-context", context)
        assert result is not None
        assert len(result) > 0

    def test_scene_context_renders(self, active_context, patch_rag_build):
        """Test scene-context.jinja2 renders with scene history."""
        context = active_context.copy()
        context["budget"] = 2000
        result = render_template("narrator.scene-context", context)
        assert result is not None
        assert len(result) > 0
        # Template should include SCENE section marker
        assert "scene" in result.lower()

    def test_scene_context_with_custom_budget(self, active_context, patch_rag_build):
        """Test scene-context.jinja2 with custom token budget."""
        context = active_context.copy()
        context["budget"] = 500
        result = render_template("narrator.scene-context", context)
        assert result is not None
        assert len(result) > 0

    def test_regenerate_context_renders(self, active_context):
        """Test regenerate-context.jinja2 renders without regeneration context."""
        result = render_template("narrator.regenerate-context", active_context)
        # Should render without error (empty when no regeneration_context)
        assert result is not None

    def test_regenerate_context_with_replace_method(self, active_context):
        """Test regenerate-context.jinja2 with replace regeneration method."""
        from unittest.mock import Mock
        context = active_context.copy()
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Rewrite with more action."
        context["regeneration_context"].method = "replace"
        result = render_template("narrator.regenerate-context", context)
        assert result is not None
        assert len(result) > 0
        # Should include the replacement direction
        assert "action" in result.lower()

    def test_regenerate_context_with_edit_method(self, active_context):
        """Test regenerate-context.jinja2 with edit regeneration method."""
        from unittest.mock import Mock
        context = active_context.copy()
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Add more suspense."
        context["regeneration_context"].method = "edit"
        context["regeneration_context"].message = "The door creaked open slowly."
        context["narrative_direction"] = "Someone enters the room."
        result = render_template("narrator.regenerate-context", context)
        assert result is not None
        assert len(result) > 0
        # Should include the first draft
        assert "door" in result.lower() or "draft" in result.lower()
        # Should include editorial instructions
        assert "suspense" in result.lower()

    def test_memory_context_renders(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 renders with memory prompt."""
        context = active_context.copy()
        context["memory_prompt"] = "What happened in the forest clearing?"
        result = render_template("narrator.memory-context", context)
        # Template relies on agent_action which returns empty list via patch
        assert result is not None

    def test_memory_context_with_query_narration(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 with narrator query context state."""
        context = active_context.copy()
        context["memory_prompt"] = "Recent events in the story"
        context["agent_context_state"] = {
            "narrator__query_narration": True,
            "narrator__query": "What is the hero's goal?"
        }
        result = render_template("narrator.memory-context", context)
        # Should render without error
        assert result is not None
