"""
Unit tests for director agent templates.

Tests template rendering without requiring an LLM connection.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from .helpers import (
    create_mock_agent,
    create_mock_character,
    create_mock_scene,
    create_base_context,
    render_template,
    assert_template_renders,
)


@pytest.fixture
def director_context():
    """Base context for director templates."""
    return create_base_context()


@pytest.fixture
def active_context(director_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="director")
    scene_token = active_scene.set(director_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield director_context

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


@pytest.fixture
def mock_focal():
    """Create a mock Focal instance for templates that use focal callbacks."""
    focal = Mock()
    focal.render_instructions = Mock(return_value="Mock focal instructions")
    focal.state = Mock()
    focal.state.schema_format = "json"

    # Mock callbacks
    focal.callbacks = Mock()
    focal.callbacks.act = Mock()
    focal.callbacks.act.render = Mock(return_value="act callback rendered")
    focal.callbacks.narrate_scene = Mock()
    focal.callbacks.narrate_scene.render = Mock(return_value="narrate_scene callback rendered")
    focal.callbacks.progress_story = Mock()
    focal.callbacks.progress_story.render = Mock(return_value="progress_story callback rendered")
    focal.callbacks.set_scene_intention = Mock()
    focal.callbacks.set_scene_intention.render = Mock(return_value="set_scene_intention callback rendered")
    focal.callbacks.do_nothing = Mock()
    focal.callbacks.do_nothing.render = Mock(return_value="do_nothing callback rendered")
    focal.callbacks.generate_scene_type = Mock()
    focal.callbacks.generate_scene_type.render = Mock(return_value="generate_scene_type callback rendered")
    focal.callbacks.add_from_template = Mock()
    focal.callbacks.add_from_template.render = Mock(return_value="add_from_template callback rendered")
    focal.callbacks.assign_voice = Mock()
    focal.callbacks.assign_voice.render = Mock(return_value="assign_voice callback rendered")
    focal.callbacks.add_detected_character = Mock()
    focal.callbacks.add_detected_character.render = Mock(return_value="add_detected_character callback rendered")

    return focal


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
def mock_budgets():
    """Create a mock budgets object for templates that use token budgets."""
    budgets = Mock()
    budgets.scene_context = 2000
    budgets.direction_history = 1000
    budgets.director_chat = 1000
    budgets.max_gamestate_tokens = 500
    budgets.set_reserved = Mock(return_value=None)
    return budgets


class TestDirectorSystemTemplates:
    """Tests for director system templates."""

    def test_system_no_decensor_renders(self, active_context):
        """Test system-no-decensor.jinja2 renders."""
        result = render_template("director.system-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        assert "narrative" in result.lower() or "guide" in result.lower()

    def test_system_renders(self, active_context):
        """Test system.jinja2 renders (includes system-no-decensor)."""
        result = render_template("director.system", active_context)
        assert result is not None
        assert len(result) > 0
        # system.jinja2 adds text about explicit content
        assert "explicit" in result.lower() or "content" in result.lower()


class TestDirectorContextTemplates:
    """Tests for director context templates."""

    def test_extra_context_renders(self, active_context):
        """Test extra-context.jinja2 renders with scene data."""
        result = render_template("director.extra-context", active_context)
        assert result is not None
        assert len(result) > 0
        # Template includes content classification section
        assert "context" in result.lower()

    def test_scene_context_renders(self, active_context, patch_rag_build):
        """Test scene-context.jinja2 renders with scene history."""
        context = active_context.copy()
        context["budget"] = 2000
        result = render_template("director.scene-context", context)
        assert result is not None
        assert len(result) > 0
        # Template should include SCENE section marker
        assert "scene" in result.lower()

    def test_scene_context_chat_renders(self, active_context, patch_rag_build):
        """Test scene-context-chat.jinja2 renders."""
        context = active_context.copy()
        context["budget"] = 2000
        # Add get_intro method to scene
        context["scene"].get_intro = Mock(return_value="Welcome to the story.")
        result = render_template("director.scene-context-chat", context)
        assert result is not None
        assert len(result) > 0
        assert "scene" in result.lower()

    def test_memory_context_renders(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 renders with memory prompt."""
        context = active_context.copy()
        context["memory_prompt"] = ["What happened recently?"]
        result = render_template("director.memory-context", context)
        # Template relies on agent_action which returns empty list via patch
        assert result is not None


