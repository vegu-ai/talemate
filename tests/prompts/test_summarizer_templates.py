"""
Unit tests for summarizer agent methods.

Tests that summarizer agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock

import talemate.instance as instance
from talemate.agents.summarize import SummarizeAgent
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
        prompt_text = str(call_args[0][0])

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

        await summarizer.find_natural_scene_termination(event_chunks)

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify events are in the prompt
        assert "inn" in prompt_text.lower()


class TestSummarizerSummarize:
    """Tests for summarize method (summarizer.summarize-dialogue template)."""

    @pytest.mark.asyncio
    async def test_summarize_calls_client(self, active_context):
        """Test that summarize calls the LLM client with rendered prompt."""
        summarizer = active_context

        # Mock response with SUMMARY_SPEC format (AfterAnchorExtractor with start="SUMMARY:")
        summarizer.client.send_prompt = AsyncMock(
            return_value="Analysis of the scene.\nSUMMARY: Elena encountered a mysterious stranger while walking through the forest."
        )

        text = "Elena walked through the forest. She met a stranger on the path."

        response = await summarizer.summarize(text)

        # Verify extraction worked correctly - should extract content after "SUMMARY:"
        assert (
            response
            == "Elena encountered a mysterious stranger while walking through the forest."
        )
        # Verify preamble content was NOT extracted (proves SUMMARY_SPEC extraction worked)
        assert "Analysis of the scene" not in response
        assert "SUMMARY:" not in response

        # Verify the client's send_prompt was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify the text appears in the prompt
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_summarize_with_extra_context(self, active_context):
        """Test summarize with extra context."""
        summarizer = active_context

        # Mock response with SUMMARY_SPEC format
        summarizer.client.send_prompt = AsyncMock(
            return_value="Context considered.\nSUMMARY: The battle continued through the night after the heroes arrived."
        )

        text = "The battle raged on through the night."
        extra_context = ["Previously: The heroes arrived at the fortress."]

        response = await summarizer.summarize(text, extra_context=extra_context)

        # Verify extraction worked correctly
        assert (
            response
            == "The battle continued through the night after the heroes arrived."
        )
        # Verify preamble content was NOT extracted
        assert "Context considered" not in response
        assert "SUMMARY:" not in response

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_with_method(self, active_context):
        """Test summarize with different summarization methods."""
        summarizer = active_context

        text = "A complex series of events unfolded."

        for method in ["short", "balanced", "long", "facts"]:
            summarizer.client.send_prompt.reset_mock()
            # Mock response with SUMMARY_SPEC format for each method
            summarizer.client.send_prompt = AsyncMock(
                return_value=f"Processing with {method} method.\nSUMMARY: Complex events occurred using {method} summarization."
            )
            response = await summarizer.summarize(text, method=method)
            # Verify extraction worked correctly
            assert response == f"Complex events occurred using {method} summarization."
            # Verify preamble content was NOT extracted
            assert f"Processing with {method} method" not in response
            assert "SUMMARY:" not in response
            summarizer.client.send_prompt.assert_called_once()


class TestSummarizerSummarizeEvents:
    """Tests for summarize_events method (summarizer.summarize-events template)."""

    @pytest.mark.asyncio
    async def test_summarize_events_calls_client(self, active_context):
        """Test that summarize_events calls the LLM client."""
        summarizer = active_context

        # Set response with CHUNK_CLEAN_SPEC format (StripPrefixExtractor removes "CHUNK N:" prefix)
        summarizer.client.send_prompt = AsyncMock(
            return_value="CHUNK 1: The hero journeyed across the land, crossing rivers and mountains."
        )

        text = "The hero began the journey. The hero crossed the river. The hero reached the mountain."

        response = await summarizer.summarize_events(text)

        # Verify extraction worked correctly - should strip "CHUNK 1:" prefix
        assert (
            response
            == "The hero journeyed across the land, crossing rivers and mountains."
        )
        # Verify prefix was stripped (proves CHUNK_CLEAN_SPEC extraction worked)
        assert "CHUNK 1:" not in response
        assert "CHUNK" not in response

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify content appears in the prompt
        assert "hero" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_summarize_events_with_extra_context(self, active_context):
        """Test summarize_events with extra context."""
        summarizer = active_context

        # Set response with CHAPTER prefix format
        summarizer.client.send_prompt = AsyncMock(
            return_value="CHAPTER 2: The hero discovered the hidden treasure in the dungeon."
        )

        text = "The hero found the treasure."
        extra_context = "Previously: The hero entered the dungeon."

        response = await summarizer.summarize_events(text, extra_context=extra_context)

        # Verify extraction worked correctly - should strip "CHAPTER 2:" prefix
        assert response == "The hero discovered the hidden treasure in the dungeon."
        # Verify prefix was stripped (proves CHUNK_CLEAN_SPEC extraction worked)
        assert "CHAPTER 2:" not in response
        assert "CHAPTER" not in response

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_events_with_analyze_chunks_strips_analysis_lines(
        self, active_context
    ):
        """Test that summarize_events strips 'ANALYSIS OF' lines when analyze_chunks is enabled.

        This tests a bug fix where CHUNK_CLEAN_SPEC strips "CHUNK N:" from everywhere
        (including "ANALYSIS OF CHUNK N:"), leaving "ANALYSIS OF " prefixes that
        need to be cleaned up separately.
        """
        summarizer = active_context

        # Response with ANALYSIS OF CHUNK lines that will have "CHUNK N:" stripped
        # by CHUNK_CLEAN_SPEC, leaving "ANALYSIS OF " prefixes
        summarizer.client.send_prompt = AsyncMock(
            return_value="""ANALYSIS OF CHUNK 1: "The characters discuss the looming threat."
