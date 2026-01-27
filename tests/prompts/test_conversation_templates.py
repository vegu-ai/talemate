"""
Unit tests for conversation agent methods.

Tests that conversation agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

import talemate.instance as instance
from talemate.agents.conversation import ConversationAgent
from talemate.scene_message import CharacterMessage
from .helpers import create_mock_scene


class MockCharacter:
    """A mock character class for isinstance checks."""

    def __init__(self, name, is_player=False, actor=None):
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
        self.current_avatar = None
        self.actor = actor

    def random_dialogue_examples(self, scene=None, num=2, strip_name=False):
        """Return example dialogue lines."""
        return ["Hello there.", "How are you?"]


class MockActor:
    """A mock actor class that wraps a character."""

    def __init__(self, character, scene):
        self.character = character
        self.scene = scene
        # Set the actor reference on the character
        character.actor = self


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that returns predictable responses."""
    client = AsyncMock()
    # Return dialogue in the movie script format: CHARACTER_NAME\ndialogue
    client.send_prompt = AsyncMock(return_value="The forest was dark and quiet.\nEND-OF-LINE")
    client.max_token_length = 4096
    client.decensor_enabled = False
    client.can_be_coerced = True
    client.model_name = "test-model"
    client.data_format = "json"
    client.name = "test-client"
    return client


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
    scene.get_character = Mock(side_effect=lambda name: player if name == "Hero" else npc)
    scene.writing_style = None
    scene.agent_state = {}
    scene.count_messages = Mock(return_value=10)

    # Mock Character class for isinstance check - use MockCharacter
    scene.Character = MockCharacter

    # Mock main_character - needs to be an Actor with a character attribute
    main_actor = Mock()
    main_actor.character = player
    scene.main_character = main_actor

    # Add characters list for iteration
    scene.characters = [player, npc]

    # Mock intent_state
    intent_state = Mock()
    intent_state.active = False
    intent_state.intent = ""
    intent_state.instructions = ""
    intent_state.phase = Mock()
    intent_state.phase.intent = ""
    intent_state.current_scene_type = None
    scene.intent_state = intent_state

    return scene


@pytest.fixture
def mock_conversation_agent_for_registry():
    """Create a mock conversation agent for registry (for template agent_action calls)."""
    conv = Mock()
    conv.actions = {
        "content": Mock(),
    }
    conv.actions["content"].config = {
        "use_scene_intent": Mock(value=True),
        "use_writing_style": Mock(value=True),
    }
    conv.content_use_scene_intent = True
    conv.content_use_writing_style = True
    # rag_build is called by templates - needs to be an async function
    conv.rag_build = AsyncMock(return_value=[])
    return conv


@pytest.fixture
def conversation_agent(mock_llm_client, mock_scene):
    """Create a ConversationAgent instance with mocked dependencies."""
    agent = ConversationAgent(client=mock_llm_client)
    agent.scene = mock_scene
    return agent


@pytest.fixture
def setup_agents(mock_conversation_agent_for_registry):
    """Set up the agent registry with mocked agents."""
    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Set up mock agents in the registry
    instance.AGENTS["conversation"] = mock_conversation_agent_for_registry

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(conversation_agent, mock_scene, setup_agents):
    """Set up active scene context for tests."""
    from talemate.context import active_scene

    scene_token = active_scene.set(mock_scene)

    yield conversation_agent

    active_scene.reset(scene_token)


