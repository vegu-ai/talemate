"""
Tests for Scene.fix_time / Scene._fix_time.

fix_time recalculates timestamps across archived_history (and layered_history)
based on TimePassageMessage entries in scene.history.
"""

import types

import pytest

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
    """Build a minimal Scene-like namespace with the fix_time methods bound."""
    scene = types.SimpleNamespace(
        ts=ts,
        history=history,
        archived_history=archived_history,
        layered_history=layered_history or [],
    )
    return scene


def fix_time(scene):
    """Call Scene._fix_time on our namespace (skip the try/except wrapper)."""
    Scene._fix_time(scene)


# ---------------------------------------------------------------------------
# Tests: fix_time with archived_history only (current behaviour)
# ---------------------------------------------------------------------------


class TestFixTimeArchivedHistory:
    """Verify fix_time correctly recalculates archived_history timestamps."""

    def test_single_time_jump(self):
        """One time passage should set ts on subsequent archived entries."""
        scene = make_scene(
            history=[
                _msg("Hello"),          # 0
                _msg("Hi"),             # 1
                _time("PT2H"),          # 2 — 2 hours
                _msg("After time"),     # 3
                _msg("More"),           # 4
            ],
            archived_history=[
                # static entry (no start/end) — should be left alone
                {"text": "Background", "ts": "PT0S"},
                # summary of messages 0-1 (before time jump at idx 2)
                {"text": "Summary A", "start": 0, "end": 1, "ts": "WRONG"},
                # summary of messages 3-4 (after time jump at idx 2)
                {"text": "Summary B", "start": 3, "end": 4, "ts": "WRONG"},
            ],
        )

        fix_time(scene)

        # Static entry unchanged
        assert scene.archived_history[0]["ts"] == "PT0S"
        # Entry ending at idx 1: no time jump before idx 1, so inherits starting_time
        assert scene.archived_history[1]["ts"] == "PT0S"
        # Entry ending at idx 4: time jump at idx 2 (PT2H) is before idx 4
        assert scene.archived_history[2]["ts"] == "PT2H"
        # scene.ts should be the last cumulative time
        assert scene.ts == "PT2H"

    def test_multiple_time_jumps_cumulative(self):
        """Multiple time passages should accumulate correctly."""
        scene = make_scene(
            history=[
                _msg("A"),              # 0
                _time("PT2H"),          # 1 — 2 hours
                _msg("B"),              # 2
                _time("PT1H"),          # 3 — +1 hour = 3 hours total
                _msg("C"),              # 4
                _time("P1D"),           # 5 — +1 day = 1 day 3 hours total
                _msg("D"),              # 6
            ],
            archived_history=[
                {"text": "Before jumps", "start": 0, "end": 0, "ts": "WRONG"},
                {"text": "After 2h", "start": 2, "end": 2, "ts": "WRONG"},
                {"text": "After 3h", "start": 4, "end": 4, "ts": "WRONG"},
                {"text": "After 1d3h", "start": 6, "end": 6, "ts": "WRONG"},
            ],
        )

        fix_time(scene)

        # end=0: no jump before idx 0
        assert scene.archived_history[0]["ts"] == "PT0S"
        # end=2: jump at idx 1 (PT2H) is before idx 2
        assert scene.archived_history[1]["ts"] == "PT2H"
        # end=4: jumps at idx 1+3 cumulative = PT3H, both before idx 4
        assert scene.archived_history[2]["ts"] == "PT3H"
        # end=6: all jumps cumulative = P1DT3H
        assert scene.archived_history[3]["ts"] == "P1DT3H"
        assert scene.ts == "P1DT3H"

    def test_static_entries_used_as_starting_time(self):
        """Static entries with ts should set the starting baseline."""
        scene = make_scene(
            history=[
                _msg("A"),              # 0
                _time("PT1H"),          # 1 — +1h from baseline
                _msg("B"),              # 2
            ],
            archived_history=[
                # static entry sets baseline to P1D
                {"text": "Background", "ts": "P1D"},
                {"text": "After 1h", "start": 0, "end": 2, "ts": "WRONG"},
            ],
        )

        fix_time(scene)

        # Baseline is P1D from static entry, +1h = P1DT1H
        assert scene.archived_history[1]["ts"] == "P1DT1H"
        assert scene.ts == "P1DT1H"

    def test_no_time_jumps(self):
        """No TimePassageMessages should leave ts at starting_time."""
        scene = make_scene(
            history=[_msg("A"), _msg("B")],
            archived_history=[
                {"text": "Summary", "start": 0, "end": 1, "ts": "PT5H"},
            ],
        )

        fix_time(scene)

        # No time jumps, so ts stays at starting_time (PT0S default)
        assert scene.ts == "PT0S"

    def test_zero_duration_time_passage(self):
        """A zero-duration time passage should not change timestamps."""
        scene = make_scene(
            history=[
                _msg("A"),              # 0
                _time("PT0S"),          # 1 — zero
                _msg("B"),              # 2
                _time("PT3H"),          # 3 — 3 hours
                _msg("C"),              # 4
            ],
            archived_history=[
                {"text": "Before", "start": 0, "end": 0, "ts": "WRONG"},
                {"text": "Middle", "start": 2, "end": 2, "ts": "WRONG"},
                {"text": "After", "start": 4, "end": 4, "ts": "WRONG"},
            ],
        )

        fix_time(scene)

        assert scene.archived_history[0]["ts"] == "PT0S"
        # PT0S added = still PT0S (but as isodate normalises it may vary)
        assert scene.archived_history[1]["ts"] in ("PT0S", "P0D")
        assert scene.archived_history[2]["ts"] == "PT3H"
        assert scene.ts == "PT3H"


