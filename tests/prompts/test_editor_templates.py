"""
Unit tests for editor agent methods.

Tests that editor agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

import talemate.instance as instance
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

    def filtered_sheet(self, *args, **kwargs):
        return f"name: {self.name}\ngender: {self.gender}"


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
    scene.writing_style = None
    scene.agent_state = {}
    scene.characters = [player, npc]
    scene.character_names = [player.name, npc.name]

    # Mock Character class for isinstance check - use MockCharacter
    scene.Character = MockCharacter

    # Mock push_history for tests that need it
    scene.push_history = AsyncMock()

    # Mock collect_messages for revision methods
    scene.collect_messages = Mock(return_value=[])
    scene.message_index = Mock(return_value=0)

    # Mock snapshot for fix-continuity templates
    scene.snapshot = Mock(return_value="Current scene state")

    # Mock intent_state
    intent_state = Mock()
    intent_state.active = True
    intent_state.intent = "A fantasy adventure story."
    intent_state.instructions = "Make the story engaging."
    intent_state.phase = Mock()
    intent_state.phase.intent = "The hero explores the forest."
    intent_state.current_scene_type = Mock(
        id="exploration",
        name="Exploration",
        description="An exploration scene",
        instructions="Focus on discovery.",
    )
    intent_state.scene_types = {}
    scene.intent_state = intent_state

    return scene


@pytest.fixture
def mock_memory_agent():
    """Create a mock memory agent."""
    memory = Mock()
    memory.query = AsyncMock(return_value="Mocked memory response")
    memory.multi_query = AsyncMock(return_value={})
    memory.compare_string_lists = AsyncMock(
        return_value={"similarity_matches": [], "cosine_similarity_matrix": []}
    )
    return memory


@pytest.fixture
def mock_summarizer_agent():
    """Create a mock summarizer agent."""
    summarizer = Mock()
    summarizer.get_cached_analysis = AsyncMock(return_value="")
    return summarizer


@pytest.fixture
def mock_narrator_agent_for_registry():
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
def editor_agent(mock_llm_client, mock_scene):
    """Create an EditorAgent instance with mocked dependencies."""
    agent = EditorAgent(client=mock_llm_client)
    agent.scene = mock_scene
    # Add state attribute for template rendering
    agent.state = Mock()
    agent.state.dynamic_instructions = []
    return agent


@pytest.fixture
def mock_director_agent():
    """Create a mock director agent for character guidance."""
    director = Mock()
    director.get_cached_character_guidance = AsyncMock(return_value="")
    return director


@pytest.fixture
def setup_agents(
    mock_memory_agent,
    mock_summarizer_agent,
    mock_narrator_agent_for_registry,
    mock_director_agent,
):
    """Set up the agent registry with mocked agents."""
    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Create mock editor for the registry
    mock_editor = Mock()
    mock_editor.rag_build = AsyncMock(return_value=[])

    # Set up mock agents in the registry
    instance.AGENTS["narrator"] = mock_narrator_agent_for_registry
    instance.AGENTS["editor"] = mock_editor
    instance.AGENTS["memory"] = mock_memory_agent
    instance.AGENTS["summarizer"] = mock_summarizer_agent
    instance.AGENTS["director"] = mock_director_agent

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(editor_agent, mock_scene, setup_agents):
    """Set up active scene and agent context for tests."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent, ActiveAgentContext

    # Create proper agent context using ActiveAgentContext
    agent_context = ActiveAgentContext(agent=editor_agent, fn=lambda: None)

    scene_token = active_scene.set(mock_scene)
    agent_token = active_agent.set(agent_context)

    yield editor_agent

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


class TestEditorAddDetailMethod:
    """Tests for the add_detail method that calls editor.add-detail template."""

    @pytest.mark.asyncio
    async def test_add_detail_calls_client(self, active_context, mock_scene):
        """Test that add_detail calls the LLM client with rendered prompt."""
        editor = active_context
        character = mock_scene.get_character("Elena")

        # Enable add_detail action
        editor.actions["add_detail"].enabled = True

        response = await editor.add_detail(
            content="Elena: Hello there.", character=character
        )

        # Verify response was returned
        assert response is not None
        assert len(response) > 0

        # Verify the client's send_prompt was called
        editor.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = editor.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])  # First positional arg is the prompt

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0
        # Verify character name appears in the prompt
        assert "Elena" in prompt_text

    @pytest.mark.asyncio
    async def test_add_detail_disabled_returns_original(
        self, active_context, mock_scene
    ):
        """Test that add_detail returns original content when disabled."""
        editor = active_context
        character = mock_scene.get_character("Elena")

        # Ensure add_detail is disabled (default)
        editor.actions["add_detail"].enabled = False

        original_content = "Elena: Hello there."
        response = await editor.add_detail(
            content=original_content, character=character
        )

        # Should return original content unchanged
        assert response == original_content

        # Client should not have been called
        editor.client.send_prompt.assert_not_called()


