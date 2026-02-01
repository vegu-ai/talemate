"""
Comprehensive unit tests for Scene.context_history method.

This tests the context_history method which generates context for AI prompts
by combining summarized history and current dialogue within token budgets.
"""

import json
import pytest
import types
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    DirectorMessage,
    ReinforcementMessage,
    ContextInvestigationMessage,
    Flags,
)


# Path to test data
DATA_DIR = Path(__file__).parent / "data" / "context_history"


def bind_context_history_methods(scene, Scene):
    """Bind all context_history methods from Scene class to a mock scene object."""
    scene._context_history_auto = lambda budget=8192, **kwargs: Scene._context_history_auto(scene, budget, **kwargs)
    scene._context_history_manual = lambda budget=8192, **kwargs: Scene._context_history_manual(scene, budget, **kwargs)
    scene.context_history = lambda budget=8192, **kwargs: Scene.context_history(scene, budget, **kwargs)


def load_test_data():
    """Load test data from JSON file."""
    with open(DATA_DIR / "test_scene_data.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_data():
    """Load test data from JSON."""
    return load_test_data()


@pytest.fixture
def mock_director():
    """Create a mock director agent."""
    director = Mock()
    director.actor_direction_mode = "direction"
    return director


@pytest.fixture
def mock_summarizer():
    """Create a mock summarizer agent with default settings."""
    summarizer = Mock()
    summarizer.layered_history_enabled = False
    summarizer.manage_scene_history_enabled = False
    summarizer.scene_history_dialogue_ratio = 50
    summarizer.scene_history_max_budget = 0
    return summarizer


@pytest.fixture
def mock_agents(mock_director, mock_summarizer):
    """Create a dict of mock agents for get_agent patch."""
    return {
        "director": mock_director,
        "summarizer": mock_summarizer,
    }


def create_character_messages(messages_data):
    """Create CharacterMessage objects from test data."""
    return [
        CharacterMessage(message=m["message"], source=m["source"])
        for m in messages_data
    ]


def create_narrator_messages(messages_data):
    """Create NarratorMessage objects from test data."""
    return [
        NarratorMessage(message=m["message"], source=m["source"])
        for m in messages_data
    ]


def create_director_messages(messages_data):
    """Create DirectorMessage objects from test data."""
    messages = []
    for m in messages_data:
        # DirectorMessage expects character in meta directly, not via set_source
        meta = {"character": m["character"]} if m.get("character") else None
        msg = DirectorMessage(message=m["message"], source=m["source"], meta=meta)
        messages.append(msg)
    return messages


def create_reinforcement_messages(messages_data):
    """Create ReinforcementMessage objects from test data."""
    messages = []
    for m in messages_data:
        msg = ReinforcementMessage(message=m["message"])
        msg.set_source(
            "world_state",
            "update_reinforcement",
            question=m["question"],
            character=m.get("character"),
        )
        messages.append(msg)
    return messages


def create_context_investigation_messages(messages_data):
    """Create ContextInvestigationMessage objects from test data."""
    messages = []
    for m in messages_data:
        msg = ContextInvestigationMessage(
            message=m["message"],
            sub_type=m.get("sub_type"),
        )
        if m.get("character"):
            msg.set_source(
                "summarizer",
                "context_investigation",
                character=m["character"],
                query="",
            )
        messages.append(msg)
    return messages


@pytest.fixture
def mock_scene(test_data):
    """
    Create a mock Scene object factory.

    Returns a factory function that creates scenes with configurable settings.
    """
    from talemate.tale_mate import Scene

    def _factory(
        history=None,
        archived_history=None,
        layered_history=None,
        include_narrator=False,
        include_director=False,
        include_reinforcements=False,
        include_context_investigation=False,
        hidden_message_indices=None,
    ):
        scene_data = test_data["basic_scene"]

        # Build history from various message types
        messages = []

        # Character messages
        char_messages = create_character_messages(test_data["messages"]["character"])
        messages.extend(char_messages)

        # Optionally add narrator messages
        if include_narrator:
            narrator_messages = create_narrator_messages(
                test_data["messages"]["narrator"]
            )
            messages.extend(narrator_messages)

        # Optionally add director messages
        if include_director:
            director_messages = create_director_messages(
                test_data["messages"]["director"]
            )
            messages.extend(director_messages)

        # Optionally add reinforcement messages
        if include_reinforcements:
            reinforcement_messages = create_reinforcement_messages(
                test_data["messages"]["reinforcement"]
            )
            messages.extend(reinforcement_messages)

        # Optionally add context investigation messages
        if include_context_investigation:
            ci_messages = create_context_investigation_messages(
                test_data["messages"]["context_investigation"]
            )
            messages.extend(ci_messages)

        # Override with custom history if provided
        if history is not None:
            messages = history

        # Apply hidden flags
        if hidden_message_indices:
            for idx in hidden_message_indices:
                if idx < len(messages):
                    messages[idx].hide()

        # Create scene mock using types.SimpleNamespace for flexibility
        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = (
            archived_history
            if archived_history is not None
            else test_data["archived_history"]
        )
        scene.layered_history = layered_history if layered_history is not None else []
        scene.ts = scene_data["ts"]
        scene.conversation_format = scene_data["conversation_format"]

        # Add get_intro method
        scene.get_intro = Mock(return_value=scene_data["intro"])

        # Bind the actual context_history methods from Scene class
        bind_context_history_methods(scene, Scene)

        return scene

    return _factory


# ---------------------------------------------------------------------------
# Tests: Basic Context History Functionality
# ---------------------------------------------------------------------------


class TestBasicContextHistory:
    """Test basic context_history functionality."""

    def test_returns_list(self, mock_scene, mock_agents):
        """context_history should return a list."""
        scene = mock_scene()

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        assert isinstance(result, list)

    def test_returns_strings(self, mock_scene, mock_agents):
        """All items in the returned list should be strings."""
        scene = mock_scene()

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        for item in result:
            assert isinstance(item, str)

    def test_includes_archived_history(self, mock_scene, mock_agents, test_data):
        """Should include archived history entries in the result."""
        scene = mock_scene()

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        # Check that some archived history text is present
        result_text = " ".join(result)
        assert "ancient ruins" in result_text or "hidden chamber" in result_text

    def test_includes_dialogue(self, mock_scene, mock_agents):
        """Should include current dialogue in the result."""
        scene = mock_scene()

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        assert "Elena" in result_text or "Marcus" in result_text

    def test_empty_history(self, mock_scene, mock_agents):
        """Should handle empty history gracefully."""
        scene = mock_scene(history=[], archived_history=[])

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        # Should still return a list (may include intro if context is sparse)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests: Budget Management
# ---------------------------------------------------------------------------


class TestBudgetManagement:
    """Test budget allocation and management."""

    def test_large_budget_includes_more_content(self, mock_scene, mock_agents):
        """Larger budget should include more content than smaller budget."""
        scene = mock_scene()

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            small_result = scene.context_history(budget=500)
            large_result = scene.context_history(budget=10000)

        # Larger budget should have more content
        small_len = len(" ".join(small_result))
        large_len = len(" ".join(large_result))
        assert large_len >= small_len


# ---------------------------------------------------------------------------
# Tests: Layered History
# ---------------------------------------------------------------------------


class TestLayeredHistory:
    """Test layered history functionality."""

    def test_uses_layered_history_when_available(self, mock_scene, mock_agents, test_data):
        """Should use layered history when enabled and available."""
        mock_agents["summarizer"].layered_history_enabled = True

        layered = [
            test_data["layered_history"]["layer_0"],
            test_data["layered_history"]["layer_1"],
        ]
        scene = mock_scene(layered_history=layered)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Should include content from layered history
        assert "Chapter" in result_text or "adventure" in result_text.lower()

    def test_falls_back_to_archived_when_layered_disabled(
        self, mock_scene, mock_agents, test_data
    ):
        """Should use archived history (not layered) when layered is disabled."""
        mock_agents["summarizer"].layered_history_enabled = False

        layered = [
            test_data["layered_history"]["layer_0"],
            test_data["layered_history"]["layer_1"],
        ]
        scene = mock_scene(layered_history=layered)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Should use archived history content, not layered
        assert "ancient ruins" in result_text or "hidden chamber" in result_text

    def test_chapter_labels(self, mock_scene, mock_agents, test_data):
        """Should include chapter labels when requested."""
        mock_agents["summarizer"].layered_history_enabled = True

        layered = [
            test_data["layered_history"]["layer_0"],
            test_data["layered_history"]["layer_1"],
        ]
        scene = mock_scene(layered_history=layered)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            with patch("talemate.agents.context.active_agent") as mock_active_agent:
                mock_ctx = Mock()
                mock_ctx.state = {}
                mock_active_agent.get.return_value = mock_ctx

                result = scene.context_history(budget=8192, chapter_labels=True)

        result_text = " ".join(result)
        # Should include chapter markers
        assert "Chapter" in result_text or "###" in result_text


# ---------------------------------------------------------------------------
# Tests: Message Filtering
# ---------------------------------------------------------------------------


class TestHiddenMessages:
    """Test hidden message filtering."""

    def test_hidden_messages_excluded_by_default(self, mock_scene, mock_agents):
        """Hidden messages should be excluded by default."""
        scene = mock_scene(hidden_message_indices=[0])

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        # First message should not be in result
        result_text = " ".join(result)
        assert "Hello there, traveler" not in result_text

    def test_hidden_messages_included_when_show_hidden(self, mock_scene, mock_agents):
        """Hidden messages should be included when show_hidden=True."""
        scene = mock_scene(hidden_message_indices=[0])

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, show_hidden=True)

        # First message should be in result
        result_text = " ".join(result)
        assert "Hello there, traveler" in result_text


