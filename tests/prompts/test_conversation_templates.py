"""
Unit tests for conversation agent templates.

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
def conversation_context():
    """Base context for conversation templates."""
    return create_base_context()


@pytest.fixture
def active_context(conversation_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="conversation")
    scene_token = active_scene.set(conversation_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield conversation_context

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


def create_mock_talking_character(name="Elena"):
    """Create a mock talking character with dialogue-specific methods."""
    char = create_mock_character(name=name, is_player=False)
    char.dialogue_instructions = "Speaks calmly and with wisdom."
    char.random_dialogue_example = f"{name}: The forest provides all we need."
    char.random_dialogue_examples = Mock(return_value=["The forest provides all we need.", "Nature is beautiful."])
    return char


def create_dialogue_context(active_context, talking_character=None, main_character=None):
    """Create the context needed for dialogue templates."""
    context = active_context.copy()

    # Create characters
    if talking_character is None:
        talking_character = create_mock_talking_character("Elena")
    if main_character is None:
        main_character = create_mock_character(name="Marcus", is_player=True)

    context["talking_character"] = talking_character
    context["main_character"] = main_character
    context["characters"] = [talking_character, main_character]
    context["formatted_names"] = "Elena and Marcus"
    context["bot_token"] = "<|BOT|>"
    context["partial_message"] = ""
    context["actor_instructions_offset"] = 0
    context["actor_instructions"] = ""
    context["direct_instruction"] = ""
    context["task_instructions"] = ""
    context["agent_context_state"] = {
        "director__actor_guidance": "",
    }

    # Add scene methods and attributes
    context["scene"].count_messages = Mock(return_value=10)
    context["scene"].intent_state = create_mock_intent_state()
    context["scene"].intent_state.active = False
    context["scene"].writing_style = None

    return context


@pytest.fixture
def patch_all_agent_calls():
    """
    Extended patch for templates that use multiple agent calls.

    This patches rag_build and other agent calls used by conversation templates.
    """
    with patch('talemate.instance.get_agent') as mock_get_agent:
        # Create different mock agents for different agent types
        mock_conversation = Mock()
        mock_conversation.rag_build = AsyncMock(return_value=[])

        mock_director = Mock()
        mock_director.get_cached_character_guidance = AsyncMock(return_value="")

        mock_memory = Mock()
        mock_memory.query = AsyncMock(return_value="Mocked memory response")
        mock_memory.multi_query = AsyncMock(return_value={})

        mock_world_state = Mock()
        mock_world_state.analyze_text_and_answer_question = AsyncMock(return_value="yes")

        def get_agent_side_effect(agent_type):
            agents = {
                "conversation": mock_conversation,
                "director": mock_director,
                "memory": mock_memory,
                "world_state": mock_world_state,
            }
            return agents.get(agent_type, Mock())

        mock_get_agent.side_effect = get_agent_side_effect
        yield mock_get_agent


class TestConversationSystemTemplates:
    """Tests for conversation system templates."""

    def test_system_no_decensor_renders(self, active_context):
        """Test system-no-decensor.jinja2 renders."""
        result = render_template("conversation.system-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        assert "creative writing" in result.lower() or "storyteller" in result.lower()

    def test_system_renders(self, active_context):
        """Test system.jinja2 renders (includes system-no-decensor)."""
        result = render_template("conversation.system", active_context)
        assert result is not None
        assert len(result) > 0
        # system.jinja2 adds text about explicit language
        assert "explicit" in result.lower() or "language" in result.lower()


class TestConversationContextTemplates:
    """Tests for conversation context templates."""

    def test_extra_context_renders(self, active_context, patch_rag_build):
        """Test extra-context.jinja2 renders with talking_character."""
        context = active_context.copy()
        context["talking_character"] = create_mock_talking_character()
        result = render_template("conversation.extra-context", context)
        assert result is not None
        assert len(result) > 0
        # Template includes content classification section
        assert "classification" in result.lower() or "context" in result.lower()

    def test_extra_context_with_reinforcements(self, active_context, patch_rag_build):
        """Test extra-context.jinja2 with reinforcements."""
        context = active_context.copy()
        context["talking_character"] = create_mock_talking_character("Elena")

        # Mock reinforcements
        mock_reinforce = Mock()
        mock_reinforce.as_context_line = "Elena always speaks in riddles."
        context["scene"].world_state.filter_reinforcements = Mock(return_value=[mock_reinforce])

        result = render_template("conversation.extra-context", context)
        assert result is not None
        assert len(result) > 0
        assert "riddles" in result.lower()

    def test_scene_context_renders(self, active_context, patch_rag_build):
        """Test scene-context.jinja2 renders with budget."""
        context = active_context.copy()
        context["budget"] = 2000
        result = render_template("conversation.scene-context", context)
        assert result is not None
        assert len(result) > 0
        # Template should include SCENE section marker
        assert "scene" in result.lower()

    def test_scene_context_with_custom_budget(self, active_context, patch_rag_build):
        """Test scene-context.jinja2 with custom token budget."""
        context = active_context.copy()
        context["budget"] = 500
        result = render_template("conversation.scene-context", context)
        assert result is not None
        assert len(result) > 0

    def test_memory_context_renders(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 renders with memory prompt."""
        context = active_context.copy()
        context["memory_prompt"] = "What happened recently in the conversation?"
        result = render_template("conversation.memory-context", context)
        # Template relies on agent_action which returns empty list via patch
        assert result is not None

    def test_memory_context_with_list_prompt(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 with list prompt."""
        context = active_context.copy()
        context["memory_prompt"] = ["Recent events", "Character interactions"]
        result = render_template("conversation.memory-context", context)
        assert result is not None


class TestConversationUtilityTemplates:
    """Tests for conversation utility templates."""

    def test_regenerate_context_renders(self, active_context):
        """Test regenerate-context.jinja2 renders without regeneration context."""
        context = active_context.copy()
        context["character"] = create_mock_character()
        result = render_template("conversation.regenerate-context", context)
        # Should render without error (empty when no regeneration_context)
        assert result is not None

    def test_regenerate_context_with_replace_method(self, active_context):
        """Test regenerate-context.jinja2 with replace regeneration method."""
        context = active_context.copy()
        context["character"] = create_mock_character()
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Rewrite with more emotion."
        context["regeneration_context"].method = "replace"
        result = render_template("conversation.regenerate-context", context)
        assert result is not None
        assert len(result) > 0
        # Should include the replacement direction
        assert "emotion" in result.lower()

    def test_regenerate_context_with_edit_method(self, active_context):
        """Test regenerate-context.jinja2 with edit regeneration method."""
        context = active_context.copy()
        context["character"] = create_mock_character()
        context["direction"] = "Original direction for the character."
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Add more suspense."
        context["regeneration_context"].method = "edit"
        context["regeneration_context"].message = "Elena looked at the door nervously."
        result = render_template("conversation.regenerate-context", context)
        assert result is not None
        assert len(result) > 0
        # Should include the first draft
        assert "door" in result.lower() or "draft" in result.lower()
        # Should include editorial instructions
        assert "suspense" in result.lower()

    def test_edit_renders(self, active_context):
        """Test edit.jinja2 renders with required context."""
        context = active_context.copy()
        context["talking_character"] = create_mock_talking_character("Elena")
        context["next_dialogue_line"] = "Elena: Hello there."
        result = render_template("conversation.edit", context)
        assert result is not None
        assert len(result) > 0
        # Template should include task about editing dialogue
        assert "editorialize" in result.lower() or "edit" in result.lower()
        # Should reference the dialogue line
        assert "hello" in result.lower()

    def test_edit_with_long_dialogue(self, active_context):
        """Test edit.jinja2 with longer dialogue."""
        context = active_context.copy()
        context["talking_character"] = create_mock_talking_character("Marcus")
        context["next_dialogue_line"] = "Marcus: I've been thinking about our journey through the forest."
        result = render_template("conversation.edit", context)
        assert result is not None
        assert len(result) > 0
        assert "journey" in result.lower() or "forest" in result.lower()


class TestConversationDialogueBaseTemplate:
    """Tests for the base dialogue.jinja2 template."""

    def test_dialogue_base_renders(self, active_context, patch_all_agent_calls):
        """Test dialogue.jinja2 renders with full context."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue", context)
        assert result is not None
        assert len(result) > 0
        # Base template should include characters section
        assert "characters" in result.lower()

    def test_dialogue_with_director_guidance(self, active_context, patch_all_agent_calls):
        """Test dialogue.jinja2 with director guidance."""
        context = create_dialogue_context(active_context)
        context["agent_context_state"]["director__actor_guidance"] = "Be more dramatic"
        result = render_template("conversation.dialogue", context)
        assert result is not None
        assert len(result) > 0
        # Should include the guidance
        assert "dramatic" in result.lower()

    def test_dialogue_with_direct_instruction(self, active_context, patch_all_agent_calls):
        """Test dialogue.jinja2 with direct instruction."""
        context = create_dialogue_context(active_context)
        context["direct_instruction"] = "Have the character reveal a secret."
        result = render_template("conversation.dialogue", context)
        assert result is not None
        assert len(result) > 0
        # Should include the instruction
        assert "secret" in result.lower()

    def test_dialogue_with_scene_intent(self, active_context, patch_all_agent_calls):
        """Test dialogue.jinja2 with active scene intent."""
        context = create_dialogue_context(active_context)
        context["scene"].intent_state.active = True
        result = render_template("conversation.dialogue", context)
        assert result is not None
        assert len(result) > 0

    def test_dialogue_with_writing_style(self, active_context, patch_all_agent_calls):
        """Test dialogue.jinja2 with writing style."""
        context = create_dialogue_context(active_context)
        context["scene"].writing_style = Mock()
        context["scene"].writing_style.instructions = "Write in a noir style with short, punchy sentences."
        result = render_template("conversation.dialogue", context)
        assert result is not None
        assert len(result) > 0


