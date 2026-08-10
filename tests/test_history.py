import pytest

from talemate.history import shift_scene_timeline
from talemate.tale_mate import Scene

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def scene_factory():
    """Return a factory that builds a real `Scene` with the given timeline state.

    Uses real `Scene` (not a stand-in) so tests catch breakage if Scene's
    `ts`/`archived_history`/`layered_history` API changes.
    """

    def _factory(ts: int = 0, archived=None, layered=None):
        scene = Scene()
        scene.ts = ts
        scene.archived_history = archived or []
        scene.layered_history = layered or []
        return scene

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "initial_ts, archived_tss, layered_tss, shift, expected_scene_ts, expected_archived_ts, expected_layered_ts",
    [
        # Hours / minutes
        (
            7200,  # initial
            [3600, 5400],
            [1800],
            3600,  # +1 hour
            10800,
            [7200, 9000],
            [5400],
        ),
        (
            7200,
            [3600, 5400],
            [1800],
            -1800,  # -30 minutes
            5400,
            [1800, 3600],
            [0],  # clamped to zero
        ),
        # Months
        (
            5184000,
            [2592000, 15552000],
            [7776000],
            2592000,  # +1 month
            7776000,
            [5184000, 18144000],
            [10368000],
        ),
        # Years
        (
            94608000,
            [31536000, 63072000],
            [15552000],
            -31536000,  # -1 year
            63072000,
            [0, 31536000],
            [0],  # clamped to zero
        ),
        # Huge shift – 1000 years
        (
            0,
            [31536000],
            [63072000],
            31536000000,
            31536000000,
            [31567536000],
            [31599072000],
        ),
    ],
    ids=["hour_plus", "hour_minus", "month_plus", "year_minus", "millennia_plus"],
)
def test_shift_scene_timeline_basic(
    scene_factory,
    initial_ts,
    archived_tss,
    layered_tss,
    shift,
    expected_scene_ts,
    expected_archived_ts,
    expected_layered_ts,
):
    """Parametrised test verifying various time-unit shifts."""

    archived = [{"ts": ts} for ts in archived_tss]
    layered = [[{"ts": ts} for ts in layered_tss]]

    scene = scene_factory(initial_ts, archived, layered)

    shift_scene_timeline(scene, shift)

    assert scene.ts == expected_scene_ts
    assert [e["ts"] for e in scene.archived_history] == expected_archived_ts
    assert [e["ts"] for e in scene.layered_history[0]] == expected_layered_ts


def test_shift_scene_timeline_noop(scene_factory):
    """A shift of zero should not mutate the scene."""

    scene = scene_factory(
        0,
        archived=[{"ts": 3600, "ts_start": 1800, "ts_end": 5400}],
        layered=[[{"ts": 900}]],
    )

    import copy

    pre_state = (
        scene.ts,
        copy.deepcopy(scene.archived_history),
        copy.deepcopy(scene.layered_history),
    )

    shift_scene_timeline(scene, 0)

    assert scene.ts == pre_state[0]
    assert scene.archived_history == pre_state[1]
    assert scene.layered_history == pre_state[2]