CHUNK 1: "Marcus and Elena debate the best strategy to defend the northern pass."
ANALYSIS OF CHUNK 2: "The dialogue shifts to supply concerns."
CHUNK 2: "They agree that rationing provisions is critical to survive the winter.\""""
        )

        text = "Test scene content for summarization."

        # Enable analyze_chunks via parameter
        response = await summarizer.summarize_events(text, analyze_chunks=True)

        # Verify the analysis lines were stripped (the bug was that "ANALYSIS OF "
        # remained after CHUNK_CLEAN_SPEC stripped "CHUNK N:")
        assert "ANALYSIS OF" not in response

        # Verify the actual content is preserved
        assert "Marcus and Elena debate the best strategy" in response
        assert "rationing provisions is critical to survive the winter" in response

        # Verify CHUNK prefixes were also stripped
        assert "CHUNK 1:" not in response
        assert "CHUNK 2:" not in response

    @pytest.mark.asyncio
    async def test_summarize_events_filters_short_lines(self, active_context):
        """Test that summarize_events filters out degenerate short lines.

        LLMs sometimes produce placeholder text like '[No content.]' when a chunk
        overlaps with prior context. Lines shorter than 20 characters should be
        stripped from the response.
        """
        summarizer = active_context

        summarizer.client.send_prompt = AsyncMock(
            return_value=(
                'CHUNK 1: "The heroes set out on their journey across the vast plains."\n'
                'CHUNK 2: "[No content.]"\n'
                'CHUNK 3: "They arrived at the ancient fortress by nightfall."'
            )
        )

        text = "Test scene content for summarization."

        response = await summarizer.summarize_events(text)

        assert "No content" not in response
        assert "heroes set out on their journey" in response
        assert "arrived at the ancient fortress" in response

    @pytest.mark.asyncio
    async def test_summarize_events_strips_whitespace_from_lines(self, active_context):
        """Test that summarize_events strips leading/trailing whitespace from lines."""
        summarizer = active_context

        summarizer.client.send_prompt = AsyncMock(
            return_value=(
                'CHUNK 1: "  The heroes ventured deep into the enchanted forest.  "\n'
                'CHUNK 2: "  They discovered a hidden temple beneath the ruins.  "'
            )
        )

        text = "Test scene content for summarization."

        response = await summarizer.summarize_events(text)

        # Lines should not have leading/trailing whitespace
        for line in response.split("\n"):
            if line:
                assert line == line.strip()

    @pytest.mark.asyncio
    async def test_summarize_events_preserves_empty_lines(self, active_context):
        """Test that empty lines (paragraph separators) are preserved."""
        summarizer = active_context

        summarizer.client.send_prompt = AsyncMock(
            return_value=(
                'CHUNK 1: "The heroes gathered their supplies and prepared for departure."\n'
                "\n"
                'CHUNK 2: "The long journey through the mountains tested their resolve."'
            )
        )

        text = "Test scene content for summarization."

        response = await summarizer.summarize_events(text)

        # Empty lines should be preserved for paragraph structure
        assert "\n\n" in response


