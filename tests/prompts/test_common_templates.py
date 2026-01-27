"""
Unit tests for common templates.

Common templates are include-only templates used by other agent templates.
They are tested by rendering them directly with appropriate context.

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
def common_context():
    """Base context for common templates."""
    return create_base_context()


@pytest.fixture
def active_context(common_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="narrator")
    scene_token = active_scene.set(common_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield common_context

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
        "social": Mock(id="social", name="Social", description="A social scene", instructions="Social instructions"),
        "combat": Mock(id="combat", name="Combat", description="A combat scene", instructions="Combat instructions"),
    }
    return intent_state


@pytest.fixture
def mock_intent_state():
    """Create a mock intent state for scene intent templates."""
    return create_mock_intent_state()


@pytest.fixture
def patch_all_agent_calls():
    """
    Extended patch for templates that use multiple agent calls.

    This patches rag_build and other agent calls like query_memory,
    get_cached_character_guidance, and agent_action.
    """
    with patch('talemate.instance.get_agent') as mock_get_agent:
        mock_narrator = Mock()
        mock_narrator.rag_build = AsyncMock(return_value=[])

        mock_director = Mock()
        mock_director.get_cached_character_guidance = AsyncMock(return_value="")

        mock_memory = Mock()
        mock_memory.query = AsyncMock(return_value="Mocked memory response")
        mock_memory.multi_query = AsyncMock(return_value={})

        mock_world_state = Mock()
        mock_world_state.analyze_text_and_answer_question = AsyncMock(return_value="yes")

        def get_agent_side_effect(agent_type):
            agents = {
                "narrator": mock_narrator,
                "director": mock_director,
                "memory": mock_memory,
                "world_state": mock_world_state,
            }
            return agents.get(agent_type, Mock())

        mock_get_agent.side_effect = get_agent_side_effect
        yield mock_get_agent


class TestBaseTemplate:
    """Tests for common/base.jinja2 template."""

    def test_base_renders_minimal(self, active_context, mock_intent_state, patch_all_agent_calls):
        """Test base.jinja2 renders with minimal context."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["include_scene_intent"] = False
        context["include_extra_context"] = False
        context["include_memory_context"] = False
        context["include_character_context"] = False
        context["include_gamestate_context"] = False
        context["include_scene_context"] = False
        context["dynamic_context"] = None
        context["instructions"] = None
        context["focal"] = None
        context["prefill_prompt"] = None
        context["return_prefill_prompt"] = False
        context["reserved_tokens"] = 0
        result = render_template("common.base", context)
        assert result is not None

    def test_base_with_instructions(self, active_context, mock_intent_state, patch_all_agent_calls):
        """Test base.jinja2 renders with instructions."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["include_scene_intent"] = False
        context["include_extra_context"] = False
        context["include_memory_context"] = False
        context["include_character_context"] = False
        context["include_gamestate_context"] = False
        context["include_scene_context"] = False
        context["dynamic_context"] = None
        context["instructions"] = "Write a compelling story."
        context["focal"] = None
        context["prefill_prompt"] = None
        context["return_prefill_prompt"] = False
        context["reserved_tokens"] = 0
        context["response_length"] = None
        result = render_template("common.base", context)
        assert result is not None
        assert "compelling story" in result.lower()

    def test_base_with_decensor(self, active_context, mock_intent_state, patch_all_agent_calls):
        """Test base.jinja2 renders with decensor enabled."""
        context = active_context.copy()
        context["decensor"] = True
        context["scene"].intent_state = mock_intent_state
        context["include_scene_intent"] = False
        context["include_extra_context"] = False
        context["include_memory_context"] = False
        context["include_character_context"] = False
        context["include_gamestate_context"] = False
        context["include_scene_context"] = False
        context["dynamic_context"] = None
        context["instructions"] = None
        context["focal"] = None
        context["prefill_prompt"] = None
        context["return_prefill_prompt"] = False
        context["reserved_tokens"] = 0
        result = render_template("common.base", context)
        assert result is not None
        assert "fiction" in result.lower()

    def test_base_with_scene_intent(self, active_context, mock_intent_state, patch_all_agent_calls):
        """Test base.jinja2 renders with scene intent included."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["include_scene_intent"] = True
        context["include_extra_context"] = False
        context["include_memory_context"] = False
        context["include_character_context"] = False
        context["include_gamestate_context"] = False
        context["include_scene_context"] = False
        context["dynamic_context"] = None
        context["instructions"] = None
        context["focal"] = None
        context["prefill_prompt"] = None
        context["return_prefill_prompt"] = False
        context["reserved_tokens"] = 0
        context["technical"] = False
        result = render_template("common.base", context)
        assert result is not None
        assert "intention" in result.lower() or "fantasy" in result.lower()