class TestConversationDialogueChatTemplate:
    """Tests for dialogue-chat.jinja2 template."""

    def test_dialogue_chat_renders(self, active_context, patch_all_agent_calls):
        """Test dialogue-chat.jinja2 renders."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-chat", context)
        assert result is not None
        assert len(result) > 0
        # Chat template should include roleplaying session text
        assert "roleplaying" in result.lower() or "dialogue" in result.lower()

    def test_dialogue_chat_with_decensor(self, active_context, patch_all_agent_calls):
        """Test dialogue-chat.jinja2 with decensor enabled."""
        context = create_dialogue_context(active_context)
        context["decensor"] = True
        result = render_template("conversation.dialogue-chat", context)
        assert result is not None
        assert len(result) > 0
        # Should include decensor text
        assert "fiction" in result.lower()

    def test_dialogue_chat_with_dialogue_examples(self, active_context, patch_all_agent_calls):
        """Test dialogue-chat.jinja2 with dialogue examples from character."""
        context = create_dialogue_context(active_context)
        context["talking_character"].random_dialogue_example = "Elena: The stars guide my path."
        result = render_template("conversation.dialogue-chat", context)
        assert result is not None
        assert len(result) > 0

    def test_dialogue_chat_early_conversation(self, active_context, patch_all_agent_calls):
        """Test dialogue-chat.jinja2 in early conversation (few messages)."""
        context = create_dialogue_context(active_context)
        context["scene"].count_messages = Mock(return_value=3)
        result = render_template("conversation.dialogue-chat", context)
        assert result is not None
        assert len(result) > 0

    def test_dialogue_chat_with_partial_message(self, active_context, patch_all_agent_calls):
        """Test dialogue-chat.jinja2 with partial message for continuation."""
        context = create_dialogue_context(active_context)
        context["partial_message"] = '"I was just thinking about'
        result = render_template("conversation.dialogue-chat", context)
        assert result is not None
        assert len(result) > 0
        # Should include the partial message in response scaffolding
        assert "thinking about" in result.lower()


class TestConversationDialogueMovieScriptTemplate:
    """Tests for dialogue-movie_script.jinja2 template."""

    def test_dialogue_movie_script_renders(self, active_context, patch_all_agent_calls):
        """Test dialogue-movie_script.jinja2 renders."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-movie_script", context)
        assert result is not None
        assert len(result) > 0
        # Movie script template should mention screenplay format
        assert "screenplay" in result.lower() or "scene" in result.lower()

    def test_dialogue_movie_script_with_decensor(self, active_context, patch_all_agent_calls):
        """Test dialogue-movie_script.jinja2 with decensor enabled."""
        context = create_dialogue_context(active_context)
        context["decensor"] = True
        result = render_template("conversation.dialogue-movie_script", context)
        assert result is not None
        assert len(result) > 0
        # Should include fiction/consent text
        assert "fiction" in result.lower() or "consent" in result.lower()

    def test_dialogue_movie_script_format(self, active_context, patch_all_agent_calls):
        """Test dialogue-movie_script.jinja2 includes format instructions."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-movie_script", context)
        assert result is not None
        assert len(result) > 0
        # Should include format instructions about uppercase names and END-OF-LINE
        assert "end-of-line" in result.lower()

    def test_dialogue_movie_script_with_partial(self, active_context, patch_all_agent_calls):
        """Test dialogue-movie_script.jinja2 with partial message."""
        context = create_dialogue_context(active_context)
        context["partial_message"] = "looking out the window"
        result = render_template("conversation.dialogue-movie_script", context)
        assert result is not None
        assert len(result) > 0
        # Should include the partial message
        assert "window" in result.lower()

    def test_dialogue_movie_script_character_uppercase(self, active_context, patch_all_agent_calls):
        """Test dialogue-movie_script.jinja2 uses uppercase character name."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-movie_script", context)
        assert result is not None
        # Response scaffolding should have character name in uppercase
        assert "ELENA" in result