class TestEditorRevisionRewriteMethod:
    """Tests for the revision_rewrite method that calls revision templates."""

    @pytest.mark.asyncio
    async def test_revision_rewrite_calls_client_when_issues_found(
        self, active_context, mock_scene, mock_memory_agent
    ):
        """Test that revision_rewrite calls the LLM client when issues are found."""
        editor = active_context

        # Enable revision
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "rewrite"
        editor.actions["revision"].config["min_issues"].value = 1

        # Provide history messages for comparison
        history_messages = [
            Mock(message="The forest was dark and mysterious.", typ="narrator"),
        ]
        mock_scene.collect_messages = Mock(return_value=history_messages)

        # Mock memory agent to return similarity matches (repetition detected)
        # [text_index, history_index, similarity]
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [[0, 0, 0.9]],
                "cosine_similarity_matrix": [],
            }
        )

        # Mock focal handler response
        with patch("talemate.game.focal.Focal") as mock_focal_class:
            mock_focal = AsyncMock()
            mock_focal.state = Mock()
            mock_focal.state.calls = [Mock(result="Revised text here.")]
            mock_focal.request = AsyncMock()
            mock_focal_class.return_value = mock_focal

            from talemate.agents.editor.revision import RevisionInformation

            info = RevisionInformation(
                text="The forest was dark. The forest was quiet.",
                character=None,
            )

            await editor.revision_rewrite(info)

            # Verify the client's send_prompt was called for analysis
            editor.client.send_prompt.assert_called()

            # Get the prompt that was sent
            call_args = editor.client.send_prompt.call_args
            prompt_text = str(call_args[0][0])

            # Verify the prompt contains the text
            assert "forest" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_revision_rewrite_returns_original_when_no_issues(
        self, active_context, mock_scene, mock_memory_agent
    ):
        """Test that revision_rewrite returns original when no issues found."""
        editor = active_context

        # Enable revision
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "rewrite"

        # Mock memory agent to return no similarity matches
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        from talemate.agents.editor.revision import RevisionInformation

        original_text = "The sun was setting over the hills."
        info = RevisionInformation(
            text=original_text,
            character=None,
        )

        response = await editor.revision_rewrite(info)

        # Should return original text since no issues
        assert response == original_text