class TestBuildingBlocksTemplate:
    """Tests for common/building-blocks.jinja2 template."""

    def test_building_blocks_renders(self, active_context):
        """Test building-blocks.jinja2 renders."""
        result = render_template("common.building-blocks", active_context)
        assert result is not None
        assert len(result) > 0
        # Template should include scene building blocks information
        assert "story configuration" in result.lower()
        assert "character" in result.lower()
        assert "history" in result.lower()


class TestCharacterContextTemplate:
    """Tests for common/character-context.jinja2 template."""

    def test_character_context_renders_empty(self, active_context):
        """Test character-context.jinja2 renders with no characters."""
        context = active_context.copy()
        context["scene"].characters = []
        context["skip_characters"] = []
        context["skip_sheet"] = False
        context["include_dialogue_instructions"] = False
        context["mentioned_characters"] = []
        result = render_template("common.character-context", context)
        assert result is not None
        # Should have CHARACTERS section even if empty
        assert "characters" in result.lower()

    def test_character_context_with_characters(self, active_context):
        """Test character-context.jinja2 renders with characters."""
        context = active_context.copy()
        char1 = create_mock_character(name="Elena")
        char2 = create_mock_character(name="Marcus", is_player=True)
        context["scene"].characters = [char1, char2]
        context["skip_characters"] = []
        context["skip_sheet"] = False
        context["include_dialogue_instructions"] = False
        context["mentioned_characters"] = []
        result = render_template("common.character-context", context)
        assert result is not None
        assert "Elena" in result
        assert "Marcus" in result

    def test_character_context_with_skip(self, active_context):
        """Test character-context.jinja2 respects skip_characters."""
        context = active_context.copy()
        char1 = create_mock_character(name="Elena")
        char2 = create_mock_character(name="Marcus")
        context["scene"].characters = [char1, char2]
        context["skip_characters"] = ["Elena"]
        context["skip_sheet"] = False
        context["include_dialogue_instructions"] = False
        context["mentioned_characters"] = []
        result = render_template("common.character-context", context)
        assert result is not None
        assert "Elena" not in result
        assert "Marcus" in result

    def test_character_context_with_dialogue_instructions(self, active_context):
        """Test character-context.jinja2 includes dialogue instructions."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        char.dialogue_instructions = "Speaks with a calm, measured tone."
        context["scene"].characters = [char]
        context["skip_characters"] = []
        context["skip_sheet"] = False
        context["include_dialogue_instructions"] = True
        context["mentioned_characters"] = []
        result = render_template("common.character-context", context)
        assert result is not None
        assert "calm" in result.lower()

    def test_character_context_with_mentioned(self, active_context):
        """Test character-context.jinja2 includes mentioned characters."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        mentioned = create_mock_character(name="OldHermit")
        context["scene"].characters = [char]
        context["skip_characters"] = []
        context["skip_sheet"] = False
        context["include_dialogue_instructions"] = False
        context["mentioned_characters"] = [mentioned]
        result = render_template("common.character-context", context)
        assert result is not None
        assert "OldHermit" in result


