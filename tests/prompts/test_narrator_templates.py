"""
Unit tests for narrator agent methods.

Tests that narrator agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock

import talemate.instance as instance
from talemate.agents.narrator import NarratorAgent
from talemate.agents.editor import EditorAgent
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

    # Mock Character class for isinstance check - use MockCharacter
    scene.Character = MockCharacter

    # Mock push_history for tests that need it
    scene.push_history = AsyncMock()

    return scene


@pytest.fixture
def mock_editor_agent():
    """Create a mock editor agent for clean_result calls."""
    editor = Mock(spec=EditorAgent)
    editor.fix_exposition_enabled = False
    editor.fix_exposition_narrator = False
    editor.fix_exposition_in_text = Mock(side_effect=lambda text: text)
    return editor


@pytest.fixture
def mock_conversation_agent():
    """Create a mock conversation agent."""
    conv = Mock()
    conv.conversation_format = "default"
    return conv


@pytest.fixture
def mock_narrator_agent_for_registry():
    """Create a mock narrator agent for registry (for template agent_action calls)."""
    narrator = Mock()
    narrator.actions = {
        "content": Mock(),
    }
    narrator.actions["content"].config = {
        "use_scene_intent": Mock(value=True),
    }
    narrator.content_use_scene_intent = True
    # rag_build is called by templates - needs to be an async function
    narrator.rag_build = AsyncMock(return_value=[])
    return narrator


@pytest.fixture
def narrator_agent(mock_llm_client, mock_scene):
    """Create a NarratorAgent instance with mocked dependencies."""
    agent = NarratorAgent(client=mock_llm_client)
    agent.scene = mock_scene

    return agent


@pytest.fixture
def setup_agents(
    mock_editor_agent,
    mock_conversation_agent,
    mock_narrator_agent_for_registry,
):
    """Set up the agent registry with mocked agents."""
    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Set up mock agents in the registry
    instance.AGENTS["narrator"] = mock_narrator_agent_for_registry
    instance.AGENTS["editor"] = mock_editor_agent
    instance.AGENTS["conversation"] = mock_conversation_agent

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(narrator_agent, mock_scene, setup_agents):
    """Set up active scene context for tests."""
    from talemate.context import active_scene

    scene_token = active_scene.set(mock_scene)

    yield narrator_agent

    active_scene.reset(scene_token)


class TestNarratorAgentMethods:
    """Tests for narrator agent methods that call the LLM."""

    @pytest.mark.asyncio
    async def test_narrate_scene_calls_client(self, active_context):
        """Test that narrate_scene calls the LLM client with rendered prompt.

        The narrator uses AsIsExtractor - the raw LLM response is extracted as-is,
        then processed through clean_result() which may strip certain patterns.
        """
        narrator = active_context

        # Set specific mock response to verify extraction
        expected_narration = "Moonlight filtered through the ancient oak trees."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_scene(
            narrative_direction="Describe the forest clearing"
        )

        # Verify response extraction worked - should return the expected narration
        assert response == expected_narration

        # Verify the client's send_prompt was called
        narrator.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]  # First positional arg is the prompt

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0

    @pytest.mark.asyncio
    async def test_narrate_scene_with_direction_in_prompt(self, active_context):
        """Test that narrative_direction appears in the rendered prompt."""
        narrator = active_context
        direction = "Focus on the mysterious stranger"

        # Set specific mock response to verify extraction
        expected_narration = "A cloaked figure emerged from the shadows."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_scene(narrative_direction=direction)

        # Verify response extraction worked
        assert response == expected_narration

        # Get the prompt that was sent
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Verify our direction was included in the prompt
        assert direction in prompt_text

    @pytest.mark.asyncio
    async def test_progress_story_calls_client(self, active_context):
        """Test that progress_story calls the LLM client and extracts the response."""
        narrator = active_context

        # Set specific mock response to verify extraction
        expected_narration = "The hero stepped forward, drawing their sword."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.progress_story(
            narrative_direction="Move the story forward"
        )

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_progress_story_default_direction(self, active_context):
        """Test progress_story with no direction uses default and extracts response."""
        narrator = active_context

        # Set specific mock response to verify extraction
        expected_narration = "A distant rumble echoed through the valley."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.progress_story()

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()

        # The default direction should be in the prompt
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]

        # Default direction is "Slightly move the current scene forward."
        assert "forward" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_narrate_query_calls_client(self, active_context):
        """Test that narrate_query calls the LLM client and extracts the response."""
        narrator = active_context
        query = "What is the current state of the forest?"

        # Set specific mock response to verify extraction
        expected_narration = (
            "The forest stands silent, its ancient trees wrapped in twilight mist."
        )
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_query(query=query)

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()

        # Verify query appears in the prompt
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert query in prompt_text

    @pytest.mark.asyncio
    async def test_narrate_query_with_extra_context(self, active_context):
        """Test narrate_query with extra context and extraction."""
        narrator = active_context
        query = "Describe the atmosphere"
        extra_context = "The scene is set at midnight"

        # Set specific mock response to verify extraction
        expected_narration = "The midnight air hung thick with anticipation."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_query(
            query=query, extra_context=extra_context
        )

        # Verify response extraction worked
        assert response == expected_narration

        narrator.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_narrate_character_calls_client(self, active_context, mock_scene):
        """Test that narrate_character calls the LLM client and extracts the response."""
        narrator = active_context
        character = mock_scene.get_character("Elena")

        # Set specific mock response to verify extraction
        expected_narration = (
            "Elena stood tall, her dark hair cascading over her shoulders."
        )
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_character(
            character=character, narrative_direction="Describe her appearance"
        )

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()

        # Verify character name appears in the prompt
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_paraphrase_calls_client(self, active_context):
        """Test that paraphrase calls the LLM client and extracts the response."""
        narrator = active_context
        text = "The warrior drew his sword and prepared for battle."

        # Set specific mock response to verify extraction
        expected_narration = (
            "The fighter unsheathed his blade, readying himself for combat."
        )
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.paraphrase(narration=text)

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()

        # Verify the text appears in the prompt
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert text in prompt_text


class TestNarratorTimePassageMethods:
    """Tests for narrator time passage and dialogue methods."""

    @pytest.mark.asyncio
    async def test_narrate_time_passage_calls_client(self, active_context):
        """Test that narrate_time_passage calls the LLM client and extracts the response."""
        narrator = active_context

        # Set specific mock response to verify extraction
        expected_narration = "The shadows lengthened as twilight settled over the land."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_time_passage(
            duration="PT2H",
            time_passed="Two hours later",
            narrative_direction="The sun has set",
        )

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()

        # Verify time_passed appears in the prompt
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Two hours later" in prompt_text

    @pytest.mark.asyncio
    async def test_narrate_after_dialogue_calls_client(
        self, active_context, mock_scene
    ):
        """Test that narrate_after_dialogue calls the LLM client and extracts the response."""
        narrator = active_context
        character = mock_scene.get_character("Elena")

        # Set specific mock response to verify extraction
        expected_narration = "The scent of pine drifted through the open window."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_after_dialogue(
            character=character, narrative_direction="Describe her reaction"
        )

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()


class TestNarratorCharacterEntryExitMethods:
    """Tests for narrator character entry/exit methods."""

    @pytest.mark.asyncio
    async def test_narrate_character_entry_calls_client(
        self, active_context, mock_scene
    ):
        """Test that narrate_character_entry calls the LLM client and extracts the response."""
        narrator = active_context
        character = mock_scene.get_character("Elena")

        # Set specific mock response to verify extraction
        expected_narration = "The door swung open and Elena stepped into the room."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_character_entry(
            character=character, narrative_direction="She enters dramatically"
        )

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()

        # Verify character name in prompt
        call_args = narrator.client.send_prompt.call_args
        prompt_text = call_args[0][0]
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_narrate_character_exit_calls_client(
        self, active_context, mock_scene
    ):
        """Test that narrate_character_exit calls the LLM client and extracts the response."""
        narrator = active_context
        character = mock_scene.get_character("Elena")

        # Set specific mock response to verify extraction
        expected_narration = "Elena turned and disappeared through the doorway."
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_character_exit(
            character=character, narrative_direction="She leaves quietly"
        )

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()


class TestNarratorEnvironmentMethod:
    """Tests for narrator environment method."""

    @pytest.mark.asyncio
    async def test_narrate_environment_calls_narrate_after_dialogue(
        self, active_context
    ):
        """Test that narrate_environment wraps narrate_after_dialogue and extracts the response."""
        narrator = active_context

        # Set specific mock response to verify extraction
        expected_narration = (
            "Wind rustled through the leaves, carrying the distant call of a bird."
        )
        narrator.client.send_prompt.return_value = expected_narration

        response = await narrator.narrate_environment(
            narrative_direction="Describe the ambient sounds"
        )

        # Verify response extraction worked
        assert response == expected_narration

        # Verify the client was called
        narrator.client.send_prompt.assert_called_once()


class TestNarratorCleanResult:
    """Tests for the clean_result method."""

    def test_clean_result_removes_character_dialogue(
        self, narrator_agent, mock_scene, setup_agents
    ):
        """Test that clean_result removes character dialogue lines."""
        # Ensure the narrator agent has the mock_scene with characters
        narrator_agent.scene = mock_scene

        # The clean_result logic checks for:
        # 1. line.lower().startswith(f"{character_name}:") - but character_name is NOT lowercased
        # 2. line.startswith(f"{character_name.upper()}") - UPPERCASE name at start
        # So we use ELENA (uppercase) to trigger the detection
        result = narrator_agent.clean_result(
            "The sun was setting.\nELENA says hello!\nThe birds flew away."
        )

        # Should stop at character dialogue (lines after ELENA are removed)
        assert "ELENA" not in result
        # Content before character dialogue should remain
        assert "The sun was setting" in result

    def test_clean_result_removes_hash_comments(
        self, narrator_agent, mock_scene, setup_agents
    ):
        """Test that clean_result removes lines starting with #."""
        # Ensure the narrator agent has the mock_scene
        narrator_agent.scene = mock_scene

        result = narrator_agent.clean_result(
            "The forest was quiet.\n# This is a comment\nThe wind blew."
        )

        # Comments should be removed
        assert "# This is a comment" not in result