# ---------------------------------------------------------------------------
# Tests: fix_time does NOT update layered_history (current gap)
# ---------------------------------------------------------------------------


class TestFixTimeLayeredHistoryBasic:
    """Verify that fix_time updates both archived_history and layered_history."""

    def test_layered_history_updated(self):
        """
        After fix_time, both archived_history and layered_history
        timestamps should be updated from scene.history time passages.
        """
        scene = make_scene(
            history=[
                _msg("A"),              # 0
                _msg("B"),              # 1
                _time("PT2H"),          # 2
                _msg("C"),              # 3
                _msg("D"),              # 4
                _time("P1D"),           # 5
                _msg("E"),              # 6
                _msg("F"),              # 7
            ],
            archived_history=[
                {"text": "Summary 0-1", "start": 0, "end": 1, "ts": "STALE", "id": "a1"},
                {"text": "Summary 3-4", "start": 3, "end": 4, "ts": "STALE", "id": "a2"},
                {"text": "Summary 6-7", "start": 6, "end": 7, "ts": "STALE", "id": "a3"},
            ],
            layered_history=[
                # Layer 0: references archived_history indices
                [
                    {
                        "text": "Layer0 entry A",
                        "start": 0,
                        "end": 1,
                        "ts": "STALE",
                        "ts_start": "STALE",
                        "ts_end": "STALE",
                        "id": "l0a",
                    },
                    {
                        "text": "Layer0 entry B",
                        "start": 2,
                        "end": 2,
                        "ts": "STALE",
                        "ts_start": "STALE",
                        "ts_end": "STALE",
                        "id": "l0b",
                    },
                ],
            ],
        )

        fix_time(scene)

        # Archived history IS fixed
        assert scene.archived_history[0]["ts"] == "PT0S"
        assert scene.archived_history[1]["ts"] == "PT2H"
        assert scene.archived_history[2]["ts"] == "P1DT2H"

        # Layered history IS fixed — timestamps derived from archived_history
        # Layer 0 entry [0]: covers archived[0..1]
        #   ts = archived[0]["ts"] = PT0S
        #   ts_end = archived[1]["ts"] = PT2H
        assert scene.layered_history[0][0]["ts"] == "PT0S"
        assert scene.layered_history[0][0]["ts_start"] == "PT0S"
        assert scene.layered_history[0][0]["ts_end"] == "PT2H"
        # Layer 0 entry [1]: covers archived[2..2]
        assert scene.layered_history[0][1]["ts"] == "P1DT2H"
        assert scene.layered_history[0][1]["ts_start"] == "P1DT2H"
        assert scene.layered_history[0][1]["ts_end"] == "P1DT2H"