class TestConversationDialogueNarrativeTemplate:
    """Tests for dialogue-narrative.jinja2 template."""

    def test_dialogue_narrative_renders(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 renders."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Narrative template should mention novel-style
        assert "novel" in result.lower() or "narrative" in result.lower()

    def test_dialogue_narrative_writing_guidelines(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 includes writing guidelines."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should include critical guidelines about character focus
        assert "critical" in result.lower()
        # Should mention avoiding purple prose
        assert "purple prose" in result.lower() or "concise" in result.lower()

    def test_dialogue_narrative_with_character_sheet(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 references character sheet."""
        context = create_dialogue_context(active_context)
        context["talking_character"].sheet = "name: Elena\ngender: female\ngoals: Find the ancient artifact"
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should mention character goals/motivations
        assert "goal" in result.lower() or "motivation" in result.lower()

    def test_dialogue_narrative_tense_consistency(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 emphasizes tense consistency."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should include tense consistency warning
        assert "tense" in result.lower()

    def test_dialogue_narrative_perspective_warning(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 includes perspective warning."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should include perspective warning
        assert "perspective" in result.lower()

    def test_dialogue_narrative_repetition_warning(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 warns about repetition."""
        context = create_dialogue_context(active_context)
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should include repetition avoidance
        assert "repetition" in result.lower() or "repeat" in result.lower()

    def test_dialogue_narrative_with_partial(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 with partial message."""
        context = create_dialogue_context(active_context)
        context["partial_message"] = "The morning sun cast long shadows"
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should include the partial message in scaffolding
        assert "morning sun" in result.lower()

    def test_dialogue_narrative_no_dialogue_examples(self, active_context, patch_all_agent_calls):
        """Test dialogue-narrative.jinja2 without dialogue examples uses narrative patterns."""
        context = create_dialogue_context(active_context)
        context["talking_character"].random_dialogue_examples = Mock(return_value=[])
        result = render_template("conversation.dialogue-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should include narrative patterns as fallback
        # (narrative-patterns.jinja2 has response structure patterns)
        assert "structure" in result.lower() or "prose" in result.lower()
