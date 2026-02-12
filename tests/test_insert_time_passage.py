"""
Tests for insert_time_passage and delete_time_passage.

insert_time_passage inserts a TimePassageMessage into scene.history before the
source range of a summarized archived_history entry, shifts all affected
start/end indices, and calls fix_time to recalculate timestamps.

delete_time_passage removes a TimePassageMessage from scene.history, shifts
indices back down, and recalculates timestamps.
"""

import types
import pytest

from talemate.history import insert_time_passage, delete_time_passage
from talemate.scene_message import CharacterMessage, TimePassageMessage
from talemate.tale_mate import Scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(text: str) -> CharacterMessage:
    return CharacterMessage(message=text, source="ai")


def _time(ts: str) -> TimePassageMessage:
    return TimePassageMessage(ts=ts, message=f"{ts} later")


def make_scene(
    history: list,
    archived_history: list,
    layered_history: list | None = None,
    ts: str = "PT0S",
):
    """Build a minimal Scene-like namespace with fix_time bound."""
    scene = types.SimpleNamespace(
        ts=ts,
        history=history,
        archived_history=archived_history,
        layered_history=layered_history or [],
    )
    # Bind fix_time so insert_time_passage can call it
    scene.fix_time = lambda: Scene._fix_time(scene)
    return scene


# ---------------------------------------------------------------------------
# Tests: basic insertion
# ---------------------------------------------------------------------------


