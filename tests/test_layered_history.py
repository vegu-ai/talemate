"""
Unit tests for layered history functions, particularly collect_source_entries.

These tests verify that source entries are correctly retrieved from the
appropriate layer when inspecting history entries.
"""

import pytest
import types
import uuid

from talemate.history import collect_source_entries, HistoryEntry
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def create_scene_message(text: str, source: str = "ai") -> CharacterMessage:
    """Create a CharacterMessage with an auto-generated id."""
    msg = CharacterMessage(message=text, source=source)
    msg.id = str(uuid.uuid4())
    return msg


def create_archived_entry(
    text: str,
    entry_id: str = None,
    start: int = None,
    end: int = None,
    ts: str = "PT0S",
) -> dict:
    """Create an archived history entry dict."""
    return {
        "id": entry_id or str(uuid.uuid4()),
        "text": text,
        "start": start,
        "end": end,
        "ts": ts,
        "ts_start": ts,
        "ts_end": ts,
    }


def create_layered_entry(
    text: str,
    entry_id: str = None,
    start: int = None,
    end: int = None,
    ts: str = "PT0S",
) -> dict:
    """Create a layered history entry dict."""
    return {
        "id": entry_id or str(uuid.uuid4()),
        "text": text,
        "start": start,
        "end": end,
        "ts": ts,
        "ts_start": ts,
        "ts_end": ts,
    }


@pytest.fixture
def mock_scene():
    """
    Create a mock Scene object factory.

    Returns a factory function that creates scenes with configurable history layers.
    """

    def _factory(
        history: list = None,
        archived_history: list = None,
        layered_history: list = None,
    ):
        scene = types.SimpleNamespace()
        scene.history = history or []
        scene.archived_history = archived_history or []
        scene.layered_history = layered_history or []
        scene.ts = "PT1H"
        return scene

    return _factory


# ---------------------------------------------------------------------------
# Tests: Layer 0 (Base layer - sources from scene.history)
# ---------------------------------------------------------------------------


class TestCollectSourceEntriesLayer0:
    """Test collect_source_entries for layer 0 (base layer) entries."""

    def test_layer0_returns_history_messages(self, mock_scene):
        """Layer 0 entries should return source entries from scene.history."""
        messages = [
            create_scene_message("Message 0"),
            create_scene_message("Message 1"),
            create_scene_message("Message 2"),
            create_scene_message("Message 3"),
            create_scene_message("Message 4"),
        ]
        scene = mock_scene(history=messages)

        entry = HistoryEntry(
            text="Summary of messages 1-3",
            ts="PT30M",
            index=0,
            layer=0,
            start=1,
            end=3,
        )

        result = collect_source_entries(scene, entry)

        assert len(result) == 3
        assert "Message 1" in result[0].text
        assert "Message 2" in result[1].text
        assert "Message 3" in result[2].text

    def test_layer0_filters_director_messages(self, mock_scene):
        """Layer 0 should filter out director, context_investigation, and reinforcement messages."""
        messages = [
            create_scene_message("Character message"),
            DirectorMessage(message="Director instruction", source="ai"),
            create_scene_message("Another character message"),
        ]
        # Set message types
        messages[1].typ = "director"

        scene = mock_scene(history=messages)

        entry = HistoryEntry(
            text="Summary",
            ts="PT30M",
            index=0,
            layer=0,
            start=0,
            end=2,
        )

        result = collect_source_entries(scene, entry)

        # Should only include character messages, not director
        assert len(result) == 2
        assert all("Director" not in r.text for r in result)

    def test_layer0_returns_empty_for_no_start_end(self, mock_scene):
        """Layer 0 entries without start/end should return empty list."""
        messages = [create_scene_message("Message 0")]
        scene = mock_scene(history=messages)

        entry = HistoryEntry(
            text="Static entry",
            ts="PT30M",
            index=0,
            layer=0,
            start=None,
            end=None,
        )

        result = collect_source_entries(scene, entry)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: Layer 1 (sources from archived_history)