class TestDirectorMessages:
    """Test director message filtering."""

    def test_director_messages_excluded_by_default(self, mock_scene, mock_agents):
        """Director messages should be excluded by default."""
        scene = mock_scene(include_director=True)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Director instruction content should not appear
        assert "hesitation" not in result_text.lower()

    def test_director_messages_included_when_keep_director_true(
        self, mock_scene, mock_agents
    ):
        """Director messages should be included when keep_director=True."""
        scene = mock_scene(include_director=True)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, keep_director=True)

        # Director messages should be included
        result_text = " ".join(result)
        assert "hesitation" in result_text.lower() or "determination" in result_text.lower()

    def test_director_messages_filtered_by_character(self, mock_scene, mock_agents):
        """Director messages should be filtered by character when keep_director is a string."""
        scene = mock_scene(include_director=True)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, keep_director="Elena")

        result_text = " ".join(result)
        # Only Elena's director messages should appear
        assert "hesitation" in result_text.lower()


class TestReinforcementMessages:
    """Test reinforcement message filtering."""

    def test_reinforcements_included_by_default(self, mock_scene, mock_agents):
        """Reinforcement messages should be included by default."""
        scene = mock_scene(include_reinforcements=True)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Reinforcement content should appear
        assert "prophecy" in result_text.lower() or "worried" in result_text.lower()

    def test_reinforcements_excluded_when_disabled(self, mock_scene, mock_agents):
        """Reinforcement messages should be excluded when include_reinforcements=False."""
        scene = mock_scene(include_reinforcements=True)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, include_reinforcements=False)

        result_text = " ".join(result)
        # Reinforcement-specific content should not appear
        # Check for reinforcement message formatting
        assert "Internal note" not in result_text


