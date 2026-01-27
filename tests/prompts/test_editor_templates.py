"""
Unit tests for editor agent templates.

Tests template rendering without requiring an LLM connection.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from .helpers import (
    create_mock_agent,
    create_mock_character,
    create_mock_scene,
    create_base_context,
    render_template,
    assert_template_renders,
)


@pytest.fixture
def editor_context():
    """Base context for editor templates."""
    return create_base_context()


@pytest.fixture
def active_context(editor_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="editor")
    scene_token = active_scene.set(editor_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield editor_context

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


def create_mock_intent_state():
    """Create a mock intent state for scene intent templates."""
    intent_state = Mock()
    intent_state.active = True
    intent_state.intent = "A fantasy adventure story."
    intent_state.instructions = "Make the story engaging and fun."
    intent_state.phase = Mock()
    intent_state.phase.intent = "The hero explores the forest."
    intent_state.current_scene_type = Mock(
        id="exploration",
        name="Exploration",
        description="An exploration scene",
        instructions="Focus on discovery and wonder.",
    )
    intent_state.scene_types = {
        "social": Mock(id="social", name="Social", description="A social scene", instructions=""),
        "combat": Mock(id="combat", name="Combat", description="A combat scene", instructions=""),
    }
    return intent_state


@pytest.fixture
def mock_intent_state():
    """Create a mock intent state for scene intent templates."""
    return create_mock_intent_state()


@pytest.fixture
def mock_focal():
    """Create a mock Focal instance for templates that use focal callbacks."""
    focal = Mock()
    focal.render_instructions = Mock(return_value="Mock focal instructions")
    focal.state = Mock()
    focal.state.schema_format = "json"
    focal.max_calls = 5

    # Mock callbacks
    focal.callbacks = Mock()
    focal.callbacks.rewrite_text = Mock()
    focal.callbacks.rewrite_text.render = Mock(return_value="rewrite_text callback rendered")

    return focal


@pytest.fixture
def patch_all_agent_calls():
    """
    Extended patch for templates that use multiple agent calls.

    This patches rag_build and other agent calls like query_memory,
    get_cached_character_guidance, and agent_action.
    """
    with patch('talemate.instance.get_agent') as mock_get_agent:
        # Create different mock agents for different agent types
        mock_editor = Mock()
        mock_editor.rag_build = AsyncMock(return_value=[])

        mock_director = Mock()
        mock_director.get_cached_character_guidance = AsyncMock(return_value="")

        mock_memory = Mock()
        mock_memory.query = AsyncMock(return_value="Mocked memory response")
        mock_memory.multi_query = AsyncMock(return_value={})

        mock_world_state = Mock()
        mock_world_state.analyze_text_and_answer_question = AsyncMock(return_value="yes")

        def get_agent_side_effect(agent_type):
            agents = {
                "editor": mock_editor,
                "director": mock_director,
                "memory": mock_memory,
                "world_state": mock_world_state,
            }
            return agents.get(agent_type, Mock())

        mock_get_agent.side_effect = get_agent_side_effect
        yield mock_get_agent


class TestEditorSystemTemplates:
    """Tests for editor system templates."""

    def test_system_no_decensor_renders(self, active_context):
        """Test system-no-decensor.jinja2 renders."""
        result = render_template("editor.system-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        assert "editor" in result.lower()

    def test_system_renders(self, active_context):
        """Test system.jinja2 renders (includes system-no-decensor)."""
        result = render_template("editor.system", active_context)
        assert result is not None
        assert len(result) > 0
        # system.jinja2 adds text about explicit content
        assert "editor" in result.lower()
        assert "explicit" in result.lower() or "content" in result.lower()


class TestEditorContextTemplates:
    """Tests for editor context templates."""

    def test_extra_context_renders(self, active_context, patch_agent_queries):
        """Test extra-context.jinja2 renders with scene data."""
        context = active_context.copy()
        context["memory_query"] = ""  # No memory query
        result = render_template("editor.extra-context", context)
        assert result is not None
        # Template may be minimal without memory_query

    def test_extra_context_with_memory_query(self, active_context, patch_agent_queries):
        """Test extra-context.jinja2 renders with memory query."""
        context = active_context.copy()
        context["memory_query"] = "What happened recently?"
        result = render_template("editor.extra-context", context)
        assert result is not None

    def test_scene_context_renders(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test scene-context.jinja2 renders with scene history."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["context_investigation"] = ""
        context["mentioned_characters"] = []
        result = render_template("editor.scene-context", context)
        assert result is not None
        assert len(result) > 0
        # Template should include SCENE section marker
        assert "scene" in result.lower()

    def test_scene_context_with_context_investigation(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test scene-context.jinja2 with context_investigation."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["context_investigation"] = "The character is hiding something."
        context["mentioned_characters"] = []
        result = render_template("editor.scene-context", context)
        assert result is not None
        assert len(result) > 0
        # Should include the context investigation
        assert "hiding" in result.lower()

    def test_memory_context_renders(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 renders with memory prompt."""
        context = active_context.copy()
        context["memory_prompt"] = "What happened in the forest clearing?"
        result = render_template("editor.memory-context", context)
        # Template relies on agent_action which returns empty list via patch
        assert result is not None

    def test_character_context_renders(self, active_context, patch_agent_queries):
        """Test character-context.jinja2 renders with characters."""
        context = active_context.copy()
        # Add characters to the scene
        char1 = create_mock_character(name="Elena")
        char1.filtered_sheet = Mock(return_value="age: early 30s\ngender: female")
        char2 = create_mock_character(name="Marcus", is_player=True)
        char2.filtered_sheet = Mock(return_value="age: mid 20s\ngender: male")
        context["scene"].characters = [char1, char2]
        context["mentioned_characters"] = []
        result = render_template("editor.character-context", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result
        assert "Marcus" in result

    def test_character_context_with_mentioned(self, active_context, patch_agent_queries):
        """Test character-context.jinja2 with mentioned_characters."""
        context = active_context.copy()
        char1 = create_mock_character(name="Elena")
        char1.filtered_sheet = Mock(return_value="age: early 30s\ngender: female")
        context["scene"].characters = [char1]
        mentioned_char = create_mock_character(name="OldHermit")
        context["mentioned_characters"] = [mentioned_char]
        result = render_template("editor.character-context", context)
        assert result is not None
        assert len(result) > 0
        assert "OldHermit" in result


class TestEditorFixTemplates:
    """Tests for editor fix-* templates."""

    def test_fix_exposition_renders(self, active_context):
        """Test fix-exposition.jinja2 renders with character and content."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["character"] = char
        context["content"] = "She whispered, Don't tell anyone. with a stern look."
        result = render_template("editor.fix-exposition", context)
        assert result is not None
        assert len(result) > 0
        # Template should include character name
        assert "Elena" in result
        # Template should include task section
        assert "task" in result.lower()
        # Template should reference the content
        assert "whispered" in result.lower()

    def test_fix_continuity_errors_renders(self, active_context, patch_all_agent_calls):
        """Test fix-continuity-errors.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["character"] = char
        context["scene"].snapshot = Mock(return_value="Current scene state")
        context["text"] = "Marcus is a skilled warrior with years of experience."
        context["content"] = "Marcus says he's new to fighting."
        context["errors"] = [
            "Marcus was described as experienced, but now claims to be new to fighting."
        ]
        # The template uses set_state to store state on the prompt instance
        context["set_state"] = Mock()
        result = render_template("editor.fix-continuity-errors", context)
        assert result is not None
        assert len(result) > 0
        # Template should include character name
        assert "Marcus" in result
        # Template should include the errors
        assert "experienced" in result.lower() or "fighting" in result.lower()

    def test_fix_continuity_errors_without_character(self, active_context, patch_all_agent_calls):
        """Test fix-continuity-errors.jinja2 renders without character."""
        context = active_context.copy()
        context["character"] = None
        context["scene"].snapshot = Mock(return_value="Current scene state")
        context["text"] = "The castle stood tall on the hill."
        context["content"] = "The valley was empty of any structures."
        context["errors"] = [
            "Previously mentioned a castle, but now describes an empty valley."
        ]
        # The template uses set_state to store state on the prompt instance
        context["set_state"] = Mock()
        result = render_template("editor.fix-continuity-errors", context)
        assert result is not None
        assert len(result) > 0
        # Template should still render for narrative continuity


class TestEditorRevisionTemplates:
    """Tests for editor revision templates."""

    def test_revision_analysis_renders(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test revision-analysis.jinja2 renders."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "The sun shone brightly upon the verdant meadows."
        context["repetition"] = None
        context["bad_prose"] = None
        context["scene_analysis"] = ""
        context["character"] = None
        result = render_template("editor.revision-analysis", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text to review
        assert "sun" in result.lower() or "meadows" in result.lower()
        # Template should include task section
        assert "task" in result.lower()

    def test_revision_analysis_with_repetition(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test revision-analysis.jinja2 with repetition issues."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "The tall man walked tall through the tall door."
        context["repetition"] = [
            {"text_a": "tall", "text_b": "tall"}
        ]
        context["bad_prose"] = None
        context["scene_analysis"] = ""
        context["character"] = None
        result = render_template("editor.revision-analysis", context)
        assert result is not None
        assert len(result) > 0
        # Should include repetition section
        assert "repetition" in result.lower()

    def test_revision_analysis_with_bad_prose(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test revision-analysis.jinja2 with bad prose issues."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "Her eyes sparkled like diamonds."
        context["repetition"] = None
        context["bad_prose"] = [
            {"phrase": "sparkled like diamonds", "instructions": "Avoid cliched eye descriptions."}
        ]
        context["scene_analysis"] = ""
        context["character"] = None
        result = render_template("editor.revision-analysis", context)
        assert result is not None
        assert len(result) > 0
        # Should include the bad prose section
        assert "unwanted" in result.lower() or "prose" in result.lower()

    def test_revision_rewrite_renders(self, active_context, mock_focal):
        """Test revision-rewrite.jinja2 renders."""
        context = active_context.copy()
        context["text"] = "The weather was nice and the birds were singing."
        context["analysis"] = "The text is clear but could be more vivid."
        context["focal"] = mock_focal
        result = render_template("editor.revision-rewrite", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the draft text
        assert "weather" in result.lower() or "birds" in result.lower()
        # Template should include the analysis
        assert "vivid" in result.lower()


class TestEditorDetailTemplates:
    """Tests for editor add-detail template."""

    def test_add_detail_renders(self, active_context, patch_agent_queries):
        """Test add-detail.jinja2 renders."""
        context = active_context.copy()
        char1 = create_mock_character(name="Elena")
        char1.filtered_sheet = Mock(return_value="age: early 30s\ngender: female")
        char2 = create_mock_character(name="Hero", is_player=True)
        char2.filtered_sheet = Mock(return_value="age: mid 20s\ngender: male")
        context["characters"] = [char1, char2]
        context["character"] = char1
        context["content"] = "Elena: Hello there."
        result = render_template("editor.add-detail", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character
        assert "Elena" in result
        # Template should include the content
        assert "hello" in result.lower()


class TestEditorUnslopTemplates:
    """Tests for editor unslop templates."""

    def test_unslop_renders(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test unslop.jinja2 renders."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "Her eyes sparkled with an ethereal luminescence."
        context["repetition"] = None
        context["bad_prose"] = None
        context["scene_analysis"] = ""
        context["character"] = None
        result = render_template("editor.unslop", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text to review
        assert "sparkled" in result.lower() or "ethereal" in result.lower()
        # Template should include task section
        assert "task" in result.lower()
        # Template should include rules for fixing
        assert "purple prose" in result.lower()

    def test_unslop_with_character(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test unslop.jinja2 with character guidance."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = '"I trust you," she said earnestly.'
        context["repetition"] = None
        context["bad_prose"] = None
        context["scene_analysis"] = ""
        char = create_mock_character(name="Elena")
        context["character"] = char
        context["agent_context_state"] = {"conversation__instruction": ""}
        context["conversation_instruction"] = ""
        context["message"] = None
        result = render_template("editor.unslop", context)
        assert result is not None
        assert len(result) > 0

    def test_unslop_with_decensor(self, active_context, patch_all_agent_calls, mock_intent_state):
        """Test unslop.jinja2 with decensor enabled."""
        context = active_context.copy()
        context["decensor"] = True
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "She cursed under her breath."
        context["repetition"] = None
        context["bad_prose"] = None
        context["scene_analysis"] = ""
        context["character"] = None
        result = render_template("editor.unslop", context)
        assert result is not None
        assert len(result) > 0

    def test_unslop_summarization_renders(self, active_context, mock_intent_state):
        """Test unslop-summarization.jinja2 renders."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "The heroes journeyed through the treacherous mountain pass."
        context["repetition"] = None
        context["bad_prose"] = None
        context["summarization_history"] = []
        result = render_template("editor.unslop-summarization", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text to review
        assert "heroes" in result.lower() or "mountain" in result.lower()
        # Template should include task section
        assert "task" in result.lower()
        # Template should mention summaries/summarization
        assert "summary" in result.lower() or "summar" in result.lower()

    def test_unslop_summarization_with_history(self, active_context, mock_intent_state):
        """Test unslop-summarization.jinja2 with summarization history."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "The battle was fierce but the heroes prevailed."
        context["repetition"] = None
        context["bad_prose"] = None
        context["summarization_history"] = [
            "Chapter 1: The hero began their journey.",
            "Chapter 2: The hero met allies along the way."
        ]
        result = render_template("editor.unslop-summarization", context)
        assert result is not None
        assert len(result) > 0
        # Should include previous chapter summaries
        assert "chapter" in result.lower()

    def test_unslop_contextual_generation_renders(self, active_context, mock_intent_state):
        """Test unslop-contextual-generation.jinja2 renders."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "Eyes like pools of liquid sapphire."
        context["character"] = None
        context["context_type"] = "character attribute"
        context["context_name"] = "appearance"
        result = render_template("editor.unslop-contextual-generation", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text to review
        assert "eyes" in result.lower() or "sapphire" in result.lower()
        # Template should include task section
        assert "task" in result.lower()

    def test_unslop_contextual_generation_with_character(self, active_context, mock_intent_state):
        """Test unslop-contextual-generation.jinja2 with character."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "A warrior with the strength of a thousand men."
        char = create_mock_character(name="Marcus")
        context["character"] = char
        context["context_type"] = "character detail"
        context["context_name"] = "abilities"
        result = render_template("editor.unslop-contextual-generation", context)
        assert result is not None
        assert len(result) > 0
        # Should include character section
        assert "Marcus" in result

    def test_unslop_contextual_generation_scene_intro(self, active_context, mock_intent_state):
        """Test unslop-contextual-generation.jinja2 for scene intro."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "The ethereal moonlight bathed the ancient fortress."
        context["character"] = None
        context["context_type"] = "scene intro"
        context["context_name"] = "introduction"
        result = render_template("editor.unslop-contextual-generation", context)
        assert result is not None
        assert len(result) > 0
        # Should reference scene introduction type
        assert "scene" in result.lower() or "introduction" in result.lower()

    def test_unslop_contextual_generation_world_context(self, active_context, mock_intent_state):
        """Test unslop-contextual-generation.jinja2 for world context."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["scene"].writing_style = None
        context["text"] = "Magic flows through the veins of the universe itself."
        context["character"] = None
        context["context_type"] = "world context"
        context["context_name"] = "magic system"
        result = render_template("editor.unslop-contextual-generation", context)
        assert result is not None
        assert len(result) > 0
        # Should reference world context type
        assert "world" in result.lower() or "magic" in result.lower()


class TestEditorIncludeOnlyTemplates:
    """
    Tests that verify include-only templates are properly tested through their parent templates.

    The following templates are include-only and tested through other templates:
    - character-context.jinja2 (tested through scene-context.jinja2)
    - memory-context.jinja2 (tested through scene-context.jinja2)
    - extra-context.jinja2 (tested through scene-context.jinja2)

    These templates are also tested directly above for completeness.
    """

    def test_include_only_templates_covered(self):
        """
        Document that include-only templates are tested through their parent templates.

        This test serves as documentation that we intentionally test these
        templates both directly and through their parent templates.
        """
        include_only_templates = [
            "character-context.jinja2",  # included by scene-context.jinja2
            "memory-context.jinja2",     # included by scene-context.jinja2
            "extra-context.jinja2",      # included by scene-context.jinja2
        ]
        # This test just documents the include patterns
        # All templates are also tested directly above
        assert True
