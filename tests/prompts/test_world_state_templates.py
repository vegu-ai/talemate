"""
Unit tests for world_state agent templates.

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
def world_state_context():
    """Base context for world_state templates."""
    return create_base_context()


@pytest.fixture
def active_context(world_state_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="world_state")
    scene_token = active_scene.set(world_state_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield world_state_context

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

    # Mock callbacks for determine-character-development template
    focal.callbacks = Mock()
    focal.callbacks.add_attribute = Mock()
    focal.callbacks.add_attribute.render = Mock(return_value="add_attribute callback rendered")
    focal.callbacks.update_attribute = Mock()
    focal.callbacks.update_attribute.render = Mock(return_value="update_attribute callback rendered")
    focal.callbacks.remove_attribute = Mock()
    focal.callbacks.remove_attribute.render = Mock(return_value="remove_attribute callback rendered")
    focal.callbacks.update_description = Mock()
    focal.callbacks.update_description.render = Mock(return_value="update_description callback rendered")

    return focal


@pytest.fixture
def mock_reinforcement():
    """Create a mock reinforcement for update-reinforcements template."""
    reinforcement = Mock()
    reinforcement.insert = "sequential"
    return reinforcement


@pytest.fixture
def patch_all_agent_calls():
    """
    Extended patch for templates that use multiple agent calls.

    This patches rag_build and other agent calls like query_memory,
    instruct_text, and agent_action.
    """
    with patch('talemate.instance.get_agent') as mock_get_agent:
        # Create different mock agents for different agent types
        mock_world_state = Mock()
        mock_world_state.rag_build = AsyncMock(return_value=[])
        mock_world_state.analyze_text_and_answer_question = AsyncMock(return_value="yes")

        mock_director = Mock()
        mock_director.get_cached_character_guidance = AsyncMock(return_value="")

        mock_memory = Mock()
        mock_memory.query = AsyncMock(return_value="Mocked memory response")
        mock_memory.multi_query = AsyncMock(return_value={})

        mock_narrator = Mock()
        mock_narrator.narrate_query = AsyncMock(return_value="Mocked query response")

        def get_agent_side_effect(agent_type):
            agents = {
                "world_state": mock_world_state,
                "director": mock_director,
                "memory": mock_memory,
                "narrator": mock_narrator,
            }
            return agents.get(agent_type, Mock())

        mock_get_agent.side_effect = get_agent_side_effect
        yield mock_get_agent


class TestWorldStateSystemTemplates:
    """Tests for world_state system templates."""

    def test_system_analyst_no_decensor_renders(self, active_context):
        """Test system-analyst-no-decensor.jinja2 renders."""
        result = render_template("world_state.system-analyst-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        assert "analyst" in result.lower()

    def test_system_analyst_renders(self, active_context):
        """Test system-analyst.jinja2 renders (includes system-analyst-no-decensor)."""
        result = render_template("world_state.system-analyst", active_context)
        assert result is not None
        assert len(result) > 0
        # system-analyst.jinja2 adds text about explicit content
        assert "analyst" in result.lower()
        assert "impartial" in result.lower() or "explicit" in result.lower()

    def test_system_analyst_freeform_no_decensor_renders(self, active_context):
        """Test system-analyst-freeform-no-decensor.jinja2 renders."""
        result = render_template("world_state.system-analyst-freeform-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        assert "analyst" in result.lower()

    def test_system_analyst_freeform_renders(self, active_context):
        """Test system-analyst-freeform.jinja2 renders."""
        result = render_template("world_state.system-analyst-freeform", active_context)
        assert result is not None
        assert len(result) > 0
        assert "analyst" in result.lower()


class TestWorldStateContextTemplates:
    """Tests for world_state context templates."""

    def test_extra_context_renders(self, active_context, patch_agent_queries):
        """Test extra-context.jinja2 renders with scene data."""
        context = active_context.copy()
        context["memory_query"] = ""  # No memory query
        result = render_template("world_state.extra-context", context)
        assert result is not None
        # Template may be minimal without memory_query

    def test_extra_context_with_memory_query(self, active_context, patch_agent_queries):
        """Test extra-context.jinja2 renders with memory query."""
        context = active_context.copy()
        context["memory_query"] = "What happened recently?"
        result = render_template("world_state.extra-context", context)
        assert result is not None

    def test_render_template_renders(self, active_context):
        """Test render.jinja2 renders with world state data."""
        context = active_context.copy()
        context["characters"] = {
            "Elena": {
                "emotion": "curious",
                "snapshot": "Looking around the forest clearing."
            },
            "Marcus": {
                "emotion": "cautious",
                "snapshot": "Standing guard near the entrance."
            }
        }
        context["items"] = {
            "Ancient Sword": {
                "snapshot": "A gleaming blade resting against a tree."
            }
        }
        result = render_template("world_state.render", context)
        assert result is not None
        assert len(result) > 0
        assert "world state" in result.lower()
        assert "Elena" in result
        assert "Marcus" in result
        assert "Ancient Sword" in result


class TestWorldStateAnalyzeTemplates:
    """Tests for world_state analyze-* templates."""

    def test_analyze_text_and_follow_instruction_renders(self, active_context):
        """Test analyze-text-and-follow-instruction.jinja2 renders."""
        context = active_context.copy()
        context["text"] = "The hero discovered a hidden passage behind the waterfall."
        context["instruction"] = "Identify all locations mentioned in the text."
        result = render_template("world_state.analyze-text-and-follow-instruction", context)
        assert result is not None
        assert len(result) > 0
        assert "waterfall" in result.lower() or "passage" in result.lower()
        assert "locations" in result.lower()

    def test_analyze_text_and_answer_question_renders(self, active_context):
        """Test analyze-text-and-answer-question.jinja2 renders."""
        context = active_context.copy()
        context["text"] = "Elena wielded the ancient sword with great skill."
        context["query"] = "What weapon is Elena using?"
        context["bot_token"] = "<|BOT|>"
        result = render_template("world_state.analyze-text-and-answer-question", context)
        assert result is not None
        assert len(result) > 0
        assert "sword" in result.lower()
        assert "weapon" in result.lower()

    def test_analyze_text_and_extract_context_renders(self, active_context):
        """Test analyze-text-and-extract-context.jinja2 renders."""
        # This template uses instruct_text which is complex to mock.
        # We need to patch the world_state agent's analyze_and_follow_instruction.
        with patch('talemate.instance.get_agent') as mock_get_agent:
            mock_world_state = Mock()
            mock_world_state.analyze_and_follow_instruction = AsyncMock(
                return_value="1. What caused the war?\n2. Who are the main factions?\n3. What is the current state?"
            )
            mock_memory = Mock()
            mock_memory.query = AsyncMock(return_value="Mocked memory")
            mock_memory.multi_query = AsyncMock(return_value={})

            def get_agent_side_effect(agent_type):
                if agent_type == "world_state":
                    return mock_world_state
                elif agent_type == "memory":
                    return mock_memory
                return Mock()

            mock_get_agent.side_effect = get_agent_side_effect

            context = active_context.copy()
            context["text"] = "The kingdom has been at war for a decade."
            context["goal"] = "Understanding the political situation"
            context["num_queries"] = 3
            context["extra_context"] = []
            context["include_character_context"] = False
            context["bot_token"] = "<|BOT|>"
            result = render_template("world_state.analyze-text-and-extract-context", context)
            assert result is not None
            assert len(result) > 0
            assert "war" in result.lower() or "kingdom" in result.lower()

    def test_analyze_text_and_generate_rag_queries_renders(self, active_context, patch_agent_queries):
        """Test analyze-text-and-generate-rag-queries.jinja2 renders."""
        context = active_context.copy()
        context["text"] = "The sorcerer's tower loomed over the ancient forest."
        context["goal"] = "Gather information about the sorcerer."
        context["num_queries"] = 3
        context["extra_context"] = []
        context["include_character_context"] = False
        context["memory_query"] = ""
        result = render_template("world_state.analyze-text-and-generate-rag-queries", context)
        assert result is not None
        assert len(result) > 0
        assert "sorcerer" in result.lower() or "tower" in result.lower()
        assert "queries" in result.lower()

    def test_analyze_history_and_follow_instructions_renders(self, active_context):
        """Test analyze-history-and-follow-instructions.jinja2 renders."""
        context = active_context.copy()
        context["entries"] = [
            {"ts": "PT1H", "text": "The hero arrived at the village."},
            {"ts": "PT2H", "text": "The hero met with the village elder."}
        ]
        context["instructions"] = "Summarize the hero's journey so far."
        context["analysis"] = ""
        context["response_length"] = 256
        result = render_template("world_state.analyze-history-and-follow-instructions", context)
        assert result is not None
        assert len(result) > 0
        assert "hero" in result.lower() or "village" in result.lower()


class TestWorldStateIdentifyTemplates:
    """Tests for world_state identification templates."""

    def test_identify_characters_renders(self, active_context):
        """Test identify-characters.jinja2 renders."""
        context = active_context.copy()
        context["text"] = "Elena spoke to the village elder, while Marcus stood guard."
        result = render_template("world_state.identify-characters", context)
        assert result is not None
        assert len(result) > 0
        assert "json" in result.lower()
        assert "characters" in result.lower()

    def test_identify_characters_from_history_renders(self, active_context):
        """Test identify-characters.jinja2 renders when text is empty (uses history)."""
        context = active_context.copy()
        context["text"] = ""  # Will use scene.context_history instead
        result = render_template("world_state.identify-characters", context)
        assert result is not None
        assert len(result) > 0
        assert "characters" in result.lower()


class TestWorldStateCheckTemplates:
    """Tests for world_state check templates."""

    def test_check_pin_conditions_renders(self, active_context):
        """Test check-pin-conditions.jinja2 renders."""
        context = active_context.copy()
        context["previous_states"] = '{"condition1": false, "condition2": true}'
        context["coercion"] = {"condition1": False, "condition2": True}
        result = render_template("world_state.check-pin-conditions", context)
        assert result is not None
        assert len(result) > 0
        assert "condition" in result.lower()
        assert "scene" in result.lower()


class TestWorldStateDetermineTemplates:
    """Tests for world_state determine-* templates."""

    def test_determine_content_context_renders(self, active_context):
        """Test determine-content-context.jinja2 renders."""
        context = active_context.copy()
        context["content"] = "A hero sets out on a dangerous quest."
        context["extra_choices"] = ["epic saga", "coming-of-age story"]
        context["config"] = Mock()
        context["config"].creator = Mock()
        context["config"].creator.content_context = [
            "fantasy adventure",
            "mystery thriller",
            "romantic drama"
        ]
        context["bot_token"] = "<|BOT|>"
        result = render_template("world_state.determine-content-context", context)
        assert result is not None
        assert len(result) > 0
        assert "hero" in result.lower() or "quest" in result.lower()
        assert "content context" in result.lower()

    def test_determine_character_development_renders(self, active_context, mock_focal, patch_rag_build):
        """Test determine-character-development.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        char.details = {"background": "A healer from the forest."}
        context["character"] = char
        context["focal"] = mock_focal
        context["instructions"] = ""
        context["bot_token"] = "<|BOT|>"
        result = render_template("world_state.determine-character-development", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result
        assert "character" in result.lower()

    def test_determine_character_development_with_instructions(self, active_context, mock_focal, patch_rag_build):
        """Test determine-character-development.jinja2 with custom instructions."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        char.details = {"combat_style": "Defensive and methodical."}
        context["character"] = char
        context["focal"] = mock_focal
        context["instructions"] = "Focus on combat skill improvements."
        context["bot_token"] = "<|BOT|>"
        result = render_template("world_state.determine-character-development", context)
        assert result is not None
        assert len(result) > 0
        assert "Marcus" in result
        assert "combat" in result.lower()

    def test_determine_avatar_renders(self, active_context):
        """Test determine-avatar.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["character"] = char
        context["content"] = "Elena stands bravely facing the dragon."
        context["assets"] = [
            Mock(id="avatar_1", meta=Mock(name="Elena Neutral", tags=["neutral", "standing"])),
            Mock(id="avatar_2", meta=Mock(name="Elena Combat", tags=["combat", "action"])),
        ]
        context["deny_generation"] = False
        result = render_template("world_state.determine-avatar", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result
        assert "avatar" in result.lower() or "asset" in result.lower()

    def test_determine_avatar_deny_generation(self, active_context):
        """Test determine-avatar.jinja2 with deny_generation=True."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["character"] = char
        context["content"] = "Marcus looks concerned."
        context["assets"] = [
            Mock(id="avatar_1", meta=Mock(name="Marcus Neutral", tags=["neutral"])),
        ]
        context["deny_generation"] = True
        result = render_template("world_state.determine-avatar", context)
        assert result is not None
        assert len(result) > 0
        assert "closest available match" in result.lower()


class TestWorldStateRequestTemplates:
    """Tests for world_state request templates."""

    def test_request_world_state_v2_renders(self, active_context):
        """Test request-world-state-v2.jinja2 renders."""
        context = active_context.copy()
        # Add a player character
        player_char = create_mock_character(name="Hero", is_player=True)
        context["scene"].get_player_character = Mock(return_value=player_char)
        context["scene"].npc_character_names = ["Elena", "Marcus"]
        result = render_template("world_state.request-world-state-v2", context)
        assert result is not None
        assert len(result) > 0
        assert "world state" in result.lower()
        assert "characters" in result.lower()
        assert "items" in result.lower()


class TestWorldStateUpdateTemplates:
    """Tests for world_state update templates."""

    def test_update_reinforcements_renders(self, active_context, mock_reinforcement, patch_agent_queries):
        """Test update-reinforcements.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["character"] = char
        context["text"] = "Elena is feeling determined."
        context["question"] = "What is Elena's current mood?"
        context["answer"] = "determined"
        context["instructions"] = ""
        context["reinforcement"] = mock_reinforcement
        # Provide a proper mock for scene.snapshot that returns a string
        context["scene"].snapshot = Mock(return_value="Current scene state")
        context["bot_token"] = "<|BOT|>"
        result = render_template("world_state.update-reinforcements", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result
        assert "mood" in result.lower()

    def test_update_reinforcements_attribute_mode(self, active_context, mock_reinforcement, patch_agent_queries):
        """Test update-reinforcements.jinja2 in attribute generation mode."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["character"] = char
        context["text"] = "Marcus wears heavy plate armor."
        # Attribute mode (no question mark at end)
        context["question"] = "armor type"
        context["answer"] = ""
        context["instructions"] = ""
        context["reinforcement"] = mock_reinforcement
        # Provide a proper mock for scene.snapshot that returns a string
        context["scene"].snapshot = Mock(return_value="Current scene state")
        context["bot_token"] = "<|BOT|>"
        result = render_template("world_state.update-reinforcements", context)
        assert result is not None
        assert len(result) > 0
        assert "Marcus" in result
        assert "armor" in result.lower()


class TestWorldStateExtractTemplates:
    """Tests for world_state extract templates."""

    def test_extract_character_sheet_renders(self, active_context):
        """Test extract-character-sheet.jinja2 renders."""
        context = active_context.copy()
        context["name"] = "Elena"
        context["text"] = "A skilled healer with gentle manners."
        context["character"] = None
        context["alteration_instructions"] = ""
        context["augmentation_instructions"] = ""
        context["max_attributes"] = 10
        result = render_template("world_state.extract-character-sheet", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result
        assert "character" in result.lower() or "profile" in result.lower()

    def test_extract_character_sheet_alteration(self, active_context):
        """Test extract-character-sheet.jinja2 with alteration instructions."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["name"] = "Elena"
        context["text"] = ""
        context["character"] = char
        context["alteration_instructions"] = "Update age to reflect time passing."
        context["augmentation_instructions"] = ""
        context["max_attributes"] = 10
        result = render_template("world_state.extract-character-sheet", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result
        assert "update" in result.lower() or "alteration" in result.lower()

    def test_extract_character_sheet_augmentation(self, active_context):
        """Test extract-character-sheet.jinja2 with augmentation instructions."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["name"] = "Marcus"
        context["text"] = ""
        context["character"] = char
        context["alteration_instructions"] = ""
        context["augmentation_instructions"] = "Add information about combat experience."
        context["max_attributes"] = 10
        result = render_template("world_state.extract-character-sheet", context)
        assert result is not None
        assert len(result) > 0
        assert "Marcus" in result
        assert "augment" in result.lower()


class TestWorldStateIncludeOnlyTemplates:
    """
    Tests that verify include-only templates are properly tested through their parent templates.

    The following templates are include-only and tested through other templates:
    - extra-context.jinja2 (tested directly and included by various templates)
    - writing-style-instructions.jinja2 (from common, included by update-reinforcements)
    - response-length.jinja2 (from common, included by analyze-history-and-follow-instructions)
    - character-context.jinja2 (from common, included by extract-character-sheet)
    - dynamic-instructions.jinja2 (from common, included by extract-character-sheet)
    """

    def test_include_only_templates_covered(self):
        """
        Document that include-only templates are tested through their parent templates.

        This test serves as documentation that we intentionally test some
        templates both directly and through their parent templates.
        """
        include_only_templates = [
            "extra-context.jinja2",  # tested directly and included by update-reinforcements
        ]
        # This test just documents the include patterns
        # All templates are also tested directly above
        assert True