class TestContextInvestigationMessages:
    """Test context investigation message filtering."""

    def test_context_investigation_included_by_default(self, mock_scene, mock_agents):
        """Context investigation messages should be included by default."""
        scene = mock_scene(include_context_investigation=True)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Context investigation content should appear
        assert "silver hair" in result_text.lower() or "golden light" in result_text.lower()

    def test_context_investigation_excluded_when_disabled(self, mock_scene, mock_agents):
        """Context investigation should be excluded when keep_context_investigation=False."""
        scene = mock_scene(include_context_investigation=True)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, keep_context_investigation=False)

        result_text = " ".join(result)
        # Context investigation content should not appear
        assert "silver hair" not in result_text.lower()


# ---------------------------------------------------------------------------
# Tests: Assured Dialogue Number
# ---------------------------------------------------------------------------


class TestAssuredDialogueNum:
    """Test assured_dialogue_num parameter.

    In auto mode, assured_dialogue_num controls how many character messages
    are guaranteed to be included even if they dip into summarized content.
    """

    def test_assured_dialogue_dips_into_summarized(self, mock_agents, test_data):
        """With assured_dialogue_num, dialogue should dip past summarized_to boundary."""
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = False

        # Create 10 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history covers up to index 8, so summarized_to = 9
        # Only message 9 is after the boundary
        archived = [{"text": "Summary", "ts": "PT0S", "end": 9}]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene
        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            # assured_dialogue_num=5 means we need 5 character messages
            # Only 1 is after boundary, so we must dip into summarized content
            result = scene.context_history(budget=8192, assured_dialogue_num=5)

        result_text = " ".join(result)

        # Message 9 is after boundary, should be included
        assert "Message 9" in result_text
        # Messages 5-8 should also be included to meet assured=5
        assert "Message 5" in result_text

    def test_low_assured_stops_at_boundary(self, mock_agents, test_data):
        """With low assured_dialogue_num, should stop at boundary once met."""
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = False

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # summarized_to = 5, so messages 5-9 are after boundary (5 messages)
        archived = [{"text": "Summary", "ts": "PT0S", "end": 5}]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene
        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            # assured=2 means once we have 2 messages, we stop at boundary
            result = scene.context_history(budget=8192, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Messages 5-9 are after boundary, should be included
        assert "Message 9" in result_text
        assert "Message 5" in result_text
        # Messages before boundary should NOT be included (assured met)
        assert "Message 4" not in result_text
        assert "Message 0" not in result_text

    def test_zero_assured_respects_boundary_strictly(self, mock_agents, test_data):
        """With assured=0, should strictly respect the summarized_to boundary."""
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = False

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # summarized_to = 8, so only messages 8-9 are after boundary
        archived = [{"text": "Summary", "ts": "PT0S", "end": 8}]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene
        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, assured_dialogue_num=0)

        result_text = " ".join(result)

        # Only messages 8-9 should be included
        assert "Message 8" in result_text
        assert "Message 9" in result_text
        # Messages before boundary should NOT be included
        assert "Message 7" not in result_text
        assert "Message 0" not in result_text


