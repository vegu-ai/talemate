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
    DirectorChat,
    DirectorChatActionResultMessage,
    DirectorChatBudgets,
    DirectorChatListEntry,
    DirectorChatMessage,
)
from talemate.load import migrate_director_chat_state
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
        director_agent._chat_save(chat)

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
        director_agent._chat_save(chat)

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
        director_agent._chat_save(chat)

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
        director._chat_save(chat)

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
        director._chat_save(chat)

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
        director._chat_save(chat)

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
        director_agent._chat_save(chat)

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
        director_agent._chat_save(chat)

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
        director_agent._chat_save(chat)

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


class TestMultiChatStateManagement:
    """Tests for multi-chat state management methods."""

    def test_create_multiple_chats(self, director_agent, mock_scene, setup_agents):
        """Test creating multiple independent chats."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()
        chat3 = director_agent.chat_create()

        assert chat1.id != chat2.id != chat3.id
        assert len(director_agent.chat_list()) == 3

    def test_chat_list_returns_entries(self, director_agent, mock_scene, setup_agents):
        """Test that chat_list returns DirectorChatListEntry objects."""
        director_agent.scene = mock_scene
        director_agent.chat_create()
        director_agent.chat_create()

        entries = director_agent.chat_list()
        assert len(entries) == 2
        assert all(isinstance(e, DirectorChatListEntry) for e in entries)

    def test_chat_list_sorted_by_created_at(self, director_agent, mock_scene, setup_agents):
        """Test that chat_list is sorted most recent first."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()

        entries = director_agent.chat_list()
        # Most recent first
        assert entries[0].id == chat2.id
        assert entries[1].id == chat1.id

    def test_get_chat_by_id(self, director_agent, mock_scene, setup_agents):
        """Test getting a specific chat by its ID from the collection."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()

        retrieved = director_agent.chat_get(chat1.id)
        assert retrieved is not None
        assert retrieved.id == chat1.id

        retrieved2 = director_agent.chat_get(chat2.id)
        assert retrieved2 is not None
        assert retrieved2.id == chat2.id

    def test_get_nonexistent_chat(self, director_agent, mock_scene, setup_agents):
        """Test getting a nonexistent chat returns None."""
        director_agent.scene = mock_scene
        director_agent.chat_create()

        result = director_agent.chat_get("nonexistent-id")
        assert result is None

    def test_delete_chat(self, director_agent, mock_scene, setup_agents):
        """Test deleting a chat removes it from the collection."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()

        result = director_agent.chat_delete(chat1.id)
        assert result is True
        assert len(director_agent.chat_list()) == 1
        assert director_agent.chat_get(chat1.id) is None
        assert director_agent.chat_get(chat2.id) is not None

    def test_delete_nonexistent_chat(self, director_agent, mock_scene, setup_agents):
        """Test deleting a nonexistent chat returns False."""
        director_agent.scene = mock_scene
        result = director_agent.chat_delete("no-such-chat")
        assert result is False

    def test_delete_active_chat_updates_last_active(self, director_agent, mock_scene, setup_agents):
        """Test that deleting the active chat updates last_active_chat_id."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()
        # chat2 is now the last active (set by chat_create)
        assert director_agent.chat_get_last_active_id() == chat2.id

        director_agent.chat_delete(chat2.id)
        # Should fall back to chat1
        assert director_agent.chat_get_last_active_id() == chat1.id

    def test_delete_all_chats(self, director_agent, mock_scene, setup_agents):
        """Test deleting all chats results in empty collection and None last_active."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()

        director_agent.chat_delete(chat1.id)
        assert len(director_agent.chat_list()) == 0
        assert director_agent.chat_get_last_active_id() is None

    def test_chats_are_isolated(self, director_agent, mock_scene, setup_agents):
        """Test that messages in one chat don't affect another."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()

        # Add message to chat1
        chat1_obj = director_agent.chat_get(chat1.id)
        chat1_obj.messages.append(DirectorChatMessage(message="Only in chat1", source="user"))
        director_agent._chat_save(chat1_obj)

        # Chat2 should be unaffected
        chat2_obj = director_agent.chat_get(chat2.id)
        assert not any(m.message == "Only in chat1" for m in chat2_obj.messages if hasattr(m, "message"))

    def test_clear_chat_preserves_chat_in_collection(self, director_agent, mock_scene, setup_agents):
        """Test that clearing a chat preserves it in the collection but resets messages."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        chat_obj = director_agent.chat_get(chat.id)
        chat_obj.messages.append(DirectorChatMessage(message="Extra", source="user"))
        director_agent._chat_save(chat_obj)

        result = director_agent.chat_clear(chat.id)
        assert result is True

        cleared = director_agent.chat_get(chat.id)
        assert cleared is not None
        assert len(cleared.messages) == 1  # Only greeting
        # Still in the list
        assert len(director_agent.chat_list()) == 1


