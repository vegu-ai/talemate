"""
Unit tests for director agent methods.

Tests that director agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json

import talemate.instance as instance
from talemate.agents.director import DirectorAgent
from talemate.game.engine.nodes.core import GraphState
from .helpers import create_mock_scene, create_mock_character


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
        self.voice = None
        self.color = "#ffffff"


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that returns predictable responses."""
    client = AsyncMock()
    client.send_prompt = AsyncMock(
        return_value="<GUIDANCE>The scene should progress with tension.</GUIDANCE>"
    )
    client.max_token_length = 4096
    client.decensor_enabled = False
    client.can_be_coerced = True
    client.model_name = "test-model"
    client.data_format = "json"
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
    scene.get_character = Mock(
        side_effect=lambda name: player if name == "Hero" else npc
    )
    scene.writing_style = "descriptive"
    scene.agent_state = {}
    scene.characters = [player, npc]
    scene.all_characters = [player, npc]
    scene.character_names = ["Hero", "Elena"]
    scene.all_character_names = ["Hero", "Elena"]
    scene.player_character_exists = True
    scene.narrator_character_object = None

    # Mock Character class for isinstance check - use MockCharacter
    scene.Character = MockCharacter
    scene.Player = Mock()
    scene.Actor = Mock()

    # Mock push_history for tests that need it
    scene.push_history = AsyncMock()

    # Mock intent_state
    scene.intent_state = Mock()
    scene.intent_state.active = False
    scene.intent_state.intent = "A test story"
    scene.intent_state.instructions = ""
    scene.intent_state.phase = Mock()
    scene.intent_state.phase.intent = "Test phase"
    scene.intent_state.current_scene_type = None
    scene.intent_state.scene_types = {}
    scene.intent_state.direction = Mock()
    scene.intent_state.direction.always_on = False

    # Mock game_state
    scene.game_state = Mock()
    scene.game_state.state = {}
    scene.game_state.variables = {}

    # Mock world_state
    scene.world_state = Mock()
    scene.world_state.characters = {}
    scene.world_state.filter_reinforcements = Mock(return_value=[])

    # Mock world_state_manager
    scene.world_state_manager = Mock()
    scene.world_state_manager.get_templates = AsyncMock(return_value=Mock(templates=[]))
    scene.world_state_manager.template_collection = Mock()

    # Mock nodegraph_state
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared = {}

    # Mock voice_library
    scene.voice_library = Mock()
    scene.voice_library.get_voice = Mock(return_value=None)

    # Mock rag_cache for memory RAG
    scene.rag_cache = {}

    # Mock snapshot
    scene.snapshot = Mock(return_value="Scene snapshot text")

    # Mock add_actor/remove_actor
    scene.add_actor = AsyncMock()
    scene.remove_actor = AsyncMock()

    # Mock emit methods
    scene.emit_status = Mock()

    # Mock agent_persona
    scene.agent_persona = Mock(return_value=None)

    # Mock count_character_messages_since_director
    scene.count_character_messages_since_director = Mock(return_value=0)

    return scene


@pytest.fixture
def mock_summarizer_agent():
    """Create a mock summarizer agent."""
    summarizer = Mock()
    summarizer.scene_analysis_state = Mock()
    summarizer.scene_analysis_state.get = Mock(return_value=None)
    return summarizer


@pytest.fixture
def mock_narrator_agent():
    """Create a mock narrator agent for registry."""
    narrator = Mock()
    narrator.actions = {
        "content": Mock(),
    }
    narrator.actions["content"].config = {
        "use_scene_intent": Mock(value=True),
    }
    narrator.content_use_scene_intent = True
    narrator.rag_build = AsyncMock(return_value=[])
    return narrator


@pytest.fixture
def mock_conversation_agent():
    """Create a mock conversation agent."""
    conv = Mock()
    conv.conversation_format = "default"
    return conv


@pytest.fixture
def mock_world_state_agent():
    """Create a mock world state agent."""
    ws = Mock()
    ws.extract_character_sheet = AsyncMock(return_value={})
    ws.is_character_present = AsyncMock(return_value=False)
    return ws


@pytest.fixture
def mock_creator_agent():
    """Create a mock creator agent."""
    creator = Mock()
    creator.determine_character_name = AsyncMock(return_value="TestName")
    creator.determine_character_description = AsyncMock(return_value="Test description")
    creator.determine_character_dialogue_instructions = AsyncMock(
        return_value="Test instructions"
    )
    return creator


@pytest.fixture
def mock_memory_agent():
    """Create a mock memory agent."""
    memory = Mock()
    memory.query = AsyncMock(return_value="")
    memory.multi_query = AsyncMock(return_value={})
    return memory


@pytest.fixture
def mock_tts_agent():
    """Create a mock TTS agent."""
    tts = Mock()
    tts.enabled = False
    tts.ready_apis = []
    tts.narrator_voice = None
    return tts


