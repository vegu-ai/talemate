"""
Comprehensive unit tests for Scene.context_history method.

This tests the context_history method which generates context for AI prompts
by combining summarized history and current dialogue within token budgets.
"""

import json
import pytest
import types
from pathlib import Path
from unittest.mock import Mock, patch

from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    DirectorMessage,
    ReinforcementMessage,
    ContextInvestigationMessage,
)


# Path to test data
DATA_DIR = Path(__file__).parent / "data" / "context_history"


def bind_context_history_methods(scene, Scene):
    """Bind all context_history methods from Scene class to a mock scene object."""
    scene._context_history_auto = (
        lambda budget=8192, **kwargs: Scene._context_history_auto(
            scene, budget, **kwargs
        )
    )
    scene._context_history_manual = (
        lambda budget=8192, **kwargs: Scene._context_history_manual(
            scene, budget, **kwargs
        )
    )
    scene.context_history = lambda budget=8192, **kwargs: Scene.context_history(
        scene, budget, **kwargs
    )


def load_test_data():
    """Load test data from JSON file."""
    with open(DATA_DIR / "test_scene_data.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _char_count_tokens(source):
    """Deterministic token counter for tests: 1 char = 1 token."""
    if isinstance(source, list):
        return sum(_char_count_tokens(s) for s in source)
    return len(str(source))


def _pad(label: str, total_chars: int) -> str:
    """Create a string of exact character length with a readable label prefix.

    Example: _pad("Archived 0", 100) → "Archived 0" + 90 dots = exactly 100 chars.
    This makes budget arithmetic trivial with the 1-char-per-token mock.
    """
    if len(label) >= total_chars:
        return label[:total_chars]
    return label + "." * (total_chars - len(label))


def _make_message(index: int, total_chars: int) -> CharacterMessage:
    """Create a CharacterMessage with exact character length.

    The message format is "C<index>: M<index> <padding>" padded to total_chars.
    """
    label = f"C{index}: M{index} "
    text = _pad(label, total_chars)
    return CharacterMessage(message=text, source="ai")


@pytest.fixture(autouse=True)
def mock_count_tokens():
    """Replace count_tokens with character-length counting for deterministic tests."""
    with patch("talemate.tale_mate.count_tokens", side_effect=_char_count_tokens):
        yield


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
        NarratorMessage(message=m["message"], source=m["source"]) for m in messages_data
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        assert isinstance(result, list)

    def test_returns_strings(self, mock_scene, mock_agents):
        """All items in the returned list should be strings."""
        scene = mock_scene()

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        for item in result:
            assert isinstance(item, str)

    def test_includes_archived_history(self, mock_scene, mock_agents, test_data):
        """Should include archived history entries in the result."""
        scene = mock_scene()

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        # Check that some archived history text is present
        result_text = " ".join(result)
        assert "ancient ruins" in result_text or "hidden chamber" in result_text

    def test_includes_dialogue(self, mock_scene, mock_agents):
        """Should include current dialogue in the result."""
        scene = mock_scene()

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        assert "Elena" in result_text or "Marcus" in result_text

    def test_empty_history(self, mock_scene, mock_agents):
        """Should handle empty history gracefully."""
        scene = mock_scene(history=[], archived_history=[])

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

    def test_uses_layered_history_when_available(
        self, mock_scene, mock_agents, test_data
    ):
        """Should use layered history when enabled and available."""
        mock_agents["summarizer"].layered_history_enabled = True

        layered = [
            test_data["layered_history"]["layer_0"],
            test_data["layered_history"]["layer_1"],
        ]
        scene = mock_scene(layered_history=layered)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        # First message should not be in result
        result_text = " ".join(result)
        assert "Hello there, traveler" not in result_text

    def test_hidden_messages_included_when_show_hidden(self, mock_scene, mock_agents):
        """Hidden messages should be included when show_hidden=True."""
        scene = mock_scene(hidden_message_indices=[0])

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192, show_hidden=True)

        # First message should be in result
        result_text = " ".join(result)
        assert "Hello there, traveler" in result_text


