import pytest

import talemate.history
import talemate.knowledge.listeners
from conftest import MockScene, bootstrap_scene
from talemate.history import shift_scene_timeline
from talemate.instance import get_agent
from talemate.knowledge.perspective_models import (
    Acquisition,
    Disclosure,
    PerspectiveView,
    SceneKnowledge,
    SourcePerspectives,
    content_digest,
)
from talemate.knowledge.schema import (
    KnowledgeEdge,
)
from talemate.scene_message import CharacterMessage, ReinforcementMessage
from talemate.tale_mate import Scene
from talemate.world_state import Reinforcement

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

    assert shift_scene_timeline(scene, 0) is None

    assert scene.ts == pre_state[0]
    assert scene.archived_history == pre_state[1]
    assert scene.layered_history == pre_state[2]


def test_shift_scene_timeline_moves_the_scene_start(scene_factory):
    scene = scene_factory(7200, archived=[{"ts": 0}])
    scene.start_ts = 3600

    assert shift_scene_timeline(scene, 1800) is None

    assert (scene.ts, scene.start_ts) == (9000, 5400)

    # clamped to zero like the entries
    shift_scene_timeline(scene, -6000)
    assert scene.start_ts == 0


# ---------------------------------------------------------------------------
# Perception stamps (#640)
# ---------------------------------------------------------------------------


def _perspectives(text: str, order: int, ts: int) -> SourcePerspectives:
    return SourcePerspectives(
        content_digest=content_digest(text),
        acquired=Acquisition(order=order, ts=ts),
        views=(PerspectiveView(audience=("Alice",), status="pending"),),
    )


@pytest.fixture()
def perception_scene(scene_factory):
    """A scene whose every kind of knowledge source carries an acquisition."""

    message = CharacterMessage(message="Alice: hello", source="ai")
    message.knowledge = _perspectives("Alice: hello", 2, 3600)
    passage = ReinforcementMessage(
        message="Alice is calm", question="mood", character_name="Alice"
    )
    passage.knowledge = _perspectives("Alice is calm", 3, 3000)

    scene = scene_factory(
        7200,
        archived=[
            {
                "id": "base-a",
                "text": "they met",
                "ts": 1800,
                "knowledge": _perspectives("they met", 4, 1800).model_dump(mode="json"),
            }
        ],
        layered=[
            [
                {
                    "id": "layer-a",
                    "text": "the meeting",
                    "ts": 1800,
                    "knowledge": _perspectives("the meeting", 5, 1800).model_dump(
                        mode="json"
                    ),
                }
            ]
        ],
    )
    scene.knowledge_eligibility = "perception"
    scene.start_ts = 1800
    scene.history = [message]
    scene.intro_knowledge = _perspectives("an opening", 1, 600)
    scene.world_state.reinforce = [
        Reinforcement(
            question="mood",
            character="Alice",
            insert="all-context",
            perspective_source=passage,
        )
    ]
    scene.knowledge = SceneKnowledge(
        last_order=6,
        disclosures=(
            Disclosure(
                id="d1",
                text="the war ended",
                audience=("Alice",),
                acquired=Acquisition(order=6, ts=5400),
                origin_scene_ts=4800,
                away_scene_ts=5000,
                message_id_boundary=0,
            ),
        ),
    )
    scene.world_state.knowledge = [
        KnowledgeEdge(id="e1", character="Alice", target="F1", ts=1200),
        KnowledgeEdge(id="e2", character="Alice", target="F2"),
    ]
    return scene


def _stamps(scene):
    sources = [scene.intro_knowledge.acquired.ts]
    sources.append(scene.history[0].knowledge.acquired.ts)
    sources.append(
        scene.world_state.reinforce[0].perspective_source.knowledge.acquired.ts
    )
    sources.append(scene.archived_history[0]["knowledge"]["acquired"]["ts"])
    sources.append(scene.layered_history[0][0]["knowledge"]["acquired"]["ts"])
    return sources


def _orders(scene):
    orders = [scene.intro_knowledge.acquired.order]
    orders.append(scene.history[0].knowledge.acquired.order)
    orders.append(
        scene.world_state.reinforce[0].perspective_source.knowledge.acquired.order
    )
    orders.append(scene.archived_history[0]["knowledge"]["acquired"]["order"])
    orders.append(scene.layered_history[0][0]["knowledge"]["acquired"]["order"])
    orders.append(scene.knowledge.disclosures[0].acquired.order)
    return orders


def test_shift_scene_timeline_moves_every_acquisition_stamp(perception_scene):
    scene = perception_scene
    orders = _orders(scene)

    assert shift_scene_timeline(scene, 1800) is None

    assert _stamps(scene) == [2400, 5400, 4800, 3600, 3600]
    disclosure = scene.knowledge.disclosures[0]
    assert (
        disclosure.acquired.ts,
        disclosure.origin_scene_ts,
        disclosure.away_scene_ts,
    ) == (7200, 6600, 6800)
    assert [edge.ts for edge in scene.world_state.knowledge] == [3000, None]
    # only the times move
    assert _orders(scene) == orders


def test_shift_scene_timeline_clamps_every_acquisition_stamp(perception_scene):
    scene = perception_scene

    shift_scene_timeline(scene, -9000)

    assert _stamps(scene) == [0, 0, 0, 0, 0]
    disclosure = scene.knowledge.disclosures[0]
    assert (
        disclosure.acquired.ts,
        disclosure.origin_scene_ts,
        disclosure.away_scene_ts,
    ) == (0, 0, 0)
    assert [edge.ts for edge in scene.world_state.knowledge] == [0, None]


def test_shift_scene_timeline_refreshes_the_knowledge_memory(
    perception_scene, monkeypatch
):
    scene = perception_scene
    invalidated = []
    monkeypatch.setattr(
        talemate.knowledge.listeners, "invalidate_memory_audiences", invalidated.append
    )

    shift_scene_timeline(scene, 600)

    assert invalidated == [scene]


def test_shift_scene_timeline_leaves_the_knowledge_memory_alone_without_a_shift(
    perception_scene, monkeypatch
):
    invalidated = []
    monkeypatch.setattr(
        talemate.knowledge.listeners, "invalidate_memory_audiences", invalidated.append
    )

    assert shift_scene_timeline(perception_scene, 0) is None

    assert invalidated == []


async def test_shift_scene_timeline_invalidates_the_audience_index_in_perception_mode():
    """A static entry's audience document takes its ts from the entry (#640)."""

    scene = MockScene()
    bootstrap_scene(scene)
    scene.knowledge_eligibility = "perception"
    scene.archived_history = [{"id": "base-a", "text": "they met", "ts": 1800}]
    memory = get_agent("memory")
    revision = memory._audience_state(scene).revision

    shift_scene_timeline(scene, 600)

    assert memory._audience_state(scene).revision > revision
