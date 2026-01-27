"""
Unit tests for summarizer agent methods.

Tests that summarizer agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

import talemate.instance as instance
from talemate.agents.summarize import SummarizeAgent
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


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that returns predictable responses."""
    client = AsyncMock()
    # Default response for summarization
    client.send_prompt = AsyncMock(return_value="SUMMARY: The hero journeyed through the forest.")
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
    scene.get_character = Mock(side_effect=lambda name: player if name == "Hero" else npc)
    scene.writing_style = "descriptive"
    scene.agent_state = {}

    # Mock Character class for isinstance check
    scene.Character = MockCharacter

    # Mock push_history for tests that need it
    scene.push_history = AsyncMock()

    # Add archived_history for layered history tests
    scene.archived_history = []

    # Add layered_history for context investigation tests
    scene.layered_history = []

    # Add intent_state for analyze scene templates
    scene.intent_state = Mock()
    scene.intent_state.active = False
    scene.intent_state.intent = ""
    scene.intent_state.phase = None
    scene.intent_state.current_scene_type = Mock()
    scene.intent_state.current_scene_type.description = "A test scene type"

    # Add count_character_messages_since_director
    scene.count_character_messages_since_director = Mock(return_value=0)

    # Add parse_characters_from_text
    scene.parse_characters_from_text = Mock(return_value=[])

    return scene


@pytest.fixture
def mock_conversation_agent():
    """Create a mock conversation agent."""
    conv = Mock()
    conv.conversation_format = "default"
    return conv


@pytest.fixture
def mock_summarizer_agent_for_registry():
    """Create a mock summarizer agent for registry (for template agent_action calls)."""
    summarizer = Mock()
    summarizer.actions = {
        "analyze_scene": Mock(),
    }
    summarizer.actions["analyze_scene"].config = {}
    # rag_build is called by templates
    summarizer.rag_build = AsyncMock(return_value=[])
    return summarizer


@pytest.fixture
def summarizer_agent(mock_llm_client, mock_scene):
    """Create a SummarizeAgent instance with mocked dependencies."""
    agent = SummarizeAgent(client=mock_llm_client)
    agent.scene = mock_scene
    return agent


@pytest.fixture
def setup_agents(
    mock_conversation_agent,
    mock_summarizer_agent_for_registry,
):
    """Set up the agent registry with mocked agents."""
    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Set up mock agents in the registry
    instance.AGENTS["summarizer"] = mock_summarizer_agent_for_registry
    instance.AGENTS["conversation"] = mock_conversation_agent

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(summarizer_agent, mock_scene, setup_agents):
    """Set up active scene context for tests."""
    from talemate.context import active_scene

    scene_token = active_scene.set(mock_scene)

    yield summarizer_agent

    active_scene.reset(scene_token)


class TestSummarizerAnalyzeDialogue:
    """Tests for analyze_dialoge method (summarizer.analyze-dialogue template)."""

    @pytest.mark.asyncio
    async def test_analyze_dialoge_calls_client(self, active_context):
        """Test that analyze_dialoge calls the LLM client with rendered prompt."""
        summarizer = active_context

        # Set a response appropriate for dialogue analysis
        summarizer.client.send_prompt = AsyncMock(
            return_value="The scene concludes at the denouement point."
        )

        dialogue = [
            "Elena: Hello there, traveler.",
            "Hero: Good to meet you.",
            "The sun was setting in the west.",
        ]

        response = await summarizer.analyze_dialoge(dialogue)

        # Verify response was returned
        assert response is not None

        # Verify the client's send_prompt was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify the dialogue is in the prompt
        assert "Elena" in prompt_text
        assert "Hero" in prompt_text


class TestSummarizerFindNaturalSceneTermination:
    """Tests for find_natural_scene_termination method."""

    @pytest.mark.asyncio
    async def test_find_natural_scene_termination_calls_client(self, active_context):
        """Test that find_natural_scene_termination calls the LLM client."""
        summarizer = active_context

        # Set a response with termination points
        summarizer.client.send_prompt = AsyncMock(
            return_value="- Progress 2\n- Progress 5"
        )

        event_chunks = [
            "The party gathered at the inn.",
            "They discussed their plan.",
            "The leader gave a rousing speech.",
            "Everyone headed to their rooms for the night.",
            "Morning came swiftly.",
            "The journey began anew.",
        ]

        result = await summarizer.find_natural_scene_termination(event_chunks)

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify events are in the prompt
        assert "inn" in prompt_text.lower()


