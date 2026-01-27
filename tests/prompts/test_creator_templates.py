"""
Unit tests for creator agent methods.

Tests that creator agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

import talemate.instance as instance
from talemate.agents.creator import CreatorAgent
from talemate.agents.creator.assistant import ContentGenerationContext
from .helpers import create_mock_scene


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that returns predictable responses."""
    client = AsyncMock()
    client.send_prompt = AsyncMock(return_value="<TITLE>Test Title</TITLE>")
    client.max_token_length = 4096
    client.decensor_enabled = False
    client.can_be_coerced = True
    client.model_name = "test-model"
    client.data_format = "json"
    return client


class MockCharacter:
    """A mock character class for isinstance checks."""

    def __init__(self, name, is_player=False):
        self.name = name
        self.is_player = is_player
        self.description = "A test character."
        self.gender = "female"
        self.greeting_text = "Hello there."
        self.dialogue_instructions = "Speaks normally."
        self.base_attributes = {"name": name}
        self.details = {}
        self.sheet = f"name: {name}"
        self.example_dialogue = []
        self.random_dialogue_example = ""

    def set_detail(self, key, value):
        """Mock set_detail for character details."""
        self.details[key] = value

    def filtered_sheet(self, *args, **kwargs):
        """Mock filtered_sheet method."""
        return self.sheet

    def sheet_filtered(self, *args, **kwargs):
        """Mock sheet_filtered method (alias for filtered_sheet)."""
        return self.sheet


@pytest.fixture
def mock_scene():
    """Create a rich mock scene for testing."""
    scene = create_mock_scene()

    # Add player character using MockCharacter class
    player = MockCharacter(name="Hero", is_player=True)
    npc = MockCharacter(name="Elena", is_player=False)

    scene.get_player_character = Mock(return_value=player)
    scene.get_npc_characters = Mock(return_value=[npc])
    scene.get_characters = Mock(return_value=[player, npc])
    scene.get_character = Mock(
        side_effect=lambda name: player if name == "Hero" else npc
    )
    # writing_style must be None or a WritingStyle instance (not Mock) for pydantic validation
    scene.writing_style = None
    scene.agent_state = {}
    scene.characters = [player, npc]
    scene.snapshot = Mock(return_value="Current scene snapshot")
    scene.num_npc_characters = Mock(return_value=1)

    # Mock Character class for isinstance check
    scene.Character = MockCharacter

    # Mock push_history for tests that need it
    scene.push_history = AsyncMock()

    # Mock intent_state for contextual generate
    scene.intent_state = Mock()
    scene.intent_state.active = False
    scene.intent_state.scene_types = {}

    # Mock log for autocomplete tests
    scene.log = Mock()
    scene.log.debug = Mock()

    return scene


@pytest.fixture
def mock_editor_agent():
    """Create a mock editor agent for cleanup calls."""
    editor = Mock()
    editor.fix_exposition_enabled = False
    editor.fix_exposition_narrator = False
    editor.fix_exposition_in_text = Mock(side_effect=lambda text: text)
    editor.cleanup_character_message = AsyncMock(side_effect=lambda text, char: text)
    return editor


@pytest.fixture
def mock_creator_agent_for_registry():
    """Create a mock creator agent for registry (for template agent_action calls)."""
    creator = Mock()
    # rag_build is called by templates - needs to be an async function
    creator.rag_build = AsyncMock(return_value=[])
    return creator


@pytest.fixture
def mock_director_agent():
    """Create a mock director agent for character guidance."""
    director = Mock()
    director.get_cached_character_guidance = AsyncMock(return_value="")
    return director


@pytest.fixture
def mock_memory_agent():
    """Create a mock memory agent for memory queries."""
    memory = Mock()
    memory.query = AsyncMock(return_value="Mocked memory response")
    memory.multi_query = AsyncMock(return_value={})
    return memory


@pytest.fixture
def mock_world_state_agent():
    """Create a mock world state agent for text analysis."""
    world_state = Mock()
    world_state.analyze_text_and_answer_question = AsyncMock(return_value="yes")
    return world_state


@pytest.fixture
def creator_agent(mock_llm_client, mock_scene):
    """Create a CreatorAgent instance with mocked dependencies."""
    agent = CreatorAgent(client=mock_llm_client)
    agent.scene = mock_scene
    return agent