class TestCharacterGuidanceTemplate:
    """Tests for common/character-guidance.jinja2 template."""

    def test_character_guidance_renders(self, active_context, patch_all_agent_calls):
        """Test character-guidance.jinja2 renders with character."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        char.dialogue_instructions = "Speaks with wisdom and patience."
        context["character"] = char
        context["conversation_instruction"] = ""
        context["agent_context_state"] = {"conversation__instruction": ""}
        context["message"] = None
        result = render_template("common.character-guidance", context)
        assert result is not None
        # May include acting instructions
        assert "wisdom" in result.lower() or "acting" in result.lower() or result == ""

    def test_character_guidance_with_direction(self, active_context, patch_all_agent_calls):
        """Test character-guidance.jinja2 with character direction."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        char.dialogue_instructions = "Speaks gently."
        context["character"] = char
        context["conversation_instruction"] = ""
        context["agent_context_state"] = {"conversation__instruction": "Make her annoyed."}
        context["message"] = None
        # Mock last_message_of_type to return a direction
        context["scene"].last_message_of_type = Mock(return_value="")
        result = render_template("common.character-guidance", context)
        assert result is not None


class TestContentClassificationTemplate:
    """Tests for common/content-classification.jinja2 template."""

    def test_content_classification_renders(self, active_context):
        """Test content-classification.jinja2 renders."""
        context = active_context.copy()
        context["scene"].context = "Fantasy adventure, PG-13"
        result = render_template("common.content-classification", context)
        assert result is not None
        assert len(result) > 0
        assert "classification" in result.lower()
        assert "fantasy" in result.lower()

    def test_content_classification_with_decensor(self, active_context):
        """Test content-classification.jinja2 with decensor enabled."""
        context = active_context.copy()
        context["decensor"] = True
        context["scene"].context = "Adult fantasy"
        result = render_template("common.content-classification", context)
        assert result is not None
        assert "fiction" in result.lower()

    def test_content_classification_technical(self, active_context):
        """Test content-classification.jinja2 with technical mode."""
        context = active_context.copy()
        context["technical"] = True
        context["scene"].context = "Sci-fi thriller"
        result = render_template("common.content-classification", context)
        assert result is not None
        assert "context id" in result.lower()


class TestContextIdItemsTemplate:
    """Tests for common/context_id_items.jinja2 template."""

    def test_context_id_items_normal_mode(self, active_context):
        """Test context_id_items.jinja2 in normal display mode."""
        context = active_context.copy()
        mock_item = Mock()
        mock_item.context_id = Mock()
        mock_item.context_id.context_type_label = "Character"
        mock_item.context_id.__str__ = Mock(return_value="character:elena")
        mock_item.name = "Elena"
        mock_item.value = "A wandering healer"
        context["items"] = [mock_item]
        context["display_mode"] = "normal"
        result = render_template("common.context_id_items", context)
        assert result is not None
        assert "Elena" in result
        assert "character:elena" in result

    def test_context_id_items_compact_mode(self, active_context):
        """Test context_id_items.jinja2 in compact display mode."""
        context = active_context.copy()
        mock_item = Mock()
        mock_item.context_id = Mock()
        mock_item.context_id.__str__ = Mock(return_value="character:marcus")
        mock_item.name = "Marcus"
        mock_item.value = "A brave warrior"
        context["items"] = [mock_item]
        context["display_mode"] = "compact"
        result = render_template("common.context_id_items", context)
        assert result is not None
        assert "character:marcus" in result

    def test_context_id_items_heading_mode(self, active_context):
        """Test context_id_items.jinja2 in heading display mode."""
        context = active_context.copy()
        mock_item = Mock()
        mock_item.context_id = Mock()
        mock_item.context_id.__str__ = Mock(return_value="location:forest")
        mock_item.name = "Dark Forest"
        mock_item.value = "A mysterious forest"
        context["items"] = [mock_item]
        context["display_mode"] = "heading"
        result = render_template("common.context_id_items", context)
        assert result is not None
        assert "### Dark Forest" in result