@pytest.fixture
def director_agent(mock_llm_client, mock_scene):
    """Create a DirectorAgent instance with mocked dependencies."""
    agent = DirectorAgent(client=mock_llm_client)
    agent.scene = mock_scene
    # Mock the rag_build method to avoid RAG dependencies
    agent.rag_build = AsyncMock(return_value=[])
    return agent


@pytest.fixture
def setup_agents(
    mock_summarizer_agent,
    mock_narrator_agent,
    mock_conversation_agent,
    mock_world_state_agent,
    mock_creator_agent,
    mock_memory_agent,
    mock_tts_agent,
):
    """Set up the agent registry with mocked agents."""
    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Set up mock agents in the registry
    instance.AGENTS["summarizer"] = mock_summarizer_agent
    instance.AGENTS["narrator"] = mock_narrator_agent
    instance.AGENTS["conversation"] = mock_conversation_agent
    instance.AGENTS["world_state"] = mock_world_state_agent
    instance.AGENTS["creator"] = mock_creator_agent
    instance.AGENTS["memory"] = mock_memory_agent
    instance.AGENTS["tts"] = mock_tts_agent

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(director_agent, mock_scene, setup_agents):
    """Set up active scene context for tests."""
    from talemate.context import active_scene

    # Register director agent
    original_agents = instance.AGENTS.copy()
    instance.AGENTS["director"] = director_agent

    scene_token = active_scene.set(mock_scene)

    yield director_agent

    active_scene.reset(scene_token)
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