class TestEditorRevisionUnslopMethod:
    """Tests for the revision_unslop method that calls unslop templates."""

    @pytest.mark.asyncio
    async def test_revision_unslop_calls_client(
        self, active_context, mock_scene, mock_memory_agent, mock_summarizer_agent
    ):
        """Test that revision_unslop calls the LLM client and extracts FIX content."""
        editor = active_context
        character = mock_scene.get_character("Elena")

        # Enable revision with unslop method
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"

        # Mock memory agent to return no similarity matches
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        # Set up client to return response with FIX tags
        expected_fix_content = '"The forest is beautiful," she said softly.'
        editor.client.send_prompt = AsyncMock(
            return_value=f"<FIX>{expected_fix_content}</FIX>"
        )

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text='Elena: "The forest is ethereally luminescent," she breathed softly.',
            character=character,
        )

        response = await editor.revision_unslop(info)

        # Verify the FIX_SPEC extractor correctly parsed the response
        # The response should be the character-prefixed extracted content
        assert response == f"Elena: {expected_fix_content}"
        # Verify FIX tags were stripped (proves FIX_SPEC extraction worked)
        assert "<FIX>" not in response
        assert "</FIX>" not in response

        # Verify the client's send_prompt was called
        editor.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = editor.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify the prompt contains expected content
        assert len(prompt_text) > 0
        assert "forest" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_revision_unslop_with_character(
        self, active_context, mock_scene, mock_memory_agent, mock_summarizer_agent
    ):
        """Test that revision_unslop extracts FIX content for character dialogue."""
        editor = active_context
        character = mock_scene.get_character("Elena")

        # Enable revision with unslop method
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"

        # Mock memory agent
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        # Set up client to return response with FIX tags
        expected_fix_content = '"Hello," she said softly.'
        editor.client.send_prompt = AsyncMock(
            return_value=f"<FIX>{expected_fix_content}</FIX>"
        )

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text='Elena: "Hello," she breathed ethereally.',
            character=character,
        )

        response = await editor.revision_unslop(info)

        # Verify the FIX_SPEC extractor correctly parsed the response
        # The response should be the character-prefixed extracted content
        assert response == f"Elena: {expected_fix_content}"
        # Verify FIX tags were stripped
        assert "<FIX>" not in response
        assert "</FIX>" not in response

        # Verify the client's send_prompt was called
        editor.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_revision_unslop_contextual_generation(
        self, active_context, mock_scene, mock_memory_agent, mock_summarizer_agent
    ):
        """Test that revision_unslop extracts FIX content for contextual generation."""
        editor = active_context

        # Enable revision with unslop method
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"

        # Mock memory agent
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        # Set up client to return response with FIX tags
        expected_fix_content = "A warrior with great strength."
        editor.client.send_prompt = AsyncMock(
            return_value=f"<FIX>{expected_fix_content}</FIX>"
        )

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="A warrior with the strength of a thousand suns.",
            character=None,
            context_type="character attribute",
            context_name="abilities",
        )

        response = await editor.revision_unslop(info)

        # Verify the FIX_SPEC extractor correctly parsed the response
        # No character prefix since character is None
        assert response == expected_fix_content
        # Verify FIX tags were stripped
        assert "<FIX>" not in response
        assert "</FIX>" not in response

        # Verify the client's send_prompt was called
        editor.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = editor.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify the prompt contains context type info
        assert "character" in prompt_text.lower() or "attribute" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_revision_unslop_summarization(
        self, active_context, mock_scene, mock_memory_agent, mock_summarizer_agent
    ):
        """Test that revision_unslop extracts FIX content for summarization."""
        editor = active_context

        # Enable revision with unslop method
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"

        # Mock memory agent
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        # Set up client to return response with FIX tags
        expected_fix_content = "The heroes journeyed through the mountains."
        editor.client.send_prompt = AsyncMock(
            return_value=f"<FIX>{expected_fix_content}</FIX>"
        )

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text="The heroes journeyed through the treacherous mountain pass.",
            character=None,
            summarization_history=["Chapter 1: The journey began."],
        )

        response = await editor.revision_unslop(info)

        # Verify the FIX_SPEC extractor correctly parsed the response
        assert response == expected_fix_content
        # Verify FIX tags were stripped
        assert "<FIX>" not in response
        assert "</FIX>" not in response

        # Verify the client's send_prompt was called
        editor.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_revision_unslop_returns_original_when_no_fix_tag(
        self, active_context, mock_scene, mock_memory_agent, mock_summarizer_agent
    ):
        """Test that revision_unslop returns original when no FIX tag in response."""
        editor = active_context
        character = mock_scene.get_character("Elena")

        # Enable revision with unslop method
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"

        # Mock memory agent
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        # Set up client to return response WITHOUT FIX tags
        editor.client.send_prompt = AsyncMock(
            return_value="The text looks fine, no changes needed."
        )

        from talemate.agents.editor.revision import RevisionInformation

        original_text = 'Elena: "The forest was quiet."'
        info = RevisionInformation(
            text=original_text,
            character=character,
        )

        response = await editor.revision_unslop(info)

        # Should return original text since no FIX tag
        assert response == original_text


class TestEditorRevisionReviseMethod:
    """Tests for the revision_revise dispatcher method."""

    @pytest.mark.asyncio
    async def test_revision_revise_dispatches_to_dedupe(
        self, active_context, mock_scene, mock_memory_agent
    ):
        """Test that revision_revise dispatches to dedupe method."""
        editor = active_context

        # Enable revision with dedupe method
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "dedupe"

        # Mock memory agent to return no matches
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        from talemate.agents.editor.revision import RevisionInformation

        original_text = "The sun was setting."
        info = RevisionInformation(
            text=original_text,
            character=None,
        )

        response = await editor.revision_revise(info)

        # Should return original text since no matches found
        assert response == original_text

        # Client should NOT be called for dedupe (no LLM needed)
        editor.client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_revision_revise_dispatches_to_unslop(
        self, active_context, mock_scene, mock_memory_agent, mock_summarizer_agent
    ):
        """Test that revision_revise dispatches to unslop and extracts FIX content."""
        editor = active_context
        character = mock_scene.get_character("Elena")

        # Enable revision with unslop method
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["revision_method"].value = "unslop"

        # Mock memory agent
        mock_memory_agent.compare_string_lists = AsyncMock(
            return_value={
                "similarity_matches": [],
                "cosine_similarity_matrix": [],
            }
        )

        # Set up client to return response with FIX tags
        expected_fix_content = '"The forest was quiet," she said.'
        editor.client.send_prompt = AsyncMock(
            return_value=f"<FIX>{expected_fix_content}</FIX>"
        )

        from talemate.agents.editor.revision import RevisionInformation

        info = RevisionInformation(
            text='Elena: "The forest was ethereally quiet," she breathed.',
            character=character,
        )

        response = await editor.revision_revise(info)

        # Verify the FIX_SPEC extractor correctly parsed the response
        assert response == f"Elena: {expected_fix_content}"
        # Verify FIX tags were stripped
        assert "<FIX>" not in response
        assert "</FIX>" not in response

        # Verify the client's send_prompt was called (unslop uses LLM)
        editor.client.send_prompt.assert_called_once()