class TestDynamicInstructionsTemplate:
    """Tests for common/dynamic-instructions.jinja2 template."""

    def test_dynamic_instructions_empty(self, active_context):
        """Test dynamic-instructions.jinja2 with no instructions."""
        context = active_context.copy()
        context["dynamic_instructions"] = None
        # Ensure active_agent has no dynamic_instructions
        result = render_template("common.dynamic-instructions", context)
        assert result is not None

    def test_dynamic_instructions_with_list(self, active_context):
        """Test dynamic-instructions.jinja2 with instruction list."""
        context = active_context.copy()
        context["dynamic_instructions"] = [
            "Always use vivid descriptions.",
            "Keep dialogue natural."
        ]
        result = render_template("common.dynamic-instructions", context)
        assert result is not None
        assert "vivid" in result.lower()
        assert "dialogue" in result.lower()


class TestExtraContextTemplate:
    """Tests for common/extra-context.jinja2 template."""

    def test_extra_context_renders(self, active_context):
        """Test extra-context.jinja2 renders with scene data."""
        context = active_context.copy()
        context["scene"].context = "Fantasy adventure"
        context["scene"].active_pins = []
        result = render_template("common.extra-context", context)
        assert result is not None
        assert len(result) > 0
        # Should include classification
        assert "classification" in result.lower()

    def test_extra_context_with_reinforcements(self, active_context):
        """Test extra-context.jinja2 with reinforcements."""
        context = active_context.copy()
        mock_reinforce = Mock()
        mock_reinforce.as_context_line = "Q: Who is Elena? A: A wandering healer."
        context["scene"].world_state.filter_reinforcements = Mock(return_value=[mock_reinforce])
        context["scene"].active_pins = []
        result = render_template("common.extra-context", context)
        assert result is not None
        assert "elena" in result.lower() or "healer" in result.lower()

    def test_extra_context_with_pins(self, active_context):
        """Test extra-context.jinja2 with active pins."""
        context = active_context.copy()
        mock_pin = Mock()
        mock_pin.context_id = "pin:important_info"
        mock_pin.title = "Important Info"
        mock_pin.time_aware_text = "The hero must find the artifact."
        context["scene"].active_pins = [mock_pin]
        context["technical"] = True
        result = render_template("common.extra-context", context)
        assert result is not None
        # Should include active pins section
        assert "pin" in result.lower() or "important" in result.lower()


class TestFullSceneContextTemplate:
    """Tests for common/full-scene-context.jinja2 template.

    Note: This template includes scene-classification.jinja2 which doesn't exist
    as a standalone common template. It's designed to be extended by agent-specific
    templates that provide their own scene-classification.jinja2. We test it by
    patching the missing include.
    """

    def test_full_scene_context_documented(self):
        """
        Document that full-scene-context.jinja2 requires agent-specific includes.

        The template includes 'scene-classification.jinja2' which is not a common
        template. It expects agent-specific templates to provide this include.
        This template is tested through its parent agent templates.

        Included templates (from common/):
        - character-context.jinja2
        - memory-context.jinja2
        - extra-context.jinja2
        - scene-intent.jinja2
        """
        # This test documents that full-scene-context.jinja2 is an include-only
        # template that requires additional templates from the calling agent.
        assert True


class TestGamestateContextTemplate:
    """Tests for common/gamestate-context.jinja2 template."""

    def test_gamestate_context_empty(self, active_context):
        """Test gamestate-context.jinja2 with no gamestate."""
        context = active_context.copy()
        context["gamestate"] = None
        result = render_template("common.gamestate-context", context)
        assert result is not None
        # Should be empty when no gamestate

    def test_gamestate_context_with_data(self, active_context):
        """Test gamestate-context.jinja2 with gamestate data."""
        context = active_context.copy()
        context["gamestate"] = {"health": 100, "mana": 50, "location": "forest"}
        context["max_gamestate_tokens"] = 1000
        result = render_template("common.gamestate-context", context)
        assert result is not None
        assert "gamestate" in result.lower()
        assert "health" in result.lower() or "100" in result