class TestInsertTimePassageBasic:
    """Verify basic insertion, index shifting, and timestamp recalculation."""

    def test_insert_before_middle_entry(self):
        """Insert a time passage before the second summarized entry."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _msg("C"),  # 2
                _msg("D"),  # 3
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 2-3", "start": 2, "end": 3, "ts": "PT0S", "id": "a2"},
            ],
        )

        tp = insert_time_passage(scene, archive_index=1, amount=2, unit="hours")

        # TimePassageMessage inserted at original start=2
        assert isinstance(scene.history[2], TimePassageMessage)
        assert tp.ts == "PT2H"

        # First entry: start=0 < insertion_index=2, end=1 < 2 => unchanged
        assert scene.archived_history[0]["start"] == 0
        assert scene.archived_history[0]["end"] == 1

        # Second entry: start=2 >= 2 => 3, end=3 >= 2 => 4
        assert scene.archived_history[1]["start"] == 3
        assert scene.archived_history[1]["end"] == 4

        # fix_time should set timestamp on second entry
        assert scene.archived_history[1]["ts"] == "PT2H"

    def test_insert_before_first_entry(self):
        """Insert before the very first summarized entry (start=0)."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _msg("C"),  # 2
                _msg("D"),  # 3
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 2-3", "start": 2, "end": 3, "ts": "PT0S", "id": "a2"},
            ],
        )

        insert_time_passage(scene, archive_index=0, amount=30, unit="minutes")

        # Inserted at index 0
        assert isinstance(scene.history[0], TimePassageMessage)
        assert len(scene.history) == 5

        # Both entries bumped
        assert scene.archived_history[0]["start"] == 1
        assert scene.archived_history[0]["end"] == 2
        assert scene.archived_history[1]["start"] == 3
        assert scene.archived_history[1]["end"] == 4

        # Time passage at index 0, both entries end > 0 => both get PT30M
        assert scene.archived_history[0]["ts"] == "PT30M"
        assert scene.archived_history[1]["ts"] == "PT30M"

    def test_insert_before_last_entry(self):
        """Insert before the last entry only shifts that entry's indices."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _msg("C"),  # 2
                _msg("D"),  # 3
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 2-3", "start": 2, "end": 3, "ts": "PT0S", "id": "a2"},
            ],
        )

        insert_time_passage(scene, archive_index=1, amount=1, unit="days")

        # First entry unchanged
        assert scene.archived_history[0]["start"] == 0
        assert scene.archived_history[0]["end"] == 1

        # Second entry shifted
        assert scene.archived_history[1]["start"] == 3
        assert scene.archived_history[1]["end"] == 4

    def test_history_length_increases(self):
        """Scene history should have one more element after insertion."""
        scene = make_scene(
            history=[_msg("A"), _msg("B")],
            archived_history=[
                {"text": "Sum", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
            ],
        )

        insert_time_passage(scene, archive_index=0, amount=1, unit="hours")

        assert len(scene.history) == 3


# ---------------------------------------------------------------------------
# Tests: validation
# ---------------------------------------------------------------------------


class TestInsertTimePassageValidation:
    """Verify error handling for invalid inputs."""

    def test_static_entry_raises(self):
        """Cannot insert time passage before a static (manual) entry."""
        scene = make_scene(
            history=[_msg("A")],
            archived_history=[
                {"text": "Static", "ts": "PT0S", "id": "s1"},
            ],
        )

        with pytest.raises(ValueError, match="not a summarized entry"):
            insert_time_passage(scene, archive_index=0, amount=1, unit="hours")

    def test_negative_index_raises(self):
        """Negative archive_index should raise IndexError."""
        scene = make_scene(
            history=[_msg("A")],
            archived_history=[
                {"text": "Sum", "start": 0, "end": 0, "ts": "PT0S", "id": "a1"},
            ],
        )

        with pytest.raises(IndexError):
            insert_time_passage(scene, archive_index=-1, amount=1, unit="hours")

    def test_out_of_bounds_index_raises(self):
        """archive_index beyond list length should raise IndexError."""
        scene = make_scene(
            history=[_msg("A")],
            archived_history=[
                {"text": "Sum", "start": 0, "end": 0, "ts": "PT0S", "id": "a1"},
            ],
        )

        with pytest.raises(IndexError):
            insert_time_passage(scene, archive_index=5, amount=1, unit="hours")


# ---------------------------------------------------------------------------
# Tests: interaction with existing time passages
# ---------------------------------------------------------------------------


class TestInsertTimePassageWithExisting:
    """Verify correct behaviour when time passages already exist."""

    def test_insert_alongside_existing_time_passage(self):
        """
        When scene.history already has TimePassageMessages, inserting a new one
        should produce correct cumulative timestamps.
        """
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _time("PT1H"),  # 2 — existing 1h passage
                _msg("C"),  # 3
                _msg("D"),  # 4
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 3-4", "start": 3, "end": 4, "ts": "PT1H", "id": "a2"},
            ],
        )

        # Insert 2h before the second entry (start=3)
        insert_time_passage(scene, archive_index=1, amount=2, unit="hours")

        # scene.history should now be:
        # [msg, msg, time(1h), time(2h), msg, msg]
        assert isinstance(scene.history[2], TimePassageMessage)
        assert scene.history[2].ts == "PT1H"  # original
        assert isinstance(scene.history[3], TimePassageMessage)
        assert scene.history[3].ts == "PT2H"  # newly inserted

        # Indices: existing time passage at idx 2 is < insertion_index=3, unaffected
        # Second entry: start 3->4, end 4->5
        assert scene.archived_history[1]["start"] == 4
        assert scene.archived_history[1]["end"] == 5

        # Cumulative: PT1H + PT2H = PT3H
        assert scene.archived_history[1]["ts"] == "PT3H"

    def test_insert_before_entry_that_precedes_existing_passage(self):
        """
        Insert before the first entry when a time passage exists after it.
        The new passage should come first in the cumulative chain.
        """
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _time("PT3H"),  # 2
                _msg("C"),  # 3
                _msg("D"),  # 4
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 3-4", "start": 3, "end": 4, "ts": "PT3H", "id": "a2"},
            ],
        )

        # Insert 30min before first entry
        insert_time_passage(scene, archive_index=0, amount=30, unit="minutes")

        # New passage at index 0, everything else shifted
        assert isinstance(scene.history[0], TimePassageMessage)
        assert scene.history[0].ts == "PT30M"

        # First entry: start 0->1, end 1->2
        assert scene.archived_history[0]["start"] == 1
        assert scene.archived_history[0]["end"] == 2

        # Second entry: start 3->4, end 4->5
        assert scene.archived_history[1]["start"] == 4
        assert scene.archived_history[1]["end"] == 5

        # Cumulative: PT30M (idx 0) + PT3H (idx 3) = PT3H30M
        assert scene.archived_history[1]["ts"] == "PT3H30M"


# ---------------------------------------------------------------------------
# Tests: layered history is not corrupted
# ---------------------------------------------------------------------------


class TestInsertTimePassageLayeredHistory:
    """Verify layered_history indices are untouched but timestamps update."""

    def test_layered_history_indices_unchanged(self):
        """
        Layered history references archived_history indices, not scene.history.
        Inserting into scene.history should not change layered start/end.
        """
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _msg("C"),  # 2
                _msg("D"),  # 3
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 2-3", "start": 2, "end": 3, "ts": "PT0S", "id": "a2"},
            ],
            layered_history=[
                [
                    {
                        "text": "L0 covers both",
                        "start": 0,
                        "end": 1,
                        "ts": "STALE",
                        "ts_start": "STALE",
                        "ts_end": "STALE",
                        "id": "l0a",
                    },
                ],
            ],
        )

        insert_time_passage(scene, archive_index=1, amount=2, unit="hours")

        # Layered history indices must remain the same
        assert scene.layered_history[0][0]["start"] == 0
        assert scene.layered_history[0][0]["end"] == 1

        # But timestamps should be updated via fix_time
        assert scene.layered_history[0][0]["ts"] == "PT0S"
        assert scene.layered_history[0][0]["ts_start"] == "PT0S"
        assert scene.layered_history[0][0]["ts_end"] == "PT2H"


# ---------------------------------------------------------------------------
# Tests: delete_time_passage
# ---------------------------------------------------------------------------


class TestDeleteTimePassageBasic:
    """Verify deletion, index shifting, and timestamp recalculation."""

    def test_delete_middle_time_passage(self):
        """Delete a time passage between two summarized entries."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _time("PT2H"),  # 2
                _msg("C"),  # 3
                _msg("D"),  # 4
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 3-4", "start": 3, "end": 4, "ts": "PT2H", "id": "a2"},
            ],
        )

        delete_time_passage(scene, history_index=2)

        # Time passage removed
        assert len(scene.history) == 4
        assert not isinstance(scene.history[2], TimePassageMessage)

        # First entry: start=0, end=1 — unchanged (both < 2)
        assert scene.archived_history[0]["start"] == 0
        assert scene.archived_history[0]["end"] == 1

        # Second entry: start=3->2, end=4->3 (both > 2)
        assert scene.archived_history[1]["start"] == 2
        assert scene.archived_history[1]["end"] == 3

        # No time passages left — fix_time returns early without updating
        # individual entry timestamps, but scene.ts is set to starting_time
        assert scene.ts == "PT0S"

    def test_delete_first_time_passage(self):
        """Delete a time passage at index 0."""
        scene = make_scene(
            history=[
                _time("PT1H"),  # 0
                _msg("A"),  # 1
                _msg("B"),  # 2
            ],
            archived_history=[
                {"text": "Sum 1-2", "start": 1, "end": 2, "ts": "PT1H", "id": "a1"},
            ],
        )

        delete_time_passage(scene, history_index=0)

        assert len(scene.history) == 2
        assert scene.archived_history[0]["start"] == 0
        assert scene.archived_history[0]["end"] == 1

    def test_delete_preserves_other_time_passages(self):
        """Delete one of multiple time passages; remaining should still work."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _time("PT1H"),  # 1
                _msg("B"),  # 2
                _time("PT2H"),  # 3
                _msg("C"),  # 4
            ],
            archived_history=[
                {"text": "Sum 0", "start": 0, "end": 0, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 2", "start": 2, "end": 2, "ts": "PT1H", "id": "a2"},
                {"text": "Sum 4", "start": 4, "end": 4, "ts": "PT3H", "id": "a3"},
            ],
        )

        # Delete the first time passage (index 1)
        delete_time_passage(scene, history_index=1)

        # History: [msg, msg, time(2h), msg]
        assert len(scene.history) == 4
        assert isinstance(scene.history[2], TimePassageMessage)
        assert scene.history[2].ts == "PT2H"

        # Indices shifted: entries after idx 1 decremented
        assert scene.archived_history[0]["start"] == 0
        assert scene.archived_history[0]["end"] == 0
        assert scene.archived_history[1]["start"] == 1
        assert scene.archived_history[1]["end"] == 1
        assert scene.archived_history[2]["start"] == 3
        assert scene.archived_history[2]["end"] == 3

        # Only PT2H remains, affects third entry
        assert scene.archived_history[2]["ts"] == "PT2H"


class TestDeleteTimePassageValidation:
    """Verify error handling for invalid deletion inputs."""

    def test_not_a_time_passage_raises(self):
        """Cannot delete a non-TimePassageMessage."""
        scene = make_scene(
            history=[_msg("A"), _msg("B")],
            archived_history=[
                {"text": "Sum", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
            ],
        )

        with pytest.raises(ValueError, match="not a TimePassageMessage"):
            delete_time_passage(scene, history_index=0)

    def test_out_of_bounds_raises(self):
        """Out-of-bounds history_index should raise IndexError."""
        scene = make_scene(
            history=[_msg("A")],
            archived_history=[],
        )

        with pytest.raises(IndexError):
            delete_time_passage(scene, history_index=5)

    def test_negative_index_raises(self):
        """Negative history_index should raise IndexError."""
        scene = make_scene(
            history=[_time("PT1H"), _msg("A")],
            archived_history=[],
        )

        with pytest.raises(IndexError):
            delete_time_passage(scene, history_index=-1)


class TestDeleteTimePassageRoundTrip:
    """Verify insert followed by delete restores original state."""

    def test_insert_then_delete_restores_indices(self):
        """Inserting and then deleting should restore original indices."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _msg("B"),  # 1
                _msg("C"),  # 2
                _msg("D"),  # 3
            ],
            archived_history=[
                {"text": "Sum 0-1", "start": 0, "end": 1, "ts": "PT0S", "id": "a1"},
                {"text": "Sum 2-3", "start": 2, "end": 3, "ts": "PT0S", "id": "a2"},
            ],
        )

        # Insert a 2h passage before second entry
        insert_time_passage(scene, archive_index=1, amount=2, unit="hours")

        # Now the time passage is at index 2
        assert isinstance(scene.history[2], TimePassageMessage)
        assert scene.archived_history[1]["start"] == 3
        assert scene.archived_history[1]["end"] == 4

        # Delete it
        delete_time_passage(scene, history_index=2)

        # Indices should be back to original
        assert len(scene.history) == 4
        assert scene.archived_history[0]["start"] == 0
        assert scene.archived_history[0]["end"] == 1
        assert scene.archived_history[1]["start"] == 2
        assert scene.archived_history[1]["end"] == 3