# ---------------------------------------------------------------------------


class TestCollectSourceEntriesLayer1:
    """Test collect_source_entries for layer 1 entries."""

    def test_layer1_returns_archived_history_entries(self, mock_scene):
        """Layer 1 entries should return source entries from archived_history."""
        archived = [
            create_archived_entry("Archived 0", start=0, end=10),
            create_archived_entry("Archived 1", start=11, end=20),
            create_archived_entry("Archived 2", start=21, end=30),
            create_archived_entry("Archived 3", start=31, end=40),
            create_archived_entry("Archived 4", start=41, end=50),
        ]
        scene = mock_scene(archived_history=archived)

        entry = HistoryEntry(
            text="Summary of archived 1-3",
            ts="PT30M",
            index=0,
            layer=1,
            start=1,
            end=3,
        )

        result = collect_source_entries(scene, entry)

        assert len(result) == 3
        assert result[0].text == "Archived 1"
        assert result[1].text == "Archived 2"
        assert result[2].text == "Archived 3"

    def test_layer1_single_entry(self, mock_scene):
        """Layer 1 should work with single entry range."""
        archived = [
            create_archived_entry("Archived 0", start=0, end=10),
            create_archived_entry("Archived 1", start=11, end=20),
        ]
        scene = mock_scene(archived_history=archived)

        entry = HistoryEntry(
            text="Summary of archived 0",
            ts="PT30M",
            index=0,
            layer=1,
            start=0,
            end=0,
        )

        result = collect_source_entries(scene, entry)

        assert len(result) == 1
        assert result[0].text == "Archived 0"

    def test_layer1_preserves_entry_metadata(self, mock_scene):
        """Layer 1 should preserve source entry metadata."""
        archived = [
            create_archived_entry(
                "Archived 0",
                entry_id="test-id-123",
                start=5,
                end=15,
                ts="PT15M",
            ),
        ]
        scene = mock_scene(archived_history=archived)

        entry = HistoryEntry(
            text="Summary",
            ts="PT30M",
            index=0,
            layer=1,
            start=0,
            end=0,
        )

        result = collect_source_entries(scene, entry)

        assert len(result) == 1
        assert result[0].id == "test-id-123"
        assert result[0].start == 5
        assert result[0].end == 15
        assert result[0].ts == "PT15M"


# ---------------------------------------------------------------------------
# Tests: Layer 2+ (sources from layered_history[layer - 2])
# ---------------------------------------------------------------------------


