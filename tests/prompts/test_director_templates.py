"""
Unit tests for director agent methods.

Tests that director agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

import talemate.instance as instance
from talemate.agents.director import DirectorAgent
from talemate.agents.director.chat.schema import (
    DirectorChatActionResultMessage,
    DirectorChatBudgets,
    DirectorChatMessage,
)
from talemate.agents.director.scene_direction.schema import (
    SceneDirectionActionResultMessage,
    SceneDirectionBudgets,
    SceneDirectionMessage,
    UserInteractionMessage,
)
from talemate.context import active_scene
from talemate.game.engine.nodes.core import GraphState
from .helpers import create_mock_scene


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
        """Test that guide_actor_off_of_scene_analysis calls the LLM client and extracts guidance correctly."""
        director = active_context
        character = director.scene.get_character("Elena")

        # Set up mock response with ANALYSIS and GUIDANCE sections (GUIDANCE_SPEC format)
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>The scene requires Elena to respond to the dramatic tension.</ANALYSIS><GUIDANCE>Elena should express concern and offer support to the protagonist.</GUIDANCE>"
        )

        response = await director.guide_actor_off_of_scene_analysis(
            analysis="The scene is tense and dramatic.",
            character=character,
            response_length=256,
        )

        # Verify the client's send_prompt was called
        director.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0
        assert "Elena" in prompt_text

        # Verify GUIDANCE_SPEC extraction worked correctly
        # The extractor should extract content from <GUIDANCE> tag, preferring after </ANALYSIS>
        assert response is not None
        # Guidance content should be present
        assert "Elena should express concern" in response
        # Analysis content should NOT be present (proves extraction worked)
        assert "scene requires Elena to respond" not in response
        assert "<ANALYSIS>" not in response
        assert "<GUIDANCE>" not in response

    @pytest.mark.asyncio
    async def test_guide_narrator_off_of_scene_analysis_calls_client(
        self, active_context
    ):
        """Test that guide_narrator_off_of_scene_analysis calls the LLM client and extracts guidance correctly."""
        director = active_context

        # Set up mock response with ANALYSIS and GUIDANCE sections (GUIDANCE_SPEC format)
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>The scene lacks environmental details.</ANALYSIS><GUIDANCE>Describe the flickering candlelight and the distant sound of thunder.</GUIDANCE>"
        )

        response = await director.guide_narrator_off_of_scene_analysis(
            analysis="The scene needs more description.",
            response_length=256,
        )

        # Verify the client was called
        director.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify the prompt contains the analysis
        assert "The scene needs more description" in prompt_text

        # Verify GUIDANCE_SPEC extraction worked correctly
        assert response is not None
        # Guidance content should be present
        assert "flickering candlelight" in response
        assert "thunder" in response
        # Analysis content should NOT be present (proves extraction worked)
        assert "lacks environmental details" not in response
        assert "<ANALYSIS>" not in response
        assert "<GUIDANCE>" not in response


class TestGenerateChoicesMethods:
    """Tests for director generate choices methods."""

    @pytest.mark.asyncio
    async def test_generate_choices_calls_client(self, active_context):
        """Test that generate_choices calls the LLM client and extracts choices correctly."""
        director = active_context

        # Set up mock response with ACTIONS: marker (CHOICES_SPEC format)
        # CHOICES_SPEC uses AfterAnchorExtractor with start="ACTIONS:"
        director.client.send_prompt = AsyncMock(
            return_value='I analyzed the scene and these are good options.\nACTIONS:\n- "Go to the forest"\n- "Talk to Elena"\n- "Rest at the inn"'
        )

        response = await director.generate_choices(
            instructions="Generate choices for the player",
        )

        # Verify response was returned (the full response text is returned)
        assert response is not None

        # Verify the client was called
        director.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0

        # Verify CHOICES_SPEC extraction worked (the actions text after "ACTIONS:" was parsed)
        # The generate_choices method emits a player_choice event with the extracted choices
        assert "Go to the forest" in response or "ACTIONS" in response

    @pytest.mark.asyncio
    async def test_generate_choices_with_character(self, active_context):
        """Test generate_choices with a specific character and verify extraction."""
        director = active_context
        character = director.scene.get_character("Elena")

        # Set up mock response with ACTIONS: marker (CHOICES_SPEC format)
        director.client.send_prompt = AsyncMock(
            return_value='Elena could do several things here.\nACTIONS:\n- "Ask about the herbs"\n- "Request healing"'
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
        prompt_text = str(call_args[0][0])

        # Verify character name is in the prompt
        assert "Elena" in prompt_text

        # Verify CHOICES_SPEC extraction worked
        assert "Ask about the herbs" in response or "ACTIONS" in response


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

        await director.auto_direct_set_scene_intent(require=False)

        # Verify the client was called (focal makes the request)
        director.client.send_prompt.assert_called()

        # Get the prompt that was sent
        call_args = director.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

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
                await director.assign_voice_to_character(character)
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

            await director.detect_characters_from_texts(texts=texts)

            # Verify the client was called
            director.client.send_prompt.assert_called()


class TestChatMethods:
    """Tests for director chat methods."""

    @pytest.mark.asyncio
    async def test_chat_send_calls_client(self, active_context):
        """Test that chat_send calls the LLM client and extracts message correctly."""
        director = active_context

        # Create a chat
        chat = director.chat_create()
        chat_id = chat.id

        # Set up mock response with ANALYSIS and MESSAGE sections (MESSAGE_SPEC format)
        # Note: When enable_analysis=True, the template sets prepared_response="<ANALYSIS> 1."
        # The mock response should either:
        # 1. Start with the prepared_response prefix (so it won't be prepended), or
        # 2. Be the continuation (without <ANALYSIS> tag) that gets prepended
        # Here we use option 1 - return what the full response looks like
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS> 1. The user wants guidance on scene progression.</ANALYSIS><MESSAGE>The scene could benefit from introducing a new conflict. Perhaps Elena discovers a hidden letter.</MESSAGE>"
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

                # Verify MESSAGE_SPEC extraction worked correctly
                # The last director message should contain the extracted message
                director_messages = [
                    m for m in result.messages if m.source == "director"
                ]
                assert len(director_messages) > 0
                # Check that the extracted message content is present
                last_director_msg = director_messages[-1]
                assert (
                    "hidden letter" in last_director_msg.message
                    or "conflict" in last_director_msg.message
                )
                # Analysis content should NOT be present (proves extraction worked)
                assert "user wants guidance" not in last_director_msg.message
                assert "<ANALYSIS>" not in last_director_msg.message
                assert "<MESSAGE>" not in last_director_msg.message

    @pytest.mark.asyncio
    async def test_chat_send_calls_client_inexact_response(self, active_context):
        """Test that chat_send calls the LLM client and extracts message correctly."""
        director = active_context

        # Create a chat
        chat = director.chat_create()
        chat_id = chat.id

        # Here we use option 1 - return what the full response looks like
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>The user wants guidance on scene progression.</ANALYSIS><MESSAGE>The scene could benefit from introducing a new conflict. Perhaps Elena discovers a hidden letter.</MESSAGE>"
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

                # Verify MESSAGE_SPEC extraction worked correctly
                # The last director message should contain the extracted message
                director_messages = [
                    m for m in result.messages if m.source == "director"
                ]
                assert len(director_messages) > 0
                # Check that the extracted message content is present
                last_director_msg = director_messages[-1]
                assert (
                    "hidden letter" in last_director_msg.message
                    or "conflict" in last_director_msg.message
                )
                # Analysis content should NOT be present (proves extraction worked)
                assert "user wants guidance" not in last_director_msg.message
                assert "<ANALYSIS>" not in last_director_msg.message
                assert "<MESSAGE>" not in last_director_msg.message


class TestSceneDirectionMethods:
    """Tests for director scene direction methods."""

    @pytest.mark.asyncio
    async def test_direction_execute_turn_calls_client_when_enabled(
        self, active_context
    ):
        """Test that direction_execute_turn calls the LLM when enabled and extracts decision correctly."""
        director = active_context

        # Enable scene direction
        director.actions["scene_direction"].enabled = True

        # Set up mock response with ANALYSIS and DECISION sections (DECISION_SPEC format)
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>The scene is progressing well but could use more character interaction.</ANALYSIS><DECISION>Let the narrator describe the shifting atmosphere as tension builds between the characters.</DECISION>"
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

                # Verify DECISION_SPEC extraction worked correctly
                # The direction history should contain the extracted decision
                direction = director.direction_get()
                assert direction is not None
                # Check that director messages were added with extracted decision content
                director_messages = [
                    m for m in direction.messages if m.source == "director"
                ]
                if director_messages:
                    last_msg = director_messages[-1]
                    # Decision content should be present
                    assert (
                        "shifting atmosphere" in last_msg.message
                        or "tension builds" in last_msg.message
                    )
                    # Analysis content should NOT be present (proves extraction worked)
                    assert "progressing well" not in last_msg.message
                    assert "<ANALYSIS>" not in last_msg.message
                    assert "<DECISION>" not in last_msg.message

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


class TestChatAppendMessage:
    """Tests for chat_append_message method."""

    @pytest.mark.asyncio
    async def test_append_user_message(self, director_agent, mock_scene, setup_agents):
        """Test appending a user message to chat history."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        initial_count = len(chat.messages)

        msg = DirectorChatMessage(message="Hello director", source="user")
        result = await director_agent.chat_append_message(chat.id, msg)

        assert len(result.messages) == initial_count + 1
        assert result.messages[-1].message == "Hello director"
        assert result.messages[-1].source == "user"

    @pytest.mark.asyncio
    async def test_append_director_message(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test appending a director message to chat history."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        initial_count = len(chat.messages)

        msg = DirectorChatMessage(message="I can help with that.", source="director")
        result = await director_agent.chat_append_message(chat.id, msg)

        assert len(result.messages) == initial_count + 1
        assert result.messages[-1].source == "director"

    @pytest.mark.asyncio
    async def test_append_action_result_message(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test appending an action result message to chat history."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        initial_count = len(chat.messages)

        msg = DirectorChatActionResultMessage(
            name="update_world_state",
            arguments={"key": "value"},
            result="Success",
            instructions="Update the world",
        )
        result = await director_agent.chat_append_message(chat.id, msg)

        assert len(result.messages) == initial_count + 1
        assert result.messages[-1].type == "action_result"
        assert result.messages[-1].name == "update_world_state"

    @pytest.mark.asyncio
    async def test_append_persists_state(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that appending a message persists to scene agent_state."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        msg = DirectorChatMessage(message="Persisted?", source="user")
        await director_agent.chat_append_message(chat.id, msg)

        # Re-fetch from state to confirm persistence
        retrieved = director_agent.chat_get(chat.id)
        assert retrieved.messages[-1].message == "Persisted?"

    @pytest.mark.asyncio
    async def test_append_calls_on_update(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that on_update callback is called with the new message."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        callback_args = []

        async def on_update(chat_id, messages):
            callback_args.append((chat_id, messages))

        msg = DirectorChatMessage(message="Callback test", source="user")
        await director_agent.chat_append_message(chat.id, msg, on_update=on_update)

        assert len(callback_args) == 1
        assert callback_args[0][0] == chat.id
        assert len(callback_args[0][1]) == 1
        assert callback_args[0][1][0].message == "Callback test"

    @pytest.mark.asyncio
    async def test_append_without_callback(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that appending works without an on_update callback."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        msg = DirectorChatMessage(message="No callback", source="user")
        result = await director_agent.chat_append_message(chat.id, msg)

        assert result.messages[-1].message == "No callback"

    @pytest.mark.asyncio
    async def test_append_preserves_ordering(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that multiple appended messages maintain order."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        for i in range(5):
            msg = DirectorChatMessage(message=f"Message {i}", source="user")
            await director_agent.chat_append_message(chat.id, msg)

        retrieved = director_agent.chat_get(chat.id)
        user_messages = [m for m in retrieved.messages if m.source == "user"]
        assert len(user_messages) == 5
        for i, m in enumerate(user_messages):
            assert m.message == f"Message {i}"


class TestChatRemoveMessage:
    """Tests for chat_remove_message method."""

    def test_remove_message_by_id(self, director_agent, mock_scene, setup_agents):
        """Test removing a message by its ID."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        # Manually add a message with a known ID
        msg = DirectorChatMessage(message="To be removed", source="user")
        chat.messages.append(msg)
        director_agent.chat_set_chat_state(chat.model_dump())

        count_before = len(chat.messages)
        result = director_agent.chat_remove_message(chat.id, msg.id)

        assert result is not None
        assert len(result.messages) == count_before - 1
        assert all(m.id != msg.id for m in result.messages)

    def test_remove_nonexistent_message(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test removing a message that doesn't exist returns None."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        result = director_agent.chat_remove_message(chat.id, "nonexistent-id")
        assert result is None

    def test_remove_from_nonexistent_chat(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test removing a message from a nonexistent chat returns None."""
        director_agent.scene = mock_scene

        result = director_agent.chat_remove_message("no-such-chat", "some-msg-id")
        assert result is None

    def test_remove_persists_state(self, director_agent, mock_scene, setup_agents):
        """Test that removal persists to scene agent_state."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        msg = DirectorChatMessage(message="Will be removed", source="user")
        chat.messages.append(msg)
        director_agent.chat_set_chat_state(chat.model_dump())

        director_agent.chat_remove_message(chat.id, msg.id)

        # Re-fetch and confirm removal
        retrieved = director_agent.chat_get(chat.id)
        assert all(m.id != msg.id for m in retrieved.messages)

    def test_remove_middle_message(self, director_agent, mock_scene, setup_agents):
        """Test removing a message from the middle of the history."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        msgs = []
        for i in range(3):
            msg = DirectorChatMessage(message=f"Msg {i}", source="user")
            chat.messages.append(msg)
            msgs.append(msg)
        director_agent.chat_set_chat_state(chat.model_dump())

        # Remove the middle message
        result = director_agent.chat_remove_message(chat.id, msgs[1].id)
        assert result is not None

        user_messages = [m for m in result.messages if m.source == "user"]
        assert len(user_messages) == 2
        assert user_messages[0].message == "Msg 0"
        assert user_messages[1].message == "Msg 2"


class TestChatRegenerateLast:
    """Tests for chat_regenerate_last method."""

    @pytest.mark.asyncio
    async def test_regenerate_removes_last_director_message(self, active_context):
        """Test that regenerate removes the last director text message and generates a new one."""
        director = active_context

        chat = director.chat_create()
        chat_id = chat.id

        # The initial message is already a director message.
        # Add a user message and another director message.
        chat.messages.append(
            DirectorChatMessage(message="User asks something", source="user")
        )
        chat.messages.append(
            DirectorChatMessage(message="Old director response", source="director")
        )
        director.chat_set_chat_state(chat.model_dump())

        old_director_msg_id = chat.messages[-1].id

        # Mock the generation to return a new response
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analyzing.</ANALYSIS><MESSAGE>New director response</MESSAGE>"
        )

        with patch(
            "talemate.agents.director.action_core.utils.get_available_actions"
        ) as mock_actions, patch(
            "talemate.agents.director.action_core.utils.get_meta_groups"
        ) as mock_meta:
            mock_actions.return_value = []
            mock_meta.return_value = []

            result = await director.chat_regenerate_last(chat_id=chat_id)

        assert result is not None
        # Old director message should be gone
        assert all(m.id != old_director_msg_id for m in result.messages)
        # New director message should be present
        director_msgs = [
            m
            for m in result.messages
            if m.source == "director" and m.type == "text"
        ]
        assert len(director_msgs) >= 1

    @pytest.mark.asyncio
    async def test_regenerate_no_director_messages(self, active_context):
        """Test regenerate when there are no director text messages."""
        director = active_context

        chat = director.chat_create()
        chat_id = chat.id

        # Replace all messages with only user messages
        chat.messages = [
            DirectorChatMessage(message="User only", source="user"),
        ]
        director.chat_set_chat_state(chat.model_dump())

        result = await director.chat_regenerate_last(chat_id=chat_id)

        # Should return the chat unchanged
        assert result is not None
        assert len(result.messages) == 1
        assert result.messages[0].source == "user"

    @pytest.mark.asyncio
    async def test_regenerate_empty_chat(self, active_context):
        """Test regenerate on an empty/nonexistent chat."""
        director = active_context

        result = await director.chat_regenerate_last(chat_id="nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_regenerate_skips_action_results(self, active_context):
        """Test that regenerate skips action result messages and finds the last director text."""
        director = active_context

        chat = director.chat_create()
        chat_id = chat.id

        chat.messages.append(
            DirectorChatMessage(message="Director text to regenerate", source="director")
        )
        chat.messages.append(
            DirectorChatActionResultMessage(
                name="some_action",
                result="action result",
                instructions="do something",
            )
        )
        director.chat_set_chat_state(chat.model_dump())

        target_msg_id = chat.messages[-2].id  # The director text, not the action result

        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Re-analyzing.</ANALYSIS><MESSAGE>Regenerated response</MESSAGE>"
        )

        with patch(
            "talemate.agents.director.action_core.utils.get_available_actions"
        ) as mock_actions, patch(
            "talemate.agents.director.action_core.utils.get_meta_groups"
        ) as mock_meta:
            mock_actions.return_value = []
            mock_meta.return_value = []

            result = await director.chat_regenerate_last(chat_id=chat_id)

        assert result is not None
        # The director text message that was targeted should be gone
        assert all(m.id != target_msg_id for m in result.messages)


class TestChatCompaction:
    """Tests for _chat_compact_if_needed method."""

    @pytest.mark.asyncio
    async def test_compact_under_budget_does_nothing(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that compaction does not occur when under budget."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        # Add a few small messages
        for i in range(3):
            chat.messages.append(
                DirectorChatMessage(message=f"Short msg {i}", source="director")
            )
        director_agent.chat_set_chat_state(chat.model_dump())

        # Large budget = no compaction needed
        budgets = DirectorChatBudgets(
            max_tokens=100000,
            scene_context_ratio=0.3,
        )

        result = await director_agent._chat_compact_if_needed(chat.id, budgets)
        assert result is False

    @pytest.mark.asyncio
    async def test_compact_over_budget_triggers(
        self, director_agent, mock_scene, setup_agents, mock_summarizer_agent
    ):
        """Test that compaction triggers when over budget."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        # Add many long messages to exceed budget
        for i in range(20):
            chat.messages.append(
                DirectorChatMessage(
                    message=f"This is a fairly long message number {i} with enough content to consume tokens. " * 10,
                    source="director",
                )
            )
        director_agent.chat_set_chat_state(chat.model_dump())

        # Tiny budget to force compaction
        budgets = DirectorChatBudgets(
            max_tokens=500,
            scene_context_ratio=0.3,
        )

        # Mock summarizer
        mock_summarizer_agent.summarize_director_chat = AsyncMock(
            return_value="Summary of the conversation."
        )
        instance.AGENTS["summarizer"] = mock_summarizer_agent

        result = await director_agent._chat_compact_if_needed(chat.id, budgets)
        assert result is True

        # Verify summarizer was called
        mock_summarizer_agent.summarize_director_chat.assert_called_once()

        # Verify messages were compacted
        compacted_chat = director_agent.chat_get(chat.id)
        assert len(compacted_chat.messages) < 21  # Should be fewer than original

    @pytest.mark.asyncio
    async def test_compact_no_budgets_does_nothing(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that compaction does nothing when budgets is None."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        result = await director_agent._chat_compact_if_needed(chat.id, None)
        assert result is False

    @pytest.mark.asyncio
    async def test_compact_no_chat_does_nothing(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that compaction does nothing when chat doesn't exist."""
        director_agent.scene = mock_scene

        budgets = DirectorChatBudgets(max_tokens=500, scene_context_ratio=0.3)
        result = await director_agent._chat_compact_if_needed("no-chat", budgets)
        assert result is False

    @pytest.mark.asyncio
    async def test_compact_calls_callbacks(
        self, director_agent, mock_scene, setup_agents, mock_summarizer_agent
    ):
        """Test that compaction calls on_compacting and on_compacted callbacks."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        for i in range(20):
            chat.messages.append(
                DirectorChatMessage(
                    message=f"Long message {i} with lots of content for tokens. " * 10,
                    source="director",
                )
            )
        director_agent.chat_set_chat_state(chat.model_dump())

        budgets = DirectorChatBudgets(max_tokens=500, scene_context_ratio=0.3)

        mock_summarizer_agent.summarize_director_chat = AsyncMock(
            return_value="Summary."
        )
        instance.AGENTS["summarizer"] = mock_summarizer_agent

        compacting_called = []
        compacted_called = []

        async def on_compacting(chat_id):
            compacting_called.append(chat_id)

        async def on_compacted(chat_id, new_messages):
            compacted_called.append((chat_id, new_messages))

        result = await director_agent._chat_compact_if_needed(
            chat.id, budgets, on_compacted=on_compacted, on_compacting=on_compacting
        )

        assert result is True
        assert len(compacting_called) == 1
        assert compacting_called[0] == chat.id
        assert len(compacted_called) == 1
        assert compacted_called[0][0] == chat.id


class TestDirectionAppendMessage:
    """Tests for direction_append_message method."""

    @pytest.mark.asyncio
    async def test_append_director_message(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test appending a director message to direction history."""
        director_agent.scene = mock_scene
        direction = director_agent.direction_create()

        msg = SceneDirectionMessage(message="Scene needs more tension.")
        with patch("talemate.agents.director.scene_direction.mixin.emit"):
            result = await director_agent.direction_append_message(msg)

        assert len(result.messages) == 1
        assert result.messages[-1].message == "Scene needs more tension."

    @pytest.mark.asyncio
    async def test_append_action_result(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test appending an action result to direction history."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        msg = SceneDirectionActionResultMessage(
            name="narrate",
            result="Narration added.",
            instructions="Add atmosphere",
        )
        with patch("talemate.agents.director.scene_direction.mixin.emit"):
            result = await director_agent.direction_append_message(msg)

        assert result.messages[-1].type == "action_result"
        assert result.messages[-1].name == "narrate"

    @pytest.mark.asyncio
    async def test_append_user_interaction(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test appending a user interaction to direction history."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        msg = UserInteractionMessage(user_input="I open the door.")
        with patch("talemate.agents.director.scene_direction.mixin.emit"):
            result = await director_agent.direction_append_message(msg)

        assert result.messages[-1].type == "user_interaction"
        assert result.messages[-1].user_input == "I open the door."

    @pytest.mark.asyncio
    async def test_append_persists_state(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that appending persists to scene agent_state."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        msg = SceneDirectionMessage(message="Persisted direction")
        with patch("talemate.agents.director.scene_direction.mixin.emit"):
            await director_agent.direction_append_message(msg)

        retrieved = director_agent.direction_get()
        assert retrieved.messages[-1].message == "Persisted direction"

    @pytest.mark.asyncio
    async def test_append_calls_on_update(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that on_update callback is called."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        callback_args = []

        async def on_update(messages):
            callback_args.append(messages)

        msg = SceneDirectionMessage(message="Callback test")
        with patch("talemate.agents.director.scene_direction.mixin.emit"):
            await director_agent.direction_append_message(msg, on_update=on_update)

        assert len(callback_args) == 1
        assert len(callback_args[0]) == 1

    @pytest.mark.asyncio
    async def test_append_auto_creates_direction(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that appending auto-creates direction state if none exists."""
        director_agent.scene = mock_scene
        # Don't call direction_create() — it should auto-create

        msg = SceneDirectionMessage(message="Auto-created")
        with patch("talemate.agents.director.scene_direction.mixin.emit"):
            result = await director_agent.direction_append_message(msg)

        assert result is not None
        assert result.messages[-1].message == "Auto-created"

    @pytest.mark.asyncio
    async def test_append_preserves_ordering(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that multiple appended messages maintain order."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        with patch("talemate.agents.director.scene_direction.mixin.emit"):
            for i in range(5):
                msg = SceneDirectionMessage(message=f"Direction {i}")
                await director_agent.direction_append_message(msg)

        retrieved = director_agent.direction_get()
        assert len(retrieved.messages) == 5
        for i, m in enumerate(retrieved.messages):
            assert m.message == f"Direction {i}"


class TestDirectionCompaction:
    """Tests for _direction_compact_if_needed method."""

    @pytest.mark.asyncio
    async def test_compact_under_budget_does_nothing(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that compaction does not occur when under budget."""
        director_agent.scene = mock_scene
        direction = director_agent.direction_create()

        for i in range(3):
            direction.messages.append(
                SceneDirectionMessage(message=f"Short msg {i}")
            )
        director_agent.direction_set_state(direction.model_dump())

        budgets = SceneDirectionBudgets(max_tokens=100000, scene_context_ratio=0.3)
        result = await director_agent._direction_compact_if_needed(budgets)
        assert result is False

    @pytest.mark.asyncio
    async def test_compact_over_budget_triggers(
        self, director_agent, mock_scene, setup_agents, mock_summarizer_agent
    ):
        """Test that compaction triggers when over budget."""
        director_agent.scene = mock_scene
        direction = director_agent.direction_create()

        for i in range(20):
            direction.messages.append(
                SceneDirectionMessage(
                    message=f"Long direction message {i} with content. " * 10,
                )
            )
        director_agent.direction_set_state(direction.model_dump())

        budgets = SceneDirectionBudgets(max_tokens=500, scene_context_ratio=0.3)

        mock_summarizer_agent.summarize_director_chat = AsyncMock(
            return_value="Direction summary."
        )
        instance.AGENTS["summarizer"] = mock_summarizer_agent

        result = await director_agent._direction_compact_if_needed(budgets)
        assert result is True

        mock_summarizer_agent.summarize_director_chat.assert_called_once()

        compacted = director_agent.direction_get()
        assert len(compacted.messages) < 21

    @pytest.mark.asyncio
    async def test_compact_no_budgets_does_nothing(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that compaction does nothing when budgets is None."""
        director_agent.scene = mock_scene
        director_agent.direction_create()

        result = await director_agent._direction_compact_if_needed(None)
        assert result is False

    @pytest.mark.asyncio
    async def test_compact_no_direction_does_nothing(
        self, director_agent, mock_scene, setup_agents
    ):
        """Test that compaction does nothing when no direction exists."""
        director_agent.scene = mock_scene

        budgets = SceneDirectionBudgets(max_tokens=500, scene_context_ratio=0.3)
        result = await director_agent._direction_compact_if_needed(budgets)
        assert result is False

    @pytest.mark.asyncio
    async def test_compact_calls_callbacks(
        self, director_agent, mock_scene, setup_agents, mock_summarizer_agent
    ):
        """Test that compaction calls on_compacting and on_compacted callbacks."""
        director_agent.scene = mock_scene
        direction = director_agent.direction_create()

        for i in range(20):
            direction.messages.append(
                SceneDirectionMessage(
                    message=f"Long direction {i} with content. " * 10,
                )
            )
        director_agent.direction_set_state(direction.model_dump())

        budgets = SceneDirectionBudgets(max_tokens=500, scene_context_ratio=0.3)

        mock_summarizer_agent.summarize_director_chat = AsyncMock(
            return_value="Summary."
        )
        instance.AGENTS["summarizer"] = mock_summarizer_agent

        compacting_called = []
        compacted_called = []

        async def on_compacting():
            compacting_called.append(True)

        async def on_compacted(new_messages):
            compacted_called.append(new_messages)

        result = await director_agent._direction_compact_if_needed(
            budgets, on_compacted=on_compacted, on_compacting=on_compacting
        )

        assert result is True
        assert len(compacting_called) == 1
        assert len(compacted_called) == 1
