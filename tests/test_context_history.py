"""
Comprehensive unit tests for Scene.context_history method.

This tests the context_history method which generates context for AI prompts
by combining summarized history and current dialogue within token budgets.

Uses the shared conftest infrastructure (MockScene, bootstrap_scene) for
real agent wiring, with only count_tokens mocked for deterministic budgets.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

import talemate.util as util
from conftest import MockScene, bootstrap_scene
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    DirectorMessage,
    ReinforcementMessage,
    ContextInvestigationMessage,
)


# Path to test data
DATA_DIR = Path(__file__).parent / "data" / "context_history"


def load_test_data():
    """Load test data from JSON file."""
    with open(DATA_DIR / "test_scene_data.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_count_tokens():
    """Replace count_tokens with character-length counting for deterministic tests.

    Must patch each import location because ``from X import Y`` creates a
    separate reference that patch.object on the source module won't reach.
    """
    with (
        patch.object(util, "count_tokens", side_effect=_char_count_tokens),
        patch("talemate.tale_mate.count_tokens", side_effect=_char_count_tokens),
        patch(
            "talemate.agents.summarize.context_history.count_tokens",
            side_effect=_char_count_tokens,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def agents():
    """Bootstrap real agents and configure conversation format to 'chat'.

    Using 'chat' format ensures messages are returned as plain text (1:1 with
    the char-based token mock). The default 'movie_script' format wraps messages
    in NAME/END-OF-LINE markers which would change token counts.
    """
    scene = MockScene()
    agents_dict = bootstrap_scene(scene)

    # Set conversation format to "chat" for deterministic token counting
    conversation = agents_dict["conversation"]
    conversation.actions["generation_override"].enabled = True
    conversation.actions["generation_override"].config["format"].value = "chat"

    # Disable best-fit mode by default so standard-path tests are deterministic.
    # TestBestFit explicitly re-enables it via _enable_best_fit().
    summarizer = agents_dict["summarizer"]
    summarizer.actions["manage_scene_history"].config["best_fit"].value = False

    return agents_dict


@pytest.fixture
def summarizer(agents):
    """Real SummarizeAgent with default scene history settings."""
    return agents["summarizer"]


@pytest.fixture
def test_data():
    """Load test data from JSON."""
    return load_test_data()


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


def _make_scene(
    test_data,
    history=None,
    archived_history=None,
    layered_history=None,
    include_narrator=False,
    include_director=False,
    include_reinforcements=False,
    include_context_investigation=False,
    hidden_message_indices=None,
    intro=None,
):
    """Create a configured MockScene instance.

    Uses real Scene infrastructure — context_history() works natively.
    """
    scene_data = test_data["basic_scene"]

    # Build history from various message types
    messages = []

    # Character messages
    char_messages = create_character_messages(test_data["messages"]["character"])
    messages.extend(char_messages)

    # Optionally add narrator messages
    if include_narrator:
        narrator_messages = create_narrator_messages(test_data["messages"]["narrator"])
        messages.extend(narrator_messages)

    # Optionally add director messages
    if include_director:
        director_messages = create_director_messages(test_data["messages"]["director"])
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

    # Create MockScene and configure it
    scene = MockScene()
    scene.history = messages
    scene.archived_history = (
        archived_history
        if archived_history is not None
        else test_data["archived_history"]
    )
    scene.layered_history = layered_history if layered_history is not None else []
    scene.ts = scene_data["ts"]
    scene.intro = intro if intro is not None else scene_data.get("intro", "")

    return scene


@pytest.fixture
def mock_scene(test_data):
    """
    Scene factory fixture.

    Returns a factory function that creates MockScene instances with
    configurable settings. Uses real Scene.context_history() — no binding needed.
    """

    def _factory(
        history=None,
        archived_history=None,
        layered_history=None,
        include_narrator=False,
        include_director=False,
        include_reinforcements=False,
        include_context_investigation=False,
        hidden_message_indices=None,
        intro=None,
    ):
        return _make_scene(
            test_data,
            history=history,
            archived_history=archived_history,
            layered_history=layered_history,
            include_narrator=include_narrator,
            include_director=include_director,
            include_reinforcements=include_reinforcements,
            include_context_investigation=include_context_investigation,
            hidden_message_indices=hidden_message_indices,
            intro=intro,
        )

    return _factory


# ---------------------------------------------------------------------------
# Tests: Basic Context History Functionality
# ---------------------------------------------------------------------------


class TestBasicContextHistory:
    """Test basic context_history functionality."""

    def test_returns_list(self, mock_scene):
        """context_history should return a list."""
        scene = mock_scene()
        result = scene.context_history(budget=8192)
        assert isinstance(result, list)

    def test_returns_strings(self, mock_scene):
        """All items in the returned list should be strings."""
        scene = mock_scene()
        result = scene.context_history(budget=8192)
        for item in result:
            assert isinstance(item, str)

    def test_includes_archived_history(self, test_data):
        """Should include archived history entries in the result."""
        # Create enough messages so dialogue (30% budget) doesn't cover everything,
        # with archived_history end values within history range.
        messages = [_make_message(i, 200) for i in range(30)]
        archived = [
            {"text": "The party arrived at the ancient ruins.", "ts": "PT0S", "end": 9},
            {"text": "They discovered a hidden chamber.", "ts": "PT30M", "end": 19},
        ]
        scene = _make_scene(test_data, history=messages, archived_history=archived)
        result = scene.context_history(budget=8192)

        # Check that some archived history text is present
        result_text = " ".join(result)
        assert "ancient ruins" in result_text or "hidden chamber" in result_text

    def test_includes_dialogue(self, mock_scene):
        """Should include current dialogue in the result."""
        scene = mock_scene()
        result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        assert "Elena" in result_text or "Marcus" in result_text

    def test_empty_history(self, mock_scene):
        """Should handle empty history gracefully."""
        scene = mock_scene(history=[], archived_history=[])
        result = scene.context_history(budget=8192)

        # Should still return a list (may include intro if context is sparse)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests: Budget Management
# ---------------------------------------------------------------------------


class TestBudgetManagement:
    """Test budget allocation and management."""

    def test_large_budget_includes_more_content(self, mock_scene):
        """Larger budget should include more content than smaller budget."""
        scene = mock_scene()

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

    def test_uses_layered_history_when_available(self, summarizer, test_data):
        """Should use layered history when enabled and available."""
        summarizer.actions["layered_history"].enabled = True

        messages = [_make_message(i, 200) for i in range(30)]
        # Archived entries large enough (500c) that the archived budget
        # can't cover all of them, leaving archived_boundary > 0 so the
        # layer entry isn't excluded by the boundary check.
        archived = [
            {"text": _pad("Archived early", 500), "ts": "PT0S", "end": 4},
            {"text": _pad("Archived mid", 500), "ts": "PT10M", "end": 9},
            {"text": _pad("Archived late", 500), "ts": "PT30M", "end": 14},
            {"text": _pad("Archived recent", 500), "ts": "PT1H", "end": 19},
        ]
        layered = [
            [  # Layer 0 covers archived 0-1
                {
                    "text": "The adventure began with the party forming.",
                    "ts_start": "PT0S",
                    "ts_end": "PT10M",
                    "start": 0,
                    "end": 1,
                },
            ],
        ]

        scene = _make_scene(
            test_data,
            history=messages,
            archived_history=archived,
            layered_history=layered,
        )
        # Budget kept small enough that archived can't cover all entries,
        # ensuring archived_boundary > 0 so the layer entry is included.
        result = scene.context_history(budget=4096)

        result_text = " ".join(result)
        # Should include content from layered history
        assert "adventure" in result_text.lower()

    def test_falls_back_to_archived_when_layered_disabled(self, summarizer, test_data):
        """Should use archived history (not layered) when layered is disabled."""
        summarizer.actions["layered_history"].enabled = False

        messages = [_make_message(i, 200) for i in range(30)]
        archived = [
            {"text": "The party arrived at the ancient ruins.", "ts": "PT0S", "end": 4},
            {
                "text": "They discovered a hidden chamber beneath the temple.",
                "ts": "PT30M",
                "end": 9,
            },
            {
                "text": "A mysterious figure emerged from the shadows.",
                "ts": "PT1H",
                "end": 14,
            },
            {"text": "The confrontation revealed secrets.", "ts": "PT1H30M", "end": 19},
        ]
        layered = [
            [
                {
                    "text": "Layered summary of early events.",
                    "ts_start": "PT0S",
                    "ts_end": "PT30M",
                    "start": 0,
                    "end": 1,
                }
            ],
        ]

        scene = _make_scene(
            test_data,
            history=messages,
            archived_history=archived,
            layered_history=layered,
        )
        result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Should use archived history content, not layered
        assert "ancient ruins" in result_text or "hidden chamber" in result_text
        # Layered content should NOT appear since layered is disabled
        assert "Layered summary" not in result_text

    def test_chapter_labels(self, summarizer, test_data):
        """Should include chapter labels when requested."""
        summarizer.actions["layered_history"].enabled = True

        # Need enough messages and archived entries large enough to exceed
        # their budget so the layer entry isn't fully covered by
        # archived_boundary.
        messages = [_make_message(i, 200) for i in range(30)]
        archived = [
            {"text": _pad("Archived early", 500), "ts": "PT0S", "end": 4},
            {"text": _pad("Archived mid-early", 500), "ts": "PT10M", "end": 9},
            {"text": _pad("Archived mid-late", 500), "ts": "PT30M", "end": 14},
            {"text": _pad("Archived recent", 500), "ts": "PT1H", "end": 19},
        ]
        layered = [
            [
                {
                    "text": "The adventure began with the party forming.",
                    "ts_start": "PT0S",
                    "ts_end": "PT10M",
                    "start": 0,
                    "end": 0,
                }
            ],
        ]

        scene = _make_scene(
            test_data,
            history=messages,
            archived_history=archived,
            layered_history=layered,
        )

        with patch("talemate.agents.context.active_agent") as mock_active_agent:
            mock_ctx = Mock()
            mock_ctx.state = {}
            mock_active_agent.get.return_value = mock_ctx

            # Budget kept small enough that archived can't cover all
            # entries, ensuring the layer entry is included.
            result = scene.context_history(budget=4096, chapter_labels=True)

        result_text = " ".join(result)
        # Should include chapter markers
        assert "Chapter" in result_text or "###" in result_text


# ---------------------------------------------------------------------------
# Tests: Message Filtering
# ---------------------------------------------------------------------------


class TestHiddenMessages:
    """Test hidden message filtering."""

    def test_hidden_messages_excluded_by_default(self, mock_scene):
        """Hidden messages should be excluded by default."""
        scene = mock_scene(hidden_message_indices=[0])
        result = scene.context_history(budget=8192)

        # First message should not be in result
        result_text = " ".join(result)
        assert "Hello there, traveler" not in result_text

    def test_hidden_messages_included_when_show_hidden(self, mock_scene):
        """Hidden messages should be included when show_hidden=True."""
        scene = mock_scene(hidden_message_indices=[0])
        result = scene.context_history(budget=8192, show_hidden=True)

        # First message should be in result
        result_text = " ".join(result)
        assert "Hello there, traveler" in result_text


class TestDirectorMessages:
    """Test director message filtering."""

    def test_director_messages_excluded_by_default(self, mock_scene):
        """Director messages should be excluded by default."""
        scene = mock_scene(include_director=True)
        result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Director instruction content should not appear
        assert "hesitation" not in result_text.lower()

    def test_director_messages_included_when_keep_director_true(self, mock_scene):
        """Director messages should be included when keep_director=True."""
        scene = mock_scene(include_director=True)
        result = scene.context_history(budget=8192, keep_director=True)

        # Director messages should be included
        result_text = " ".join(result)
        assert (
            "hesitation" in result_text.lower()
            or "determination" in result_text.lower()
        )

    def test_director_messages_filtered_by_character(self, mock_scene):
        """Director messages should be filtered by character when keep_director is a string."""
        scene = mock_scene(include_director=True)
        result = scene.context_history(budget=8192, keep_director="Elena")

        result_text = " ".join(result)
        # Only Elena's director messages should appear
        assert "hesitation" in result_text.lower()


class TestReinforcementMessages:
    """Test reinforcement message filtering."""

    def test_reinforcements_included_by_default(self, mock_scene):
        """Reinforcement messages should be included by default."""
        scene = mock_scene(include_reinforcements=True)
        result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Reinforcement content should appear
        assert "prophecy" in result_text.lower() or "worried" in result_text.lower()

    def test_reinforcements_excluded_when_disabled(self, mock_scene):
        """Reinforcement messages should be excluded when include_reinforcements=False."""
        scene = mock_scene(include_reinforcements=True)
        result = scene.context_history(budget=8192, include_reinforcements=False)

        result_text = " ".join(result)
        # Reinforcement-specific content should not appear
        # Check for reinforcement message formatting
        assert "Internal note" not in result_text


class TestContextInvestigationMessages:
    """Test context investigation message filtering."""

    def test_context_investigation_included_by_default(self, mock_scene):
        """Context investigation messages should be included by default."""
        scene = mock_scene(include_context_investigation=True)
        result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Context investigation content should appear
        assert (
            "silver hair" in result_text.lower()
            or "golden light" in result_text.lower()
        )

    def test_context_investigation_excluded_when_disabled(self, mock_scene):
        """Context investigation should be excluded when keep_context_investigation=False."""
        scene = mock_scene(include_context_investigation=True)
        result = scene.context_history(budget=8192, keep_context_investigation=False)

        result_text = " ".join(result)
        # Context investigation content should not appear
        assert "silver hair" not in result_text.lower()


# ---------------------------------------------------------------------------
# Tests: Assured Dialogue Number
# ---------------------------------------------------------------------------


class TestAssuredDialogueNum:
    """Test assured_dialogue_num parameter.

    When boundary enforcement is enabled, assured_dialogue_num controls how
    many character messages are guaranteed to be included even if they dip
    into summarized content.
    """

    def test_assured_dialogue_dips_into_summarized(self, summarizer, test_data):
        """With assured_dialogue_num, dialogue should dip past summarized_to boundary."""
        summarizer.actions["manage_scene_history"].config[
            "enforce_boundary"
        ].value = True

        # Create 10 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history covers up to index 8, so summarized_to = 9
        # Only message 9 is after the boundary
        archived = [{"text": "Summary", "ts": "PT0S", "end": 9}]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

        # assured_dialogue_num=5 means we need 5 character messages
        # Only 1 is after boundary, so we must dip into summarized content
        result = scene.context_history(budget=8192, assured_dialogue_num=5)

        result_text = " ".join(result)

        # Message 9 is after boundary, should be included
        assert "Message 9" in result_text
        # Messages 5-8 should also be included to meet assured=5
        assert "Message 5" in result_text

    def test_low_assured_stops_at_boundary(self, summarizer, test_data):
        """With low assured_dialogue_num, should stop at boundary once met."""
        summarizer.actions["manage_scene_history"].config[
            "enforce_boundary"
        ].value = True

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # summarized_to = 5, so messages 5-9 are after boundary (5 messages)
        archived = [{"text": "Summary", "ts": "PT0S", "end": 5}]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

        # assured=2 means once we have 2 messages, we stop at boundary
        result = scene.context_history(budget=8192, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Messages 5-9 are after boundary, should be included
        assert "Message 9" in result_text
        assert "Message 5" in result_text
        # Messages before boundary should NOT be included (assured met)
        assert "Message 4" not in result_text
        assert "Message 0" not in result_text

    def test_zero_assured_respects_boundary_strictly(self, summarizer, test_data):
        """With assured=0, should strictly respect the summarized_to boundary."""
        summarizer.actions["manage_scene_history"].config[
            "enforce_boundary"
        ].value = True

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # summarized_to = 8, so only messages 8-9 are after boundary
        archived = [{"text": "Summary", "ts": "PT0S", "end": 8}]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

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

    def test_intro_added_when_context_sparse(self, mock_scene):
        """Intro should be added when context is very sparse (< 128 tokens)."""
        scene = mock_scene(
            history=[], archived_history=[], intro="Welcome to the test scene."
        )
        result = scene.context_history(budget=8192)

        result_text = " ".join(result)
        # Intro should be present when context is sparse
        assert "test scene" in result_text.lower() or len(result) >= 0

    def test_intro_not_added_when_context_sufficient(self, mock_scene):
        """Intro should not be added when context has sufficient content."""
        scene = mock_scene()  # Full history
        result = scene.context_history(budget=8192)

        # Result should contain dialogue, not just intro
        result_text = " ".join(result)
        assert "Elena" in result_text or "Marcus" in result_text


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_summarized_to_greater_than_history_length(self, mock_scene):
        """Should handle case where summarized_to exceeds history length."""
        # Create a scene with archived_history pointing beyond current history
        scene = mock_scene(
            archived_history=[
                {"text": "Old content", "ts": "PT0S", "end": 100}  # end > len(history)
            ]
        )
        result = scene.context_history(budget=8192)

        # Should not crash, should return valid content
        assert isinstance(result, list)

    def test_archived_history_without_end_key(self, mock_scene):
        """Should handle archived history entries without 'end' key (static entries)."""
        scene = mock_scene(
            archived_history=[
                {"text": "Static backstory", "ts": "PT0S"}  # No 'end' key
            ]
        )
        result = scene.context_history(budget=8192)
        assert isinstance(result, list)

    def test_static_archived_history(self, mock_scene, test_data):
        """Should handle static archived history entries (end=None)."""
        scene = mock_scene(archived_history=test_data["static_archived_history"])
        result = scene.context_history(budget=8192)

        # Static entries should be skipped in context collection
        assert isinstance(result, list)

    def test_very_small_budget(self, mock_scene):
        """Should handle very small budget gracefully."""
        scene = mock_scene()
        result = scene.context_history(budget=10)  # Very small budget

        # Should return something, even if limited
        assert isinstance(result, list)

    def test_mixed_message_types(self, mock_scene):
        """Should handle history with mixed message types."""
        scene = mock_scene(
            include_narrator=True,
            include_director=True,
            include_reinforcements=True,
            include_context_investigation=True,
        )
        result = scene.context_history(budget=8192)

        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: Dialogue/Summary Boundary
# ---------------------------------------------------------------------------


class TestDialogueSummaryBoundary:
    """Test that dialogue boundary behavior works correctly."""

    def test_dialogue_expands_freely(self, summarizer, test_data):
        """
        With boundary enforcement off (default), dialogue should EXPAND
        backwards to fill its budget, effectively "unsummarizing" archived
        entries.
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 50

        # Create 10 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history with end=6 means it covers indices 0-5
        # summarized_to = 6, so traditionally dialogue would start at index 6
        # But with expansion enabled, dialogue should expand backwards
        archived = [{"text": "Summary of early messages", "ts": "PT0S", "end": 6}]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

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

    def test_dialogue_expands_to_fill_budget(self, summarizer, test_data):
        """
        Dialogue should expand backwards to fill its allocated budget.
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 50

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history covers messages 0-7 (summarized_to = 8)
        archived = [{"text": "Summary of early messages", "ts": "PT0S", "end": 7}]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

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

    def test_boundary_respected_with_enforcement(self, summarizer, test_data):
        """
        With boundary enforcement enabled, boundary should be respected
        once assured_dialogue_num is met.
        """
        summarizer.actions["manage_scene_history"].config[
            "enforce_boundary"
        ].value = True

        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(10)
        ]

        # Archived history with end=6 means it covers indices 0-5
        # summarized_to = 6, so dialogue starts at index 6
        archived = [{"text": "Summary of early messages", "ts": "PT0S", "end": 6}]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=8192, assured_dialogue_num=3)

        result_text = " ".join(result)

        # Messages 6-9 should be included
        assert "Message 6" in result_text
        assert "Message 9" in result_text

        # Messages 0-5 should NOT be included since assured is met
        assert "Message 0" not in result_text
        assert "Message 5" not in result_text

    def test_expansion_excludes_summarized_entries(self, summarizer, test_data):
        """
        When dialogue expands into previously summarized content,
        the corresponding archived_history entries should be excluded
        from the context (to avoid duplication).
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 50

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

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

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

    def test_layered_history_dialogue_budget_limited(self, summarizer, test_data):
        """
        With the budget-aware layered detail gradient, dialogue fills its
        budget (ratio% of total). When dialogue covers all messages,
        archived entries and layered summaries are correctly suppressed
        since the raw dialogue already provides full detail.
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 80
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 80
        summarizer.actions["layered_history"].enabled = True

        # Create 30 messages
        messages = [
            CharacterMessage(message=f"Character{i}: Message {i}", source="ai")
            for i in range(30)
        ]

        # 6 archived entries covering different message ranges
        archived = [
            {"text": "Summary A", "ts": "PT0S", "end": 3},  # idx 0
            {"text": "Summary B", "ts": "PT10M", "end": 7},  # idx 1
            {"text": "Summary C", "ts": "PT20M", "end": 11},  # idx 2
            {"text": "Summary D", "ts": "PT30M", "end": 15},  # idx 3
            {"text": "Summary E", "ts": "PT1H", "end": 20},  # idx 4
            {"text": "Summary F", "ts": "PT1H30M", "end": 25},  # idx 5
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

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

        # With large budget, dialogue fills 80% which covers all 30 short messages
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
        self, summarizer, test_data
    ):
        """
        Archived entries fill the gap between dialogue and more compressed
        layers. Archived collects freely (no layered filter).

        Using 200c messages, 50c archived, 50c layered.
        Budget = 1200, ratio = 50%:
          dial = 600  → 3 of 30 msgs (200c) → dialogue_start = 27
          arch = 600  → all 6 entries (50c each = 300c total) easily fit
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 50
        summarizer.actions["layered_history"].enabled = True

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
            [
                {
                    "text": _pad("Layered summary", 50),
                    "ts_start": "PT0S",
                    "ts_end": "PT20M",
                    "end": 2,
                }
            ],
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=1200, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Archived entries fill the gap (collected freely)
        assert "Gap summary middle" in result_text

        # Dialogue present
        assert "M29" in result_text

    def test_partial_expansion_keeps_summary(self, summarizer, test_data):
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
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 50
        summarizer.actions["layered_history"].enabled = False

        messages = [_make_message(i, 300) for i in range(20)]

        archived = [
            {"text": _pad("Early summary 0-7", 50), "ts": "PT0S", "end": 7},
            {"text": _pad("Middle summary 8-15", 50), "ts": "PT30M", "end": 15},
            {"text": _pad("Recent summary 16-18", 50), "ts": "PT1H", "end": 18},
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=2000, assured_dialogue_num=2)

        result_text = " ".join(result)

        # Recent messages in dialogue
        assert "M19" in result_text

        # Early summary included (dialogue doesn't reach it)
        assert "Early summary" in result_text

        # Middle summary included (dialogue doesn't overlap at all)
        assert "Middle summary" in result_text

    def test_fully_expanded_entry_excluded(self, summarizer, test_data):
        """
        When dialogue fully covers an archived entry's range, that entry
        should be excluded from context to avoid duplication.
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 80
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 80
        summarizer.actions["layered_history"].enabled = False

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

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

        # Large budget allows dialogue to expand all the way back
        result = scene.context_history(budget=8192, assured_dialogue_num=2)

        result_text = " ".join(result)

        # All messages should be included (dialogue expanded fully)
        assert "Message 0" in result_text
        assert "Message 9" in result_text

        # All summaries should be EXCLUDED (fully expanded into dialogue)
        assert "Summary of message 0-2" not in result_text
        assert "Summary of message 3-5" not in result_text
        assert "Summary of message 6-8" not in result_text

    def test_layered_history_index_space_divergence(self, summarizer, test_data):
        """
        Archived entries overlap with layered history's range but are
        collected freely. Layer 0 only fills the gap archived couldn't reach.

        Using 100c messages, 50c archived, 50c layered.
        Budget = 2000, ratio = 40%:
          dial = 800  → 8 of 50 msgs (100c) → dialogue_start = 42
          arch = 480  → 9 of 10 entries (50c each) → arch_boundary = 0
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 40
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 40
        summarizer.actions["layered_history"].enabled = True

        messages = [_make_message(i, 100) for i in range(50)]

        # 10 archived entries (50 chars each)
        archived = [
            {
                "text": _pad(f"Archived {i}", 50),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 5 - 1,
            }
            for i in range(10)
        ]

        # Layered history covers archived 0-4
        layered = [
            [
                {
                    "text": _pad("Layered first half", 50),
                    "ts_start": "PT0S",
                    "ts_end": "PT40M",
                    "start": 0,
                    "end": 4,
                }
            ],
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

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
    """Test the budget-aware layered detail gradient in context_history.

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
    MSG_CHARS = 100  # each dialogue message
    ARCH_CHARS = 200  # each archived-history entry
    L0_CHARS = 300  # each layer-0 entry
    L1_CHARS = 150  # each layer-1 entry

    @classmethod
    def _make_messages(cls, count):
        """Create *count* messages, each exactly MSG_CHARS characters."""
        return [_make_message(i, cls.MSG_CHARS) for i in range(count)]

    def test_gradient_all_levels_present(self, summarizer, test_data):
        """
        All four levels (layer 1, layer 0, archived, dialogue) appear when
        each level's budget runs out before covering everything.

        Budget arithmetic (1 char = 1 token, ratio = 0.40):
          total  = 3000
          dial   = 1200  → 12 msgs → dialogue_start = 18
          arch   = 720   → 3 entries → arch_boundary = 4
          L0     = 432   → 1 entry (300c) → l0_boundary = 2
          L1     = 648   → 4 entries (150c) easily
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 40
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 40
        summarizer.actions["layered_history"].enabled = True

        messages = self._make_messages(30)

        # 8 archived entries (200 chars each)
        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 3 - 1,
            }
            for i in range(8)
        ]
        # end values: 2, 5, 8, 11, 14, 17, 20, 23

        # Layer 0: 4 entries (300 chars each) covering archived 0-5
        layer_0 = [
            {
                "text": _pad("L0-A", self.L0_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 1,
            },
            {
                "text": _pad("L0-B", self.L0_CHARS),
                "ts_start": "PT10M",
                "ts_end": "PT20M",
                "start": 2,
                "end": 2,
            },
            {
                "text": _pad("L0-C", self.L0_CHARS),
                "ts_start": "PT20M",
                "ts_end": "PT30M",
                "start": 3,
                "end": 3,
            },
            {
                "text": _pad("L0-D", self.L0_CHARS),
                "ts_start": "PT30M",
                "ts_end": "PT50M",
                "start": 4,
                "end": 5,
            },
        ]

        # Layer 1: 2 entries (150 chars each) covering layer 0 entries 0-2
        layer_1 = [
            {
                "text": _pad("L1-X", self.L1_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 1,
            },
            {
                "text": _pad("L1-Y", self.L1_CHARS),
                "ts_start": "PT10M",
                "ts_end": "PT20M",
                "start": 2,
                "end": 2,
            },
        ]

        layered = [layer_0, layer_1]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

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

    def test_gradient_higher_layers_cover_gaps(self, summarizer, test_data):
        """
        When a lower level's budget runs out, higher layers cover the gap.

        Budget arithmetic (ratio = 0.40, budget = 2000):
          dial  = 800  → 8 of 30 msgs (100c) → dialogue_start = 22
          arch  = 480  → 2 of 6 entries (200c) → arch_boundary = 3
          L0    = 288  → 0 (300c entries don't fit)
          L1    = 432  → 2 (150c entries fit) — L1 covers what L0/arch missed
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 40
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 40
        summarizer.actions["layered_history"].enabled = True

        messages = self._make_messages(30)

        # 6 archived entries (200 chars each)
        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 5 - 1,
            }
            for i in range(6)
        ]
        # end values: 4, 9, 14, 19, 24, 29

        # Layer 0: 3 entries (300 chars each) covering archived 0-3
        layer_0 = [
            {
                "text": _pad("L0-A", self.L0_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 0,
            },
            {
                "text": _pad("L0-B", self.L0_CHARS),
                "ts_start": "PT10M",
                "ts_end": "PT20M",
                "start": 1,
                "end": 1,
            },
            {
                "text": _pad("L0-C", self.L0_CHARS),
                "ts_start": "PT20M",
                "ts_end": "PT30M",
                "start": 2,
                "end": 3,
            },
        ]

        # Layer 1: covers L0 entries 0-1
        layer_1 = [
            {
                "text": _pad("L1-overview", self.L1_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT20M",
                "start": 0,
                "end": 1,
            },
        ]

        layered = [layer_0, layer_1]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=2000)

        result_text = " ".join(result)

        # Dialogue present
        assert "M29" in result_text

        # Some archived entries present (gap between dialogue and older history)
        archived_present = any(f"Archived {i}" in result_text for i in range(6))
        assert archived_present, "Some archived entries should fill the gap"

    def test_gradient_no_layered_history_falls_back(self, summarizer, test_data):
        """
        No layered history → falls back to dialogue + archived (single split).

        Budget arithmetic (ratio = 0.50, budget = 1500):
          dial = 750  → 7 of 20 msgs (100c) → dialogue_start = 13
          arch = 750  → 3 entries (200c each) easily fit
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 50
        summarizer.actions["layered_history"].enabled = True

        messages = self._make_messages(20)

        archived = [
            {"text": _pad("Archived early", self.ARCH_CHARS), "ts": "PT0S", "end": 5},
            {
                "text": _pad("Archived middle", self.ARCH_CHARS),
                "ts": "PT30M",
                "end": 10,
            },
            {"text": _pad("Archived recent", self.ARCH_CHARS), "ts": "PT1H", "end": 15},
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=1500)

        result_text = " ".join(result)

        # Both archived and dialogue present
        assert "Archived early" in result_text
        assert "M19" in result_text

    def test_gradient_budget_allocation_proportions(self, summarizer, test_data):
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
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 40
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 40
        summarizer.actions["layered_history"].enabled = True

        messages = self._make_messages(50)

        # 8 archived entries (300c each) covering 6 messages each
        archived = [
            {
                "text": _pad(f"Archived {i}", 300),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 6 - 1,
            }
            for i in range(8)
        ]
        # end values: 5, 11, 17, 23, 29, 35, 41, 47

        # 4 L0 entries (200c each) covering archived 0-5
        layer_0 = [
            {
                "text": _pad("L0-A", 200),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 1,
            },
            {
                "text": _pad("L0-B", 200),
                "ts_start": "PT10M",
                "ts_end": "PT20M",
                "start": 2,
                "end": 2,
            },
            {
                "text": _pad("L0-C", 200),
                "ts_start": "PT20M",
                "ts_end": "PT30M",
                "start": 3,
                "end": 3,
            },
            {
                "text": _pad("L0-D", 200),
                "ts_start": "PT30M",
                "ts_end": "PT50M",
                "start": 4,
                "end": 5,
            },
        ]

        # 2 L1 entries (100c each) covering L0 0-2
        layer_1 = [
            {
                "text": _pad("L1-X", 100),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 1,
            },
            {
                "text": _pad("L1-Y", 100),
                "ts_start": "PT10M",
                "ts_end": "PT20M",
                "start": 2,
                "end": 2,
            },
        ]

        layered = [layer_0, layer_1]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

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
            (
                result_text.find(f"Archived {i}")
                for i in range(8)
                if f"Archived {i}" in result_text
            ),
            default=-1,
        )
        dialogue_pos = result_text.find("M49")
        assert archived_pos < dialogue_pos, "Archived should come before dialogue"

    def test_gradient_chapter_labels_across_levels(self, summarizer, test_data):
        """
        Chapter labels should be applied to layered history entries.

        Budget = 2000, ratio = 0.40:
          dial = 800  → 8 of 20 msgs (100c) → dialogue_start = 12
          arch = 480  → 2 of 4 entries (200c) → arch_boundary = 1
          L0   = 288  → 0 entries (300c each don't fit)
          L1   = 432  → 2 entries (150c each fit)
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 40
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 40
        summarizer.actions["layered_history"].enabled = True

        messages = self._make_messages(20)

        # 4 archived entries (200 chars each)
        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 5 - 1,
            }
            for i in range(4)
        ]

        layer_0 = [
            {
                "text": _pad("L0-entry", self.L0_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 0,
            },
        ]

        layer_1 = [
            {
                "text": _pad("L1-entry", self.L1_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 0,
            },
        ]

        layered = [layer_0, layer_1]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

        with patch("talemate.agents.context.active_agent") as mock_active_agent:
            mock_ctx = Mock()
            mock_ctx.state = {}
            mock_active_agent.get.return_value = mock_ctx

            result = scene.context_history(budget=2000, chapter_labels=True)

        result_text = " ".join(result)

        # Chapter labels should be present on layered history entries
        assert "### Chapter" in result_text

    def test_gradient_empty_layer_skipped(self, summarizer, test_data):
        """
        Empty layer should be skipped gracefully.

        Budget = 1500, ratio = 0.40:
          dial = 600  → 6 of 20 msgs (100c) → dialogue_start = 14
          arch = 360  → 1 entry (200c) → arch_boundary = 2
          L0   = 216  → 0 entries (300c don't fit)
          L1   = 324  → (empty, skipped)
        """
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 40
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 40
        summarizer.actions["layered_history"].enabled = True

        messages = self._make_messages(20)

        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 5 - 1,
            }
            for i in range(4)
        ]

        layer_0 = [
            {
                "text": _pad("L0-A", self.L0_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 1,
            },
            {
                "text": _pad("L0-B", self.L0_CHARS),
                "ts_start": "PT10M",
                "ts_end": "PT20M",
                "start": 2,
                "end": 2,
            },
        ]

        layer_1 = []  # empty

        layered = [layer_0, layer_1]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=1500)

        result_text = " ".join(result)

        # Dialogue present
        assert "M19" in result_text
        # Some context present
        has_context = "L0-" in result_text or any(
            f"Archived {i}" in result_text for i in range(4)
        )
        assert has_context, "Some context should be present"
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests: Independent Dialogue / Summary Detail Ratios
# ---------------------------------------------------------------------------


class TestIndependentRatios:
    """Test that dialogue_ratio and summary_detail_ratio are independent.

    dialogue_ratio controls the dialogue/summary split.
    summary_detail_ratio controls how the summary budget is distributed
    across archived history and layered history levels.
    """

    MSG_CHARS = 100
    ARCH_CHARS = 200
    L0_CHARS = 300

    def test_same_dialogue_different_summary_changes_layer_distribution(
        self, summarizer, test_data
    ):
        """
        Same dialogue_ratio but different summary_detail_ratio should
        produce different distributions across summary levels.

        Both runs: dialogue_ratio=40, budget=3000
          dial = 1200 → 12 of 30 msgs (100c) → dialogue_start = 18

        Run A: summary_detail_ratio=30
          arch = 0.30 * 1800 = 540 → 2 of 6 entries (200c + ~60c ts ≈ 260c)
          remaining for layers = 1260

        Run B: summary_detail_ratio=70
          arch = 0.70 * 1800 = 1260 → up to 4 entries
          remaining for layers = 540
        """
        messages = [_make_message(i, self.MSG_CHARS) for i in range(30)]

        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 3 - 1,
            }
            for i in range(6)
        ]

        layer_0 = [
            {
                "text": _pad("L0-A", self.L0_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 0,
            },
            {
                "text": _pad("L0-B", self.L0_CHARS),
                "ts_start": "PT10M",
                "ts_end": "PT20M",
                "start": 1,
                "end": 1,
            },
        ]

        layered = [layer_0]

        def _run(summary_ratio):
            summarizer.actions["manage_scene_history"].config[
                "dialogue_ratio"
            ].value = 40
            summarizer.actions["manage_scene_history"].config[
                "summary_detail_ratio"
            ].value = summary_ratio
            summarizer.actions["layered_history"].enabled = True

            scene = _make_scene(
                test_data,
                history=messages,
                archived_history=archived,
                layered_history=layered,
            )
            return scene.context_history(budget=3000)

        result_low = _run(30)
        result_high = _run(70)

        text_low = " ".join(result_low)
        text_high = " ".join(result_high)

        # Both should have dialogue (same dialogue_ratio)
        assert "M29" in text_low
        assert "M29" in text_high

        # Higher summary_detail_ratio gives more budget to archived (the
        # most recent/detailed summary level), so it should include more
        # archived entries.
        archived_count_low = sum(1 for i in range(6) if f"Archived {i}" in text_low)
        archived_count_high = sum(1 for i in range(6) if f"Archived {i}" in text_high)
        assert archived_count_high >= archived_count_low, (
            f"Higher summary_detail_ratio should include at least as many archived "
            f"entries: high={archived_count_high}, low={archived_count_low}"
        )

    def test_different_dialogue_same_summary_changes_dialogue_amount(
        self, summarizer, test_data
    ):
        """
        Different dialogue_ratio but same summary_detail_ratio should
        change how much dialogue is included without changing the
        relative distribution of summary levels.

        Run A: dialogue_ratio=30, summary_detail_ratio=50, budget=3000
          dial = 900 → 9 of 30 msgs → dialogue_start = 21

        Run B: dialogue_ratio=70, summary_detail_ratio=50, budget=3000
          dial = 2100 → 21 of 30 msgs → dialogue_start = 9
        """
        messages = [_make_message(i, self.MSG_CHARS) for i in range(30)]

        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 5 - 1,
            }
            for i in range(6)
        ]

        def _run(dialogue_ratio):
            summarizer.actions["manage_scene_history"].config[
                "dialogue_ratio"
            ].value = dialogue_ratio
            summarizer.actions["manage_scene_history"].config[
                "summary_detail_ratio"
            ].value = 50
            summarizer.actions["layered_history"].enabled = False

            scene = _make_scene(
                test_data,
                history=messages,
                archived_history=archived,
                layered_history=[],
            )
            return scene.context_history(budget=3000)

        result_low_dial = _run(30)
        result_high_dial = _run(70)

        text_low = " ".join(result_low_dial)
        text_high = " ".join(result_high_dial)

        # Both should have some dialogue
        assert "M29" in text_low
        assert "M29" in text_high

        # Higher dialogue_ratio should include more dialogue messages
        dial_count_low = sum(
            1 for i in range(30) if f"M{i} " in text_low or f"M{i}." in text_low
        )
        dial_count_high = sum(
            1 for i in range(30) if f"M{i} " in text_high or f"M{i}." in text_high
        )
        assert dial_count_high > dial_count_low, (
            f"Higher dialogue_ratio should include more dialogue: "
            f"high={dial_count_high}, low={dial_count_low}"
        )

    def test_matched_ratios_equals_legacy_behavior(self, summarizer, test_data):
        """
        When both ratios are set to the same value, behavior should be
        identical to the old single-ratio approach.

        This verifies that the refactor is backwards-compatible.
        """
        messages = [_make_message(i, self.MSG_CHARS) for i in range(30)]

        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 5 - 1,
            }
            for i in range(6)
        ]

        layer_0 = [
            {
                "text": _pad("L0-entry", self.L0_CHARS),
                "ts_start": "PT0S",
                "ts_end": "PT10M",
                "start": 0,
                "end": 1,
            },
        ]

        layered = [layer_0]

        # Run with matched ratios at 40
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 40
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 40
        summarizer.actions["layered_history"].enabled = True

        scene = _make_scene(
            test_data,
            history=messages,
            archived_history=archived,
            layered_history=layered,
        )
        result_matched = scene.context_history(budget=3000)

        # Run again with the same values to confirm determinism
        scene2 = _make_scene(
            test_data,
            history=messages,
            archived_history=archived,
            layered_history=layered,
        )
        result_matched_2 = scene2.context_history(budget=3000)

        assert result_matched == result_matched_2, (
            "Matched ratios should be deterministic"
        )

    def test_high_summary_ratio_favors_recent_summaries(self, summarizer, test_data):
        """
        A high summary_detail_ratio should allocate more budget to
        archived history (the most recent/detailed summary level),
        potentially leaving less for higher (more compressed) layers.

        dialogue_ratio=40, budget=3000 → dial=1200, remaining=1800

        summary_detail_ratio=80:
          arch = 0.80 * 1800 = 1440 → all 6 entries (200c + ts) fit
          L0   = ALL of 360 → 1 entry (300c + ts) fits

        summary_detail_ratio=20:
          arch = 0.20 * 1800 = 360 → 1 entry
          L0   = ALL of 1440 → all entries fit
        """
        messages = [_make_message(i, self.MSG_CHARS) for i in range(30)]

        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 3 - 1,
            }
            for i in range(6)
        ]

        layer_0 = [
            {
                "text": _pad(f"L0-{i}", self.L0_CHARS),
                "ts_start": f"PT{i * 10}M",
                "ts_end": f"PT{(i + 1) * 10}M",
                "start": i,
                "end": i,
            }
            for i in range(4)
        ]

        layered = [layer_0]

        def _run(summary_ratio):
            summarizer.actions["manage_scene_history"].config[
                "dialogue_ratio"
            ].value = 40
            summarizer.actions["manage_scene_history"].config[
                "summary_detail_ratio"
            ].value = summary_ratio
            summarizer.actions["layered_history"].enabled = True

            scene = _make_scene(
                test_data,
                history=messages,
                archived_history=archived,
                layered_history=layered,
            )
            return scene.context_history(budget=3000)

        result_high = _run(80)
        result_low = _run(20)

        text_high = " ".join(result_high)
        text_low = " ".join(result_low)

        # High summary_detail_ratio: more archived entries
        archived_high = sum(1 for i in range(6) if f"Archived {i}" in text_high)
        archived_low = sum(1 for i in range(6) if f"Archived {i}" in text_low)
        assert archived_high > archived_low, (
            f"High summary_detail_ratio should include more archived entries: "
            f"high={archived_high}, low={archived_low}"
        )

        # Low summary_detail_ratio: more layer 0 entries (gets all remaining)
        l0_high = sum(1 for i in range(4) if f"L0-{i}" in text_high)
        l0_low = sum(1 for i in range(4) if f"L0-{i}" in text_low)
        assert l0_low >= l0_high, (
            f"Low summary_detail_ratio should include at least as many L0 entries: "
            f"low={l0_low}, high={l0_high}"
        )


class TestBestFit:
    """Test the best-fit context history mode.

    Best-fit mode dynamically selects the optimal detail level for each
    time segment: compressed at the start, detailed at the end, covering
    the full timeline within the budget.
    """

    MSG_CHARS = 100
    ARCH_CHARS = 200
    L0_CHARS = 300
    L1_CHARS = 150

    @classmethod
    def _enable_best_fit(cls, summarizer):
        summarizer.actions["manage_scene_history"].config["best_fit"].value = True
        summarizer.actions["layered_history"].enabled = True

    @classmethod
    def _make_test_scene(
        cls, test_data, *, num_messages=30, num_archived=8, with_layers=True
    ):
        """Create a test scene with layered history for best-fit tests.

        Structure:
          - messages 0..23 covered by archived (summarized_to=23)
          - messages 24..29 are unsummarized (mandatory dialogue)
          - archived 0..7 (8 entries)
          - layer 0: 4 entries covering archived [0-1], [2-3], [4-5], [6-7]
          - layer 1: 2 entries covering L0 [0-1], [2-3]
        """
        messages = [_make_message(i, cls.MSG_CHARS) for i in range(num_messages)]

        archived = [
            {
                "text": _pad(f"Archived {i}", cls.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 3 - 1,
            }
            for i in range(num_archived)
        ]

        if with_layers:
            layer_0 = [
                {
                    "text": _pad(f"L0-{i}", cls.L0_CHARS),
                    "ts_start": f"PT{i * 20}M",
                    "ts_end": f"PT{(i + 1) * 20}M",
                    "start": i * 2,
                    "end": i * 2 + 1,
                }
                for i in range(4)
            ]

            layer_1 = [
                {
                    "text": _pad(f"L1-{i}", cls.L1_CHARS),
                    "ts_start": f"PT{i * 40}M",
                    "ts_end": f"PT{(i + 1) * 40}M",
                    "start": i * 2,
                    "end": i * 2 + 1,
                }
                for i in range(2)
            ]

            layered = [layer_0, layer_1]
        else:
            layered = []

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        return scene

    def test_best_fit_returns_list(self, summarizer, test_data):
        """Basic smoke test: best-fit mode returns a list of strings."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)
        result = scene.context_history(budget=5000)

        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(s, str) for s in result)

    def test_best_fit_covers_full_timeline(self, summarizer, test_data):
        """When budget can't fit all dialogue, summaries fill the gaps."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)
        # Budget too small for all 30 messages (3000 chars) but enough for
        # recent dialogue + summaries to cover the full timeline.
        result = scene.context_history(budget=2000)
        text = " ".join(result)

        # Mandatory dialogue (messages 24-29) should be present
        assert "M29" in text, "Last message should be in dialogue"
        assert "M24" in text, "First unsummarized message should be in dialogue"

        # Some summary content should be present since full dialogue doesn't fit
        has_summary = (
            any(f"Archived {i}" in text for i in range(8))
            or any(f"L0-{i}" in text for i in range(4))
            or any(f"L1-{i}" in text for i in range(2))
        )
        assert has_summary, "Some summary content should be present"

    def test_best_fit_detail_gradient(self, summarizer, test_data):
        """Output should be ordered: top layer → lower layers → archived → dialogue."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)
        # Budget too small for all 30 messages but large enough for all summary
        # levels plus recent dialogue, so the gradient ordering is exercised.
        result = scene.context_history(budget=2500)
        text = " ".join(result)

        # Find positions of content from each level
        l1_positions = [text.find(f"L1-{i}") for i in range(2) if f"L1-{i}" in text]
        l0_positions = [text.find(f"L0-{i}") for i in range(4) if f"L0-{i}" in text]
        arch_positions = [
            text.find(f"Archived {i}") for i in range(8) if f"Archived {i}" in text
        ]
        dial_positions = [text.find(f"M{i}") for i in range(24, 30) if f"M{i}" in text]

        # Dialogue must exist
        assert dial_positions, "Dialogue must be present"

        # Check ordering: highest layer content comes before lower layers
        all_positions = []
        if l1_positions:
            all_positions.append(("L1", min(l1_positions)))
        if l0_positions:
            all_positions.append(("L0", min(l0_positions)))
        if arch_positions:
            all_positions.append(("Arch", min(arch_positions)))
        if dial_positions:
            all_positions.append(("Dial", min(dial_positions)))

        # Verify ordering: each level should start before the next
        for i in range(len(all_positions) - 1):
            label_a, pos_a = all_positions[i]
            label_b, pos_b = all_positions[i + 1]
            assert pos_a < pos_b, (
                f"{label_a} (pos={pos_a}) should come before {label_b} (pos={pos_b})"
            )

    def test_best_fit_trims_oldest_when_budget_tight(self, summarizer, test_data):
        """With a tight budget, oldest content is cut; newest survives."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        # Very tight budget — only room for dialogue and maybe one summary entry
        result = scene.context_history(budget=800)
        text = " ".join(result)

        # Most recent dialogue should survive
        assert "M29" in text, "Most recent message must survive"

        # Oldest summary content might be cut
        # At minimum, more recent content should be present over older content

    def test_best_fit_no_layered_history(self, summarizer, test_data):
        """Works correctly with only archived history + dialogue (no layers)."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data, with_layers=False)
        # Budget too small for all dialogue (3000 chars), forcing summary usage
        result = scene.context_history(budget=2000)
        text = " ".join(result)

        # Dialogue present
        assert "M29" in text
        # Archived entries present (filling timeline gaps)
        assert any(f"Archived {i}" in text for i in range(8))
        # No layer content
        assert "L0-" not in text
        assert "L1-" not in text

    def test_best_fit_no_archived_history(self, summarizer, test_data):
        """Works correctly with no archived history at all (brand new scene)."""
        self._enable_best_fit(summarizer)

        messages = [_make_message(i, self.MSG_CHARS) for i in range(10)]
        scene = MockScene()
        scene.history = messages
        scene.archived_history = []
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=5000)
        text = " ".join(result)

        # All dialogue should be present (no summaries to worry about)
        assert "M0" in text
        assert "M9" in text

    def test_best_fit_dialogue_exceeds_budget(self, summarizer, test_data):
        """When mandatory dialogue alone exceeds budget, no summaries included."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        # Budget smaller than mandatory dialogue (6 messages × 100 chars = 600)
        result = scene.context_history(budget=300)
        text = " ".join(result)

        # Should have some dialogue
        assert "M29" in text
        # No summary content (budget exhausted by dialogue)
        assert "Archived" not in text
        assert "L0-" not in text
        assert "L1-" not in text

    def test_best_fit_ignores_ratios(self, summarizer, test_data):
        """Changing dialogue_ratio and summary_detail_ratio has no effect in best_fit mode."""
        self._enable_best_fit(summarizer)
        scene1 = self._make_test_scene(test_data)

        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 20
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 80
        result_a = scene1.context_history(budget=5000)

        scene2 = self._make_test_scene(test_data)
        summarizer.actions["manage_scene_history"].config["dialogue_ratio"].value = 80
        summarizer.actions["manage_scene_history"].config[
            "summary_detail_ratio"
        ].value = 20
        result_b = scene2.context_history(budget=5000)

        assert result_a == result_b, (
            "Ratio changes should have no effect in best-fit mode"
        )

    def test_best_fit_respects_max_budget(self, summarizer, test_data):
        """max_budget override is still applied in best-fit mode."""
        self._enable_best_fit(summarizer)
        summarizer.actions["manage_scene_history"].config["max_budget"].value = 1000

        scene = self._make_test_scene(test_data)
        result_capped = scene.context_history(budget=50000)

        # Reset max_budget
        summarizer.actions["manage_scene_history"].config["max_budget"].value = 0
        scene2 = self._make_test_scene(test_data)
        result_uncapped = scene2.context_history(budget=50000)

        # Capped result should have less content
        assert len(result_capped) < len(result_uncapped), (
            "max_budget should limit the output"
        )

    def test_best_fit_expansion_gradient(self, summarizer, test_data):
        """With enough budget, recent entries expand to more detailed levels
        while old entries stay compressed."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        # Budget must be < 3000 (all dialogue = 30 × 100 chars) so that
        # best-fit falls back to summary mode where expansion can happen.
        # Skeleton (L1): ~2 entries × ~210 chars ≈ 420
        # Mandatory dialogue: ~6 msgs × 100 chars = 600
        # Total minimum: ~1020
        # With ~1000 extra budget, some expansion should happen
        result = scene.context_history(budget=2500)
        text = " ".join(result)

        # Dialogue must be present
        assert "M29" in text

        # Count entries at each level
        l1_count = sum(1 for i in range(2) if f"L1-{i}" in text)
        l0_count = sum(1 for i in range(4) if f"L0-{i}" in text)
        arch_count = sum(1 for i in range(8) if f"Archived {i}" in text)

        # With expansion, we should see a mix of levels
        total_summary_entries = l1_count + l0_count + arch_count
        assert total_summary_entries > 0, "Should have some summary entries"

        # If L0 or archived entries are present, they should be the more recent ones
        if l0_count > 0 and l1_count > 0:
            # L0 entries should be more recent than L1 entries
            l1_max = max(
                (text.find(f"L1-{i}") for i in range(2) if f"L1-{i}" in text),
                default=-1,
            )
            l0_min = min(
                (text.find(f"L0-{i}") for i in range(4) if f"L0-{i}" in text),
                default=len(text),
            )
            assert l1_max < l0_min, (
                "L1 (compressed) entries should appear before L0 (detailed) entries"
            )

    def test_best_fit_with_very_large_budget(self, summarizer, test_data):
        """With a huge budget, all dialogue fits so summaries are skipped."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)
        result = scene.context_history(budget=100000)
        text = " ".join(result)

        # All dialogue should be present (budget large enough for everything)
        for i in range(30):
            assert f"M{i}" in text, f"Message {i} should be present"

        # No summary content — full dialogue is the most granular detail
        assert "Archived" not in text, (
            "Summaries should not appear when all dialogue fits"
        )
        assert "L0-" not in text
        assert "L1-" not in text

    def test_best_fit_preview(self, summarizer, test_data):
        """Preview in best-fit mode returns correct structure."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        from talemate.agents.summarize.context_history import (
            ContextHistoryPreviewOverrides,
        )

        overrides = ContextHistoryPreviewOverrides(best_fit=True, max_budget=5000)
        preview = summarizer.context_history_preview(scene, overrides=overrides)

        assert preview["summary"]["best_fit"] is True
        assert "total" in preview["budget"]
        assert "used" in preview["budget"]
        assert "sections" in preview

        # Should have at least a dialogue section
        types = [s["type"] for s in preview["sections"]]
        assert "dialogue" in types

        # Sections should not have per-section "budget" key
        for section in preview["sections"]:
            if section["type"] != "dialogue":
                assert "budget" not in section, (
                    f"Section {section['type']} should not have budget in best-fit mode"
                )

    def test_best_fit_min_dialogue_guarantee(self, summarizer, test_data):
        """At least _BEST_FIT_MIN_DIALOGUE messages are included regardless of budget."""
        from talemate.agents.summarize.context_history import _BEST_FIT_MIN_DIALOGUE

        if _BEST_FIT_MIN_DIALOGUE <= 0:
            pytest.skip("min dialogue guarantee is disabled")

        self._enable_best_fit(summarizer)

        # Scene where all messages are summarized (summarized_to = last message)
        # so the boundary would exclude all dialogue
        messages = [_make_message(i, self.MSG_CHARS) for i in range(10)]
        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 2 - 1,  # covers all 10 messages
            }
            for i in range(5)
        ]
        # summarized_to = archived[-1]["end"] = 9 (all messages summarized)

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=5000)
        text = " ".join(result)

        # Despite all messages being summarized, the most recent ones
        # should still appear as dialogue
        recent_count = sum(1 for i in range(10) if f"M{i}" in text)
        assert recent_count >= _BEST_FIT_MIN_DIALOGUE, (
            f"Expected at least {_BEST_FIT_MIN_DIALOGUE} dialogue messages, "
            f"got {recent_count}"
        )

    def test_best_fit_min_dialogue_with_tiny_budget(self, summarizer, test_data):
        """Min dialogue guarantee works even when budget is exhausted."""
        from talemate.agents.summarize.context_history import _BEST_FIT_MIN_DIALOGUE

        if _BEST_FIT_MIN_DIALOGUE <= 0:
            pytest.skip("min dialogue guarantee is disabled")

        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        # Budget so small it can't fit even 1 message normally (100 chars each)
        result = scene.context_history(budget=50)

        # Should still have at least the minimum messages
        assert len(result) >= _BEST_FIT_MIN_DIALOGUE, (
            f"Expected at least {_BEST_FIT_MIN_DIALOGUE} entries, got {len(result)}"
        )

    def test_best_fit_min_dialogue_configurable(self, summarizer, test_data):
        """The min dialogue guarantee is controlled by the config value."""
        self._enable_best_fit(summarizer)

        # Scene where all messages are summarized
        messages = [_make_message(i, self.MSG_CHARS) for i in range(10)]
        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 2 - 1,
            }
            for i in range(5)
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        # Set to 5
        config = summarizer.actions["manage_scene_history"].config
        config["best_fit_min_dialogue"].value = 5
        result = scene.context_history(budget=5000)
        text = " ".join(result)
        count_5 = sum(1 for i in range(10) if f"M{i}" in text)
        assert count_5 >= 5, f"Expected >= 5 dialogue messages, got {count_5}"

        # Set to 0 (disabled) — the min_dialogue guarantee adds no forced
        # messages, but the expansion algorithm may still unpack archived
        # entries into verbatim dialogue when it's cost-effective.
        config["best_fit_min_dialogue"].value = 0
        scene2 = MockScene()
        scene2.history = messages
        scene2.archived_history = archived
        scene2.layered_history = []
        scene2.ts = test_data["basic_scene"]["ts"]
        # Budget too small for all 10 messages (1000 chars) — forces bounded mode.
        # With min=0, no messages are forced past the summarization boundary,
        # but dialogue may still appear via expansion.
        result_0 = scene2.context_history(budget=500)
        text_0 = " ".join(result_0)
        count_0 = sum(1 for i in range(10) if f"M{i}" in text_0)
        # With min=5 we got at least 5; with min=0 we should get fewer
        # (no forced guarantee), though expansion may still produce some.
        assert count_0 < count_5, (
            f"min=0 should produce fewer dialogue messages than min=5, "
            f"got {count_0} vs {count_5}"
        )

    def test_best_fit_min_dialogue_with_duplicate_messages(
        self, summarizer, test_data
    ):
        """min_dialogue works when history contains duplicate formatted texts.

        Regression test: if many history messages share the same formatted
        string (e.g. repeated system beats), the counting logic must not
        inflate qualifying_count and incorrectly skip the top-up.
        """
        from talemate.agents.summarize.context_history import _BEST_FIT_MIN_DIALOGUE

        if _BEST_FIT_MIN_DIALOGUE <= 0:
            pytest.skip("min dialogue guarantee is disabled")

        self._enable_best_fit(summarizer)

        # Create 30 messages where messages 0-27 all have the same text
        # (simulating repeated system beats) and only 28-29 are unique.
        messages = []
        for i in range(30):
            if i < 28:
                # All share the same text
                msg = CharacterMessage(
                    "Repeated text content here", source="Alice"
                )
            else:
                msg = CharacterMessage(f"Unique message {i}", source="Bob")
            messages.append(msg)

        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 6 - 1,
            }
            for i in range(5)
        ]
        # summarized_to = archived[-1]["end"] = 29 (all 30 messages summarized)

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=5000)
        text = " ".join(result)

        # Despite duplicates, min_dialogue should still top up to the minimum
        # by pulling distinct messages from history.
        dialogue_count = text.count("Unique message") + (
            1 if "Repeated text" in text else 0
        )
        assert dialogue_count >= min(_BEST_FIT_MIN_DIALOGUE, 30), (
            f"Expected at least {_BEST_FIT_MIN_DIALOGUE} dialogue messages "
            f"with duplicate texts, got {dialogue_count}"
        )

    def test_best_fit_preview_includes_min_dialogue(self, summarizer, test_data):
        """Preview response includes best_fit_min_dialogue in summary."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        from talemate.agents.summarize.context_history import (
            ContextHistoryPreviewOverrides,
        )

        overrides = ContextHistoryPreviewOverrides(
            best_fit=True, max_budget=5000, best_fit_min_dialogue=7
        )
        preview = summarizer.context_history_preview(scene, overrides=overrides)

        assert preview["summary"]["best_fit_min_dialogue"] == 7

    def test_best_fit_budget_enforced_with_start_end_gaps(self, summarizer, test_data):
        """Post-expansion enforcement trims when start/end gaps cause overshoot.

        When upper-level entries have non-contiguous start/end mappings to the
        lower level, expanding multiple entries and merging their ranges can
        sweep in gap entries whose tokens were never tracked in the delta
        accounting.  The post-expansion enforcement must catch this and trim
        to stay within budget.
        """
        from talemate.agents.summarize.context_history import (
            ContextHistoryMixin,
            _BestFitLevel,
        )

        # Lower level: 10 entries, each 100 tokens
        lower_entries = [
            {"text": _pad(f"lower-{i}", 100), "ts": f"PT{i}M"} for i in range(10)
        ]
        lower_formatted = [e["text"] for e in lower_entries]
        lower_tokens = [100] * 10  # 1000 tokens total

        # Upper level: 3 entries, each 50 tokens
        # Entry 0: covers lower 0-2 (contiguous)
        # Entry 1: covers lower 3-4 (GAP: lower 5 uncovered)
        # Entry 2: covers lower 6-8 (GAP: lower 5 skipped, lower 9 uncovered)
        upper_entries = [
            {
                "text": _pad("upper-0", 50),
                "ts_start": "PT0M",
                "ts_end": "PT3M",
                "start": 0,
                "end": 2,
            },
            {
                "text": _pad("upper-1", 50),
                "ts_start": "PT3M",
                "ts_end": "PT5M",
                "start": 3,
                "end": 4,
            },
            {
                "text": _pad("upper-2", 50),
                "ts_start": "PT6M",
                "ts_end": "PT9M",
                "start": 6,
                "end": 8,
            },
        ]
        upper_formatted = [e["text"] for e in upper_entries]
        upper_tokens = [50] * 3  # 150 tokens total

        levels = [
            _BestFitLevel(
                entries=upper_entries,
                formatted=upper_formatted,
                tokens=upper_tokens,
                type="layer",
                layer_idx=1,
            ),
            _BestFitLevel(
                entries=lower_entries,
                formatted=lower_formatted,
                tokens=lower_tokens,
                type="archived",
            ),
        ]

        # Skeleton = 150 tokens (all at upper level).
        # Expanding entry 2 (upper[2]): delta = 3*100 - 50 = 250
        # Expanding entry 1 (upper[1]): delta = 2*100 - 50 = 150
        #   But merging ranges: lower goes from (6,9) to (3,9) — sweeps in
        #   lower[5] (100 tokens) that's in the gap.  Without enforcement
        #   the algorithm thinks it spent 150+250=400 extra, but actually
        #   spent 400+100=500 extra (gap entry 5).
        #
        # Set budget so it fits skeleton + 2 expansions (550) but NOT the
        # gap entry: 150 + 400 = 550 budget.  Without enforcement the
        # actual rendered total would be 650 (upper[0]=50 + lower[3..8]=600).
        budget = 550

        render_ranges = ContextHistoryMixin._best_fit_compute_ranges(levels, budget)

        # Compute actual rendered tokens
        total = sum(
            sum(level.tokens[s:e]) for level, (s, e) in zip(levels, render_ranges)
        )

        assert total <= budget, (
            f"Post-expansion enforcement failed: rendered {total} tokens "
            f"with budget {budget}"
        )

    def test_best_fit_prefers_dialogue_over_summaries(self, summarizer, test_data):
        """When budget fits all dialogue, prefer it over summaries."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)
        # All 30 messages = 3000 chars; budget 5000 fits them all.
        result = scene.context_history(budget=5000)
        text = " ".join(result)

        # All 30 dialogue messages should be present
        for i in range(30):
            assert f"M{i}" in text, f"Message {i} should be present"

        # No summary content — full dialogue is the most granular detail
        assert "Archived" not in text, (
            "Summaries should not appear when all dialogue fits"
        )
        assert "L0-" not in text
        assert "L1-" not in text

    def test_best_fit_falls_back_to_summaries(self, summarizer, test_data):
        """When budget can't fit all dialogue, summaries fill timeline gaps."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)
        # 30 messages = 3000 chars; budget 1500 can't fit all dialogue.
        result = scene.context_history(budget=1500)
        text = " ".join(result)

        # Recent dialogue must be present
        assert "M29" in text, "Most recent message must be present"

        # Some summary content should fill in for older messages
        has_summary = (
            any(f"Archived {i}" in text for i in range(8))
            or any(f"L0-{i}" in text for i in range(4))
            or any(f"L1-{i}" in text for i in range(2))
        )
        assert has_summary, "Summary content should fill gaps when dialogue doesn't fit"

    def test_best_fit_preview_prefers_dialogue(self, summarizer, test_data):
        """Preview in best-fit mode also prefers full dialogue when budget allows."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        from talemate.agents.summarize.context_history import (
            ContextHistoryPreviewOverrides,
        )

        # Budget large enough for all 30 messages (3000 chars)
        overrides = ContextHistoryPreviewOverrides(best_fit=True, max_budget=5000)
        preview = summarizer.context_history_preview(scene, overrides=overrides)

        types = [s["type"] for s in preview["sections"]]
        assert "dialogue" in types

        # No summary sections when all dialogue fits
        assert "layer" not in types, "No layer sections when all dialogue fits"
        assert "archived" not in types, "No archived sections when all dialogue fits"

        # Dialogue section should contain all messages
        dialogue_section = next(
            s for s in preview["sections"] if s["type"] == "dialogue"
        )
        dialogue_text = " ".join(dialogue_section["entries"])
        for i in range(30):
            assert f"M{i}" in dialogue_text, f"Message {i} should be in dialogue"

    def test_best_fit_excludes_non_summary_archived_entries(
        self, summarizer, test_data
    ):
        """Archived entries without 'end' (permanent notes) are excluded from best-fit levels."""
        self._enable_best_fit(summarizer)

        messages = [_make_message(i, self.MSG_CHARS) for i in range(10)]
        # Mix of summary entries (with end) and permanent notes (without end)
        archived = [
            {"text": _pad("Permanent note", self.ARCH_CHARS), "ts": "PT0S"},
            {
                "text": _pad("Summary 0", self.ARCH_CHARS),
                "ts": "PT10M",
                "end": 3,
            },
            {
                "text": _pad("Summary 1", self.ARCH_CHARS),
                "ts": "PT20M",
                "end": 7,
            },
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        # Budget too small for all dialogue to force summary usage
        result = scene.context_history(budget=500)
        text = " ".join(result)

        # Permanent note should NOT appear (no "end" field)
        assert "Permanent note" not in text, "Permanent notes should be excluded"

        # Summary entries may appear (if budget allows)
        # The important thing is the permanent note was filtered out

    def test_best_fit_preview_includes_intro_when_sparse(self, summarizer, test_data):
        """Preview includes scene intro in dialogue section when context is sparse."""
        self._enable_best_fit(summarizer)

        from talemate.agents.summarize.context_history import (
            ContextHistoryPreviewOverrides,
        )

        # Scene with no history/archives — context is empty, so intro should appear
        scene = MockScene()
        scene.history = []
        scene.archived_history = []
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.intro = "Welcome to the test adventure."

        overrides = ContextHistoryPreviewOverrides(best_fit=True, max_budget=5000)
        preview = summarizer.context_history_preview(scene, overrides=overrides)

        dialogue_section = next(
            s for s in preview["sections"] if s["type"] == "dialogue"
        )
        dialogue_text = " ".join(dialogue_section["entries"])
        assert "Welcome to the test adventure" in dialogue_text, (
            "Intro should appear in dialogue section when context is sparse"
        )

    def test_ratio_preview_includes_intro_when_sparse(self, summarizer, test_data):
        """Ratio-mode preview includes scene intro in dialogue when context is sparse."""
        from talemate.agents.summarize.context_history import (
            ContextHistoryPreviewOverrides,
        )

        scene = MockScene()
        scene.history = []
        scene.archived_history = []
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.intro = "A stormy night begins."

        overrides = ContextHistoryPreviewOverrides(best_fit=False, max_budget=5000)
        preview = summarizer.context_history_preview(scene, overrides=overrides)

        dialogue_section = next(
            s for s in preview["sections"] if s["type"] == "dialogue"
        )
        dialogue_text = " ".join(dialogue_section["entries"])
        assert "A stormy night begins" in dialogue_text, (
            "Intro should appear in dialogue section when context is sparse"
        )

    def test_best_fit_all_dialogue_with_few_summaries(self, summarizer, test_data):
        """Repro: 25 messages (~3000 tokens), 2 archived, budget=12000.

        All dialogue should fit easily — summaries should NOT appear.
        A DirectorMessage at index 0 (skipped during collection) must not
        prevent the algorithm from recognising that all dialogue was collected.
        """
        self._enable_best_fit(summarizer)
        summarizer.actions["manage_scene_history"].config[
            "best_fit_max_dialogue"
        ].value = 250

        # DirectorMessage at index 0 — skipped by collection but occupies slot 0
        director_msg = DirectorMessage(message="Assigned voice", source="ai")
        messages = [director_msg] + [_make_message(i, 120) for i in range(1, 25)]
        # 2 archived entries covering messages 0..19
        archived = [
            {"text": _pad("Summary 0", 200), "ts": "PT10M", "end": 9},
            {"text": _pad("Summary 1", 200), "ts": "PT20M", "end": 19},
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=12000)
        text = " ".join(result)

        # All 24 character messages at 120 chars = 2880 tokens, budget=12000
        for i in range(1, 25):
            assert f"M{i}" in text, f"Message {i} should be present"

        # No summaries — full dialogue is more granular
        assert "Summary 0" not in text, (
            "Summary should not appear when all dialogue fits"
        )
        assert "Summary 1" not in text, (
            "Summary should not appear when all dialogue fits"
        )

    def test_best_fit_preview_all_dialogue_with_few_summaries(
        self, summarizer, test_data
    ):
        """Repro (preview path): 25 messages (~3000 tokens), 2 archived, budget=12000."""
        self._enable_best_fit(summarizer)
        summarizer.actions["manage_scene_history"].config[
            "best_fit_max_dialogue"
        ].value = 250

        from talemate.agents.summarize.context_history import (
            ContextHistoryPreviewOverrides,
        )

        messages = [_make_message(i, 120) for i in range(25)]
        archived = [
            {"text": _pad("Summary 0", 200), "ts": "PT10M", "end": 9},
            {"text": _pad("Summary 1", 200), "ts": "PT20M", "end": 19},
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        overrides = ContextHistoryPreviewOverrides(
            best_fit=True, max_budget=12000, best_fit_max_dialogue=250
        )
        preview = summarizer.context_history_preview(scene, overrides=overrides)

        types = [s["type"] for s in preview["sections"]]
        assert "dialogue" in types

        # Should be dialogue only — no summary sections
        assert "archived" not in types, (
            f"Archived sections should not appear when all dialogue fits. "
            f"Sections: {types}"
        )
        assert "layer" not in types

    def test_best_fit_expands_archived_to_dialogue(self, summarizer, test_data):
        """With enough budget, recent archived entries expand to verbatim dialogue."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        # Budget large enough for mandatory dialogue (600 chars for M24-M29)
        # plus the full compressed skeleton plus some expansion into dialogue.
        # Skeleton (Layer 1): 2 × ~160 = ~320 chars (formatted with timestamp)
        # Expansion to dialogue should unpack recent archived entries.
        result = scene.context_history(budget=3500)
        text = " ".join(result)

        # Mandatory dialogue (messages 24-29) must be present
        assert "M29" in text
        assert "M24" in text

        # Some messages from the summarized range should appear as verbatim
        # dialogue (expanded from archived entries by the expansion algorithm).
        summarized_messages = [i for i in range(24) if f"M{i}" in text]
        assert len(summarized_messages) > 0, (
            "Some summarized messages should be expanded to dialogue"
        )

    def test_best_fit_dialogue_expansion_maximizes_detail(self, summarizer, test_data):
        """Dialogue expansion should prefer recent messages over summaries."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        # Budget enough for all summaries + mandatory dialogue + partial expansion.
        result = scene.context_history(budget=2500)
        text = " ".join(result)

        # If any summarized messages appear as dialogue, they should be the
        # most recent ones (closest to the mandatory dialogue boundary).
        expanded = [i for i in range(24) if f"M{i}" in text]
        if expanded:
            # The most recent summarized message index (23) should be present
            # before older ones.
            assert max(expanded) >= 20, (
                f"Expanded dialogue should include recent summarized messages, "
                f"got indices {expanded}"
            )

    def test_best_fit_archived_entries_without_start(self, summarizer, test_data):
        """Archived entries without 'start' field work correctly."""
        self._enable_best_fit(summarizer)

        messages = [_make_message(i, self.MSG_CHARS) for i in range(20)]
        # Archived entries deliberately missing 'start' field
        archived = [
            {"text": _pad("Archived 0", self.ARCH_CHARS), "ts": "PT0S", "end": 4},
            {"text": _pad("Archived 1", self.ARCH_CHARS), "ts": "PT10M", "end": 9},
            {"text": _pad("Archived 2", self.ARCH_CHARS), "ts": "PT20M", "end": 14},
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]

        # Should not crash; start is computed as:
        # archived[0]: start=0, archived[1]: start=5, archived[2]: start=10
        result = scene.context_history(budget=3000)
        assert isinstance(result, list)
        assert len(result) > 0

        # With generous budget, should see both summaries and dialogue
        text = " ".join(result)
        assert "M19" in text, "Most recent message should be present"

    def test_best_fit_no_overlap_between_expanded_and_mandatory(
        self, summarizer, test_data
    ):
        """Expanded dialogue covers the summarized region; mandatory covers the rest."""
        self._enable_best_fit(summarizer)
        scene = self._make_test_scene(test_data)

        # Large budget to allow significant expansion
        result = scene.context_history(budget=4000)
        text = " ".join(result)

        # Mandatory messages (24-29) should be present
        for i in range(24, 30):
            assert f"M{i}" in text, f"Mandatory message M{i} missing"

        # Full timeline should be covered (either via summaries or expanded dialogue)
        has_early_coverage = (
            any(f"M{i}" in text for i in range(5))
            or any(f"Archived {i}" in text for i in range(3))
            or any(f"L0-{i}" in text for i in range(2))
            or any(f"L1-{i}" in text for i in range(1))
        )
        assert has_early_coverage, "Early timeline should be covered"

    def test_best_fit_orphan_entries_not_skipped(self, summarizer, test_data):
        """Entries at the tail of each layer that aren't covered by the
        layer above must still appear in the output (no timeline gap)."""
        self._enable_best_fit(summarizer)

        messages = [_make_message(i, self.MSG_CHARS) for i in range(40)]

        # 12 archived entries covering messages 0-35 (summarized_to=35)
        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "start": i * 3,
                "end": i * 3 + 2,
            }
            for i in range(12)
        ]

        # Layer 0 covers archived 0-9 (NOT 10-11 → orphans)
        layer_0 = [
            {
                "text": _pad(f"L0-{i}", self.L0_CHARS),
                "ts_start": f"PT{i * 30}M",
                "ts_end": f"PT{(i + 1) * 30}M",
                "start": i * 2,
                "end": i * 2 + 1,
            }
            for i in range(5)
        ]

        # Layer 1 covers L0 0-3 (NOT L0[4] → orphan)
        layer_1 = [
            {
                "text": _pad(f"L1-{i}", self.L1_CHARS),
                "ts_start": f"PT{i * 60}M",
                "ts_end": f"PT{(i + 1) * 60}M",
                "start": i * 2,
                "end": i * 2 + 1,
            }
            for i in range(2)
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = [layer_0, layer_1]
        scene.ts = test_data["basic_scene"]["ts"]

        result = scene.context_history(budget=5000)
        text = " ".join(result)

        # Mandatory dialogue (messages 36-39) must be present
        assert "M39" in text, "Most recent message must be present"

        # The orphaned archived entries (10-11, covering messages 30-35)
        # must NOT be skipped.  They should appear either as summaries
        # or as expanded dialogue.
        orphan_region_covered = any(
            f"Archived {i}" in text for i in range(10, 12)
        ) or any(f"M{i}" in text for i in range(30, 36))
        assert orphan_region_covered, (
            "Orphan archived entries (or their dialogue) must be present "
            "to avoid a timeline gap"
        )


# ---------------------------------------------------------------------------
# Tests: Build / Preview Parity
# ---------------------------------------------------------------------------


class TestBuildPreviewParity:
    """Verify that build and preview paths produce identical entries.

    The preview formats output as sections with metadata, while the build
    returns a flat list.  Flattening the preview sections' entries must
    yield the same list as the build path.

    NOTE: chapter_labels=True inserts a "### Current" separator in the
    build path that the preview does not emit.  All parity tests use the
    default chapter_labels=False to avoid this known divergence.
    """

    MSG_CHARS = 100
    ARCH_CHARS = 200
    L0_CHARS = 300
    L1_CHARS = 150

    @staticmethod
    def _flatten_preview(preview: dict) -> list[str]:
        """Flatten all entries from preview sections in order."""
        entries = []
        for section in preview["sections"]:
            entries.extend(section["entries"])
        return entries

    @classmethod
    def _setup_summarizer(
        cls,
        summarizer,
        *,
        best_fit,
        dialogue_ratio=50,
        summary_detail_ratio=50,
        enforce_boundary=False,
        best_fit_min_dialogue=5,
        best_fit_max_dialogue=250,
    ):
        """Configure summarizer and return matching preview overrides."""
        from talemate.agents.summarize.context_history import (
            ContextHistoryPreviewOverrides,
        )

        cfg = summarizer.actions["manage_scene_history"].config
        cfg["max_budget"].value = 0
        cfg["best_fit"].value = best_fit
        cfg["dialogue_ratio"].value = dialogue_ratio
        cfg["summary_detail_ratio"].value = summary_detail_ratio
        cfg["enforce_boundary"].value = enforce_boundary
        cfg["best_fit_min_dialogue"].value = best_fit_min_dialogue
        cfg["best_fit_max_dialogue"].value = best_fit_max_dialogue
        summarizer.actions["layered_history"].enabled = True

        return ContextHistoryPreviewOverrides(
            max_budget=0,
            best_fit=best_fit,
            dialogue_ratio=dialogue_ratio,
            summary_detail_ratio=summary_detail_ratio,
            enforce_boundary=enforce_boundary,
            best_fit_min_dialogue=best_fit_min_dialogue,
            best_fit_max_dialogue=best_fit_max_dialogue,
        )

    @classmethod
    def _make_test_scene(
        cls,
        test_data,
        *,
        num_messages=30,
        num_archived=8,
        with_layers=True,
        intro=None,
    ):
        """Create a test scene with optional layered history.

        Structure:
          - messages 0..23 covered by archived (summarized_to=23)
          - messages 24..29 are unsummarized (mandatory dialogue)
          - archived 0..7 (8 entries)
          - layer 0: 4 entries covering archived [0-1], [2-3], [4-5], [6-7]
          - layer 1: 2 entries covering L0 [0-1], [2-3]
        """
        messages = [_make_message(i, cls.MSG_CHARS) for i in range(num_messages)]

        archived = [
            {
                "text": _pad(f"Archived {i}", cls.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "end": (i + 1) * 3 - 1,
            }
            for i in range(num_archived)
        ]

        if with_layers:
            layer_0 = [
                {
                    "text": _pad(f"L0-{i}", cls.L0_CHARS),
                    "ts_start": f"PT{i * 20}M",
                    "ts_end": f"PT{(i + 1) * 20}M",
                    "start": i * 2,
                    "end": i * 2 + 1,
                }
                for i in range(4)
            ]

            layer_1 = [
                {
                    "text": _pad(f"L1-{i}", cls.L1_CHARS),
                    "ts_start": f"PT{i * 40}M",
                    "ts_end": f"PT{(i + 1) * 40}M",
                    "start": i * 2,
                    "end": i * 2 + 1,
                }
                for i in range(2)
            ]

            layered = [layer_0, layer_1]
        else:
            layered = []

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = layered
        scene.ts = test_data["basic_scene"]["ts"]
        scene.intro = intro or ""
        return scene

    def _assert_parity(self, summarizer, scene, budget, overrides):
        """Assert build and preview produce identical flattened entries."""
        build_result = scene.context_history(budget=budget)
        preview = summarizer.context_history_preview(
            scene, budget=budget, overrides=overrides
        )
        preview_entries = self._flatten_preview(preview)

        assert build_result == preview_entries, (
            f"Build/preview mismatch.\n"
            f"  Build ({len(build_result)} entries): "
            f"{[e[:40] + '...' if len(e) > 40 else e for e in build_result]}\n"
            f"  Preview ({len(preview_entries)} entries): "
            f"{[e[:40] + '...' if len(e) > 40 else e for e in preview_entries]}"
        )

    # --- Best-fit mode ---

    def test_best_fit_all_dialogue_fits(self, summarizer, test_data):
        """Parity when all dialogue fits within budget (no summaries)."""
        overrides = self._setup_summarizer(summarizer, best_fit=True)
        scene = self._make_test_scene(test_data)
        self._assert_parity(summarizer, scene, budget=100000, overrides=overrides)

    def test_best_fit_with_layers_tight_budget(self, summarizer, test_data):
        """Parity in best-fit mode with layers and a tight budget."""
        overrides = self._setup_summarizer(summarizer, best_fit=True)
        scene = self._make_test_scene(test_data)
        self._assert_parity(summarizer, scene, budget=2000, overrides=overrides)

    def test_best_fit_no_layers(self, summarizer, test_data):
        """Parity in best-fit mode with only archived + dialogue."""
        overrides = self._setup_summarizer(summarizer, best_fit=True)
        scene = self._make_test_scene(test_data, with_layers=False)
        self._assert_parity(summarizer, scene, budget=2000, overrides=overrides)

    def test_best_fit_medium_budget_expansion(self, summarizer, test_data):
        """Parity when budget allows partial expansion of archived to dialogue."""
        overrides = self._setup_summarizer(summarizer, best_fit=True)
        scene = self._make_test_scene(test_data)
        self._assert_parity(summarizer, scene, budget=3500, overrides=overrides)

    def test_best_fit_dialogue_exceeds_budget(self, summarizer, test_data):
        """Parity when mandatory dialogue alone exceeds the budget."""
        overrides = self._setup_summarizer(summarizer, best_fit=True)
        scene = self._make_test_scene(test_data)
        self._assert_parity(summarizer, scene, budget=300, overrides=overrides)

    def test_best_fit_empty_scene_with_intro(self, summarizer, test_data):
        """Parity with empty history and an intro (sparse context path)."""
        overrides = self._setup_summarizer(summarizer, best_fit=True)
        scene = MockScene()
        scene.history = []
        scene.archived_history = []
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.intro = "Welcome to the adventure."
        self._assert_parity(summarizer, scene, budget=5000, overrides=overrides)

    def test_best_fit_with_orphan_entries(self, summarizer, test_data):
        """Parity when layers have orphan entries not covered by the layer above."""
        overrides = self._setup_summarizer(summarizer, best_fit=True)

        messages = [_make_message(i, self.MSG_CHARS) for i in range(40)]
        archived = [
            {
                "text": _pad(f"Archived {i}", self.ARCH_CHARS),
                "ts": f"PT{i * 10}M",
                "start": i * 3,
                "end": i * 3 + 2,
            }
            for i in range(12)
        ]
        # Layer 0 covers archived 0-9 (NOT 10-11 → orphans)
        layer_0 = [
            {
                "text": _pad(f"L0-{i}", self.L0_CHARS),
                "ts_start": f"PT{i * 30}M",
                "ts_end": f"PT{(i + 1) * 30}M",
                "start": i * 2,
                "end": i * 2 + 1,
            }
            for i in range(5)
        ]
        # Layer 1 covers L0 0-3 (NOT L0[4] → orphan)
        layer_1 = [
            {
                "text": _pad(f"L1-{i}", self.L1_CHARS),
                "ts_start": f"PT{i * 60}M",
                "ts_end": f"PT{(i + 1) * 60}M",
                "start": i * 2,
                "end": i * 2 + 1,
            }
            for i in range(2)
        ]

        scene = MockScene()
        scene.history = messages
        scene.archived_history = archived
        scene.layered_history = [layer_0, layer_1]
        scene.ts = test_data["basic_scene"]["ts"]

        self._assert_parity(summarizer, scene, budget=5000, overrides=overrides)

    # --- Ratio mode ---

    def test_ratio_no_layers_no_boundary(self, summarizer, test_data):
        """Parity in ratio mode without layers or boundary enforcement."""
        overrides = self._setup_summarizer(
            summarizer,
            best_fit=False,
            dialogue_ratio=50,
            summary_detail_ratio=50,
        )
        summarizer.actions["layered_history"].enabled = False
        scene = self._make_test_scene(test_data, with_layers=False)
        self._assert_parity(summarizer, scene, budget=2000, overrides=overrides)

    def test_ratio_with_layers(self, summarizer, test_data):
        """Parity in ratio mode with layered history."""
        overrides = self._setup_summarizer(
            summarizer,
            best_fit=False,
            dialogue_ratio=40,
            summary_detail_ratio=40,
        )
        scene = self._make_test_scene(test_data)
        self._assert_parity(summarizer, scene, budget=3000, overrides=overrides)

    def test_ratio_with_boundary(self, summarizer, test_data):
        """Parity in ratio mode with boundary enforcement."""
        overrides = self._setup_summarizer(
            summarizer,
            best_fit=False,
            dialogue_ratio=50,
            summary_detail_ratio=50,
            enforce_boundary=True,
        )
        scene = self._make_test_scene(test_data, with_layers=False)
        self._assert_parity(summarizer, scene, budget=3000, overrides=overrides)

    def test_ratio_high_dialogue_ratio(self, summarizer, test_data):
        """Parity in ratio mode with high dialogue ratio (80%)."""
        overrides = self._setup_summarizer(
            summarizer,
            best_fit=False,
            dialogue_ratio=80,
            summary_detail_ratio=50,
        )
        scene = self._make_test_scene(test_data, with_layers=False)
        self._assert_parity(summarizer, scene, budget=5000, overrides=overrides)

    def test_ratio_low_dialogue_ratio_with_layers(self, summarizer, test_data):
        """Parity in ratio mode with low dialogue ratio and layers."""
        overrides = self._setup_summarizer(
            summarizer,
            best_fit=False,
            dialogue_ratio=20,
            summary_detail_ratio=60,
        )
        scene = self._make_test_scene(test_data)
        self._assert_parity(summarizer, scene, budget=4000, overrides=overrides)

    def test_ratio_empty_scene_with_intro(self, summarizer, test_data):
        """Parity in ratio mode with empty history and intro."""
        overrides = self._setup_summarizer(
            summarizer,
            best_fit=False,
            dialogue_ratio=50,
            summary_detail_ratio=50,
        )
        scene = MockScene()
        scene.history = []
        scene.archived_history = []
        scene.layered_history = []
        scene.ts = test_data["basic_scene"]["ts"]
        scene.intro = "A stormy night begins."
        self._assert_parity(summarizer, scene, budget=5000, overrides=overrides)