class TestEditorUtilityMethods:
    """Tests for editor utility methods (non-LLM calls)."""

    def test_fix_exposition_in_text_chat_format(self, editor_agent, mock_scene):
        """Test fix_exposition_in_text with chat formatting."""
        editor_agent.scene = mock_scene
        editor_agent.actions["fix_exposition"].config["formatting"].value = "chat"

        text = 'Elena: "Hello there." She smiled.'
        result = editor_agent.fix_exposition_in_text(text)

        # Should process the text
        assert result is not None
        assert len(result) > 0

    def test_fix_exposition_in_text_novel_format(self, editor_agent, mock_scene):
        """Test fix_exposition_in_text with novel formatting."""
        editor_agent.scene = mock_scene
        editor_agent.actions["fix_exposition"].config["formatting"].value = "novel"

        text = 'Elena: "Hello there." *She smiled.*'
        result = editor_agent.fix_exposition_in_text(text)

        # Should process the text and remove asterisks
        assert result is not None
        assert "*" not in result


class TestEditorCleanupMethods:
    """Tests for editor cleanup methods."""

    @pytest.mark.asyncio
    async def test_cleanup_character_message(self, active_context, mock_scene):
        """Test cleanup_character_message processes text correctly."""
        editor = active_context
        character = mock_scene.get_character("Elena")

        # Enable fix_exposition
        editor.actions["fix_exposition"].enabled = True
        editor.actions["fix_exposition"].config["formatting"].value = "novel"

        content = 'Elena: "Hello there." *She smiled warmly.*'
        result = await editor.cleanup_character_message(content, character)

        # Should return processed content
        assert result is not None
        assert "Elena" in result

    @pytest.mark.asyncio
    async def test_clean_up_narration(self, active_context):
        """Test clean_up_narration processes text correctly."""
        editor = active_context

        # Enable fix_exposition
        editor.actions["fix_exposition"].enabled = True
        editor.actions["fix_exposition"].config["narrator"].value = True
        editor.actions["fix_exposition"].config["formatting"].value = "novel"

        content = "*The sun set slowly over the horizon.*"
        result = await editor.clean_up_narration(content)

        # Should return processed content
        assert result is not None

    @pytest.mark.asyncio
    async def test_cleanup_user_input(self, active_context):
        """Test cleanup_user_input processes text correctly."""
        editor = active_context

        # Enable fix_exposition
        editor.actions["fix_exposition"].enabled = True
        editor.actions["fix_exposition"].config["user_input"].value = True
        editor.actions["fix_exposition"].config["formatting"].value = "chat"

        text = "Hello there"
        result = await editor.cleanup_user_input(text)

        # Should wrap in quotes for chat format
        assert result is not None
        assert '"' in result

    @pytest.mark.asyncio
    async def test_cleanup_user_input_special_prefix(self, active_context):
        """Test cleanup_user_input preserves special prefix commands."""
        editor = active_context

        # Enable fix_exposition
        editor.actions["fix_exposition"].enabled = True

        # Commands starting with special prefixes should not be modified
        for prefix in ["!", "@", "/"]:
            text = f"{prefix}command arg1 arg2"
            result = await editor.cleanup_user_input(text)
            assert result == text


class TestEditorProperties:
    """Tests for editor agent properties."""

    def test_fix_exposition_enabled_property(self, editor_agent):
        """Test fix_exposition_enabled property."""
        editor_agent.actions["fix_exposition"].enabled = True
        assert editor_agent.fix_exposition_enabled is True

        editor_agent.actions["fix_exposition"].enabled = False
        assert editor_agent.fix_exposition_enabled is False

    def test_fix_exposition_formatting_property(self, editor_agent):
        """Test fix_exposition_formatting property."""
        editor_agent.actions["fix_exposition"].config["formatting"].value = "chat"
        assert editor_agent.fix_exposition_formatting == "chat"

        editor_agent.actions["fix_exposition"].config["formatting"].value = "novel"
        assert editor_agent.fix_exposition_formatting == "novel"

    def test_revision_enabled_property(self, editor_agent):
        """Test revision_enabled property."""
        editor_agent.actions["revision"].enabled = True
        assert editor_agent.revision_enabled is True

        editor_agent.actions["revision"].enabled = False
        assert editor_agent.revision_enabled is False

    def test_revision_method_property(self, editor_agent):
        """Test revision_method property."""
        editor_agent.actions["revision"].config["revision_method"].value = "dedupe"
        assert editor_agent.revision_method == "dedupe"

        editor_agent.actions["revision"].config["revision_method"].value = "unslop"
        assert editor_agent.revision_method == "unslop"

        editor_agent.actions["revision"].config["revision_method"].value = "rewrite"
        assert editor_agent.revision_method == "rewrite"