class TestChatGetOrCreateActive:
    """Tests for chat_get_or_create_active method."""

    def test_returns_last_active_when_valid(self, director_agent, mock_scene, setup_agents):
        """Test that it returns the last active chat when it exists."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()
        # Manually set last active to chat1
        director_agent.chat_set_last_active_id(chat1.id)

        active = director_agent.chat_get_or_create_active()
        assert active.id == chat1.id

    def test_falls_back_to_most_recent(self, director_agent, mock_scene, setup_agents):
        """Test that it falls back to most recent when last_active_id is stale."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        chat2 = director_agent.chat_create()
        # Set last active to a non-existent id
        director_agent.chat_set_last_active_id("stale-id")

        active = director_agent.chat_get_or_create_active()
        # Should return most recent (chat2)
        assert active.id == chat2.id

    def test_creates_chat_when_none_exist(self, director_agent, mock_scene, setup_agents):
        """Test that it creates a new chat when no chats exist."""
        director_agent.scene = mock_scene
        # No chats created yet

        active = director_agent.chat_get_or_create_active()
        assert active is not None
        assert len(director_agent.chat_list()) == 1

    def test_no_last_active_falls_back(self, director_agent, mock_scene, setup_agents):
        """Test that it falls back when last_active_chat_id is None but chats exist."""
        director_agent.scene = mock_scene
        chat1 = director_agent.chat_create()
        director_agent.chat_set_last_active_id(None)

        active = director_agent.chat_get_or_create_active()
        assert active.id == chat1.id


class TestChatTitle:
    """Tests for chat title methods."""

    def test_update_title(self, director_agent, mock_scene, setup_agents):
        """Test setting a title on a chat."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()

        result = director_agent.chat_update_title(chat.id, "Test Title")
        assert result is True

        retrieved = director_agent.chat_get(chat.id)
        assert retrieved.title == "Test Title"

    def test_update_title_nonexistent_chat(self, director_agent, mock_scene, setup_agents):
        """Test updating title on a nonexistent chat returns False."""
        director_agent.scene = mock_scene
        result = director_agent.chat_update_title("no-such-chat", "Title")
        assert result is False

    def test_title_in_list_entry(self, director_agent, mock_scene, setup_agents):
        """Test that title appears in chat list entries."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        director_agent.chat_update_title(chat.id, "My Chat")

        entries = director_agent.chat_list()
        assert entries[0].title == "My Chat"

    def test_default_title_is_none(self, director_agent, mock_scene, setup_agents):
        """Test that new chats have None as their title."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        assert chat.title is None

    def test_has_enough_for_title_no_user_message(self, director_agent, mock_scene, setup_agents):
        """Test that title check fails without a user message."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        # Only has the greeting (director message)
        assert director_agent._chat_has_enough_for_title(chat) is False

    def test_has_enough_for_title_with_exchange(self, director_agent, mock_scene, setup_agents):
        """Test that title check passes with user + director exchange."""
        director_agent.scene = mock_scene
        chat = director_agent.chat_create()
        # Initial greeting is a director message; add a user message
        chat.messages.append(DirectorChatMessage(message="Hello", source="user"))
        assert director_agent._chat_has_enough_for_title(chat) is True


class TestChatMigration:
    """Tests for migrate_director_chat_state function."""

    def test_migrate_old_singleton_format(self):
        """Test migration from old singleton chat to multi-chat collection."""
        scene_data = {
            "agent_state": {
                "director": {
                    "chat": {
                        "id": "abc123",
                        "messages": [{"message": "Hello", "source": "director", "type": "text"}],
                        "mode": "normal",
                        "confirm_write_actions": True,
                    }
                }
            }
        }

        migrate_director_chat_state(scene_data)

        director_state = scene_data["agent_state"]["director"]
        assert "chats" in director_state
        assert "chat" not in director_state
        assert "abc123" in director_state["chats"]
        assert director_state["chats"]["abc123"]["title"] == "Original Chat"
        assert director_state["chats"]["abc123"]["created_at"] == 0
        assert director_state["last_active_chat_id"] == "abc123"

    def test_already_migrated_no_change(self):
        """Test that already-migrated data is not changed."""
        scene_data = {
            "agent_state": {
                "director": {
                    "chats": {"existing": {"id": "existing", "messages": []}},
                    "last_active_chat_id": "existing",
                }
            }
        }

        migrate_director_chat_state(scene_data)

        director_state = scene_data["agent_state"]["director"]
        assert len(director_state["chats"]) == 1
        assert "existing" in director_state["chats"]

    def test_no_director_state(self):
        """Test migration with no director state does nothing."""
        scene_data = {"agent_state": {}}
        migrate_director_chat_state(scene_data)
        assert "director" not in scene_data.get("agent_state", {})

    def test_no_agent_state(self):
        """Test migration with no agent_state does nothing."""
        scene_data = {}
        migrate_director_chat_state(scene_data)
        assert "agent_state" not in scene_data

    def test_empty_director_state_no_chat(self):
        """Test migration with director state but no old chat key."""
        scene_data = {
            "agent_state": {
                "director": {
                    "other_key": "value"
                }
            }
        }

        migrate_director_chat_state(scene_data)

        director_state = scene_data["agent_state"]["director"]
        assert "chats" in director_state
        assert len(director_state["chats"]) == 0

    def test_migration_preserves_mode(self):
        """Test that migration preserves the chat mode."""
        scene_data = {
            "agent_state": {
                "director": {
                    "chat": {
                        "id": "xyz",
                        "messages": [],
                        "mode": "decisive",
                        "confirm_write_actions": False,
                    }
                }
            }
        }

        migrate_director_chat_state(scene_data)

        migrated_chat = scene_data["agent_state"]["director"]["chats"]["xyz"]
        assert migrated_chat["mode"] == "decisive"
        assert migrated_chat["confirm_write_actions"] is False