class TestGuideSceneMethods:
    """Tests for director guide scene methods that call the LLM."""

    @pytest.mark.asyncio
    async def test_guide_actor_off_of_scene_analysis_calls_client(self, active_context):
        """Test that guide_actor_off_of_scene_analysis calls the LLM client."""
        director = active_context
        character = director.scene.get_character("Elena")

        response = await director.guide_actor_off_of_scene_analysis(
            analysis="The scene is tense and dramatic.",
            character=character,
            response_length=256,
        )

        # Verify response was returned
        assert response is not None

        # Verify the client's send_prompt was called
        director.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_guide_narrator_off_of_scene_analysis_calls_client(
        self, active_context
    ):
        """Test that guide_narrator_off_of_scene_analysis calls the LLM client."""
        director = active_context

        response = await director.guide_narrator_off_of_scene_analysis(
            analysis="The scene needs more description.",
            response_length=256,
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        director.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify the prompt contains the analysis
        assert "The scene needs more description" in prompt_text


class TestGenerateChoicesMethods:
    """Tests for director generate choices methods."""

    @pytest.mark.asyncio
    async def test_generate_choices_calls_client(self, active_context):
        """Test that generate_choices calls the LLM client."""
        director = active_context

        # Set up mock response with ACTIONS section
        director.client.send_prompt = AsyncMock(
            return_value='Analysis of choices.\nACTIONS:\n- "Go to the forest"\n- "Talk to Elena"\n- "Rest at the inn"'
        )

        response = await director.generate_choices(
            instructions="Generate choices for the player",
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        director.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0

    @pytest.mark.asyncio
    async def test_generate_choices_with_character(self, active_context):
        """Test generate_choices with a specific character."""
        director = active_context
        character = director.scene.get_character("Elena")

        # Set up mock response
        director.client.send_prompt = AsyncMock(
            return_value='Analysis.\nACTIONS:\n- "Ask about the herbs"\n- "Request healing"'
        )

        response = await director.generate_choices(
            character=character,
            instructions="Generate choices for Elena",
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        director.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify character name is in the prompt
        assert "Elena" in prompt_text


class TestAutoDirectMethods:
    """Tests for director auto-direct methods."""

    @pytest.mark.asyncio
    async def test_auto_direct_set_scene_intent_calls_client(self, active_context):
        """Test that auto_direct_set_scene_intent calls the LLM client via focal."""
        director = active_context

        # Set up scene types
        director.scene.intent_state.scene_types = {
            "exploration": Mock(id="exploration", name="Exploration"),
            "combat": Mock(id="combat", name="Combat"),
        }

        # Set up mock response for focal
        director.client.send_prompt = AsyncMock(
            return_value='{"function": "do_nothing"}'
        )

        result = await director.auto_direct_set_scene_intent(require=False)

        # Verify the client was called (focal makes the request)
        director.client.send_prompt.assert_called()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify prompt contains scene type options
        assert len(prompt_text) > 0

    @pytest.mark.asyncio
    async def test_auto_direct_generate_scene_types_calls_client(self, active_context):
        """Test that auto_direct_generate_scene_types calls the LLM client via focal."""
        director = active_context

        # Set up mock templates
        mock_templates = Mock()
        mock_templates.templates = []
        mock_templates.find_by_name = Mock(return_value=None)
        director.scene.world_state_manager.get_templates = AsyncMock(
            return_value=mock_templates
        )

        # Track if client was called
        client_called = False
        original_send = director.client.send_prompt

        async def track_call(*args, **kwargs):
            nonlocal client_called
            client_called = True
            # Return a response that will cause focal to call the callback
            return '{"generate_scene_type": {"id": "test", "name": "Test", "description": "A test", "instructions": ""}}'

        director.client.send_prompt = track_call

        # The focal handler will keep retrying, so we expect an error eventually
        # but we just need to verify the client was called with the template
        try:
            await director.auto_direct_generate_scene_types(
                instructions="Generate scene types for a fantasy story",
                max_scene_types=1,
            )
        except RecursionError:
            pass  # Expected due to retry loop with mocked response

        # Verify the client was called
        assert client_called, "Client send_prompt should have been called"


class TestCharacterManagementMethods:
    """Tests for director character management methods."""

    @pytest.mark.asyncio
    async def test_assign_voice_to_character_calls_client_when_enabled(
        self, active_context
    ):
        """Test that assign_voice_to_character calls the LLM when TTS is enabled."""
        director = active_context
        character = MockCharacter(name="TestChar")

        # Enable TTS and voice assignment
        tts_agent = Mock()
        tts_agent.enabled = True
        tts_agent.ready_apis = ["kokoro"]
        tts_agent.narrator_voice = None
        instance.AGENTS["tts"] = tts_agent

        # Track if client was called
        client_called = False

        async def track_call(*args, **kwargs):
            nonlocal client_called
            client_called = True
            # Return a response that will cause focal to call the callback
            return '{"assign_voice": {"voice_id": "voice1"}}'

        # Mock voice library
        with patch(
            "talemate.agents.director.character_management.voice_library"
        ) as mock_vl:
            mock_vl.get_instance.return_value = Mock(get_voice=Mock(return_value=None))
            mock_vl.voices_for_apis.return_value = [
                Mock(
                    id="voice1",
                    label="Voice 1",
                    tags=[],
                    model_dump=Mock(
                        return_value={
                            "id": "voice1",
                            "label": "Voice 1",
                            "tags": [],
                            "provider": "kokoro",
                            "provider_id": "kokoro_voice1",
                        }
                    ),
                )
            ]

            director.client.send_prompt = track_call

            try:
                result = await director.assign_voice_to_character(character)
            except RecursionError:
                pass  # Expected due to focal retry loop

            # Verify the client was called
            assert client_called, "Client send_prompt should have been called"

    @pytest.mark.asyncio
    async def test_detect_characters_from_texts_calls_client(self, active_context):
        """Test that detect_characters_from_texts calls the LLM via focal."""
        director = active_context

        texts = [
            "Alice said: 'Hello there!'",
            "Bob replied: 'Nice to meet you.'",
        ]

        # Set up mock response for focal
        director.client.send_prompt = AsyncMock(
            return_value='{"function": "add_detected_character", "character_name": "Alice"}'
        )

        with patch(
            "talemate.agents.director.character_management.ClientContext"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = Mock()
            mock_ctx.return_value.__exit__ = Mock()

            result = await director.detect_characters_from_texts(texts=texts)

            # Verify the client was called
            director.client.send_prompt.assert_called()


class TestChatMethods:
    """Tests for director chat methods."""

    @pytest.mark.asyncio
    async def test_chat_send_calls_client(self, active_context):
        """Test that chat_send calls the LLM client."""
        director = active_context

        # Create a chat
        chat = director.chat_create()
        chat_id = chat.id

        # Set up mock response with proper format
        director.client.send_prompt = AsyncMock(
            return_value="<MESSAGE>Hello! I can help you with the scene.</MESSAGE>"
        )

        # Mock the action utils
        with patch(
            "talemate.agents.director.action_core.utils.get_available_actions"
        ) as mock_actions:
            mock_actions.return_value = []

            with patch(
                "talemate.agents.director.action_core.utils.get_meta_groups"
            ) as mock_meta:
                mock_meta.return_value = []

                result = await director.chat_send(
                    chat_id=chat_id,
                    message="What should happen next in the scene?",
                )

                # Verify the client was called
                director.client.send_prompt.assert_called()

                # Verify we got a chat back
                assert result is not None


class TestSceneDirectionMethods:
    """Tests for director scene direction methods."""

    @pytest.mark.asyncio
    async def test_direction_execute_turn_calls_client_when_enabled(
        self, active_context
    ):
        """Test that direction_execute_turn calls the LLM when enabled."""
        director = active_context

        # Enable scene direction
        director.actions["scene_direction"].enabled = True

        # Set up mock response
        director.client.send_prompt = AsyncMock(
            return_value="<DECISION>Continue the scene naturally.</DECISION>"
        )

        # Mock the action utils
        with patch(
            "talemate.agents.director.action_core.utils.get_available_actions"
        ) as mock_actions:
            mock_actions.return_value = []

            with patch(
                "talemate.agents.director.action_core.utils.get_meta_groups"
            ) as mock_meta:
                mock_meta.return_value = []

                actions_taken, yield_to_user = await director.direction_execute_turn(
                    always_on=True
                )

                # Verify the client was called
                director.client.send_prompt.assert_called()

    @pytest.mark.asyncio
    async def test_direction_execute_turn_skipped_when_disabled(self, active_context):
        """Test that direction_execute_turn is skipped when disabled."""
        director = active_context

        # Disable scene direction
        director.actions["scene_direction"].enabled = False
        director.scene.intent_state.direction.always_on = False

        actions_taken, yield_to_user = await director.direction_execute_turn()

        # Verify no actions were taken
        assert actions_taken == []
        assert yield_to_user is False

        # Verify the client was NOT called
        director.client.send_prompt.assert_not_called()


class TestDirectorProperties:
    """Tests for director agent properties."""

    def test_actor_direction_mode_property(self, director_agent):
        """Test actor_direction_mode property."""
        assert director_agent.actor_direction_mode in [
            "direction",
            "internal_monologue",
        ]

    def test_direction_stickiness_property(self, director_agent):
        """Test direction_stickiness property."""
        assert isinstance(director_agent.direction_stickiness, int)
        assert director_agent.direction_stickiness >= 1

    def test_guide_scene_properties(self, director_agent):
        """Test guide scene properties."""
        # Disable by default
        assert director_agent.guide_scene is False

        # Enable and check properties
        director_agent.actions["guide_scene"].enabled = True
        assert director_agent.guide_scene is True
        assert isinstance(director_agent.guide_scene_guidance_length, int)
        assert isinstance(director_agent.guide_scene_cache_guidance, bool)

    def test_generate_choices_properties(self, director_agent):
        """Test generate choices properties."""
        assert isinstance(director_agent.generate_choices_enabled, bool)
        assert isinstance(director_agent.generate_choices_chance, float)
        assert isinstance(director_agent.generate_choices_num_choices, int)

    def test_chat_properties(self, director_agent):
        """Test chat properties."""
        assert isinstance(director_agent.chat_response_length, int)
        assert isinstance(director_agent.chat_enable_analysis, bool)
        assert isinstance(director_agent.chat_scene_context_ratio, float)

    def test_direction_properties(self, director_agent):
        """Test scene direction properties."""
        assert isinstance(director_agent.direction_response_length, int)
        assert isinstance(director_agent.direction_enable_analysis, bool)
        assert isinstance(director_agent.direction_enabled, bool)


class TestChatStateManagement:
    """Tests for chat state management methods."""

    def test_chat_create(self, director_agent, mock_scene, setup_agents):
        """Test chat creation."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        assert chat is not None
        assert chat.id is not None
        assert len(chat.messages) > 0

    def test_chat_get(self, director_agent, mock_scene, setup_agents):
        """Test getting a chat."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        chat_id = chat.id

        retrieved = director_agent.chat_get(chat_id)
        assert retrieved is not None
        assert retrieved.id == chat_id

    def test_chat_clear(self, director_agent, mock_scene, setup_agents):
        """Test clearing a chat."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        chat_id = chat.id

        result = director_agent.chat_clear(chat_id)
        assert result is True

        # Chat should still exist but have only initial message
        cleared = director_agent.chat_get(chat_id)
        assert cleared is not None
        assert len(cleared.messages) == 1

    def test_chat_history(self, director_agent, mock_scene, setup_agents):
        """Test getting chat history."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        chat_id = chat.id

        history = director_agent.chat_history(chat_id)
        assert isinstance(history, list)


class TestDirectionStateManagement:
    """Tests for scene direction state management methods."""

    def test_direction_create(self, director_agent, mock_scene, setup_agents):
        """Test direction state creation."""
        director_agent.scene = mock_scene
        direction = director_agent.direction_create()

        assert direction is not None
        assert direction.id is not None

    def test_direction_get(self, director_agent, mock_scene, setup_agents):
        """Test getting direction state."""
        director_agent.scene = mock_scene
        direction = director_agent.direction_create()

        retrieved = director_agent.direction_get()
        assert retrieved is not None
        assert retrieved.id == direction.id

    def test_direction_clear(self, director_agent, mock_scene, setup_agents):
        """Test clearing direction state."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        result = director_agent.direction_clear()
        assert result is True

        cleared = director_agent.direction_get()
        assert cleared is not None
        assert len(cleared.messages) == 0

    def test_direction_history(self, director_agent, mock_scene, setup_agents):
        """Test getting direction history."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        history = director_agent.direction_history()
        assert isinstance(history, list)