@pytest.fixture
def setup_agents(
    mock_editor_agent,
    mock_creator_agent_for_registry,
    mock_director_agent,
    mock_memory_agent,
    mock_world_state_agent,
):
    """Set up the agent registry with mocked agents."""
    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Set up mock agents in the registry
    instance.AGENTS["creator"] = mock_creator_agent_for_registry
    instance.AGENTS["editor"] = mock_editor_agent
    instance.AGENTS["director"] = mock_director_agent
    instance.AGENTS["memory"] = mock_memory_agent
    instance.AGENTS["world_state"] = mock_world_state_agent

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(creator_agent, mock_scene, setup_agents):
    """Set up active scene context for tests."""
    from talemate.context import active_scene

    scene_token = active_scene.set(mock_scene)

    yield creator_agent

    active_scene.reset(scene_token)


class TestCreatorGenerateTitleMethod:
    """Tests for generate_title method."""

    @pytest.mark.asyncio
    async def test_generate_title_calls_client(self, active_context):
        """Test that generate_title calls the LLM client with rendered prompt."""
        creator = active_context

        response = await creator.generate_title(
            text="A hero ventures into the dark forest to save the kingdom from an ancient evil."
        )

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client's send_prompt was called
        creator.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]  # First positional arg is the prompt

        # Verify the prompt contains expected content
        assert "hero" in prompt_text.lower() or "forest" in prompt_text.lower()
        assert "title" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_generate_title_parses_title_tags(self, active_context):
        """Test that generate_title extracts title from TITLE tags."""
        creator = active_context
        creator.client.send_prompt.return_value = "<TITLE>The Dark Forest</TITLE>"

        response = await creator.generate_title(text="A story about a forest.")

        assert response == "The Dark Forest"