class TestNarratorActionToNarration:
    """Tests for action_to_narration method."""

    @pytest.mark.asyncio
    async def test_action_to_narration_calls_method(self, active_context, mock_scene):
        """Test that action_to_narration calls the specified method and extracts the response."""
        narrator = active_context
        character = mock_scene.get_character("Elena")

        # Set specific mock response to verify extraction
        expected_narration = "Elena's eyes sparkled with determination."
        narrator.client.send_prompt.return_value = expected_narration

        message = await narrator.action_to_narration(
            action_name="narrate_character", emit_message=False, character=character
        )

        # Verify the message contains the extracted narration
        assert message is not None
        assert message.message == expected_narration

        # Verify push_history was called
        mock_scene.push_history.assert_called_once()

    def test_action_to_meta_generates_source(
        self, narrator_agent, mock_scene, setup_agents
    ):
        """Test that action_to_meta generates proper meta dict."""
        # Ensure the narrator agent has the mock_scene
        narrator_agent.scene = mock_scene

        # Use a character from the mock_scene so it matches scene.Character type
        character = mock_scene.get_character("Elena")

        meta = narrator_agent.action_to_meta(
            action_name="narrate_character",
            parameters={"character": character, "narrative_direction": "test"},
        )

        assert meta["agent"] == "narrator"
        assert meta["function"] == "narrate_character"
        assert "character" in meta["arguments"]
        # Character should be converted to name string
        assert meta["arguments"]["character"] == "Elena"