class TestCollectSourceEntriesLayer2Plus:
    """Test collect_source_entries for layer 2+ entries.

    This is the critical test class for the bug fix. Layer 2 entries should
    source from layered_history[0], layer 3 from layered_history[1], etc.
    """

    def test_layer2_returns_from_layered_history_0(self, mock_scene):
        """Layer 2 entries should return source entries from layered_history[0]."""
        # layered_history[0] contains entries that summarize archived_history
        layer_0 = [
            create_layered_entry("Layer0 Entry 0", start=0, end=5),
            create_layered_entry("Layer0 Entry 1", start=6, end=10),
            create_layered_entry("Layer0 Entry 2", start=11, end=15),
            create_layered_entry("Layer0 Entry 3", start=16, end=20),
        ]
        # layered_history[1] contains entries that summarize layered_history[0]
        layer_1 = [
            create_layered_entry("Layer1 Entry 0", start=0, end=1),
            create_layered_entry("Layer1 Entry 1", start=2, end=3),
        ]

        scene = mock_scene(layered_history=[layer_0, layer_1])

        # Layer 2 entry (stored in layered_history[1]) should look in layered_history[0]
        entry = HistoryEntry(
            text="Summary of layer0 entries 1-2",
            ts="PT30M",
            index=0,
            layer=2,
            start=1,
            end=2,
        )

        result = collect_source_entries(scene, entry)

        assert len(result) == 2
        assert result[0].text == "Layer0 Entry 1"
        assert result[1].text == "Layer0 Entry 2"

    def test_layer3_returns_from_layered_history_1(self, mock_scene):
        """Layer 3 entries should return source entries from layered_history[1]."""
        layer_0 = [
            create_layered_entry("Layer0 Entry 0", start=0, end=5),
            create_layered_entry("Layer0 Entry 1", start=6, end=10),
        ]
        layer_1 = [
            create_layered_entry("Layer1 Entry 0", start=0, end=0),
            create_layered_entry("Layer1 Entry 1", start=1, end=1),
        ]
        layer_2 = [
            create_layered_entry("Layer2 Entry 0", start=0, end=1),
        ]

        scene = mock_scene(layered_history=[layer_0, layer_1, layer_2])

        # Layer 3 entry (stored in layered_history[2]) should look in layered_history[1]
        entry = HistoryEntry(
            text="Summary of layer1 entries 0-1",
            ts="PT30M",
            index=0,
            layer=3,
            start=0,
            end=1,
        )

        result = collect_source_entries(scene, entry)

        assert len(result) == 2
        assert result[0].text == "Layer1 Entry 0"
        assert result[1].text == "Layer1 Entry 1"

    def test_layer2_returns_empty_for_out_of_range_indices(self, mock_scene):
        """Layer 2 should return empty list when indices are out of range."""
        layer_0 = [
            create_layered_entry("Layer0 Entry 0", start=0, end=5),
            create_layered_entry("Layer0 Entry 1", start=6, end=10),
        ]
        layer_1 = [
            create_layered_entry("Layer1 Entry 0", start=0, end=1),
        ]

        scene = mock_scene(layered_history=[layer_0, layer_1])

        # Request indices that don't exist in layer_0
        entry = HistoryEntry(
            text="Summary with out-of-range indices",
            ts="PT30M",
            index=0,
            layer=2,
            start=10,
            end=15,
        )

        result = collect_source_entries(scene, entry)

        # Should return empty since indices 10-15 don't exist in layer_0
        assert result == []

    def test_layer2_full_range(self, mock_scene):
        """Layer 2 should correctly retrieve all entries when range covers entire layer."""
        layer_0 = [
            create_layered_entry("Layer0 Entry 0", start=0, end=5),
            create_layered_entry("Layer0 Entry 1", start=6, end=10),
            create_layered_entry("Layer0 Entry 2", start=11, end=15),
        ]
        layer_1 = [
            create_layered_entry("Layer1 Entry 0", start=0, end=2),
        ]

        scene = mock_scene(layered_history=[layer_0, layer_1])

        entry = HistoryEntry(
            text="Summary of all layer0 entries",
            ts="PT30M",
            index=0,
            layer=2,
            start=0,
            end=2,
        )

        result = collect_source_entries(scene, entry)

        assert len(result) == 3
        assert result[0].text == "Layer0 Entry 0"
        assert result[1].text == "Layer0 Entry 1"
        assert result[2].text == "Layer0 Entry 2"


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestCollectSourceEntriesEdgeCases:
    """Test edge cases for collect_source_entries."""

    def test_returns_empty_for_none_start(self, mock_scene):
        """Should return empty list when start is None."""
        scene = mock_scene()

        entry = HistoryEntry(
            text="Entry with no start",
            ts="PT30M",
            index=0,
            layer=1,
            start=None,
            end=5,
        )

        result = collect_source_entries(scene, entry)
        assert result == []

    def test_returns_empty_for_none_end(self, mock_scene):
        """Should return empty list when end is None."""
        scene = mock_scene()

        entry = HistoryEntry(
            text="Entry with no end",
            ts="PT30M",
            index=0,
            layer=1,
            start=0,
            end=None,
        )

        result = collect_source_entries(scene, entry)
        assert result == []

    def test_empty_archived_history(self, mock_scene):
        """Should return empty list when archived_history is empty."""
        scene = mock_scene(archived_history=[])

        entry = HistoryEntry(
            text="Summary",
            ts="PT30M",
            index=0,
            layer=1,
            start=0,
            end=5,
        )

        result = collect_source_entries(scene, entry)
        assert result == []

    def test_empty_layered_history(self, mock_scene):
        """Should handle missing layered_history gracefully."""
        scene = mock_scene(layered_history=[[]])  # One empty layer

        entry = HistoryEntry(
            text="Summary",
            ts="PT30M",
            index=0,
            layer=2,
            start=0,
            end=5,
        )

        result = collect_source_entries(scene, entry)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: Regression test for the original bug