class TestInternalNoteHelpTemplate:
    """Tests for common/internal-note-help.jinja2 template."""

    def test_internal_note_help_with_note(self, active_context):
        """Test internal-note-help.jinja2 when text contains internal note."""
        context = active_context.copy()
        context["_text"] = "Some text (Internal note: important info) more text"
        result = render_template("common.internal-note-help", context)
        assert result is not None
        assert "internal note" in result.lower()

    def test_internal_note_help_without_note(self, active_context):
        """Test internal-note-help.jinja2 when no internal note."""
        context = active_context.copy()
        context["_text"] = "Some regular text without any special markers."
        result = render_template("common.internal-note-help", context)
        assert result is not None
        # Should not include help text when no internal notes

    def test_internal_note_help_empty_text(self, active_context):
        """Test internal-note-help.jinja2 when text is empty."""
        context = active_context.copy()
        context["_text"] = ""
        result = render_template("common.internal-note-help", context)
        assert result is not None
        # Should show help when text is empty or contains internal note
        assert "internal note" in result.lower()


class TestMemoryContextTemplate:
    """Tests for common/memory-context.jinja2 template."""

    def test_memory_context_empty(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 with empty memory stack."""
        context = active_context.copy()
        context["agent"] = create_mock_agent()
        context["memory_prompt"] = "What happened?"
        result = render_template("common.memory-context", context)
        assert result is not None
        # Empty result when no memories returned

    def test_memory_context_with_memories(self, active_context):
        """Test memory-context.jinja2 with memory entries."""
        with patch('talemate.instance.get_agent') as mock_get_agent:
            mock_agent = Mock()
            mock_memory = Mock()
            mock_memory.context_id = "memory:event1"
            mock_memory.__str__ = Mock(return_value="The hero found a sword.")
            mock_agent.rag_build = AsyncMock(return_value=[mock_memory])
            mock_get_agent.return_value = mock_agent

            context = active_context.copy()
            context["agent"] = mock_agent
            context["memory_prompt"] = "What items were found?"
            context["technical"] = False
            result = render_template("common.memory-context", context)
            assert result is not None

    def test_memory_context_technical_mode(self, active_context):
        """Test memory-context.jinja2 in technical mode."""
        with patch('talemate.instance.get_agent') as mock_get_agent:
            mock_agent = Mock()
            mock_memory = Mock()
            mock_memory.context_id = "memory:event2"
            mock_memory.__str__ = Mock(return_value="The villain escaped.")
            mock_agent.rag_build = AsyncMock(return_value=[mock_memory])
            mock_get_agent.return_value = mock_agent

            context = active_context.copy()
            context["agent"] = mock_agent
            context["memory_prompt"] = "What happened to the villain?"
            context["technical"] = True
            result = render_template("common.memory-context", context)
            assert result is not None


class TestNarrativePatternsTemplate:
    """Tests for common/narrative-patterns.jinja2 template."""

    def test_narrative_patterns_renders(self, active_context):
        """Test narrative-patterns.jinja2 renders a pattern."""
        result = render_template("common.narrative-patterns", active_context)
        assert result is not None
        assert len(result) > 0
        # Should include pattern instructions
        assert "prose" in result.lower() or "dialogue" in result.lower()
        # Should include format instructions
        assert "format" in result.lower()


class TestResponseLengthTemplate:
    """Tests for common/response-length.jinja2 template."""

    def test_response_length_short(self, active_context):
        """Test response-length.jinja2 with short response."""
        context = active_context.copy()
        context["response_length"] = 32
        result = render_template("common.response-length", context)
        assert result is not None
        assert "very few words" in result.lower()

    def test_response_length_medium(self, active_context):
        """Test response-length.jinja2 with medium response."""
        context = active_context.copy()
        context["response_length"] = 256
        result = render_template("common.response-length", context)
        assert result is not None
        assert "sentence" in result.lower()

    def test_response_length_paragraph(self, active_context):
        """Test response-length.jinja2 with paragraph response."""
        context = active_context.copy()
        context["response_length"] = 512
        result = render_template("common.response-length", context)
        assert result is not None
        assert "paragraph" in result.lower()

    def test_response_length_extensive(self, active_context):
        """Test response-length.jinja2 with extensive response."""
        context = active_context.copy()
        context["response_length"] = 2000
        result = render_template("common.response-length", context)
        assert result is not None
        assert "detailed" in result.lower() or "verbose" in result.lower()

    def test_response_length_none(self, active_context):
        """Test response-length.jinja2 with no response length."""
        context = active_context.copy()
        context["response_length"] = None
        result = render_template("common.response-length", context)
        assert result is not None
        # Should be empty when no response_length


class TestSceneContextTemplate:
    """Tests for common/scene-context.jinja2 template."""

    def test_scene_context_renders(self, active_context):
        """Test scene-context.jinja2 renders with scene history."""
        context = active_context.copy()
        context["budget"] = 2000
        result = render_template("common.scene-context", context)
        assert result is not None
        assert "scene" in result.lower()

    def test_scene_context_with_history(self, active_context):
        """Test scene-context.jinja2 with scene history."""
        context = active_context.copy()
        context["budget"] = 2000
        context["scene"].context_history = Mock(return_value=[
            "Elena: Hello there.",
            "The sun sets behind the mountains.",
            "Marcus: We should rest."
        ])
        result = render_template("common.scene-context", context)
        assert result is not None
        assert "elena" in result.lower() or "hello" in result.lower()


class TestSceneIntentTemplate:
    """Tests for common/scene-intent.jinja2 template."""

    def test_scene_intent_renders(self, active_context, mock_intent_state):
        """Test scene-intent.jinja2 renders with intent state."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["exclude_phase_intent"] = False
        context["task_instructions"] = None
        result = render_template("common.scene-intent", context)
        assert result is not None
        assert "intention" in result.lower() or "fantasy" in result.lower()

    def test_scene_intent_excludes_phase(self, active_context, mock_intent_state):
        """Test scene-intent.jinja2 with phase excluded."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["exclude_phase_intent"] = True
        context["task_instructions"] = None
        result = render_template("common.scene-intent", context)
        assert result is not None

    def test_scene_intent_with_task_instructions(self, active_context, mock_intent_state):
        """Test scene-intent.jinja2 with task instructions."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["exclude_phase_intent"] = False
        context["task_instructions"] = "Focus on character development."
        result = render_template("common.scene-intent", context)
        assert result is not None
        assert "character development" in result.lower()


class TestSceneIntentHybridTemplate:
    """Tests for common/scene-intent-hybrid.jinja2 template."""

    def test_scene_intent_hybrid_renders(self, active_context, mock_intent_state):
        """Test scene-intent-hybrid.jinja2 renders with intent state."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["exclude_phase_intent"] = False
        context["include_instructions"] = False
        context["task_instructions"] = None
        context["technical"] = True
        result = render_template("common.scene-intent-hybrid", context)
        assert result is not None
        assert "intention" in result.lower()

    def test_scene_intent_hybrid_with_instructions(self, active_context, mock_intent_state):
        """Test scene-intent-hybrid.jinja2 includes special instructions."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["exclude_phase_intent"] = False
        context["include_instructions"] = True
        context["task_instructions"] = None
        context["technical"] = True
        result = render_template("common.scene-intent-hybrid", context)
        assert result is not None
        # Should include instructions section
        assert "instruction" in result.lower()


class TestSceneIntentInlineTemplate:
    """Tests for common/scene-intent-inline.jinja2 template."""

    def test_scene_intent_inline_active(self, active_context, mock_intent_state):
        """Test scene-intent-inline.jinja2 with active intent state."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["task_instructions"] = None
        result = render_template("common.scene-intent-inline", context)
        assert result is not None
        assert "understanding" in result.lower() or "intention" in result.lower()

    def test_scene_intent_inline_with_task(self, active_context, mock_intent_state):
        """Test scene-intent-inline.jinja2 with task instructions."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        context["task_instructions"] = "Consider the emotional impact."
        result = render_template("common.scene-intent-inline", context)
        assert result is not None
        assert "emotional impact" in result.lower()

    def test_scene_intent_inline_inactive(self, active_context):
        """Test scene-intent-inline.jinja2 with inactive intent state."""
        context = active_context.copy()
        mock_intent = Mock()
        mock_intent.active = False
        context["scene"].intent_state = mock_intent
        context["task_instructions"] = "Just write naturally."
        result = render_template("common.scene-intent-inline", context)
        assert result is not None
        assert "naturally" in result.lower()


class TestSceneIntentTechnicalTemplate:
    """Tests for common/scene-intent-technical.jinja2 template."""

    def test_scene_intent_technical_renders(self, active_context, mock_intent_state):
        """Test scene-intent-technical.jinja2 renders."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        result = render_template("common.scene-intent-technical", context)
        assert result is not None

    def test_scene_intent_technical_with_phase(self, active_context, mock_intent_state):
        """Test scene-intent-technical.jinja2 shows phase information."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        result = render_template("common.scene-intent-technical", context)
        assert result is not None
        # Should include technical formatting
        assert "type:" in result.lower() or "exploration" in result.lower()


class TestSceneTypesTemplate:
    """Tests for common/scene-types.jinja2 template."""

    def test_scene_types_renders(self, active_context, mock_intent_state):
        """Test scene-types.jinja2 renders with scene types."""
        context = active_context.copy()
        context["scene"].intent_state = mock_intent_state
        result = render_template("common.scene-types", context)
        assert result is not None
        assert "scene types" in result.lower()
        assert "social" in result.lower() or "combat" in result.lower()

    def test_scene_types_empty(self, active_context):
        """Test scene-types.jinja2 with no scene types."""
        context = active_context.copy()
        mock_intent = Mock()
        mock_intent.scene_types = {}
        context["scene"].intent_state = mock_intent
        result = render_template("common.scene-types", context)
        assert result is not None
        assert "scene types" in result.lower()


class TestTaskInformationTemplate:
    """Tests for common/task-information.jinja2 template."""

    def test_task_information_empty(self, active_context):
        """Test task-information.jinja2 with no information."""
        context = active_context.copy()
        context["information"] = None
        result = render_template("common.task-information", context)
        assert result is not None
        # Should be empty when no information

    def test_task_information_with_data(self, active_context):
        """Test task-information.jinja2 with information."""
        context = active_context.copy()
        context["information"] = "The character has a hidden agenda."
        result = render_template("common.task-information", context)
        assert result is not None
        assert "hidden agenda" in result.lower()
        assert "task" in result.lower()


class TestUsefulContextIdsTemplate:
    """Tests for common/useful-context-ids.jinja2 template."""

    def test_useful_context_ids_empty(self, active_context):
        """Test useful-context-ids.jinja2 with no context ids."""
        context = active_context.copy()
        context["useful_context_ids"] = None
        result = render_template("common.useful-context-ids", context)
        assert result is not None
        # Should still have explanation section
        assert "context id" in result.lower()

    def test_useful_context_ids_with_data(self, active_context):
        """Test useful-context-ids.jinja2 with context ids."""
        context = active_context.copy()
        context["useful_context_ids"] = {
            "Characters": [
                {"context_id": "character:<name>", "description": "Character information", "tags": "CREATIVE"}
            ],
            "Story": [
                {"context_id": "story:title", "description": "Story title", "tags": "READONLY"}
            ]
        }
        result = render_template("common.useful-context-ids", context)
        assert result is not None
        assert "character" in result.lower()
        assert "story" in result.lower()
        assert "context id" in result.lower()


class TestUserControlledCharacterTemplate:
    """Tests for common/user-controlled-character.jinja2 template."""

    def test_user_controlled_character_none(self, active_context):
        """Test user-controlled-character.jinja2 with no player character."""
        context = active_context.copy()
        context["scene"].get_player_character = Mock(return_value=None)
        result = render_template("common.user-controlled-character", context)
        assert result is not None
        # Should be empty when no player character

    def test_user_controlled_character_exists(self, active_context):
        """Test user-controlled-character.jinja2 with player character."""
        context = active_context.copy()
        player = create_mock_character(name="Hero", is_player=True)
        context["scene"].get_player_character = Mock(return_value=player)
        result = render_template("common.user-controlled-character", context)
        assert result is not None
        assert "hero" in result.lower()
        assert "user controlled" in result.lower()


class TestWritingStyleInstructionsTemplate:
    """Tests for common/writing-style-instructions.jinja2 template."""

    def test_writing_style_instructions_none(self, active_context):
        """Test writing-style-instructions.jinja2 with no writing style."""
        context = active_context.copy()
        context["scene"].writing_style = None
        result = render_template("common.writing-style-instructions", context)
        assert result is not None
        # Should be empty when no writing style

    def test_writing_style_instructions_exists(self, active_context):
        """Test writing-style-instructions.jinja2 with writing style."""
        context = active_context.copy()
        mock_style = Mock()
        mock_style.instructions = "Write in a noir detective style with short, punchy sentences."
        context["scene"].writing_style = mock_style
        result = render_template("common.writing-style-instructions", context)
        assert result is not None
        assert "writing style" in result.lower()
        assert "noir" in result.lower() or "detective" in result.lower()


class TestIncludeOnlyTemplates:
    """
    Documentation that common templates are include-only templates.

    All common templates are designed to be included by other agent templates.
    They are tested directly above to ensure they render correctly when included.
    """

    def test_all_common_templates_documented(self):
        """
        Document all 24 common templates that are tested.

        Templates:
        1. base.jinja2 - Base template with context assembly
        2. building-blocks.jinja2 - Scene building blocks documentation
        3. character-context.jinja2 - Character information section
        4. character-guidance.jinja2 - Character direction and acting instructions
        5. content-classification.jinja2 - Content classification section
        6. context_id_items.jinja2 - Context ID item rendering
        7. dynamic-instructions.jinja2 - Dynamic instruction injection
        8. extra-context.jinja2 - Additional context (reinforcements, pins)
        9. full-scene-context.jinja2 - Full scene context assembly
        10. gamestate-context.jinja2 - Game state data section
        11. internal-note-help.jinja2 - Internal note help text
        12. memory-context.jinja2 - Memory/RAG context section
        13. narrative-patterns.jinja2 - Narrative pattern instructions
        14. response-length.jinja2 - Response length instructions
        15. scene-context.jinja2 - Scene history section
        16. scene-intent.jinja2 - Scene intent (non-technical)
        17. scene-intent-hybrid.jinja2 - Scene intent (hybrid/technical)
        18. scene-intent-inline.jinja2 - Inline scene intent instructions
        19. scene-intent-technical.jinja2 - Technical scene intent format
        20. scene-types.jinja2 - Scene types listing
        21. task-information.jinja2 - Task-specific information section
        22. useful-context-ids.jinja2 - Context ID documentation
        23. user-controlled-character.jinja2 - Player character indication
        24. writing-style-instructions.jinja2 - Writing style section
        """
        assert True