class TestDirectorGuideNarrationTemplates:
    """Tests for director guide-narration templates."""

    def test_guide_narration_renders(self, active_context, patch_rag_build):
        """Test guide-narration.jinja2 renders."""
        context = active_context.copy()
        context["agent_context_state"] = {
            "narrator__narrative_direction": "",
            "narrator__query": "",
            "narrator__visual_narration": False,
            "narrator__sensory_narration": False,
            "narrator__time_narration": False,
            "narrator__character": None,
            "narrator__writing_style": False,
        }
        context["analysis"] = "The scene is tense and dramatic."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        # Add intent_state to scene
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].writing_style = None
        result = render_template("director.guide-narration", context)
        assert result is not None
        assert len(result) > 0

    def test_guide_narration_with_visual_renders(self, active_context, patch_rag_build):
        """Test guide-narration.jinja2 with visual narration mode."""
        context = active_context.copy()
        context["agent_context_state"] = {
            "narrator__narrative_direction": "",
            "narrator__query": "",
            "narrator__visual_narration": True,
            "narrator__sensory_narration": False,
            "narrator__time_narration": False,
            "narrator__character": None,
            "narrator__writing_style": False,
        }
        context["analysis"] = "The scene is tense and dramatic."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].writing_style = None
        result = render_template("director.guide-narration", context)
        assert result is not None
        assert len(result) > 0
        assert "visual" in result.lower()

    def test_guide_narration_with_sensory_renders(self, active_context, patch_rag_build):
        """Test guide-narration.jinja2 with sensory narration mode."""
        context = active_context.copy()
        context["agent_context_state"] = {
            "narrator__narrative_direction": "",
            "narrator__query": "",
            "narrator__visual_narration": False,
            "narrator__sensory_narration": True,
            "narrator__time_narration": False,
            "narrator__character": None,
            "narrator__writing_style": False,
        }
        context["analysis"] = "The scene is tense and dramatic."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].writing_style = None
        result = render_template("director.guide-narration", context)
        assert result is not None
        assert len(result) > 0
        assert "sensory" in result.lower()

    def test_guide_narration_with_time_renders(self, active_context, patch_rag_build):
        """Test guide-narration.jinja2 with time narration mode."""
        context = active_context.copy()
        context["agent_context_state"] = {
            "narrator__narrative_direction": "",
            "narrator__query": "",
            "narrator__visual_narration": False,
            "narrator__sensory_narration": False,
            "narrator__time_narration": True,
            "narrator__character": None,
            "narrator__writing_style": False,
        }
        context["analysis"] = "The scene is tense and dramatic."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].writing_style = None
        # Add time message
        context["scene"].last_message_of_type = Mock(return_value="Two hours later...")
        result = render_template("director.guide-narration", context)
        assert result is not None
        assert len(result) > 0

    def test_guide_narration_with_query_renders(self, active_context, patch_rag_build):
        """Test guide-narration.jinja2 with query mode."""
        context = active_context.copy()
        context["agent_context_state"] = {
            "narrator__narrative_direction": "",
            "narrator__query": "What is the hero doing?",
            "narrator__visual_narration": False,
            "narrator__sensory_narration": False,
            "narrator__time_narration": False,
            "narrator__character": None,
            "narrator__writing_style": False,
        }
        context["analysis"] = "The scene is tense and dramatic."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].writing_style = None
        result = render_template("director.guide-narration", context)
        assert result is not None
        assert len(result) > 0

    def test_guide_narration_with_visual_character_renders(self, active_context, patch_rag_build):
        """Test guide-narration.jinja2 with visual character narration mode."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["agent_context_state"] = {
            "narrator__narrative_direction": "",
            "narrator__query": "",
            "narrator__visual_narration": True,
            "narrator__sensory_narration": False,
            "narrator__time_narration": False,
            "narrator__character": char,
            "narrator__writing_style": False,
        }
        context["analysis"] = "The scene is tense and dramatic."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = True
        context["scene"].writing_style = None
        result = render_template("director.guide-narration", context)
        assert result is not None
        assert len(result) > 0
        assert "Marcus" in result


class TestDirectorGuideConversationTemplates:
    """Tests for director guide-conversation templates."""

    def test_guide_conversation_renders(self, active_context, patch_rag_build):
        """Test guide-conversation.jinja2 renders."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["agent_context_state"] = {
            "conversation__instruction": "",
        }
        context["analysis"] = "The conversation is getting tense."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        context["regeneration_context"] = None
        context["conversation_instruction"] = "Talk to the traveler."
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].writing_style = None
        context["scene"].count_character_messages_since_director = Mock(return_value=0)
        result = render_template("director.guide-conversation", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result

    def test_guide_conversation_with_regeneration_context(self, active_context, patch_rag_build):
        """Test guide-conversation.jinja2 with regeneration context."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["agent_context_state"] = {
            "conversation__instruction": "",
        }
        context["analysis"] = "The conversation is getting tense."
        context["response_length"] = 200
        context["bot_token"] = "<|BOT|>"
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Make it more dramatic."
        context["regeneration_context"].method = "edit"
        context["regeneration_context"].message = "Hello there."
        context["conversation_instruction"] = "Talk to the traveler."
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].writing_style = None
        context["scene"].count_character_messages_since_director = Mock(return_value=0)
        result = render_template("director.guide-conversation", context)
        assert result is not None
        assert len(result) > 0


class TestDirectorChatTemplates:
    """Tests for director chat templates."""

    def test_chat_renders(self, active_context, patch_rag_build, mock_budgets):
        """Test chat.jinja2 renders."""
        context = active_context.copy()
        context["budgets"] = mock_budgets
        context["history"] = [
            Mock(type="user", source="user", message="Hello, Director!"),
        ]
        context["available_functions"] = []
        context["chat_enable_analysis"] = False
        context["mode"] = "normal"
        context["custom_instructions"] = ""
        context["persona_name"] = None
        context["scene"].intent_state = create_mock_intent_state()
        context["scene"].get_player_character = Mock(return_value=None)
        context["scene"].get_intro = Mock(return_value="Welcome to the story.")
        # Add director_history_trim function
        context["director_history_trim"] = Mock(return_value=context["history"])
        result = render_template("director.chat", context)
        assert result is not None
        assert len(result) > 0
        assert "director" in result.lower()

    def test_chat_with_analysis_renders(self, active_context, patch_rag_build, mock_budgets):
        """Test chat.jinja2 with analysis enabled."""
        context = active_context.copy()
        context["budgets"] = mock_budgets
        context["history"] = [
            Mock(type="user", source="user", message="What happened in the story?"),
        ]
        context["available_functions"] = []
        context["chat_enable_analysis"] = True
        context["mode"] = "decisive"
        context["custom_instructions"] = "Be helpful."
        context["persona_name"] = "Guide"
        context["scene"].intent_state = create_mock_intent_state()
        context["scene"].get_player_character = Mock(return_value=None)
        context["scene"].get_intro = Mock(return_value="Welcome to the story.")
        context["director_history_trim"] = Mock(return_value=context["history"])
        result = render_template("director.chat", context)
        assert result is not None
        assert len(result) > 0
        assert "analysis" in result.lower()

    def test_chat_execute_actions_renders(self, active_context, mock_focal):
        """Test chat-execute-actions.jinja2 renders."""
        context = active_context.copy()
        context["focal"] = mock_focal
        context["has_character_callback"] = False
        context["history"] = [
            Mock(type="user", source="user", message="Update the character."),
        ]
        context["selections"] = [
            {"name": "update_character", "instructions": "Update John's mood."},
        ]
        context["callbacks_unique"] = []
        context["ordered_instructions"] = {}
        context["ordered_examples"] = {}
        context["ordered_argument_usage"] = {}
        result = render_template("director.chat-execute-actions", context)
        assert result is not None
        assert len(result) > 0


class TestDirectorSceneDirectionTemplates:
    """Tests for director scene direction templates."""

    def test_scene_direction_renders(self, active_context, patch_rag_build, mock_budgets):
        """Test scene-direction.jinja2 renders."""
        context = active_context.copy()
        context["budgets"] = mock_budgets
        context["history"] = []
        context["direction_history_trim"] = Mock(return_value=[])
        context["available_functions"] = []
        context["direction_enable_analysis"] = False
        context["maintain_turn_balance"] = False
        context["turn_balance"] = Mock(total_messages_analyzed=0)
        context["user_agency"] = Mock(should_remind=False)
        context["scene"].intent_state = create_mock_intent_state()
        context["scene"].get_player_character = Mock(return_value=None)
        context["scene"].get_intro = Mock(return_value="Welcome to the story.")
        context["scene"].game_state = Mock()
        context["scene"].game_state.state = {}
        result = render_template("director.scene-direction", context)
        assert result is not None
        assert len(result) > 0
        assert "director" in result.lower() or "scene" in result.lower()

    def test_scene_direction_with_history_renders(self, active_context, patch_rag_build, mock_budgets):
        """Test scene-direction.jinja2 with direction history."""
        context = active_context.copy()
        context["budgets"] = mock_budgets
        context["history"] = [
            Mock(type="action_result", name="direct_scene", instructions="Move the story forward.", result={"success": True}),
        ]
        context["direction_history_trim"] = Mock(return_value=context["history"])
        context["available_functions"] = []
        context["direction_enable_analysis"] = True
        context["maintain_turn_balance"] = True
        context["turn_balance"] = Mock(
            total_messages_analyzed=5,
            narrator_message_count=2,
            narrator_percentage=40.0,
            narrator_overused=False,
            narrator_neglected=False,
            character_message_counts={"Elena": 3},
            character_percentages={"Elena": 60.0},
            neglected_characters=[],
        )
        context["user_agency"] = Mock(should_remind=False)
        context["scene"].intent_state = create_mock_intent_state()
        context["scene"].get_player_character = Mock(return_value=None)
        context["scene"].get_intro = Mock(return_value="Welcome to the story.")
        context["scene"].game_state = Mock()
        context["scene"].game_state.state = {}
        result = render_template("director.scene-direction", context)
        assert result is not None
        assert len(result) > 0

    def test_query_scene_direction_renders(self, active_context):
        """Test query-scene-direction.jinja2 renders."""
        context = active_context.copy()
        context["scene_direction"] = [
            {"action": "direct_scene", "instructions": "Move the story forward."},
        ]
        context["query"] = "What actions have you taken?"
        result = render_template("director.query-scene-direction", context)
        assert result is not None
        assert len(result) > 0
        assert "query" in result.lower() or "actions" in result.lower()


class TestDirectorAutodirectTemplates:
    """Tests for director autodirect templates."""

    def test_autodirect_evaluate_renders(self, active_context, patch_rag_build):
        """Test autodirect-evaluate.jinja2 renders."""
        context = active_context.copy()
        context["candidates"] = [create_mock_character(name="Elena")]
        context["candidate_names"] = ["Elena"]
        context["narrator_available"] = True
        context["bot_token"] = "<|BOT|>"
        context["scene"].intent_state = Mock()
        context["scene"].intent_state.active = False
        context["scene"].agent_state = Mock()
        context["scene"].agent_state.summarizer = None
        result = render_template("director.autodirect-evaluate", context)
        assert result is not None
        assert len(result) > 0

    def test_autodirect_execute_renders(self, active_context, patch_rag_build, mock_focal):
        """Test autodirect-execute.jinja2 renders."""
        context = active_context.copy()
        context["candidates"] = [create_mock_character(name="Elena")]
        context["candidate_names"] = "Elena"  # String, not list
        context["analysis"] = "Elena should respond to the question."
        context["focal"] = mock_focal
        context["bot_token"] = "<|BOT|>"
        context["scene"].intent_state = create_mock_intent_state()
        context["scene"].agent_state = Mock()
        context["scene"].agent_state.summarizer = None
        result = render_template("director.autodirect-execute", context)
        assert result is not None
        assert len(result) > 0


class TestDirectorDetermineActionTemplates:
    """Tests for director action determination templates."""

    def test_direct_determine_next_action_renders(self, active_context, patch_rag_build, mock_focal):
        """Test direct-determine-next-action.jinja2 renders."""
        context = active_context.copy()
        context["candidates"] = [create_mock_character(name="Elena")]
        context["candidate_names"] = "Elena"  # String, not list
        context["focal"] = mock_focal
        context["scene"].intent_state = create_mock_intent_state()
        context["scene"].agent_state = Mock()
        context["scene"].agent_state.summarizer = None
        result = render_template("director.direct-determine-next-action", context)
        assert result is not None
        assert len(result) > 0

    def test_direct_determine_scene_intent_renders(self, active_context, patch_rag_build, mock_focal, mock_intent_state):
        """Test direct-determine-scene-intent.jinja2 renders."""
        context = active_context.copy()
        context["scene_type_ids"] = "social, combat, passive_narration"
        context["require"] = False
        context["focal"] = mock_focal
        context["scene"].intent_state = mock_intent_state
        context["scene"].agent_state = Mock()
        context["scene"].agent_state.summarizer = None
        result = render_template("director.direct-determine-scene-intent", context)
        assert result is not None
        assert len(result) > 0


class TestDirectorGenerateTemplates:
    """Tests for director generation templates."""

    def test_generate_choices_renders(self, active_context):
        """Test generate-choices.jinja2 renders."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Marcus")
        context["num_choices"] = 3
        context["instructions"] = ""
        result = render_template("director.generate-choices", context)
        assert result is not None
        assert len(result) > 0
        assert "Marcus" in result

    def test_generate_scene_types_renders(self, active_context, patch_rag_build, mock_focal, mock_intent_state):
        """Test generate-scene-types.jinja2 renders."""
        context = active_context.copy()
        context["focal"] = mock_focal
        context["instructions"] = "Generate scene types for a fantasy adventure."
        context["scene_type_templates"] = None
        context["scene"].intent_state = mock_intent_state
        context["scene"].agent_state = Mock()
        context["scene"].agent_state.summarizer = None
        result = render_template("director.generate-scene-types", context)
        assert result is not None
        assert len(result) > 0