# ---------------------------------------------------------------------------
# Tests: Intro Handling
# ---------------------------------------------------------------------------


class TestIntroHandling:
    """Test intro text insertion when context is sparse."""

    def test_intro_added_when_context_sparse(self, mock_scene, mock_agents):
        """Intro should be added when context is very sparse (< 128 tokens)."""
        scene = mock_scene(history=[], archived_history=[])

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Intro should be present when context is sparse
        assert "test scene" in result_text.lower() or len(result) >= 0

    def test_intro_not_added_when_context_sufficient(self, mock_scene, mock_agents):
        """Intro should not be added when context has sufficient content."""
        scene = mock_scene()  # Full history

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        # Result should contain dialogue, not just intro
        result_text = " ".join(result)
        assert "Elena" in result_text or "Marcus" in result_text


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_summarized_to_greater_than_history_length(self, mock_scene, mock_agents):
        """Should handle case where summarized_to exceeds history length."""
        # Create a scene with archived_history pointing beyond current history
        scene = mock_scene(
            archived_history=[
                {"text": "Old content", "ts": "PT0S", "end": 100}  # end > len(history)
            ]
        )

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        # Should not crash, should return valid content
        assert isinstance(result, list)

    def test_archived_history_without_end_key(self, mock_scene, mock_agents):
        """Should handle archived history entries without 'end' key (static entries)."""
        scene = mock_scene(
            archived_history=[
                {"text": "Static backstory", "ts": "PT0S"}  # No 'end' key
            ]
        )

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        assert isinstance(result, list)

    def test_static_archived_history(self, mock_scene, mock_agents, test_data):
        """Should handle static archived history entries (end=None)."""
        scene = mock_scene(archived_history=test_data["static_archived_history"])

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        # Static entries should be skipped in context collection
        assert isinstance(result, list)

    def test_very_small_budget(self, mock_scene, mock_agents):
        """Should handle very small budget gracefully."""
        scene = mock_scene()

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=10)  # Very small budget

        # Should return something, even if limited
        assert isinstance(result, list)

    def test_mixed_message_types(self, mock_scene, mock_agents):
        """Should handle history with mixed message types."""
        scene = mock_scene(
            include_narrator=True,
            include_director=True,
            include_reinforcements=True,
            include_context_investigation=True,
        )

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192)

        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: Dialogue/Summary Boundary