class TestNarratorResponseLengthCalculation:
    """Tests for response length calculation."""

    def test_calc_response_length_with_value(self, narrator_agent):
        """Test calc_response_length with specified value."""
        narrator_agent.actions["generation_override"].enabled = True
        narrator_agent.actions["generation_override"].config[
            "length_narrate_scene"
        ].value = 256

        # Should return the explicitly provided value
        result = narrator_agent.calc_response_length(128, "narrate_scene")
        assert result == 128

        # Explicit value is used directly (no ceiling)
        result = narrator_agent.calc_response_length(512, "narrate_scene")
        assert result == 512

    def test_calc_response_length_with_default(self, narrator_agent):
        """Test calc_response_length with default from per-action config."""
        narrator_agent.actions["generation_override"].enabled = True
        narrator_agent.actions["generation_override"].config[
            "length_narrate_scene"
        ].value = 256

        # None or negative value should use per-action config
        result = narrator_agent.calc_response_length(None, "narrate_scene")
        assert result == 256

        result = narrator_agent.calc_response_length(-1, "narrate_scene")
        assert result == 256

    def test_calc_response_length_different_actions(self, narrator_agent):
        """Test that different actions can have different response lengths."""
        narrator_agent.actions["generation_override"].enabled = True
        narrator_agent.actions["generation_override"].config[
            "length_narrate_scene"
        ].value = 256
        narrator_agent.actions["generation_override"].config[
            "length_narrate_query"
        ].value = 512

        result_scene = narrator_agent.calc_response_length(None, "narrate_scene")
        result_query = narrator_agent.calc_response_length(None, "narrate_query")

        assert result_scene == 256
        assert result_query == 512


class TestNarratorProperties:
    """Tests for narrator agent properties."""

    def test_extra_instructions_property(self, narrator_agent):
        """Test extra_instructions property."""
        narrator_agent.actions["generation_override"].enabled = True
        narrator_agent.actions["generation_override"].config[
            "instructions"
        ].value = "Test instruction"

        assert narrator_agent.extra_instructions == "Test instruction"

    def test_extra_instructions_disabled(self, narrator_agent):
        """Test extra_instructions when disabled."""
        narrator_agent.actions["generation_override"].enabled = False

        assert narrator_agent.extra_instructions == ""

    def test_jiggle_property(self, narrator_agent):
        """Test jiggle property."""
        narrator_agent.actions["generation_override"].enabled = True
        narrator_agent.actions["generation_override"].config["jiggle"].value = 0.5

        assert narrator_agent.jiggle == 0.5

    def test_action_response_length(self, narrator_agent):
        """Test action_response_length method."""
        narrator_agent.actions["generation_override"].enabled = True
        narrator_agent.actions["generation_override"].config[
            "length_progress_story"
        ].value = 512

        assert narrator_agent.action_response_length("progress_story") == 512