# ---------------------------------------------------------------------------
# Tests: fix_time SHOULD update layered_history (expected after fix)
# ---------------------------------------------------------------------------


class TestFixTimeLayeredHistory:
    """Verify fix_time correctly updates layered_history timestamps."""

    def test_single_layer_timestamps_fixed(self):
        """
        Layer 0 of layered_history references archived_history via start/end.
        After fix_time, its ts/ts_start/ts_end should reflect the updated
        archived_history timestamps.
        """
        scene = make_scene(
            history=[
                _msg("A"),              # 0
                _msg("B"),              # 1
                _time("PT2H"),          # 2
                _msg("C"),              # 3
                _msg("D"),              # 4
                _time("P1D"),           # 5
                _msg("E"),              # 6
                _msg("F"),              # 7
            ],
            archived_history=[
                {"text": "Summary 0-1", "start": 0, "end": 1, "ts": "STALE", "id": "a1"},
                {"text": "Summary 3-4", "start": 3, "end": 4, "ts": "STALE", "id": "a2"},
                {"text": "Summary 6-7", "start": 6, "end": 7, "ts": "STALE", "id": "a3"},
            ],
            layered_history=[
                # Layer 0: references archived_history[0..1] and archived_history[2]
                [
                    {
                        "text": "Layer0 summary of archived 0-1",
                        "start": 0,
                        "end": 1,
                        "ts": "STALE",
                        "ts_start": "STALE",
                        "ts_end": "STALE",
                        "id": "l0a",
                    },
                    {
                        "text": "Layer0 summary of archived 2",
                        "start": 2,
                        "end": 2,
                        "ts": "STALE",
                        "ts_start": "STALE",
                        "ts_end": "STALE",
                        "id": "l0b",
                    },
                ],
            ],
        )

        fix_time(scene)

        # Archived history is fixed:
        # a1 end=1: no jump before idx 1 → PT0S
        # a2 end=4: jump at idx 2 (PT2H) before idx 4 → PT2H
        # a3 end=7: jumps cumulative P1DT2H before idx 7 → P1DT2H
        assert scene.archived_history[0]["ts"] == "PT0S"
        assert scene.archived_history[1]["ts"] == "PT2H"
        assert scene.archived_history[2]["ts"] == "P1DT2H"

        # Layer 0 entry [0]: covers archived[0..1]
        #   ts = archived[0]["ts"] = PT0S
        #   ts_start = archived[0]["ts"] = PT0S (archived has no ts_start)
        #   ts_end = archived[1]["ts"] = PT2H
        assert scene.layered_history[0][0]["ts"] == "PT0S"
        assert scene.layered_history[0][0]["ts_start"] == "PT0S"
        assert scene.layered_history[0][0]["ts_end"] == "PT2H"

        # Layer 0 entry [1]: covers archived[2..2]
        #   ts = archived[2]["ts"] = P1DT2H
        #   ts_start = P1DT2H
        #   ts_end = P1DT2H
        assert scene.layered_history[0][1]["ts"] == "P1DT2H"
        assert scene.layered_history[0][1]["ts_start"] == "P1DT2H"
        assert scene.layered_history[0][1]["ts_end"] == "P1DT2H"

    def test_multi_layer_timestamps_cascade(self):
        """
        Layer 1 references layer 0, which references archived_history.
        All should be updated after fix_time.
        """
        scene = make_scene(
            history=[
                _msg("A"),              # 0
                _time("PT1H"),          # 1
                _msg("B"),              # 2
                _time("PT1H"),          # 3
                _msg("C"),              # 4
                _time("PT1H"),          # 5
                _msg("D"),              # 6
            ],
            archived_history=[
                {"text": "Sum 0", "start": 0, "end": 0, "ts": "STALE", "id": "a1"},
                {"text": "Sum 2", "start": 2, "end": 2, "ts": "STALE", "id": "a2"},
                {"text": "Sum 4", "start": 4, "end": 4, "ts": "STALE", "id": "a3"},
                {"text": "Sum 6", "start": 6, "end": 6, "ts": "STALE", "id": "a4"},
            ],
            layered_history=[
                # Layer 0: references archived_history
                [
                    {"text": "L0 A", "start": 0, "end": 1, "ts": "STALE",
                     "ts_start": "STALE", "ts_end": "STALE", "id": "l0a"},
                    {"text": "L0 B", "start": 2, "end": 3, "ts": "STALE",
                     "ts_start": "STALE", "ts_end": "STALE", "id": "l0b"},
                ],
                # Layer 1: references layered_history[0]
                [
                    {"text": "L1 A", "start": 0, "end": 1, "ts": "STALE",
                     "ts_start": "STALE", "ts_end": "STALE", "id": "l1a"},
                ],
            ],
        )

        fix_time(scene)

        # Archived: jumps at idx 1,3,5 → cumulative PT1H, PT2H, PT3H
        assert scene.archived_history[0]["ts"] == "PT0S"   # end=0, no jump before
        assert scene.archived_history[1]["ts"] == "PT1H"   # end=2, jump at 1
        assert scene.archived_history[2]["ts"] == "PT2H"   # end=4, jumps at 1,3
        assert scene.archived_history[3]["ts"] == "PT3H"   # end=6, jumps at 1,3,5

        # Layer 0 entry [0]: covers archived[0..1]
        assert scene.layered_history[0][0]["ts"] == "PT0S"
        assert scene.layered_history[0][0]["ts_start"] == "PT0S"
        assert scene.layered_history[0][0]["ts_end"] == "PT1H"

        # Layer 0 entry [1]: covers archived[2..3]
        assert scene.layered_history[0][1]["ts"] == "PT2H"
        assert scene.layered_history[0][1]["ts_start"] == "PT2H"
        assert scene.layered_history[0][1]["ts_end"] == "PT3H"

        # Layer 1 entry [0]: covers layered_history[0][0..1]
        #   ts_end = l0[1].ts_end = PT3H (l0[1] covers archived[2..3])
        assert scene.layered_history[1][0]["ts"] == "PT0S"
        assert scene.layered_history[1][0]["ts_start"] == "PT0S"
        assert scene.layered_history[1][0]["ts_end"] == "PT3H"

    def test_layered_entry_without_ts_start_ts_end(self):
        """
        If a layered entry has no ts_start/ts_end fields, fix_time should
        still set them based on the source layer.
        """
        scene = make_scene(
            history=[
                _msg("A"),              # 0
                _time("PT5H"),          # 1
                _msg("B"),              # 2
            ],
            archived_history=[
                {"text": "Sum 0", "start": 0, "end": 0, "ts": "STALE", "id": "a1"},
                {"text": "Sum 2", "start": 2, "end": 2, "ts": "STALE", "id": "a2"},
            ],
            layered_history=[
                [
                    {
                        "text": "L0 covers both",
                        "start": 0,
                        "end": 1,
                        "ts": "STALE",
                        "id": "l0a",
                        # no ts_start or ts_end
                    },
                ],
            ],
        )

        fix_time(scene)

        assert scene.layered_history[0][0]["ts"] == "PT0S"
        assert scene.layered_history[0][0]["ts_start"] == "PT0S"
        assert scene.layered_history[0][0]["ts_end"] == "PT5H"

    def test_empty_layered_history(self):
        """fix_time should not crash when layered_history is empty."""
        scene = make_scene(
            history=[_msg("A"), _time("PT1H"), _msg("B")],
            archived_history=[
                {"text": "Sum", "start": 0, "end": 2, "ts": "STALE"},
            ],
            layered_history=[],
        )

        fix_time(scene)

        assert scene.archived_history[0]["ts"] == "PT1H"
        assert scene.ts == "PT1H"