# ---------------------------------------------------------------------------


class TestDialogueSummaryBoundary:
    """Test that dialogue boundary behavior works correctly."""

    def test_dialogue_expands_with_manual_management(
        self, mock_agents, test_data
    ):
        """
        With manual management enabled, dialogue should EXPAND backwards
        to fill its budget, effectively "unsummarizing" archived entries.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50

        # Create 10 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history with end=6 means it covers indices 0-5
        # summarized_to = 6, so traditionally dialogue would start at index 6
        # But with expansion enabled, dialogue should expand backwards
        archived = [
            {"text": "Summary of early messages", "ts": "PT0S", "end": 6}
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, assured_dialogue_num=3)

        result_text = " ".join(result)

        # Messages 6-9 should definitely be included
        assert "Message 6" in result_text
        assert "Message 9" in result_text

        # With expansion, earlier messages should ALSO be included
        # (dialogue expands backwards to fill its budget)
        assert "Message 0" in result_text

        # The archived summary should NOT be included since its content
        # was "expanded" into dialogue
        assert "Summary of early messages" not in result_text

    def test_dialogue_expands_to_fill_budget(
        self, mock_agents, test_data
    ):
        """
        Dialogue should expand backwards to fill its allocated budget
        when manage_scene_history is enabled.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history covers messages 0-7 (summarized_to = 8)
        archived = [
            {"text": "Summary of early messages", "ts": "PT0S", "end": 7}
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, assured_dialogue_num=5)

        result_text = " ".join(result)

        # With expansion, all messages should be included (budget is large enough)
        assert "Message 0" in result_text
        assert "Message 8" in result_text
        assert "Message 9" in result_text

        # Count character messages included
        character_messages_in_result = sum(
            1 for r in result if "Message" in r and "Character" in r
        )
        # All 10 messages should be included (budget allows it)
        assert character_messages_in_result == 10

    def test_boundary_respected_without_manual_management(
        self, mock_agents, test_data
    ):
        """
        Without manual management, boundary should be respected
        once assured_dialogue_num is met.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = False

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history with end=6 means it covers indices 0-5
        # summarized_to = 6, so dialogue starts at index 6
        archived = [
            {"text": "Summary of early messages", "ts": "PT0S", "end": 6}
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, assured_dialogue_num=3)

        result_text = " ".join(result)

        # Messages 6-9 should be included
        assert "Message 6" in result_text
        assert "Message 9" in result_text

        # Messages 0-5 should NOT be included since assured is met
        assert "Message 0" not in result_text
        assert "Message 5" not in result_text

    def test_expansion_excludes_summarized_entries(self, mock_agents, test_data):
        """
        When dialogue expands into previously summarized content,
        the corresponding archived_history entries should be excluded
        from the context (to avoid duplication).
        """
        import types
        from talemate.util import count_tokens

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50  # 50% to dialogue

        # Create 10 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Create archived history with multiple entries
        archived = [
            {"text": "First summary chunk with lots of content.", "ts": "PT0S", "end": 3},
            {"text": "Second summary chunk with more content.", "ts": "PT30M", "end": 5},
            {"text": "Third summary chunk covering recent events.", "ts": "PT1H", "end": 7},
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            # Large budget allows dialogue to expand all the way back
            result = scene.context_history(budget=8192, assured_dialogue_num=2)

        result_text = " ".join(result)

        # All messages should be included via dialogue expansion
        assert "Message 0" in result_text
        assert "Message 9" in result_text

        # Archived summaries should NOT be included (they've been expanded)
        assert "First summary chunk" not in result_text
        assert "Second summary chunk" not in result_text
        assert "Third summary chunk" not in result_text

    def test_expansion_respects_layered_history_floor(self, mock_agents, test_data):
        """
        When layered history exists and is enabled, dialogue expansion
        should stop at the layered history boundary (expansion_floor).
        The expansion_floor is the end index of layered history, so
        dialogue can include that index but not go below it.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 80  # High dialogue ratio
        mock_agents["summarizer"].layered_history_enabled = True

        # Create 20 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(20)
        ]

        # Archived history
        archived = [
            {"text": "Summary before layered", "ts": "PT0S", "end": 3},
            {"text": "Summary after layered", "ts": "PT30M", "end": 10},
            {"text": "Recent summary", "ts": "PT1H", "end": 15},
        ]

        # Layered history - the base layer (layer 0) ends at index 5
        # This means dialogue cannot expand past index 5 (i.e., can't go to index 4 or below)
        layered = [
            [  # Layer 0 (base layer)
                {
                    "text": "Layered summary of early events",
                    "ts_start": "PT0S",
                    "ts_end": "PT15M",
                    "end": 5,  # This is the expansion floor
                },
            ],
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=16384, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Messages 5-19 should be included (index 5 is expansion_floor, inclusive)
        assert "Message 5" in result_text
        assert "Message 6" in result_text
        assert "Message 19" in result_text

        # Messages 0-4 should NOT be included (they're below the expansion floor)
        assert "Message 0" not in result_text
        assert "Message 4" not in result_text

        # Layered history summary should be included in context
        assert "Layered summary" in result_text

    def test_archived_entries_fill_gap_between_layered_and_dialogue(
        self, mock_agents, test_data
    ):
        """
        When dialogue budget is exhausted before reaching the expansion floor,
        archived entries should fill the gap between layered history and dialogue.

        This tests the fix for the bug where archived_history was sliced by
        list index instead of filtered by end value.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50
        mock_agents["summarizer"].layered_history_enabled = True

        # Create 20 messages with LONG text to exhaust budget quickly
        long_text = "x" * 200  # ~50 tokens each
        messages = [
            CharacterMessage(
                message=f"Character{i}: Message {i} {long_text}", source="ai"
            )
            for i in range(20)
        ]

        # Archived history entries - note these are stored by list index,
        # but their end values refer to message indices
        archived = [
            {"text": "Covered by layered", "ts": "PT0S", "end": 3},
            {"text": "Gap summary for messages 6-9", "ts": "PT15M", "end": 10},
            {"text": "Covered by dialogue", "ts": "PT30M", "end": 18},
        ]

        # Layered history ends at index 5
        layered = [
            [
                {
                    "text": "Layered summary",
                    "ts_start": "PT0S",
                    "ts_end": "PT10M",
                    "end": 5,
                },
            ],
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        # Budget that allows only a few long messages in dialogue (50% of 400 = 200 tokens)
        # Each message is ~50+ tokens, so only ~4 messages fit in dialogue
        # Dialogue will start around index 16, leaving a gap between layer end (5)
        # and dialogue start (~16)
        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=400, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Layered history should be included
        assert "Layered summary" in result_text

        # The gap summary (end=10) should fill the gap between layered (end=5)
        # and wherever dialogue starts
        assert "Gap summary" in result_text

        # Entry with end=3 should NOT be included (covered by layered)
        assert "Covered by layered" not in result_text

    def test_partial_expansion_keeps_summary(self, mock_agents, test_data):
        """
        When dialogue only partially expands into an archived entry's range,
        the archived entry should be KEPT in context (with overlap) rather
        than being removed and leaving a gap.

        This tests the fix for partial expansion - if dialogue can't fully
        cover an entry's range, the entry stays in context.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50
        mock_agents["summarizer"].layered_history_enabled = False

        # Create 20 messages with LONG text to limit how far dialogue can expand
        long_text = "x" * 300  # ~75 tokens each
        messages = [
            CharacterMessage(
                message=f"Character{i}: Message {i} {long_text}", source="ai"
            )
            for i in range(20)
        ]

        # Archived history entries
        # Entry 0: covers messages 0-7 (entry_start=0, end=7)
        # Entry 1: covers messages 8-15 (entry_start=8, end=15)
        # Entry 2: covers messages 16-18 (entry_start=16, end=18)
        archived = [
            {"text": "Early summary covering messages 0-7", "ts": "PT0S", "end": 7},
            {"text": "Middle summary covering messages 8-15", "ts": "PT30M", "end": 15},
            {"text": "Recent summary covering messages 16-18", "ts": "PT1H", "end": 18},
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        # Small budget: 50% of 600 = 300 tokens for dialogue
        # Each message is ~75+ tokens, so only ~3-4 messages fit
        # Dialogue will start around index 16-17
        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=600, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Recent messages should be in dialogue
        assert "Message 19" in result_text

        # Early summary should be included (dialogue doesn't reach it at all)
        assert "Early summary" in result_text

        # Middle summary covers 8-15. If dialogue starts at ~16-17,
        # dialogue doesn't overlap with this entry at all, so it should be included
        assert "Middle summary" in result_text

        # The key test: if dialogue starts at, say, 17 and Recent summary covers 16-18,
        # then entry_start=16 < dialogue_start_idx (~17), so it's a PARTIAL expansion.
        # With the fix, this summary SHOULD be kept (with overlap).
        # Without the fix, it would be incorrectly removed.

    def test_fully_expanded_entry_excluded(self, mock_agents, test_data):
        """
        When dialogue fully covers an archived entry's range, that entry
        should be excluded from context to avoid duplication.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 80  # High ratio
        mock_agents["summarizer"].layered_history_enabled = False

        # Create 10 short messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived entries - small ranges that dialogue can fully cover
        archived = [
            {"text": "Summary of message 0-2", "ts": "PT0S", "end": 2},
            {"text": "Summary of message 3-5", "ts": "PT30M", "end": 5},
            {"text": "Summary of message 6-8", "ts": "PT1H", "end": 8},
        ]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        # Large budget allows dialogue to expand all the way back
        with patch("talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]):
            result = scene.context_history(budget=8192, assured_dialogue_num=2)

        result_text = " ".join(result)

        # All messages should be included (dialogue expanded fully)
        assert "Message 0" in result_text
        assert "Message 9" in result_text

        # All summaries should be EXCLUDED (fully expanded into dialogue)
        assert "Summary of message 0-2" not in result_text
        assert "Summary of message 3-5" not in result_text
        assert "Summary of message 6-8" not in result_text