class TestSummarizerSummarizeDirectorChat:
    """Tests for summarize_director_chat method (summarizer.summarize-director-chat template)."""

    @pytest.mark.asyncio
    async def test_summarize_director_chat_calls_client(self, active_context):
        """Test that summarize_director_chat calls the LLM client."""
        summarizer = active_context

        # Mock response - note: template uses set_prepared_response("SUMMARY:") so
        # the response should start with content that follows the SUMMARY: prefix
        # The prompt system prepends "SUMMARY:" if not already present
        summarizer.client.send_prompt = AsyncMock(
            return_value="The user requested a character update to make them brave, which was successfully applied."
        )

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

        # Verify extraction worked correctly - template prepends "SUMMARY:" which is then extracted
        assert (
            response
            == "The user requested a character update to make them brave, which was successfully applied."
        )

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify history content appears in the prompt
        assert "character" in prompt_text.lower()


class TestSummarizerAnalyzeSceneForNextAction:
    """Tests for analyze_scene_for_next_action method."""

    @pytest.mark.asyncio
    async def test_analyze_scene_for_conversation_calls_client(
        self, active_context, mock_scene
    ):
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
        prompt_text = str(call_args[0][0])

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


class TestSummarizerMarkupContextForTTS:
    """Tests for markup_context_for_tts method."""

    @pytest.mark.asyncio
    async def test_markup_context_for_tts_calls_client(self, active_context):
        """Test that markup_context_for_tts calls the LLM client."""
        summarizer = active_context

        # Set response with MARKUP_SPEC format (AnchorExtractor with <MARKUP>...</MARKUP>)
        summarizer.client.send_prompt = AsyncMock(
            return_value='Here is the markup:\n<MARKUP>[1] "Hello there," said Elena. [SPEAKER: Elena]\n[2] Marcus nodded. [SPEAKER: Narrator]</MARKUP>\nEnd of markup.'
        )

        text = '"Hello there," said Elena. Marcus nodded.'

        response = await summarizer.markup_context_for_tts(text)

        # Verify extraction worked correctly - should extract content between <MARKUP> tags
        assert (
            response
            == '[1] "Hello there," said Elena. [SPEAKER: Elena]\n[2] Marcus nodded. [SPEAKER: Narrator]'
        )
        # Verify preamble and tags were NOT extracted (proves MARKUP_SPEC extraction worked)
        assert "Here is the markup" not in response
        assert "End of markup" not in response
        assert "<MARKUP>" not in response
        assert "</MARKUP>" not in response

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = summarizer.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

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

    @pytest.mark.asyncio
    async def test_markup_context_for_tts_fallback_on_missing_tags(
        self, active_context
    ):
        """Test markup_context_for_tts returns original text when MARKUP tags are missing."""
        summarizer = active_context

        # Response without proper MARKUP tags - extraction should fail
        summarizer.client.send_prompt = AsyncMock(
            return_value='The markup is: [1] "Hello there," said Elena.'
        )

        text = '"Hello there," said Elena. Marcus nodded.'

        response = await summarizer.markup_context_for_tts(text)

        # Should fall back to original text when extraction fails
        assert response == text

        # Verify the client was called
        summarizer.client.send_prompt.assert_called_once()


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

    def test_analyze_scene_property(self, summarizer_agent):
        """Test analyze_scene property."""
        # Default is False (experimental feature)
        assert summarizer_agent.analyze_scene is False