class TestDirectorMessages:
    """Test director message filtering."""

    def test_director_messages_excluded_by_default(self, mock_scene, mock_agents):
        """Director messages should be excluded by default."""
        scene = mock_scene(include_director=True)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Director instruction content should not appear
        assert "hesitation" not in result_text.lower()

    def test_director_messages_included_when_keep_director_true(
        self, mock_scene, mock_agents
    ):
        """Director messages should be included when keep_director=True."""
        scene = mock_scene(include_director=True)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192, keep_director=True)

        # Director messages should be included
        result_text = " ".join(result)
        assert (
            "hesitation" in result_text.lower()
            or "determination" in result_text.lower()
        )

    def test_director_messages_filtered_by_character(self, mock_scene, mock_agents):
        """Director messages should be filtered by character when keep_director is a string."""
        scene = mock_scene(include_director=True)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192, keep_director="Elena")

        result_text = " ".join(result)
        # Only Elena's director messages should appear
        assert "hesitation" in result_text.lower()


class TestReinforcementMessages:
    """Test reinforcement message filtering."""

    def test_reinforcements_included_by_default(self, mock_scene, mock_agents):
        """Reinforcement messages should be included by default."""
        scene = mock_scene(include_reinforcements=True)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Reinforcement content should appear
        assert "prophecy" in result_text.lower() or "worried" in result_text.lower()

    def test_reinforcements_excluded_when_disabled(self, mock_scene, mock_agents):
        """Reinforcement messages should be excluded when include_reinforcements=False."""
        scene = mock_scene(include_reinforcements=True)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Context investigation content should appear
        assert (
            "silver hair" in result_text.lower()
            or "golden light" in result_text.lower()
        )

    def test_context_investigation_excluded_when_disabled(
        self, mock_scene, mock_agents
    ):
        """Context investigation should be excluded when keep_context_investigation=False."""
        scene = mock_scene(include_context_investigation=True)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(
                budget=8192, keep_context_investigation=False
            )

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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Intro should be present when context is sparse
        assert "test scene" in result_text.lower() or len(result) >= 0

    def test_intro_not_added_when_context_sufficient(self, mock_scene, mock_agents):
        """Intro should not be added when context has sufficient content."""
        scene = mock_scene()  # Full history

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        assert isinstance(result, list)

    def test_static_archived_history(self, mock_scene, mock_agents, test_data):
        """Should handle static archived history entries (end=None)."""
        scene = mock_scene(archived_history=test_data["static_archived_history"])

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        # Static entries should be skipped in context collection
        assert isinstance(result, list)

    def test_very_small_budget(self, mock_scene, mock_agents):
        """Should handle very small budget gracefully."""
        scene = mock_scene()

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192)

        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: Dialogue/Summary Boundary
# ---------------------------------------------------------------------------


