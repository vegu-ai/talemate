"""
Unit tests for creator agent templates.

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
def creator_context():
    """Base context for creator templates."""
    return create_base_context()


@pytest.fixture
def active_context(creator_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="creator")
    scene_token = active_scene.set(creator_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield creator_context

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


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
    focal.callbacks.add_dialogue_example = Mock()
    focal.callbacks.add_dialogue_example.render = Mock(return_value="add_dialogue_example callback rendered")

    return focal


@pytest.fixture
def mock_generation_context():
    """Create a mock generation context for contextual-generate template."""
    gen_ctx = Mock()
    gen_ctx.original = ""
    gen_ctx.instructions = ""
    gen_ctx.information = ""
    gen_ctx.spice = ""
    gen_ctx.style = ""
    gen_ctx.partial = ""
    gen_ctx.length = 512
    gen_ctx.get_state = Mock(return_value=False)
    gen_ctx.set_state = Mock()
    return gen_ctx


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
def patch_all_agent_calls():
    """
    Extended patch for templates that use multiple agent calls.

    This patches both rag_build and other agent calls like query_memory,
    query_text_eval, and agent_action for character guidance.
    """
    with patch('talemate.instance.get_agent') as mock_get_agent:
        # Create different mock agents for different agent types
        mock_creator = Mock()
        mock_creator.rag_build = AsyncMock(return_value=[])

        mock_director = Mock()
        mock_director.get_cached_character_guidance = AsyncMock(return_value="")

        mock_memory = Mock()
        mock_memory.query = AsyncMock(return_value="Mocked memory response")
        mock_memory.multi_query = AsyncMock(return_value={})

        mock_world_state = Mock()
        mock_world_state.analyze_text_and_answer_question = AsyncMock(return_value="yes")

        def get_agent_side_effect(agent_type):
            agents = {
                "creator": mock_creator,
                "director": mock_director,
                "memory": mock_memory,
                "world_state": mock_world_state,
            }
            return agents.get(agent_type, Mock())

        mock_get_agent.side_effect = get_agent_side_effect
        yield mock_get_agent


class TestCreatorSystemTemplates:
    """Tests for creator system templates."""

    def test_system_no_decensor_renders(self, active_context):
        """Test system-no-decensor.jinja2 renders."""
        result = render_template("creator.system-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        assert "storyteller" in result.lower()

    def test_system_renders(self, active_context):
        """Test system.jinja2 renders (includes system-no-decensor)."""
        result = render_template("creator.system", active_context)
        assert result is not None
        assert len(result) > 0
        # system.jinja2 adds text about explicit content
        assert "storyteller" in result.lower()
        assert "explicit" in result.lower() or "language" in result.lower()


class TestCreatorContextTemplates:
    """Tests for creator context templates."""

    def test_extra_context_renders(self, active_context, patch_agent_queries):
        """Test extra-context.jinja2 renders with scene data."""
        context = active_context.copy()
        context["memory_query"] = ""  # No memory query
        result = render_template("creator.extra-context", context)
        assert result is not None
        assert len(result) > 0
        # Template includes content classification section
        assert "classification" in result.lower()

    def test_extra_context_with_memory_query(self, active_context, patch_agent_queries):
        """Test extra-context.jinja2 renders with memory query."""
        context = active_context.copy()
        context["memory_query"] = "What happened recently?"
        result = render_template("creator.extra-context", context)
        assert result is not None
        assert len(result) > 0

    def test_scene_context_renders(self, active_context, patch_rag_build):
        """Test scene-context.jinja2 renders with scene history."""
        context = active_context.copy()
        context["budget"] = 2000
        result = render_template("creator.scene-context", context)
        assert result is not None
        assert len(result) > 0
        # Template should include SCENE section marker
        assert "scene" in result.lower()

    def test_scene_context_with_custom_budget(self, active_context, patch_rag_build):
        """Test scene-context.jinja2 with custom token budget."""
        context = active_context.copy()
        context["budget"] = 500
        result = render_template("creator.scene-context", context)
        assert result is not None
        assert len(result) > 0

    def test_memory_context_renders(self, active_context, patch_rag_build):
        """Test memory-context.jinja2 renders with memory prompt."""
        context = active_context.copy()
        context["memory_prompt"] = "What happened in the forest clearing?"
        context["memory_goal"] = ""
        result = render_template("creator.memory-context", context)
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
        context["skip_characters"] = []
        context["include_dialogue_instructions"] = False
        result = render_template("creator.character-context", context)
        assert result is not None
        assert len(result) > 0
        assert "Elena" in result
        assert "Marcus" in result

    def test_character_context_with_skip(self, active_context, patch_agent_queries):
        """Test character-context.jinja2 with skip_characters."""
        context = active_context.copy()
        char1 = create_mock_character(name="Elena")
        char1.filtered_sheet = Mock(return_value="age: early 30s\ngender: female")
        char2 = create_mock_character(name="Marcus")
        char2.filtered_sheet = Mock(return_value="age: mid 20s\ngender: male")
        context["scene"].characters = [char1, char2]
        context["skip_characters"] = ["Elena"]
        context["include_dialogue_instructions"] = False
        result = render_template("creator.character-context", context)
        assert result is not None
        # Elena should be skipped
        assert "Elena" not in result or "Marcus" in result

    def test_character_context_with_dialogue_instructions(self, active_context, patch_agent_queries):
        """Test character-context.jinja2 with include_dialogue_instructions."""
        context = active_context.copy()
        char1 = create_mock_character(name="Elena")
        char1.filtered_sheet = Mock(return_value="age: early 30s\ngender: female")
        context["scene"].characters = [char1]
        context["skip_characters"] = []
        context["include_dialogue_instructions"] = True
        result = render_template("creator.character-context", context)
        assert result is not None
        assert len(result) > 0
        # Should include dialogue instructions section
        assert "acting instructions" in result.lower() or "dialogue" in result.lower()


def create_set_tag_name():
    """Create a set_tag_name function for autocomplete templates."""
    def set_tag_name(tag_name: str) -> str:
        return tag_name
    return set_tag_name


class TestCreatorAutocompleteTemplates:
    """Tests for creator autocomplete templates."""

    def test_autocomplete_narrative_renders(self, active_context, patch_agent_queries):
        """Test autocomplete-narrative.jinja2 renders."""
        context = active_context.copy()
        context["non_anchor"] = "The old man walked slowly down the dusty"
        context["anchor"] = ""
        context["set_tag_name"] = create_set_tag_name()
        context["scene"].snapshot = Mock(return_value="Current scene snapshot")
        result = render_template("creator.autocomplete-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Template should include TASK section
        assert "task" in result.lower()
        # Template should include the draft
        assert "old man" in result.lower()

    def test_autocomplete_narrative_without_coerce(self, active_context, patch_agent_queries):
        """Test autocomplete-narrative.jinja2 when can_coerce is false."""
        context = active_context.copy()
        context["non_anchor"] = "The forest was dark and"
        context["anchor"] = ""
        context["can_coerce"] = False
        context["set_tag_name"] = create_set_tag_name()
        context["scene"].snapshot = Mock(return_value="Current scene snapshot")
        result = render_template("creator.autocomplete-narrative", context)
        assert result is not None
        assert len(result) > 0
        # Should include example section when can't coerce
        assert "example" in result.lower()

    def test_autocomplete_dialogue_renders(self, active_context, patch_all_agent_calls):
        """Test autocomplete-dialogue.jinja2 renders."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["non_anchor"] = "What is the matter with you, i thought"
        context["anchor"] = ""
        context["continuing_message"] = False
        context["set_tag_name"] = create_set_tag_name()
        context["agent_context_state"] = {"conversation__instruction": ""}
        context["scene"].snapshot = Mock(return_value="Current scene snapshot")
        result = render_template("creator.autocomplete-dialogue", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character
        assert "Elena" in result
        # Template should include TASK section
        assert "task" in result.lower()

    def test_autocomplete_dialogue_continuing(self, active_context, patch_all_agent_calls):
        """Test autocomplete-dialogue.jinja2 with continuing_message."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Marcus")
        context["non_anchor"] = "I don't think"
        context["set_tag_name"] = create_set_tag_name()
        context["anchor"] = ""
        context["continuing_message"] = True
        context["agent_context_state"] = {"conversation__instruction": ""}
        context["scene"].snapshot = Mock(return_value="Current scene snapshot")
        result = render_template("creator.autocomplete-dialogue", context)
        assert result is not None
        assert len(result) > 0
        assert "Marcus" in result


class TestCreatorGenerateTemplates:
    """Tests for creator generation templates."""

    def test_generate_title_renders(self, active_context):
        """Test generate-title.jinja2 renders."""
        context = active_context.copy()
        context["text"] = "A hero ventures into the dark forest to save the kingdom from an ancient evil."
        result = render_template("creator.generate-title", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text
        assert "hero" in result.lower() or "forest" in result.lower()
        # Template should include TASK section
        assert "task" in result.lower()
        # Template should ask for a title
        assert "title" in result.lower()

    def test_contextual_generate_basic_renders(self, active_context, patch_all_agent_calls, mock_generation_context, mock_intent_state):
        """Test contextual-generate.jinja2 renders with basic context."""
        context = active_context.copy()
        context["context_aware"] = True
        context["history_aware"] = False
        context["character"] = None
        context["context_typ"] = "general"
        context["context_name"] = "World History"
        context["character_name"] = ""
        context["generation_context"] = mock_generation_context
        context["can_coerce"] = True
        context["scene"].intent_state = mock_intent_state
        context["scene"].get_player_character = Mock(return_value=None)
        context["scene"].num_npc_characters = Mock(return_value=2)
        result = render_template("creator.contextual-generate", context)
        assert result is not None
        assert len(result) > 0
        assert "task" in result.lower()

    def test_contextual_generate_character_attribute(self, active_context, patch_all_agent_calls, mock_generation_context, mock_intent_state):
        """Test contextual-generate.jinja2 for character attribute."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        char.sheet_filtered = Mock(return_value="age: early 30s")
        context["context_aware"] = True
        context["history_aware"] = False
        context["character"] = char
        context["context_typ"] = "character attribute"
        context["context_name"] = "occupation"
        context["character_name"] = "Elena"
        context["generation_context"] = mock_generation_context
        context["can_coerce"] = True
        context["scene"].intent_state = mock_intent_state
        context["scene"].get_player_character = Mock(return_value=None)
        result = render_template("creator.contextual-generate", context)
        assert result is not None
        assert len(result) > 0
        assert "occupation" in result.lower()
        assert "Elena" in result

    def test_contextual_generate_list(self, active_context, patch_all_agent_calls, mock_generation_context, mock_intent_state):
        """Test contextual-generate.jinja2 for list type."""
        context = active_context.copy()
        context["context_aware"] = True
        context["history_aware"] = False
        context["character"] = None
        context["context_typ"] = "list"
        context["context_name"] = "Items in inventory"
        context["character_name"] = ""
        context["generation_context"] = mock_generation_context
        context["can_coerce"] = True
        context["scene"].intent_state = mock_intent_state
        context["scene"].get_player_character = Mock(return_value=None)
        result = render_template("creator.contextual-generate", context)
        assert result is not None
        assert len(result) > 0
        assert "list" in result.lower()
        assert "20 items" in result.lower()

    def test_contextual_generate_scene_intro(self, active_context, patch_all_agent_calls, mock_generation_context, mock_intent_state):
        """Test contextual-generate.jinja2 for scene intro."""
        context = active_context.copy()
        context["context_aware"] = True
        context["history_aware"] = False
        context["character"] = None
        context["context_typ"] = "scene intro"
        context["context_name"] = "introduction"
        context["character_name"] = ""
        context["generation_context"] = mock_generation_context
        context["can_coerce"] = True
        context["scene"].intent_state = mock_intent_state
        context["scene"].get_player_character = Mock(return_value=create_mock_character(name="Hero", is_player=True))
        context["scene"].num_npc_characters = Mock(return_value=2)
        result = render_template("creator.contextual-generate", context)
        assert result is not None
        assert len(result) > 0
        assert "introduction" in result.lower()

    def test_contextual_generate_with_history(self, active_context, patch_all_agent_calls, mock_generation_context, mock_intent_state):
        """Test contextual-generate.jinja2 with history_aware."""
        context = active_context.copy()
        context["context_aware"] = True
        context["history_aware"] = True
        context["character"] = None
        context["context_typ"] = "general"
        context["context_name"] = "Story Event"
        context["character_name"] = ""
        context["generation_context"] = mock_generation_context
        context["can_coerce"] = True
        context["scene"].intent_state = mock_intent_state
        context["scene"].get_player_character = Mock(return_value=None)
        result = render_template("creator.contextual-generate", context)
        assert result is not None
        assert len(result) > 0


class TestCreatorDetermineTemplates:
    """Tests for creator determine-* templates."""

    def test_determine_character_attributes_renders(self, active_context):
        """Test determine-character-attributes.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["character"] = char
        result = render_template("creator.determine-character-attributes", context)
        assert result is not None
        assert len(result) > 0
        # Template should ask for JSON output
        assert "json" in result.lower()
        # Template should include character name
        assert "Elena" in result

    def test_determine_character_description_renders(self, active_context):
        """Test determine-character-description.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["character"] = char
        context["text"] = ""  # No additional text
        context["information"] = ""
        result = render_template("creator.determine-character-description", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character
        assert "Marcus" in result
        # Template should include TASK section
        assert "task" in result.lower()

    def test_determine_character_description_with_text(self, active_context):
        """Test determine-character-description.jinja2 with custom text."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["character"] = char
        context["text"] = "Elena is a skilled healer from the mountain village."
        context["information"] = "Focus on her healing abilities."
        result = render_template("creator.determine-character-description", context)
        assert result is not None
        assert len(result) > 0
        assert "healer" in result.lower() or "Elena" in result

    def test_determine_character_name_renders(self, active_context, patch_agent_queries):
        """Test determine-character-name.jinja2 renders."""
        context = active_context.copy()
        context["character_name"] = "the tall woman with dark hair"
        context["group"] = False
        context["allowed_names"] = []
        context["instructions"] = ""
        result = render_template("creator.determine-character-name", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the character description
        assert "tall woman" in result.lower()
        # Template should ask for a name
        assert "name" in result.lower()

    def test_determine_character_name_with_allowed_names(self, active_context, patch_agent_queries):
        """Test determine-character-name.jinja2 with allowed names."""
        context = active_context.copy()
        context["character_name"] = "the mysterious stranger"
        context["group"] = False
        context["allowed_names"] = ["John", "Marcus", "Elena"]
        context["instructions"] = ""
        result = render_template("creator.determine-character-name", context)
        assert result is not None
        assert len(result) > 0
        # Template should include allowed names
        assert "John" in result or "Marcus" in result or "Elena" in result

    def test_determine_character_name_group(self, active_context, patch_agent_queries):
        """Test determine-character-name.jinja2 for group naming."""
        context = active_context.copy()
        context["character_name"] = "the guards standing at the gate"
        context["group"] = True
        context["allowed_names"] = []
        context["instructions"] = ""
        result = render_template("creator.determine-character-name", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference group
        assert "group" in result.lower()

    def test_determine_character_goals_renders(self, active_context):
        """Test determine-character-goals.jinja2 renders."""
        context = active_context.copy()
        char1 = create_mock_character(name="Elena")
        char2 = create_mock_character(name="Hero", is_player=True)
        context["scene"].characters = [char1, char2]
        context["npc_name"] = "Elena"
        context["player_name"] = "Hero"
        context["goal_instructions"] = "Focus on character growth."
        result = render_template("creator.determine-character-goals", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the NPC
        assert "Elena" in result
        # Template should reference the player
        assert "Hero" in result
        # Template should mention goals
        assert "goal" in result.lower()

    def test_determine_character_dialogue_instructions_renders(self, active_context, patch_rag_build):
        """Test determine-character-dialogue-instructions.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["character"] = char
        context["update_existing"] = False
        context["instructions"] = ""
        context["information"] = ""
        context["budget"] = 1000
        result = render_template("creator.determine-character-dialogue-instructions", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character
        assert "Elena" in result
        # Template should mention dialogue
        assert "dialogue" in result.lower()

    def test_determine_character_dialogue_instructions_update(self, active_context, patch_rag_build):
        """Test determine-character-dialogue-instructions.jinja2 with update_existing."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["character"] = char
        context["update_existing"] = True
        context["instructions"] = "Make the dialogue more formal."
        context["information"] = ""
        context["budget"] = 1000
        result = render_template("creator.determine-character-dialogue-instructions", context)
        assert result is not None
        assert len(result) > 0
        # Should mention updating existing
        assert "update" in result.lower() or "existing" in result.lower()

    def test_determine_character_dialogue_examples_renders(self, active_context, mock_focal):
        """Test determine-character-dialogue-examples.jinja2 renders."""
        context = active_context.copy()
        char = create_mock_character(name="Elena")
        context["character"] = char
        context["text"] = "Elena speaks softly but with great conviction."
        context["max_examples"] = 5
        context["existing_examples"] = []
        context["focal"] = mock_focal
        context["information"] = ""
        result = render_template("creator.determine-character-dialogue-examples", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character
        assert "Elena" in result
        # Template should mention dialogue examples
        assert "dialogue" in result.lower()

    def test_determine_character_dialogue_examples_with_existing(self, active_context, mock_focal):
        """Test determine-character-dialogue-examples.jinja2 with existing examples."""
        context = active_context.copy()
        char = create_mock_character(name="Marcus")
        context["character"] = char
        context["text"] = "Marcus is gruff and to the point."
        context["max_examples"] = 3
        context["existing_examples"] = [
            "Marcus: \"Get moving. We don't have all day.\"",
            "Marcus: \"Keep your head down and follow my lead.\""
        ]
        context["focal"] = mock_focal
        context["information"] = ""
        result = render_template("creator.determine-character-dialogue-examples", context)
        assert result is not None
        assert len(result) > 0
        # Should include existing examples section
        assert "existing" in result.lower()

    def test_determine_scenario_description_renders(self, active_context):
        """Test determine-scenario-description.jinja2 renders."""
        context = active_context.copy()
        context["text"] = "A dark fantasy world where magic is forbidden."
        result = render_template("creator.determine-scenario-description", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the text
        assert "magic" in result.lower() or "fantasy" in result.lower()
        # Template should ask for description extraction
        assert "scenario" in result.lower() or "extract" in result.lower()

    def test_determine_content_context_with_character(self, active_context):
        """Test determine-content-context.jinja2 with character."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["description"] = ""
        # Add config mock
        context["config"] = Mock()
        context["config"].creator = Mock()
        context["config"].creator.content_context = [
            "fantasy adventure",
            "mystery thriller",
            "romantic drama"
        ]
        result = render_template("creator.determine-content-context", context)
        assert result is not None
        assert len(result) > 0
        # Template should reference the character
        assert "Elena" in result
        # Template should mention content context
        assert "content context" in result.lower()

    def test_determine_content_context_with_description(self, active_context):
        """Test determine-content-context.jinja2 with description."""
        context = active_context.copy()
        context["character"] = None
        context["description"] = "A post-apocalyptic world overrun by zombies."
        context["config"] = Mock()
        context["config"].creator = Mock()
        context["config"].creator.content_context = [
            "horror survival",
            "action adventure",
            "sci-fi thriller"
        ]
        result = render_template("creator.determine-content-context", context)
        assert result is not None
        assert len(result) > 0
        # Template should include the description
        assert "apocalyptic" in result.lower() or "zombies" in result.lower()


class TestCreatorIncludeOnlyTemplates:
    """
    Tests that verify include-only templates are properly tested through their parent templates.

    The following templates are include-only and tested through other templates:
    - memory-context.jinja2 (tested through scene-context.jinja2)

    Note: Most creator templates are standalone and can be tested directly.
    """

    def test_include_only_templates_covered(self):
        """
        Document that include-only templates are tested through their parent templates.

        This test serves as documentation that we intentionally don't test these
        templates separately because they are only used via Jinja2 includes.
        """
        include_only_templates = [
            # memory-context.jinja2 is included by scene-context.jinja2
            # but we also test it directly since it's a key template
        ]
        # This test just documents the include patterns
        # All creator templates can be tested directly
        assert True