class TestSummarizerSummarize:
    """Tests for summarize method (summarizer.summarize-dialogue template)."""

    @pytest.mark.asyncio
    async def test_summarize_calls_client(self, active_context):
        """Test that summarize calls the LLM client with rendered prompt."""
        summarizer = active_context

        text = "Elena walked through the forest. She met a stranger on the path."

        response = await summarizer.summarize(text)

        # Verify response was returned
        assert response is not None

        # Verify the client's send_prompt was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify the text appears in the prompt
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_summarize_with_extra_context(self, active_context):
        """Test summarize with extra context."""
        summarizer = active_context

        text = "The battle raged on through the night."
        extra_context = ["Previously: The heroes arrived at the fortress."]

        response = await summarizer.summarize(text, extra_context=extra_context)

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_with_method(self, active_context):
        """Test summarize with different summarization methods."""
        summarizer = active_context

        text = "A complex series of events unfolded."

        for method in ["short", "balanced", "long", "facts"]:
            summarizer.client.send_prompt.reset_mock()
            response = await summarizer.summarize(text, method=method)
            assert response is not None
            summarizer.client.send_prompt.assert_called_once()


class TestSummarizerSummarizeEvents:
    """Tests for summarize_events method (summarizer.summarize-events template)."""

    @pytest.mark.asyncio
    async def test_summarize_events_calls_client(self, active_context):
        """Test that summarize_events calls the LLM client."""
        summarizer = active_context

        # Set appropriate response for events summarization
        summarizer.client.send_prompt = AsyncMock(
            return_value="CHUNK 1: The events progressed steadily."
        )

        text = "The hero began the journey. The hero crossed the river. The hero reached the mountain."

        response = await summarizer.summarize_events(text)

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify content appears in the prompt
        assert "hero" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_summarize_events_with_extra_context(self, active_context):
        """Test summarize_events with extra context."""
        summarizer = active_context

        summarizer.client.send_prompt = AsyncMock(
            return_value="CHUNK 1: The events continued."
        )

        text = "The hero found the treasure."
        extra_context = "Previously: The hero entered the dungeon."

        response = await summarizer.summarize_events(text, extra_context=extra_context)

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()


class TestSummarizerSummarizeDirectorChat:
    """Tests for summarize_director_chat method (summarizer.summarize-director-chat template)."""

    @pytest.mark.asyncio
    async def test_summarize_director_chat_calls_client(self, active_context):
        """Test that summarize_director_chat calls the LLM client."""
        summarizer = active_context

        history = [
            {"type": "message", "source": "user", "message": "Update the character."},
            {
                "type": "message",
                "source": "director",
                "message": "I'll update the character now.",
            },
            {
                "type": "action_result",
                "source": "director",
                "name": "update_character",
                "instructions": "Make them brave",
                "result": {"success": True},
            },
        ]

        response = await summarizer.summarize_director_chat(history)

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify history content appears in the prompt
        assert "character" in prompt_text.lower()


