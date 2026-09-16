import pytest

from talemate.history import shift_scene_timeline
from talemate.knowledge.schema import Fact, FactRestatement
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

    assert shift_scene_timeline(scene, 0) == set()

    assert scene.ts == pre_state[0]
    assert scene.archived_history == pre_state[1]
    assert scene.layered_history == pre_state[2]


def test_shift_scene_timeline_moves_the_scene_start_and_the_facts(scene_factory):
    scene = scene_factory(7200, archived=[{"ts": 0}])
    scene.start_ts = 3600
    scene.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="bound",
            ts=3600,
            last_seen_ts=5400,
            restated_by=(FactRestatement(message_id=2, ts=5400),),
        ),
        "F2": Fact(id="F2", text="manual", ts=7000, last_seen_ts=7000),
        "F3": Fact(id="F3", text="no time"),
    }

    assert shift_scene_timeline(scene, 1800) == {"F1", "F2"}

    assert (scene.ts, scene.start_ts) == (9000, 5400)
    f1, f2, f3 = scene.world_state.facts.values()
    assert (f1.ts, f1.last_seen_ts, f1.restated_by[0].ts) == (5400, 7200, 7200)
    assert (f2.ts, f2.last_seen_ts) == (8800, 8800)
    assert (f3.ts, f3.last_seen_ts) == (None, None)

    # clamped to zero like the entries
    shift_scene_timeline(scene, -6000)
    assert (scene.start_ts, f1.ts, f1.last_seen_ts) == (0, 0, 1200)
