"""
Tests for Scene.fix_time / Scene._fix_time.

fix_time recalculates timestamps across archived_history (and layered_history)
based on TimePassageMessage entries in scene.history.
"""

from talemate.scene_message import CharacterMessage, TimePassageMessage
from talemate.tale_mate import Scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(text: str) -> CharacterMessage:
    return CharacterMessage(message=text, source="ai")


def _time(ts: int) -> TimePassageMessage:
    return TimePassageMessage(ts=ts, message=f"{ts} seconds later")


def make_scene(
    history: list,
    archived_history: list,
    layered_history: list | None = None,
    ts: int = 0,
):
    """Build a real `Scene` populated with the requested timeline state.

    Uses the production `Scene` class so changes to its `_fix_time`
    semantics surface here.
    """
    scene = Scene()
    scene.ts = ts
    scene.history = history
    scene.archived_history = archived_history
    scene.layered_history = layered_history or []
    return scene


def fix_time(scene: Scene):
    """Call Scene._fix_time directly to skip the try/except wrapper in fix_time."""
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
                _msg("Hello"),  # 0
                _msg("Hi"),  # 1
                _time(7200),  # 2 — 2 hours
                _msg("After time"),  # 3
                _msg("More"),  # 4
            ],
            archived_history=[
                # static entry (no start/end) — should be left alone
                {"text": "Background", "ts": 0},
                # summary of messages 0-1 (before time jump at idx 2)
                {"text": "Summary A", "start": 0, "end": 1, "ts": -1},
                # summary of messages 3-4 (after time jump at idx 2)
                {"text": "Summary B", "start": 3, "end": 4, "ts": -1},
            ],
        )

        fix_time(scene)

        # Static entry unchanged
        assert scene.archived_history[0]["ts"] == 0
        # Entry ending at idx 1: no time jump before idx 1, so inherits starting_time
        assert scene.archived_history[1]["ts"] == 0
        # Entry ending at idx 4: time jump at idx 2 (2h) is before idx 4
        assert scene.archived_history[2]["ts"] == 7200
        # scene.ts should be the last cumulative time
        assert scene.ts == 7200

    def test_multiple_time_jumps_cumulative(self):
        """Multiple time passages should accumulate correctly."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _time(7200),  # 1 — 2 hours
                _msg("B"),  # 2
                _time(3600),  # 3 — +1 hour = 3 hours total
                _msg("C"),  # 4
                _time(86400),  # 5 — +1 day = 1 day 3 hours total
                _msg("D"),  # 6
            ],
            archived_history=[
                {"text": "Before jumps", "start": 0, "end": 0, "ts": -1},
                {"text": "After 2h", "start": 2, "end": 2, "ts": -1},
                {"text": "After 3h", "start": 4, "end": 4, "ts": -1},
                {"text": "After 1d3h", "start": 6, "end": 6, "ts": -1},
            ],
        )

        fix_time(scene)

        # end=0: no jump before idx 0
        assert scene.archived_history[0]["ts"] == 0
        # end=2: jump at idx 1 (2h) is before idx 2
        assert scene.archived_history[1]["ts"] == 7200
        # end=4: jumps at idx 1+3 cumulative = 3h, both before idx 4
        assert scene.archived_history[2]["ts"] == 10800
        # end=6: all jumps cumulative = 1d 3h
        assert scene.archived_history[3]["ts"] == 97200
        assert scene.ts == 97200

    def test_scene_start_is_the_starting_time(self):
        """The scene start sets the baseline of the time passages."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _time(3600),  # 1 — +1h from baseline
                _msg("B"),  # 2
            ],
            archived_history=[
                {"text": "Background", "ts": 0},
                {"text": "After 1h", "start": 0, "end": 2, "ts": -1},
            ],
        )
        scene.start_ts = 86400

        fix_time(scene)

        # Baseline is the 1 day scene start, +1h = 1d 1h
        assert scene.archived_history[0]["ts"] == 0
        assert scene.archived_history[1]["ts"] == 90000
        assert scene.ts == 90000

    def test_static_entry_does_not_set_the_starting_time(self):
        """A second static entry added in a session is not the scene start."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _time(3600),  # 1
                _msg("B"),  # 2
            ],
            archived_history=[
                {"text": "Background", "ts": 0},
                {"text": "Later background", "ts": 43200},
                {"text": "After 1h", "start": 0, "end": 2, "ts": -1},
            ],
        )
        scene.start_ts = 86400

        fix_time(scene)

        assert scene.archived_history[1]["ts"] == 43200
        assert scene.archived_history[2]["ts"] == 90000
        assert scene.ts == 90000

    def test_no_time_jumps(self):
        """With no TimePassageMessage every summary is at the scene start."""
        scene = make_scene(
            history=[_msg("A"), _msg("B")],
            archived_history=[
                {"text": "Summary", "start": 0, "end": 1, "ts": 18000},
            ],
        )

        fix_time(scene)

        assert scene.archived_history[0]["ts"] == 0
        assert scene.ts == 0

    def test_last_passage_deleted_recomputes_the_entries(self):
        """Entries do not keep the time of a passage that no longer exists."""
        scene = make_scene(
            history=[_msg("A"), _msg("B"), _msg("C")],
            archived_history=[
                {"text": "Background", "ts": 0},
                {"text": "Summary A", "start": 0, "end": 0, "ts": 3600},
                {"text": "Summary B", "start": 1, "end": 2, "ts": 90000},
            ],
            layered_history=[
                [{"text": "Layer", "start": 1, "end": 2, "ts": 3600}],
            ],
        )
        scene.start_ts = 3600

        fix_time(scene)

        assert [e["ts"] for e in scene.archived_history] == [0, 3600, 3600]
        assert scene.layered_history[0][0]["ts_end"] == 3600
        assert scene.ts == 3600

    def test_zero_duration_time_passage(self):
        """A zero-duration time passage should not change timestamps."""
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _time(0),  # 1 — zero
                _msg("B"),  # 2
                _time(10800),  # 3 — 3 hours
                _msg("C"),  # 4
            ],
            archived_history=[
                {"text": "Before", "start": 0, "end": 0, "ts": -1},
                {"text": "Middle", "start": 2, "end": 2, "ts": -1},
                {"text": "After", "start": 4, "end": 4, "ts": -1},
            ],
        )

        fix_time(scene)

        assert scene.archived_history[0]["ts"] == 0
        # zero added = still zero
        assert scene.archived_history[1]["ts"] == 0
        assert scene.archived_history[2]["ts"] == 10800
        assert scene.ts == 10800


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
                _msg("A"),  # 0
                _msg("B"),  # 1
                _time(7200),  # 2
                _msg("C"),  # 3
                _msg("D"),  # 4
                _time(86400),  # 5
                _msg("E"),  # 6
                _msg("F"),  # 7
            ],
            archived_history=[
                {
                    "text": "Summary 0-1",
                    "start": 0,
                    "end": 1,
                    "ts": -1,
                    "id": "a1",
                },
                {
                    "text": "Summary 3-4",
                    "start": 3,
                    "end": 4,
                    "ts": -1,
                    "id": "a2",
                },
                {
                    "text": "Summary 6-7",
                    "start": 6,
                    "end": 7,
                    "ts": -1,
                    "id": "a3",
                },
            ],
            layered_history=[
                # Layer 0: references archived_history indices
                [
                    {
                        "text": "Layer0 entry A",
                        "start": 0,
                        "end": 1,
                        "ts": -1,
                        "ts_start": -1,
                        "ts_end": -1,
                        "id": "l0a",
                    },
                    {
                        "text": "Layer0 entry B",
                        "start": 2,
                        "end": 2,
                        "ts": -1,
                        "ts_start": -1,
                        "ts_end": -1,
                        "id": "l0b",
                    },
                ],
            ],
        )

        fix_time(scene)

        # Archived history IS fixed
        assert scene.archived_history[0]["ts"] == 0
        assert scene.archived_history[1]["ts"] == 7200
        assert scene.archived_history[2]["ts"] == 93600

        # Layered history IS fixed — timestamps derived from archived_history
        # Layer 0 entry [0]: covers archived[0..1]
        #   ts = archived[0]["ts"] = 0
        #   ts_end = archived[1]["ts"] = 2h
        assert scene.layered_history[0][0]["ts"] == 0
        assert scene.layered_history[0][0]["ts_start"] == 0
        assert scene.layered_history[0][0]["ts_end"] == 7200
        # Layer 0 entry [1]: covers archived[2..2]
        assert scene.layered_history[0][1]["ts"] == 93600
        assert scene.layered_history[0][1]["ts_start"] == 93600
        assert scene.layered_history[0][1]["ts_end"] == 93600


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
                _msg("A"),  # 0
                _msg("B"),  # 1
                _time(7200),  # 2
                _msg("C"),  # 3
                _msg("D"),  # 4
                _time(86400),  # 5
                _msg("E"),  # 6
                _msg("F"),  # 7
            ],
            archived_history=[
                {
                    "text": "Summary 0-1",
                    "start": 0,
                    "end": 1,
                    "ts": -1,
                    "id": "a1",
                },
                {
                    "text": "Summary 3-4",
                    "start": 3,
                    "end": 4,
                    "ts": -1,
                    "id": "a2",
                },
                {
                    "text": "Summary 6-7",
                    "start": 6,
                    "end": 7,
                    "ts": -1,
                    "id": "a3",
                },
            ],
            layered_history=[
                # Layer 0: references archived_history[0..1] and archived_history[2]
                [
                    {
                        "text": "Layer0 summary of archived 0-1",
                        "start": 0,
                        "end": 1,
                        "ts": -1,
                        "ts_start": -1,
                        "ts_end": -1,
                        "id": "l0a",
                    },
                    {
                        "text": "Layer0 summary of archived 2",
                        "start": 2,
                        "end": 2,
                        "ts": -1,
                        "ts_start": -1,
                        "ts_end": -1,
                        "id": "l0b",
                    },
                ],
            ],
        )

        fix_time(scene)

        # Archived history is fixed:
        # a1 end=1: no jump before idx 1 → 0
        # a2 end=4: jump at idx 2 (2h) before idx 4 → 2h
        # a3 end=7: jumps cumulative 1d 2h before idx 7 → 1d 2h
        assert scene.archived_history[0]["ts"] == 0
        assert scene.archived_history[1]["ts"] == 7200
        assert scene.archived_history[2]["ts"] == 93600

        # Layer 0 entry [0]: covers archived[0..1]
        #   ts = archived[0]["ts"] = 0
        #   ts_start = archived[0]["ts"] = 0 (archived has no ts_start)
        #   ts_end = archived[1]["ts"] = 2h
        assert scene.layered_history[0][0]["ts"] == 0
        assert scene.layered_history[0][0]["ts_start"] == 0
        assert scene.layered_history[0][0]["ts_end"] == 7200

        # Layer 0 entry [1]: covers archived[2..2]
        #   ts = archived[2]["ts"] = 1d 2h
        #   ts_start = 1d 2h
        #   ts_end = 1d 2h
        assert scene.layered_history[0][1]["ts"] == 93600
        assert scene.layered_history[0][1]["ts_start"] == 93600
        assert scene.layered_history[0][1]["ts_end"] == 93600

    def test_multi_layer_timestamps_cascade(self):
        """
        Layer 1 references layer 0, which references archived_history.
        All should be updated after fix_time.
        """
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _time(3600),  # 1
                _msg("B"),  # 2
                _time(3600),  # 3
                _msg("C"),  # 4
                _time(3600),  # 5
                _msg("D"),  # 6
            ],
            archived_history=[
                {"text": "Sum 0", "start": 0, "end": 0, "ts": -1, "id": "a1"},
                {"text": "Sum 2", "start": 2, "end": 2, "ts": -1, "id": "a2"},
                {"text": "Sum 4", "start": 4, "end": 4, "ts": -1, "id": "a3"},
                {"text": "Sum 6", "start": 6, "end": 6, "ts": -1, "id": "a4"},
            ],
            layered_history=[
                # Layer 0: references archived_history
                [
                    {
                        "text": "L0 A",
                        "start": 0,
                        "end": 1,
                        "ts": -1,
                        "ts_start": -1,
                        "ts_end": -1,
                        "id": "l0a",
                    },
                    {
                        "text": "L0 B",
                        "start": 2,
                        "end": 3,
                        "ts": -1,
                        "ts_start": -1,
                        "ts_end": -1,
                        "id": "l0b",
                    },
                ],
                # Layer 1: references layered_history[0]
                [
                    {
                        "text": "L1 A",
                        "start": 0,
                        "end": 1,
                        "ts": -1,
                        "ts_start": -1,
                        "ts_end": -1,
                        "id": "l1a",
                    },
                ],
            ],
        )

        fix_time(scene)

        # Archived: jumps at idx 1,3,5 → cumulative 1h, 2h, 3h
        assert scene.archived_history[0]["ts"] == 0  # end=0, no jump before
        assert scene.archived_history[1]["ts"] == 3600  # end=2, jump at 1
        assert scene.archived_history[2]["ts"] == 7200  # end=4, jumps at 1,3
        assert scene.archived_history[3]["ts"] == 10800  # end=6, jumps at 1,3,5

        # Layer 0 entry [0]: covers archived[0..1]
        assert scene.layered_history[0][0]["ts"] == 0
        assert scene.layered_history[0][0]["ts_start"] == 0
        assert scene.layered_history[0][0]["ts_end"] == 3600

        # Layer 0 entry [1]: covers archived[2..3]
        assert scene.layered_history[0][1]["ts"] == 7200
        assert scene.layered_history[0][1]["ts_start"] == 7200
        assert scene.layered_history[0][1]["ts_end"] == 10800

        # Layer 1 entry [0]: covers layered_history[0][0..1]
        #   ts_end = l0[1].ts_end = 3h (l0[1] covers archived[2..3])
        assert scene.layered_history[1][0]["ts"] == 0
        assert scene.layered_history[1][0]["ts_start"] == 0
        assert scene.layered_history[1][0]["ts_end"] == 10800

    def test_layered_entry_without_ts_start_ts_end(self):
        """
        If a layered entry has no ts_start/ts_end fields, fix_time should
        still set them based on the source layer.
        """
        scene = make_scene(
            history=[
                _msg("A"),  # 0
                _time(18000),  # 1
                _msg("B"),  # 2
            ],
            archived_history=[
                {"text": "Sum 0", "start": 0, "end": 0, "ts": -1, "id": "a1"},
                {"text": "Sum 2", "start": 2, "end": 2, "ts": -1, "id": "a2"},
            ],
            layered_history=[
                [
                    {
                        "text": "L0 covers both",
                        "start": 0,
                        "end": 1,
                        "ts": -1,
                        "id": "l0a",
                        # no ts_start or ts_end
                    },
                ],
            ],
        )

        fix_time(scene)

        assert scene.layered_history[0][0]["ts"] == 0
        assert scene.layered_history[0][0]["ts_start"] == 0
        assert scene.layered_history[0][0]["ts_end"] == 18000

    def test_empty_layered_history(self):
        """fix_time should not crash when layered_history is empty."""
        scene = make_scene(
            history=[_msg("A"), _time(3600), _msg("B")],
            archived_history=[
                {"text": "Sum", "start": 0, "end": 2, "ts": -1},
            ],
            layered_history=[],
        )

        fix_time(scene)

        assert scene.archived_history[0]["ts"] == 3600
        assert scene.ts == 3600