class TestDirectorCharacterManagementTemplates:
    """Tests for director character management templates."""

    def test_cm_assign_voice_renders(self, active_context, patch_rag_build, mock_focal):
        """Test cm-assign-voice.jinja2 renders."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["voices"] = [
            Mock(id="kokoro:af_heart", label="Female Voice", tags=["female", "young"], used=False),
            Mock(id="elevenlabs:abc123", label="Male Voice", tags=["male", "adult"], used=True),
        ]
        context["focal"] = mock_focal
        context["narrator_voice"] = None
        context["scene"].agent_state = Mock()
        context["scene"].agent_state.summarizer = None
        result = render_template("director.cm-assign-voice", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result

    def test_cm_detect_characters_from_texts_renders(self, active_context, mock_focal):
        """Test cm-detect-characters-from-texts.jinja2 renders."""
        context = active_context.copy()
        context["texts"] = [
            "Alice said: 'Hello there!'",
            "Bob replied: 'Nice to meet you.'",
        ]
        context["focal"] = mock_focal
        context["already_detected_names"] = []
        result = render_template("director.cm-detect-characters-from-texts", context)
        assert result is not None
        assert len(result) > 0
        assert "Alice" in result or "detect" in result.lower()


class TestDirectorImageGenerationTemplates:
    """Tests for director image generation templates."""

    def test_action_create_image_renders(self, active_context):
        """Test action-create-image.jinja2 renders."""
        context = active_context.copy()
        context["instructions"] = "Create an image of the forest clearing."
        result = render_template("director.action-create-image", context)
        assert result is not None
        assert len(result) > 0
        assert "image" in result.lower()

    def test_instruct_avatar_generation_renders(self, active_context):
        """Test instruct-avatar-generation.jinja2 renders."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["assets"] = [
            Mock(id="avatar_001", meta=Mock(name="Elena Portrait", tags=["portrait", "female"])),
        ]
        result = render_template("director.instruct-avatar-generation", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result


class TestDirectorRegenerateContextTemplates:
    """Tests for director regenerate context templates."""

    def test_guide_narrative_regenerate_context_renders(self, active_context):
        """Test guide-narrative-regenerate-context.jinja2 renders with replace method."""
        context = active_context.copy()
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Make it more dramatic."
        context["regeneration_context"].method = "replace"
        context["regeneration_context"].message = ""
        context["original_instructions"] = ""
        result = render_template("director.guide-narrative-regenerate-context", context)
        assert result is not None
        assert len(result) > 0
        assert "dramatic" in result.lower()

    def test_guide_narrative_regenerate_context_edit_renders(self, active_context):
        """Test guide-narrative-regenerate-context.jinja2 renders with edit method."""
        context = active_context.copy()
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Add more suspense."
        context["regeneration_context"].method = "edit"
        context["regeneration_context"].message = "The door creaked open."
        context["original_instructions"] = "Describe the entrance."
        result = render_template("director.guide-narrative-regenerate-context", context)
        assert result is not None
        assert len(result) > 0
        assert "suspense" in result.lower() or "draft" in result.lower()

    def test_guide_conversation_regenerate_context_renders(self, active_context):
        """Test guide-conversation-regenerate-context.jinja2 renders."""
        context = active_context.copy()
        context["regeneration_context"] = Mock()
        context["regeneration_context"].direction = "Make it more emotional."
        context["regeneration_context"].method = "replace"
        context["regeneration_context"].message = ""
        context["original_instructions"] = ""
        result = render_template("director.guide-conversation-regenerate-context", context)
        assert result is not None
        assert len(result) > 0
        assert "emotional" in result.lower()

    def test_guide_narrative_direction_renders(self, active_context):
        """Test guide-narrative-direction.jinja2 renders with narrative direction."""
        context = active_context.copy()
        context["narrative_direction"] = "The hero discovers a hidden passage."
        context["regeneration_context"] = None
        result = render_template("director.guide-narrative-direction", context)
        assert result is not None
        assert len(result) > 0
        assert "hidden passage" in result.lower()


class TestDirectorIncludeOnlyTemplates:
    """
    Tests that verify include-only templates are properly tested through their parent templates.

    The following templates are include-only and tested through guide-narration.jinja2:
    - guide-narration-progress.jinja2
    - guide-narration-sensory.jinja2
    - guide-narration-time.jinja2
    - guide-narration-query.jinja2
    - guide-narration-visual.jinja2
    - guide-narration-visual-character.jinja2
    - guide-narration-writing-style.jinja2

    The following templates are include-only and tested through other parent templates:
    - chat-instructions.jinja2 (tested through chat.jinja2)
    - chat-common-tasks.jinja2 (tested through chat.jinja2)
    - scene-direction-instructions.jinja2 (tested through scene-direction.jinja2)
    - scene-direction-turn-balance.jinja2 (tested through scene-direction.jinja2)
    - scene-direction-raw-log.jinja2 (tested through query-scene-direction.jinja2)
    """

    def test_include_only_templates_covered(self):
        """
        Document that include-only templates are tested through their parent templates.

        This test serves as documentation that we intentionally don't test these
        templates directly because they are only used via Jinja2 includes.
        """
        include_only_templates = [
            "guide-narration-progress.jinja2",
            "guide-narration-sensory.jinja2",
            "guide-narration-time.jinja2",
            "guide-narration-query.jinja2",
            "guide-narration-visual.jinja2",
            "guide-narration-visual-character.jinja2",
            "guide-narration-writing-style.jinja2",
            "chat-instructions.jinja2",
            "chat-common-tasks.jinja2",
            "scene-direction-instructions.jinja2",
            "scene-direction-turn-balance.jinja2",
            "scene-direction-raw-log.jinja2",
        ]
        # This test just documents the include-only templates
        assert len(include_only_templates) == 12