# ---------------------------------------------------------------------------


class TestCollectSourceEntriesRegressionBug:
    """
    Regression tests for the bug where layer 2+ entries were looking
    in the wrong layered_history index.

    The bug was: source_layer_index = entry.layer - 1 (wrong)
    The fix is:  source_layer_index = entry.layer - 2 (correct)

    Layer mapping:
    - Layer 1 entries -> archived_history (special case)
    - Layer 2 entries -> layered_history[0]
    - Layer 3 entries -> layered_history[1]
    - Layer N entries -> layered_history[N-2]
    """

    def test_layer2_does_not_look_in_wrong_layer(self, mock_scene):
        """
        This test reproduces the original bug scenario.

        Before the fix, layer 2 entries would look in layered_history[1]
        instead of layered_history[0], causing either wrong data or empty
        results when indices didn't exist in the wrong layer.
        """
        # layered_history[0] has 10 entries
        layer_0 = [
            create_layered_entry(f"Layer0 Entry {i}", start=i * 5, end=i * 5 + 4)
            for i in range(10)
        ]

        # layered_history[1] has only 3 entries
        layer_1 = [
            create_layered_entry(f"Layer1 Entry {i}", start=i * 3, end=i * 3 + 2)
            for i in range(3)
        ]

        scene = mock_scene(layered_history=[layer_0, layer_1])

        # Layer 2 entry with start=5, end=8
        # These indices exist in layer_0 but NOT in layer_1
        entry = HistoryEntry(
            text="Summary of layer0 entries 5-8",
            ts="PT30M",
            index=0,
            layer=2,
            start=5,
            end=8,
        )

        result = collect_source_entries(scene, entry)

        # With the fix: should find 4 entries from layer_0
        # With the bug: would find empty list (indices 5-8 don't exist in layer_1)
        assert len(result) == 4
        assert result[0].text == "Layer0 Entry 5"
        assert result[1].text == "Layer0 Entry 6"
        assert result[2].text == "Layer0 Entry 7"
        assert result[3].text == "Layer0 Entry 8"

    def test_layer2_with_indices_that_exist_in_both_layers(self, mock_scene):
        """
        Test case where indices exist in both layers but should still
        return from the correct layer (layered_history[0] for layer 2).
        """
        # Both layers have entries at indices 0-2, but with different content
        layer_0 = [
            create_layered_entry("CORRECT Layer0 Entry 0"),
            create_layered_entry("CORRECT Layer0 Entry 1"),
            create_layered_entry("CORRECT Layer0 Entry 2"),
        ]

        layer_1 = [
            create_layered_entry("WRONG Layer1 Entry 0"),
            create_layered_entry("WRONG Layer1 Entry 1"),
            create_layered_entry("WRONG Layer1 Entry 2"),
        ]

        scene = mock_scene(layered_history=[layer_0, layer_1])

        entry = HistoryEntry(
            text="Summary",
            ts="PT30M",
            index=0,
            layer=2,
            start=0,
            end=2,
        )

        result = collect_source_entries(scene, entry)

        # Should get "CORRECT" entries from layer_0, not "WRONG" from layer_1
        assert len(result) == 3
        assert all("CORRECT" in r.text for r in result)
        assert all("WRONG" not in r.text for r in result)