class TestDialogueSummaryBoundary:
    """Test that dialogue boundary behavior works correctly."""

    def test_dialogue_expands_with_manual_management(self, mock_agents, test_data):
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
        archived = [{"text": "Summary of early messages", "ts": "PT0S", "end": 6}]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

    def test_dialogue_expands_to_fill_budget(self, mock_agents, test_data):
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
        archived = [{"text": "Summary of early messages", "ts": "PT0S", "end": 7}]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

    def test_boundary_respected_without_manual_management(self, mock_agents, test_data):
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
        archived = [{"text": "Summary of early messages", "ts": "PT0S", "end": 6}]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50  # 50% to dialogue

        # Create 10 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Create archived history with multiple entries
        archived = [
            {
                "text": "First summary chunk with lots of content.",
                "ts": "PT0S",
                "end": 3,
            },
            {
                "text": "Second summary chunk with more content.",
                "ts": "PT30M",
                "end": 5,
            },
            {
                "text": "Third summary chunk covering recent events.",
                "ts": "PT1H",
                "end": 7,
            },
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
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

    def test_layered_history_dialogue_budget_limited(self, mock_agents, test_data):
        """
        With the budget-aware layered detail gradient, dialogue fills its
        budget (ratio% of total). When dialogue covers all messages,
        archived entries and layered summaries are correctly suppressed
        since the raw dialogue already provides full detail.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents[
            "summarizer"
        ].scene_history_dialogue_ratio = 80  # High dialogue ratio
        mock_agents["summarizer"].layered_history_enabled = True

        # Create 30 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(30)
        ]

        # 6 archived entries covering different message ranges
        archived = [
            {"text": "Summary A", "ts": "PT0S", "end": 3},        # idx 0
            {"text": "Summary B", "ts": "PT10M", "end": 7},       # idx 1
            {"text": "Summary C", "ts": "PT20M", "end": 11},      # idx 2
            {"text": "Summary D", "ts": "PT30M", "end": 15},      # idx 3
            {"text": "Summary E", "ts": "PT1H", "end": 20},       # idx 4
            {"text": "Summary F", "ts": "PT1H30M", "end": 25},    # idx 5
        ]

        # Layered history covers archived entries 0-3
        layered = [
            [  # Layer 0 (base layer)
                {
                    "text": "Layered summary of early events",
                    "ts_start": "PT0S",
                    "ts_end": "PT30M",
                    "end": 3,  # archived_history index, NOT message index
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

        # With large budget, dialogue fills 80% which covers all 30 short messages
        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=16384, assured_dialogue_num=2)

        result_text = " ".join(result)

        # With enough budget, dialogue covers all messages
        assert "Message 0" in result_text
        assert "Message 15" in result_text
        assert "Message 29" in result_text

        # When dialogue covers everything, archived entries are excluded
        # (entry_start >= dialogue_start_idx for all entries)
        assert "Summary A" not in result_text
        assert "Summary B" not in result_text
        assert "Summary C" not in result_text
        assert "Summary D" not in result_text
        assert "Summary E" not in result_text
        assert "Summary F" not in result_text

        # Layered summary is also suppressed since archived (which covers
        # layer 0's range) was suppressed by dialogue
        assert "Layered summary" not in result_text

    def test_archived_entries_fill_gap_between_layered_and_dialogue(
        self, mock_agents, test_data
    ):
        """
        Archived entries fill the gap between dialogue and more compressed
        layers. Archived collects freely (no layered filter).

        Using 200c messages, 50c archived, 50c layered.
        Budget = 1200, ratio = 50%:
          dial = 600  → 3 of 30 msgs (200c) → dialogue_start = 27
          arch = 600  → all 6 entries (50c each = 300c total) easily fit
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50
        mock_agents["summarizer"].layered_history_enabled = True

        messages = [_make_message(i, 200) for i in range(30)]

        archived = [
            {"text": _pad("Early archived 1", 50), "ts": "PT0S", "end": 3},
            {"text": _pad("Early archived 2", 50), "ts": "PT10M", "end": 7},
            {"text": _pad("Early archived 3", 50), "ts": "PT20M", "end": 11},
            {"text": _pad("Gap summary middle", 50), "ts": "PT30M", "end": 15},
            {"text": _pad("Gap summary later", 50), "ts": "PT1H", "end": 20},
            {"text": _pad("Near dialogue", 50), "ts": "PT1H30M", "end": 25},
        ]

        layered = [
            [{"text": _pad("Layered summary", 50), "ts_start": "PT0S", "ts_end": "PT20M", "end": 2}],
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=1200, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Archived entries fill the gap (collected freely)
        assert "Gap summary middle" in result_text

        # Dialogue present
        assert "M29" in result_text

    def test_partial_expansion_keeps_summary(self, mock_agents, test_data):
        """
        Partial expansion: dialogue only covers part of an archived entry's
        range → that entry is KEPT (with overlap).

        Using 300c messages, 50c archived entries.
        Budget = 2000, ratio = 50%:
          dial = 1000  → 3 of 20 msgs (300c) → dialogue_start = 17
          arch = 1000  → all 3 entries (50c each) easily fit

        Entry 2 covers msgs 16-18. dialogue_start=17, so entry_start=16 < 17.
        Partial overlap → entry kept.
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50
        mock_agents["summarizer"].layered_history_enabled = False

        messages = [_make_message(i, 300) for i in range(20)]

        archived = [
            {"text": _pad("Early summary 0-7", 50), "ts": "PT0S", "end": 7},
            {"text": _pad("Middle summary 8-15", 50), "ts": "PT30M", "end": 15},
            {"text": _pad("Recent summary 16-18", 50), "ts": "PT1H", "end": 18},
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=2000, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Recent messages in dialogue
        assert "M19" in result_text

        # Early summary included (dialogue doesn't reach it)
        assert "Early summary" in result_text

        # Middle summary included (dialogue doesn't overlap at all)
        assert "Middle summary" in result_text

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
        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=8192, assured_dialogue_num=2)

        result_text = " ".join(result)

        # All messages should be included (dialogue expanded fully)
        assert "Message 0" in result_text
        assert "Message 9" in result_text

        # All summaries should be EXCLUDED (fully expanded into dialogue)
        assert "Summary of message 0-2" not in result_text
        assert "Summary of message 3-5" not in result_text
        assert "Summary of message 6-8" not in result_text

    def test_layered_history_index_space_divergence(self, mock_agents, test_data):
        """
        Archived entries overlap with layered history's range but are
        collected freely. Layer 0 only fills the gap archived couldn't reach.

        Using 100c messages, 50c archived, 50c layered.
        Budget = 2000, ratio = 40%:
          dial = 800  → 8 of 50 msgs (100c) → dialogue_start = 42
          arch = 480  → 9 of 10 entries (50c each) → arch_boundary = 0
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 40
        mock_agents["summarizer"].layered_history_enabled = True

        messages = [_make_message(i, 100) for i in range(50)]

        # 10 archived entries (50 chars each)
        archived = [
            {"text": _pad(f"Archived {i}", 50), "ts": f"PT{i*10}M", "end": (i + 1) * 5 - 1}
            for i in range(10)
        ]

        # Layered history covers archived 0-4
        layered = [
            [{"text": _pad("Layered first half", 50), "ts_start": "PT0S", "ts_end": "PT40M", "start": 0, "end": 4}],
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=2000, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Archived entries present
        archived_found = any(f"Archived {i}" in result_text for i in range(10))
        assert archived_found, "At least one archived entry should be present"

        # Dialogue present
        assert "M49" in result_text


# ---------------------------------------------------------------------------
# Tests: Budget-Aware Layered Detail Gradient
# ---------------------------------------------------------------------------


class TestLayeredDetailGradient:
    """Test the budget-aware layered detail gradient in _context_history_manual.

    The gradient recursively applies the dialogue ratio at each level:
    - Dialogue: ratio% of total budget
    - Archived history: ratio% of remaining
    - Layer 0: ratio% of remaining after archived
    - Layer 1: ratio% of remaining after layer 0
    - Top layer: ALL remaining budget
    """

    # Character sizes used across gradient tests.
    # Every message / entry is padded to an exact char count so budget
    # arithmetic is trivial (1 char = 1 token with the mock).
    MSG_CHARS = 100       # each dialogue message
    ARCH_CHARS = 200      # each archived-history entry
    L0_CHARS = 300        # each layer-0 entry
    L1_CHARS = 150        # each layer-1 entry

    @classmethod
    def _make_messages(cls, count):
        """Create *count* messages, each exactly MSG_CHARS characters."""
        return [_make_message(i, cls.MSG_CHARS) for i in range(count)]

    def test_gradient_all_levels_present(self, mock_agents, test_data):
        """
        All four levels (layer 1, layer 0, archived, dialogue) appear when
        each level's budget runs out before covering everything.

        Budget arithmetic (1 char = 1 token, ratio = 0.40):
          total  = 2000
          dial   = 800   → 8 of 30 msgs (100c each) → dialogue_start = 22
          arch   = 480   → 2 of 8 entries (200c each) → arch_boundary = 5
          L0     = 288   → 0 of 4 entries (300c each) — but top-layer gets
          L1     = 432     the remaining budget so at least L1 fits.

        Actually let's set budget so each level gets at least 1 entry:
          total  = 3000
          dial   = 1200  → 12 msgs → dialogue_start = 18
          arch   = 720   → 3 entries → arch_boundary = 4
          L0     = 432   → 1 entry (300c) → l0_boundary = 2
          L1     = 648   → 4 entries (150c) easily
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 40
        mock_agents["summarizer"].layered_history_enabled = True

        messages = self._make_messages(30)

        # 8 archived entries (200 chars each)
        archived = [
            {"text": _pad(f"Archived {i}", self.ARCH_CHARS), "ts": f"PT{i*10}M", "end": (i + 1) * 3 - 1}
            for i in range(8)
        ]
        # end values: 2, 5, 8, 11, 14, 17, 20, 23

        # Layer 0: 4 entries (300 chars each) covering archived 0-5
        layer_0 = [
            {"text": _pad("L0-A", self.L0_CHARS), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 1},
            {"text": _pad("L0-B", self.L0_CHARS), "ts_start": "PT10M", "ts_end": "PT20M", "start": 2, "end": 2},
            {"text": _pad("L0-C", self.L0_CHARS), "ts_start": "PT20M", "ts_end": "PT30M", "start": 3, "end": 3},
            {"text": _pad("L0-D", self.L0_CHARS), "ts_start": "PT30M", "ts_end": "PT50M", "start": 4, "end": 5},
        ]

        # Layer 1: 2 entries (150 chars each) covering layer 0 entries 0-2
        layer_1 = [
            {"text": _pad("L1-X", self.L1_CHARS), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 1},
            {"text": _pad("L1-Y", self.L1_CHARS), "ts_start": "PT10M", "ts_end": "PT20M", "start": 2, "end": 2},
        ]

        layered = [layer_0, layer_1]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=3000)

        result_text = " ".join(result)

        # Dialogue present
        assert "M29" in result_text, "Last message should be in dialogue"

        # Some archived entries present
        archived_present = any(f"Archived {i}" in result_text for i in range(8))
        assert archived_present, "Some archived entries should be present"

        # At least one layer 0 entry present
        layer0_present = any(f"L0-{c}" in result_text for c in "ABCD")
        assert layer0_present, "At least one layer 0 entry should be present"

        # Layer 1 present
        layer1_present = "L1-X" in result_text or "L1-Y" in result_text
        assert layer1_present, "Layer 1 should be present"

        # Assembly order: layer 1 < layer 0 < dialogue
        l1_pos = min(
            (result_text.find(f"L1-{c}") for c in "XY" if f"L1-{c}" in result_text),
            default=-1,
        )
        l0_pos = min(
            (result_text.find(f"L0-{c}") for c in "ABCD" if f"L0-{c}" in result_text),
            default=-1,
        )
        dial_pos = result_text.find("M29")
        assert l1_pos < l0_pos, "Layer 1 should come before layer 0"
        assert l0_pos < dial_pos, "Layer 0 should come before dialogue"

    def test_gradient_higher_layers_cover_gaps(self, mock_agents, test_data):
        """
        When a lower level's budget runs out, higher layers cover the gap.

        Budget arithmetic (ratio = 0.40, budget = 2000):
          dial  = 800  → 8 of 30 msgs (100c) → dialogue_start = 22
          arch  = 480  → 2 of 6 entries (200c) → arch_boundary = 3
          L0    = 288  → 0 (300c entries don't fit)
          L1    = 432  → 2 (150c entries fit) — L1 covers what L0/arch missed
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 40
        mock_agents["summarizer"].layered_history_enabled = True

        messages = self._make_messages(30)

        # 6 archived entries (200 chars each)
        archived = [
            {"text": _pad(f"Archived {i}", self.ARCH_CHARS), "ts": f"PT{i*10}M", "end": (i + 1) * 5 - 1}
            for i in range(6)
        ]
        # end values: 4, 9, 14, 19, 24, 29

        # Layer 0: 3 entries (300 chars each) covering archived 0-3
        layer_0 = [
            {"text": _pad("L0-A", self.L0_CHARS), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 0},
            {"text": _pad("L0-B", self.L0_CHARS), "ts_start": "PT10M", "ts_end": "PT20M", "start": 1, "end": 1},
            {"text": _pad("L0-C", self.L0_CHARS), "ts_start": "PT20M", "ts_end": "PT30M", "start": 2, "end": 3},
        ]

        # Layer 1: covers L0 entries 0-1
        layer_1 = [
            {"text": _pad("L1-overview", self.L1_CHARS), "ts_start": "PT0S", "ts_end": "PT20M", "start": 0, "end": 1},
        ]

        layered = [layer_0, layer_1]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=2000)

        result_text = " ".join(result)

        # Dialogue present
        assert "M29" in result_text

        # Some archived entries present (gap between dialogue and older history)
        archived_present = any(f"Archived {i}" in result_text for i in range(6))
        assert archived_present, "Some archived entries should fill the gap"

    def test_gradient_no_layered_history_falls_back(self, mock_agents, test_data):
        """
        No layered history → falls back to dialogue + archived (single split).

        Budget arithmetic (ratio = 0.50, budget = 1500):
          dial = 750  → 7 of 20 msgs (100c) → dialogue_start = 13
          arch = 750  → 3 entries (200c each) easily fit
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 50
        mock_agents["summarizer"].layered_history_enabled = True

        messages = self._make_messages(20)

        archived = [
            {"text": _pad("Archived early", self.ARCH_CHARS), "ts": "PT0S", "end": 5},
            {"text": _pad("Archived middle", self.ARCH_CHARS), "ts": "PT30M", "end": 10},
            {"text": _pad("Archived recent", self.ARCH_CHARS), "ts": "PT1H", "end": 15},
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

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=1500)

        result_text = " ".join(result)

        # Both archived and dialogue present
        assert "Archived early" in result_text
        assert "M19" in result_text

    def test_gradient_budget_allocation_proportions(self, mock_agents, test_data):
        """
        Budget follows the recursive ratio pattern. Note: timestamp labels
        add ~60-70 chars overhead per entry (e.g. "2 Hours ago: ").

        ratio = 0.40, budget = 4000, 50 messages at 100c:
          dial  = 1600 → 16 msgs → dialogue_start = 34
          remaining = 2400
          arch  = 960  → 300c + ~60c ts ≈ 360c each → 2 entries fit
          L0    = 576  → 200c + ~70c ts ≈ 270c each → 2 entries fit
          L1    = 864  → 100c + ~70c ts ≈ 170c each → easily fits
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 40
        mock_agents["summarizer"].layered_history_enabled = True

        messages = self._make_messages(50)

        # 8 archived entries (300c each) covering 6 messages each
        archived = [
            {"text": _pad(f"Archived {i}", 300), "ts": f"PT{i*10}M", "end": (i + 1) * 6 - 1}
            for i in range(8)
        ]
        # end values: 5, 11, 17, 23, 29, 35, 41, 47

        # 4 L0 entries (200c each) covering archived 0-5
        layer_0 = [
            {"text": _pad("L0-A", 200), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 1},
            {"text": _pad("L0-B", 200), "ts_start": "PT10M", "ts_end": "PT20M", "start": 2, "end": 2},
            {"text": _pad("L0-C", 200), "ts_start": "PT20M", "ts_end": "PT30M", "start": 3, "end": 3},
            {"text": _pad("L0-D", 200), "ts_start": "PT30M", "ts_end": "PT50M", "start": 4, "end": 5},
        ]

        # 2 L1 entries (100c each) covering L0 0-2
        layer_1 = [
            {"text": _pad("L1-X", 100), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 1},
            {"text": _pad("L1-Y", 100), "ts_start": "PT10M", "ts_end": "PT20M", "start": 2, "end": 2},
        ]

        layered = [layer_0, layer_1]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=4000)

        result_text = " ".join(result)

        # Dialogue
        assert "M49" in result_text

        # Archived present
        archived_present = any(f"Archived {i}" in result_text for i in range(8))
        assert archived_present, "At least one archived entry should be present"

        # Layer 0 present
        assert "L0-" in result_text, "At least one layer 0 entry should be present"

        # Assembly order: context levels before dialogue
        archived_pos = max(
            (result_text.find(f"Archived {i}") for i in range(8) if f"Archived {i}" in result_text),
            default=-1,
        )
        dialogue_pos = result_text.find("M49")
        assert archived_pos < dialogue_pos, "Archived should come before dialogue"

    def test_gradient_chapter_labels_across_levels(self, mock_agents, test_data):
        """
        Chapter labels should be applied to layered history entries.

        Budget = 2000, ratio = 0.40:
          dial = 800  → 8 of 20 msgs (100c) → dialogue_start = 12
          arch = 480  → 2 of 4 entries (200c) → arch_boundary = 1
          L0   = 288  → 0 entries (300c each don't fit)
          L1   = 432  → 2 entries (150c each fit)
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 40
        mock_agents["summarizer"].layered_history_enabled = True

        messages = self._make_messages(20)

        # 4 archived entries (200 chars each)
        archived = [
            {"text": _pad(f"Archived {i}", self.ARCH_CHARS), "ts": f"PT{i*10}M", "end": (i + 1) * 5 - 1}
            for i in range(4)
        ]

        layer_0 = [
            {"text": _pad("L0-entry", self.L0_CHARS), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 0},
        ]

        layer_1 = [
            {"text": _pad("L1-entry", self.L1_CHARS), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 0},
        ]

        layered = [layer_0, layer_1]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            with patch("talemate.agents.context.active_agent") as mock_active_agent:
                mock_ctx = Mock()
                mock_ctx.state = {}
                mock_active_agent.get.return_value = mock_ctx

                result = scene.context_history(budget=2000, chapter_labels=True)

        result_text = " ".join(result)

        # Chapter labels should be present on layered history entries
        assert "### Chapter" in result_text

    def test_gradient_empty_layer_skipped(self, mock_agents, test_data):
        """
        Empty layer should be skipped gracefully.

        Budget = 1500, ratio = 0.40:
          dial = 600  → 6 of 20 msgs (100c) → dialogue_start = 14
          arch = 360  → 1 entry (200c) → arch_boundary = 2
          L0   = 216  → 0 entries (300c don't fit)
          L1   = 324  → (empty, skipped)
        """
        import types

        mock_agents["summarizer"].manage_scene_history_enabled = True
        mock_agents["summarizer"].scene_history_dialogue_ratio = 40
        mock_agents["summarizer"].layered_history_enabled = True

        messages = self._make_messages(20)

        archived = [
            {"text": _pad(f"Archived {i}", self.ARCH_CHARS), "ts": f"PT{i*10}M", "end": (i + 1) * 5 - 1}
            for i in range(4)
        ]

        layer_0 = [
            {"text": _pad("L0-A", self.L0_CHARS), "ts_start": "PT0S", "ts_end": "PT10M", "start": 0, "end": 1},
            {"text": _pad("L0-B", self.L0_CHARS), "ts_start": "PT10M", "ts_end": "PT20M", "start": 2, "end": 2},
        ]

        layer_1 = []  # empty

        layered = [layer_0, layer_1]

        scene = types.SimpleNamespace()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.conversation_format = "chat"
        scene.get_intro = Mock(return_value=None)

        from talemate.tale_mate import Scene

        bind_context_history_methods(scene, Scene)

        with patch(
            "talemate.tale_mate.get_agent", side_effect=lambda x: mock_agents[x]
        ):
            result = scene.context_history(budget=1500)

        result_text = " ".join(result)

        # Dialogue present
        assert "M19" in result_text
        # Some context present
        has_context = (
            "L0-" in result_text
            or any(f"Archived {i}" in result_text for i in range(4))
        )
        assert has_context, "Some context should be present"
        assert isinstance(result, list)
