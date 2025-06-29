import pytest
import types

from talemate.history import shift_scene_timeline
from talemate.util import iso8601_add

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dummy_scene():
    """Return a minimal Scene-like object whose attributes can be adjusted by
    individual tests. The fixture yields a *factory* so each test can create
    its own independent instance without repeating boilerplate."""

    def _factory(ts: str = "PT0S", archived=None, layered=None):
        scene = types.SimpleNamespace()
        scene.ts = ts
        scene.archived_history = archived or []
        scene.layered_history = layered or []
        return scene

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "initial_ts, archived_tss, layered_tss, shift_iso, expected_scene_ts, expected_archived_ts, expected_layered_ts",
    [
        # Hours / minutes
        (
            "PT2H",  # initial
            ["PT1H", "PT90M"],
            ["PT30M"],
            "PT1H",  # +1 hour
            "PT3H",
            ["PT2H", "PT2H30M"],
            ["PT1H30M"],
        ),
        (
            "PT2H",
            ["PT1H", "PT90M"],
            ["PT30M"],
            "-PT30M",  # -30 minutes
            "PT1H30M",
            ["PT30M", "PT1H"],
            ["P0D"],  # zero becomes P0D
        ),
        # Months
        (
            "P2M",
            ["P1M", "P6M"],
            ["P3M"],
            "P1M",  # +1 month
            "P3M",
            ["P2M", "P7M"],
            ["P4M"],
        ),
        # Years
        (
            "P3Y",
            ["P1Y", "P2Y"],
            ["P6M"],
            "-P1Y",  # -1 year
            "P2Y",
            ["P0D", "P1Y"],
            ["P0D"],  # clamped to zero
        ),
        # Huge shift – 1000 years
        (
            "P0D",
            ["P1Y"],
            ["P2Y"],
            "P1000Y",
            "P1000Y",
            ["P1001Y"],
            ["P1002Y"],
        ),
    ],
    ids=[
        "hour_plus", "hour_minus", "month_plus", "year_minus", "millennia_plus"
    ],
)
def test_shift_scene_timeline_basic(
    dummy_scene,
    initial_ts,
    archived_tss,
    layered_tss,
    shift_iso,
    expected_scene_ts,
    expected_archived_ts,
    expected_layered_ts,
):
    """Parametrised test verifying various time-unit shifts."""

    archived = [{"ts": ts} for ts in archived_tss]
    layered = [[{"ts": ts} for ts in layered_tss]]

    scene = dummy_scene(initial_ts, archived, layered)

    shift_scene_timeline(scene, shift_iso)

    assert scene.ts == expected_scene_ts
    assert [e["ts"] for e in scene.archived_history] == expected_archived_ts
    assert [e["ts"] for e in scene.layered_history[0]] == expected_layered_ts


def test_shift_scene_timeline_noop(dummy_scene):
    """A shift of PT0S (and variants) should not mutate the scene."""

    scene = dummy_scene(
        "PT0S",
        archived=[{"ts": "PT1H", "ts_start": "PT30M", "ts_end": "PT90M"}],
        layered=[[{"ts": "PT15M"}]],
    )

    import copy
    pre_state = (
        scene.ts,
        copy.deepcopy(scene.archived_history),
        copy.deepcopy(scene.layered_history),
    )

    shift_scene_timeline(scene, "PT0S")

    assert scene.ts == pre_state[0]
    assert scene.archived_history == pre_state[1]
    assert scene.layered_history == pre_state[2] 