class TestCreatorContentContextMethods:
    """Tests for content context determination methods."""

    @pytest.mark.asyncio
    async def test_determine_content_context_for_character_calls_client(
        self, active_context, mock_scene
    ):
        """Test that determine_content_context_for_character calls the LLM client."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "fantasy adventure"

        response = await creator.determine_content_context_for_character(
            character=character
        )

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify character name appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_determine_content_context_for_description_calls_client(
        self, active_context
    ):
        """Test that determine_content_context_for_description calls the LLM client."""
        creator = active_context
        creator.client.send_prompt.return_value = "post-apocalyptic survival"

        response = await creator.determine_content_context_for_description(
            description="A post-apocalyptic world overrun by zombies."
        )

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify description appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "apocalyptic" in prompt_text.lower() or "zombies" in prompt_text.lower()


class TestCreatorCharacterMethods:
    """Tests for character creation and determination methods."""

    @pytest.mark.asyncio
    async def test_determine_character_attributes_calls_client(
        self, active_context, mock_scene
    ):
        """Test that determine_character_attributes calls the LLM client."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        # Return valid JSON that won't trigger AI fallback fixing
        creator.client.send_prompt.return_value = (
            '{"age": "early 30s", "occupation": "healer"}'
        )

        response = await creator.determine_character_attributes(character=character)

        # Verify response was returned
        assert response is not None

        # Verify the client was called (may be called multiple times for JSON fixing)
        assert creator.client.send_prompt.call_count >= 1

        # Get the first prompt that was sent (the main attributes prompt)
        call_args_list = creator.client.send_prompt.call_args_list
        prompt_text = call_args_list[0][0][0]
        assert "Elena" in prompt_text
        # Template should ask for JSON output
        assert "json" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_determine_character_name_calls_client(self, active_context):
        """Test that determine_character_name calls the LLM client."""
        creator = active_context
        creator.client.send_prompt.return_value = "<NAME>Elena</NAME>"

        response = await creator.determine_character_name(
            character_name="the tall woman with dark hair"
        )

        # Verify response was returned
        assert response is not None
        assert response == "Elena"

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify character description appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "tall woman" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_determine_character_name_with_allowed_names(self, active_context):
        """Test determine_character_name with allowed names list."""
        creator = active_context
        creator.client.send_prompt.return_value = "<NAME>Marcus</NAME>"

        response = await creator.determine_character_name(
            character_name="the mysterious stranger",
            allowed_names=["John", "Marcus", "Elena"],
        )

        assert response == "Marcus"

        # Verify allowed names appear in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert (
            "John" in prompt_text or "Marcus" in prompt_text or "Elena" in prompt_text
        )

    @pytest.mark.asyncio
    async def test_determine_character_name_group(self, active_context):
        """Test determine_character_name for group naming."""
        creator = active_context
        creator.client.send_prompt.return_value = "<NAME>The Guards</NAME>"

        response = await creator.determine_character_name(
            character_name="the guards standing at the gate", group=True
        )

        assert response == "The Guards"

        # Verify group reference appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "group" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_determine_character_description_calls_client(
        self, active_context, mock_scene
    ):
        """Test that determine_character_description calls the LLM client."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = (
            "Elena is a skilled healer with kind eyes."
        )

        response = await creator.determine_character_description(character=character)

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify character name appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_determine_character_description_with_text(
        self, active_context, mock_scene
    ):
        """Test determine_character_description with custom text."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = (
            "Elena is a skilled healer from the mountain village."
        )

        response = await creator.determine_character_description(
            character=character,
            text="Elena is a skilled healer from the mountain village.",
            instructions="Focus on her healing abilities.",
        )

        assert response is not None
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_determine_character_goals_calls_client(
        self, active_context, mock_scene
    ):
        """Test that determine_character_goals calls the LLM client."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        # Make set_detail an async mock
        character.set_detail = AsyncMock()
        creator.client.send_prompt.return_value = (
            "Elena wants to find a cure for the plague."
        )

        response = await creator.determine_character_goals(
            character=character, goal_instructions="Focus on character growth."
        )

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify names appear in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Elena" in prompt_text
        assert "Hero" in prompt_text  # Player character
        assert "goal" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_determine_character_dialogue_instructions_calls_client(
        self, active_context, mock_scene
    ):
        """Test that determine_character_dialogue_instructions calls the LLM client."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "Speaks softly with a gentle tone."

        response = await creator.determine_character_dialogue_instructions(
            character=character
        )

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify character name appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Elena" in prompt_text
        assert "dialogue" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_determine_character_dialogue_instructions_update(
        self, active_context, mock_scene
    ):
        """Test determine_character_dialogue_instructions with update_existing."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "Speaks formally and with authority."

        response = await creator.determine_character_dialogue_instructions(
            character=character,
            instructions="Make the dialogue more formal.",
            update_existing=True,
        )

        assert response is not None
        creator.client.send_prompt.assert_called_once()


class TestCreatorDialogueExamplesMethod:
    """Tests for determine_character_dialogue_examples method using Focal."""

    @pytest.mark.asyncio
    async def test_determine_character_dialogue_examples_calls_focal(
        self, active_context, mock_scene
    ):
        """Test that determine_character_dialogue_examples uses Focal handler."""
        creator = active_context
        character = mock_scene.get_character("Elena")

        # Mock the Focal handler's request to avoid actual LLM calls
        with patch("talemate.agents.creator.character.focal.Focal") as MockFocal:
            mock_focal_instance = Mock()
            mock_focal_instance.request = AsyncMock()
            mock_focal_instance.context = {}
            MockFocal.return_value = mock_focal_instance

            await creator.determine_character_dialogue_examples(
                character=character,
                text="Elena speaks softly but with great conviction.",
                max_examples=5,
            )

            # Verify Focal was created and request was called
            MockFocal.assert_called_once()
            mock_focal_instance.request.assert_called_once_with(
                "creator.determine-character-dialogue-examples"
            )


class TestCreatorScenarioMethods:
    """Tests for scenario creation methods."""

    @pytest.mark.asyncio
    async def test_determine_scenario_description_calls_client(self, active_context):
        """Test that determine_scenario_description calls the LLM client."""
        creator = active_context
        creator.client.send_prompt.return_value = (
            "A dark fantasy world where magic is forbidden."
        )

        response = await creator.determine_scenario_description(
            text="A dark fantasy world where magic is forbidden and the old gods have been forgotten."
        )

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify text appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "magic" in prompt_text.lower() or "fantasy" in prompt_text.lower()


class TestCreatorContextualGenerateMethod:
    """Tests for contextual_generate method."""

    @pytest.mark.asyncio
    async def test_contextual_generate_calls_client(self, active_context, mock_scene):
        """Test that contextual_generate calls the LLM client."""
        creator = active_context
        creator.client.send_prompt.return_value = "A detailed description of the world."

        generation_context = ContentGenerationContext(
            context="general:World History",
            instructions="Describe the world's history",
            length=100,
        )

        response = await creator.contextual_generate(generation_context)

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_contextual_generate_character_attribute(
        self, active_context, mock_scene
    ):
        """Test contextual_generate for character attribute."""
        creator = active_context
        creator.client.send_prompt.return_value = "healer"

        generation_context = ContentGenerationContext(
            context="character attribute:occupation",
            character="Elena",
            instructions="",
            length=192,
        )

        response = await creator.contextual_generate(generation_context)

        assert response is not None
        creator.client.send_prompt.assert_called_once()

        # Verify character context appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "occupation" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_contextual_generate_list_type(self, active_context, mock_scene):
        """Test contextual_generate for list type."""
        creator = active_context
        creator.client.send_prompt.return_value = '["sword", "shield", "potion"]'

        generation_context = ContentGenerationContext(
            context="list:Items in inventory",
            instructions="Generate inventory items",
            length=256,
        )

        response = await creator.contextual_generate(generation_context)

        # List type should return JSON
        assert response is not None
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_character_attribute_wrapper(
        self, active_context, mock_scene
    ):
        """Test generate_character_attribute wrapper method."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "healer"

        response = await creator.generate_character_attribute(
            character=character, attribute_name="occupation", instructions="Be creative"
        )

        assert response is not None
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_character_detail_wrapper(self, active_context, mock_scene):
        """Test generate_character_detail wrapper method."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = (
            "She learned healing from the forest hermits."
        )

        response = await creator.generate_character_detail(
            character=character,
            detail_name="background",
            instructions="Focus on her past",
        )

        assert response is not None
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_scene_title_wrapper(self, active_context, mock_scene):
        """Test generate_scene_title wrapper method."""
        creator = active_context
        creator.client.send_prompt.return_value = "The Forest Clearing"

        response = await creator.generate_scene_title(
            instructions="Create a title about the forest"
        )

        assert response is not None
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_thematic_list_wrapper(self, active_context, mock_scene):
        """Test generate_thematic_list wrapper method."""
        creator = active_context
        creator.client.send_prompt.return_value = '["sword", "shield", "potion"]'

        response = await creator.generate_thematic_list(
            instructions="Generate fantasy items", iterations=1
        )

        assert response is not None
        assert isinstance(response, list)


class TestCreatorAutocompleteMethods:
    """Tests for autocomplete methods."""

    @pytest.mark.asyncio
    async def test_autocomplete_dialogue_calls_client(self, active_context, mock_scene):
        """Test that autocomplete_dialogue calls the LLM client."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = (
            "<CONTINUE>that you are here</CONTINUE>"
        )

        response = await creator.autocomplete_dialogue(
            input="I am so glad", character=character, emit_signal=False
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

        # Verify character name appears in the prompt
        call_args = creator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_autocomplete_dialogue_extracts_continuation(
        self, active_context, mock_scene
    ):
        """Test that autocomplete_dialogue extracts continuation from tags."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = (
            "<CONTINUE>that you are here</CONTINUE>"
        )

        response = await creator.autocomplete_dialogue(
            input="I am so glad", character=character, emit_signal=False
        )

        # Should extract content from tags
        assert "that you are here" in response

    @pytest.mark.asyncio
    async def test_autocomplete_narrative_calls_client(
        self, active_context, mock_scene
    ):
        """Test that autocomplete_narrative calls the LLM client."""
        creator = active_context
        creator.client.send_prompt.return_value = (
            "<CONTINUE>and the wind howled through the trees</CONTINUE>"
        )

        response = await creator.autocomplete_narrative(
            input="The forest was dark", emit_signal=False
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_autocomplete_narrative_extracts_continuation(
        self, active_context, mock_scene
    ):
        """Test that autocomplete_narrative extracts continuation from tags."""
        creator = active_context
        creator.client.send_prompt.return_value = (
            "<CONTINUE>and the wind howled</CONTINUE>"
        )

        response = await creator.autocomplete_narrative(
            input="The forest was dark", emit_signal=False
        )

        # Should extract content from tags
        assert "and the wind howled" in response

    @pytest.mark.asyncio
    async def test_autocomplete_dialogue_with_custom_length(
        self, active_context, mock_scene
    ):
        """Test autocomplete_dialogue with custom response length."""
        creator = active_context
        character = mock_scene.get_character("Elena")
        creator.client.send_prompt.return_value = "<CONTINUE>hello</CONTINUE>"

        response = await creator.autocomplete_dialogue(
            input="I am", character=character, emit_signal=False, response_length=32
        )

        assert response is not None
        creator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_autocomplete_narrative_with_custom_length(
        self, active_context, mock_scene
    ):
        """Test autocomplete_narrative with custom response length."""
        creator = active_context
        creator.client.send_prompt.return_value = "<CONTINUE>quiet</CONTINUE>"

        response = await creator.autocomplete_narrative(
            input="The forest was", emit_signal=False, response_length=32
        )

        assert response is not None
        creator.client.send_prompt.assert_called_once()


class TestCreatorAgentProperties:
    """Tests for creator agent properties."""

    def test_autocomplete_dialogue_suggestion_length_property(self, creator_agent):
        """Test autocomplete_dialogue_suggestion_length property."""
        # Default value should be set from actions
        length = creator_agent.autocomplete_dialogue_suggestion_length
        assert isinstance(length, int)
        assert length > 0

    def test_autocomplete_narrative_suggestion_length_property(self, creator_agent):
        """Test autocomplete_narrative_suggestion_length property."""
        # Default value should be set from actions
        length = creator_agent.autocomplete_narrative_suggestion_length
        assert isinstance(length, int)
        assert length > 0