class TestSummarizerAnalyzeSceneForNextAction:
    """Tests for analyze_scene_for_next_action method."""

    @pytest.mark.asyncio
    async def test_analyze_scene_for_conversation_calls_client(self, active_context, mock_scene):
        """Test analyze_scene_for_next_action for conversation type."""
        summarizer = active_context

        # Set appropriate response
        summarizer.client.send_prompt = AsyncMock(
            return_value="The scene is building tension as characters negotiate."
        )

        character = MockCharacter(name="TestChar")

        response = await summarizer.analyze_scene_for_next_action(
            typ="conversation", character=character, length=512
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify character name appears in the prompt
        assert "TestChar" in prompt_text

    @pytest.mark.asyncio
    async def test_analyze_scene_for_narration_calls_client(self, active_context):
        """Test analyze_scene_for_next_action for narration type."""
        summarizer = active_context

        # Set appropriate response
        summarizer.client.send_prompt = AsyncMock(
            return_value="The narrative should focus on the environment."
        )

        response = await summarizer.analyze_scene_for_next_action(
            typ="narration", character=None, length=1024
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()


class TestSummarizerSuggestContextInvestigations:
    """Tests for suggest_context_investigations method."""

    @pytest.mark.asyncio
    async def test_suggest_context_investigations_for_conversation(self, active_context, mock_scene):
        """Test suggest_context_investigations for conversation analysis type."""
        summarizer = active_context

        # Enable layered history for context investigation
        mock_scene.layered_history = [
            [{"text": "Chapter 1 events", "start": 0, "end": 5, "ts_start": "PT0S", "ts_end": "PT1H"}]
        ]

        # Set appropriate response
        summarizer.client.send_prompt = AsyncMock(
            return_value="Investigate chapter 1.1 for character background."
        )

        character = MockCharacter(name="ConvoChar")

        response = await summarizer.suggest_context_investigations(
            analysis="The scene shows tension between characters.",
            analysis_type="conversation",
            character=character,
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify character name appears in the prompt
        assert "ConvoChar" in prompt_text

    @pytest.mark.asyncio
    async def test_suggest_context_investigations_for_narration_progress(self, active_context, mock_scene):
        """Test suggest_context_investigations for narration-progress analysis type."""
        summarizer = active_context

        mock_scene.layered_history = [
            [{"text": "Chapter 1 events", "start": 0, "end": 5, "ts_start": "PT0S", "ts_end": "PT1H"}]
        ]

        summarizer.client.send_prompt = AsyncMock(
            return_value="Investigate chapter 1.1 for plot progression."
        )

        response = await summarizer.suggest_context_investigations(
            analysis="The story is progressing toward the climax.",
            analysis_type="narration",
            analysis_sub_type="progress",
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()


class TestSummarizerUpdateContextInvestigation:
    """Tests for update_context_investigation method."""

    @pytest.mark.asyncio
    async def test_update_context_investigation_calls_client(self, active_context):
        """Test that update_context_investigation calls the LLM client."""
        summarizer = active_context

        # Set appropriate response
        summarizer.client.send_prompt = AsyncMock(
            return_value="The hero had been preparing for this journey for months."
        )

        response = await summarizer.update_context_investigation(
            current_context_investigation="The hero was tired from the journey.",
            new_context_investigation="The hero had rested the night before.",
            analysis="The scene shows a confrontation.",
        )

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()


class TestSummarizerMarkupContextForTTS:
    """Tests for markup_context_for_tts method."""

    @pytest.mark.asyncio
    async def test_markup_context_for_tts_calls_client(self, active_context):
        """Test that markup_context_for_tts calls the LLM client."""
        summarizer = active_context

        # Set appropriate response with markup
        summarizer.client.send_prompt = AsyncMock(
            return_value='<MARKUP>[1] "Hello there," said Elena. [SPEAKER: Elena]\n[2] Marcus nodded. [SPEAKER: Narrator]</MARKUP>'
        )

        text = '"Hello there," said Elena. Marcus nodded.'

        response = await summarizer.markup_context_for_tts(text)

        # Verify response was returned
        assert response is not None

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify text appears in the prompt
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_markup_context_for_tts_no_quotes(self, active_context):
        """Test markup_context_for_tts returns original text when no quotes."""
        summarizer = active_context

        text = "The forest was quiet and peaceful."

        response = await summarizer.markup_context_for_tts(text)

        # Should return original text without calling the client
        assert response == text
        summarizer.client.send_prompt.assert_not_called()


class TestSummarizerInvestigateContext:
    """Tests for investigate_context method (uses focal handler)."""

    @pytest.mark.asyncio
    async def test_investigate_context_calls_focal(self, active_context, mock_scene):
        """Test that investigate_context sets up focal handler correctly."""
        summarizer = active_context

        # Set up layered history
        mock_scene.layered_history = [
            [
                {
                    "text": "Layer 0 entry 0",
                    "start": 0,
                    "end": 2,
                    "ts_start": "PT0S",
                    "ts_end": "PT30M",
                },
                {
                    "text": "Layer 0 entry 1",
                    "start": 3,
                    "end": 5,
                    "ts_start": "PT30M",
                    "ts_end": "PT1H",
                },
            ]
        ]

        # Set up archived history as the base layer
        mock_scene.archived_history = [
            {"text": "Base entry 0", "ts": "PT0S", "start": 0, "end": 0},
            {"text": "Base entry 1", "ts": "PT10M", "start": 1, "end": 1},
            {"text": "Base entry 2", "ts": "PT20M", "start": 2, "end": 2},
        ]

        # Mock the focal handler response - abort to exit cleanly
        summarizer.client.send_prompt = AsyncMock(
            return_value='```json\n{"name": "abort", "arguments": {}}\n```'
        )

        # Mock agents needed by focal handler - add to AGENTS dict directly
        mock_director = Mock()
        mock_director.log_action = Mock()

        mock_world_state = Mock()
        mock_world_state.analyze_history_and_follow_instructions = AsyncMock(
            return_value="The answer to the query."
        )

        # Save and restore AGENTS
        original_agents = instance.AGENTS.copy()
        instance.AGENTS["director"] = mock_director
        instance.AGENTS["world_state"] = mock_world_state

        try:
            result = await summarizer.investigate_context(
                layer=0, index=0, query="What happened?", analysis="Scene analysis"
            )

            # Verify the client was called (prompt was rendered and sent)
            assert summarizer.client.send_prompt.called
        finally:
            instance.AGENTS.clear()
            instance.AGENTS.update(original_agents)


class TestSummarizerRequestContextInvestigations:
    """Tests for request_context_investigations method."""

    @pytest.mark.asyncio
    async def test_request_context_investigations_calls_focal(self, active_context, mock_scene):
        """Test that request_context_investigations sets up focal handler."""
        summarizer = active_context

        # Set up layered history
        mock_scene.layered_history = [
            [
                {
                    "text": "Layer 0 entry 0",
                    "start": 0,
                    "end": 2,
                    "ts_start": "PT0S",
                    "ts_end": "PT30M",
                }
            ]
        ]

        mock_scene.archived_history = [
            {"text": "Base entry 0", "ts": "PT0S", "start": 0, "end": 0},
        ]

        # Mock the focal handler response - abort to exit cleanly
        summarizer.client.send_prompt = AsyncMock(
            return_value='```json\n{"name": "abort", "arguments": {}}\n```'
        )

        # Mock agents needed by focal handler - add to AGENTS dict directly
        mock_director = Mock()
        mock_director.log_action = Mock()

        # Save and restore AGENTS
        original_agents = instance.AGENTS.copy()
        instance.AGENTS["director"] = mock_director

        try:
            result = await summarizer.request_context_investigations(
                analysis="Investigate the hero's background."
            )

            # Verify the client was called
            summarizer.client.send_prompt.assert_called()
        finally:
            instance.AGENTS.clear()
            instance.AGENTS.update(original_agents)


class TestSummarizerCleanResult:
    """Tests for the clean_result method."""

    def test_clean_result_removes_hash_comments(self, summarizer_agent):
        """Test that clean_result removes lines starting with #."""
        result = summarizer_agent.clean_result(
            "The forest was quiet.\n# This is a comment\nThe wind blew."
        )

        # Comments should be removed
        assert "# This is a comment" not in result

    def test_clean_result_strips_partial_sentences(self, summarizer_agent):
        """Test that clean_result strips partial sentences."""
        # Text ending with incomplete sentence
        result = summarizer_agent.clean_result(
            "The hero completed the quest. The next morning"
        )

        # Should strip the incomplete sentence
        assert "The hero completed the quest" in result


class TestSummarizerProperties:
    """Tests for summarizer agent properties."""

    def test_threshold_property(self, summarizer_agent):
        """Test threshold property returns config value."""
        assert summarizer_agent.threshold == 1536  # Default value

    def test_archive_method_property(self, summarizer_agent):
        """Test archive_method property returns config value."""
        assert summarizer_agent.archive_method == "balanced"  # Default value

    def test_layered_history_enabled_property(self, summarizer_agent):
        """Test layered_history_enabled property."""
        assert summarizer_agent.layered_history_enabled is True  # Default

    def test_context_investigation_enabled_property(self, summarizer_agent):
        """Test context_investigation_enabled property."""
        # Default is False (experimental feature)
        assert summarizer_agent.context_investigation_enabled is False

    def test_analyze_scene_property(self, summarizer_agent):
        """Test analyze_scene property."""
        # Default is False (experimental feature)
        assert summarizer_agent.analyze_scene is False