class TestConverseMethod:
    """Tests for the converse() method which is the main agent method that calls the LLM."""

    @pytest.mark.asyncio
    async def test_converse_calls_client(self, active_context, mock_scene):
        """Test that converse calls the LLM client with rendered prompt."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        messages = await agent.converse(actor)

        # Verify response was returned
        assert messages is not None
        assert len(messages) > 0
        assert isinstance(messages[0], CharacterMessage)

        # Verify the client's send_prompt was called
        agent.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]  # First positional arg is the prompt

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0

    @pytest.mark.asyncio
    async def test_converse_with_instruction(self, active_context, mock_scene):
        """Test that converse includes instruction in the prompt."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)
        instruction = "Express surprise about the weather"

        await agent.converse(actor, instruction=instruction)

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify instruction appears in the prompt
        assert instruction in prompt_text

    @pytest.mark.asyncio
    async def test_converse_movie_script_format(self, active_context, mock_scene):
        """Test converse with movie_script format (default)."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        # Ensure movie_script format is used
        agent.actions["generation_override"].config["format"].value = "movie_script"

        await agent.converse(actor)

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Movie script format should mention screenplay
        assert "screenplay" in prompt_text.lower()
        # Should include END-OF-LINE instruction
        assert "end-of-line" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_converse_chat_format(self, active_context, mock_scene):
        """Test converse with chat format."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        # Set chat format
        agent.actions["generation_override"].config["format"].value = "chat"

        await agent.converse(actor)

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Chat format should mention roleplaying session
        assert "roleplaying" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_converse_narrative_format(self, active_context, mock_scene):
        """Test converse with narrative format."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        # Set narrative format
        agent.actions["generation_override"].config["format"].value = "narrative"

        await agent.converse(actor)

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Narrative format should mention novel-style
        assert "novel" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_converse_includes_character_sheet(self, active_context, mock_scene):
        """Test that converse includes character information in the prompt."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        await agent.converse(actor)

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Character name should appear in the prompt
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_converse_includes_scene_context(self, active_context, mock_scene):
        """Test that converse includes scene context in the prompt."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        await agent.converse(actor)

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Scene description should be included
        assert mock_scene.description in prompt_text or "scene" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_converse_with_decensor(self, active_context, mock_scene, mock_llm_client):
        """Test converse with decensor enabled."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        # Enable decensor
        mock_llm_client.decensor_enabled = True

        await agent.converse(actor)

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Should include decensor-related text (fiction/consent)
        assert "fiction" in prompt_text.lower() or "consent" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_converse_response_contains_character_name(self, active_context, mock_scene):
        """Test that converse response is prefixed with character name."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        messages = await agent.converse(actor)

        # The response should start with the character name
        assert messages[0].message.startswith("Elena:")

    @pytest.mark.asyncio
    async def test_converse_with_task_instructions(self, active_context, mock_scene):
        """Test converse with custom task instructions."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        actor = MockActor(npc, mock_scene)

        # Set custom task instructions
        agent.actions["generation_override"].config["instructions"].value = "Be extra dramatic"

        await agent.converse(actor)

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Task instructions should appear in prompt
        assert "extra dramatic" in prompt_text.lower()


class TestConverseWithDifferentCharacters:
    """Tests for converse with different character configurations."""

    @pytest.mark.asyncio
    async def test_converse_with_dialogue_instructions(self, active_context, mock_scene):
        """Test that dialogue instructions are included in the prompt."""
        agent = active_context
        npc = mock_scene.get_character("Elena")
        npc.dialogue_instructions = "Always speak in riddles and metaphors"
        actor = MockActor(npc, mock_scene)

        await agent.converse(actor)

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Dialogue instructions should appear in prompt
        assert "riddles" in prompt_text.lower() or "metaphors" in prompt_text.lower()


class TestCleanResult:
    """Tests for the clean_result method."""

    def test_clean_result_removes_hash_comments(self, conversation_agent):
        """Test that clean_result removes content after #."""
        result = conversation_agent.clean_result(
            "Hello there.# This is a comment",
            Mock(name="Elena")
        )

        assert "#" not in result
        assert "Hello there" in result

    def test_clean_result_removes_internal_markers(self, conversation_agent):
        """Test that clean_result removes (Internal markers."""
        result = conversation_agent.clean_result(
            "Hello there.(Internal thought: this is hidden)",
            Mock(name="Elena")
        )

        assert "(Internal" not in result
        assert "Hello there" in result

    def test_clean_result_fixes_spacing(self, conversation_agent):
        """Test that clean_result fixes ' :' spacing."""
        result = conversation_agent.clean_result(
            "Elena : Hello there.",
            Mock(name="Elena")
        )

        assert " :" not in result


class TestConversationProperties:
    """Tests for conversation agent properties."""

    def test_conversation_format_property(self, conversation_agent):
        """Test conversation_format property returns correct format."""
        conversation_agent.actions["generation_override"].enabled = True
        conversation_agent.actions["generation_override"].config["format"].value = "narrative"

        assert conversation_agent.conversation_format == "narrative"

    def test_conversation_format_default(self, conversation_agent):
        """Test conversation_format defaults to movie_script when disabled."""
        conversation_agent.actions["generation_override"].enabled = False

        assert conversation_agent.conversation_format == "movie_script"

    def test_generation_settings_task_instructions(self, conversation_agent):
        """Test generation_settings_task_instructions property."""
        conversation_agent.actions["generation_override"].config["instructions"].value = "Test instruction"

        assert conversation_agent.generation_settings_task_instructions == "Test instruction"

    def test_generation_settings_response_length(self, conversation_agent):
        """Test generation_settings_response_length property."""
        conversation_agent.actions["generation_override"].config["length"].value = 256

        assert conversation_agent.generation_settings_response_length == 256


class TestAllowRepetitionBreak:
    """Tests for allow_repetition_break method."""

    def test_allows_repetition_break_for_converse(self, conversation_agent):
        """Test that repetition break is allowed for converse."""
        assert conversation_agent.allow_repetition_break("any", "converse") is True

    def test_disallows_repetition_break_for_other_methods(self, conversation_agent):
        """Test that repetition break is not allowed for other methods."""
        assert conversation_agent.allow_repetition_break("any", "other_method") is False
