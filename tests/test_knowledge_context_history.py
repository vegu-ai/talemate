"""
The perspective filter of the context history: spans the character missed
are dropped at every level and replaced by one gap line.
"""

from unittest.mock import patch

import pytest

import talemate.util as util
from conftest import MockScene, bootstrap_scene
from talemate.knowledge.schema import KnowledgeEdge
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    DirectorMessage,
    ReinforcementMessage,
)


def _chars(source):
    if isinstance(source, list):
        return sum(_chars(s) for s in source)
    return len(str(source))


@pytest.fixture(autouse=True)
def _count_tokens():
    with (
        patch.object(util, "count_tokens", side_effect=_chars),
        patch("talemate.tale_mate.count_tokens", side_effect=_chars),
        patch(
            "talemate.agents.summarize.context_history.count_tokens",
            side_effect=_chars,
        ),
    ):
        yield


@pytest.fixture
def summarizer():
    scene = MockScene()
    agents = bootstrap_scene(scene)
    conversation = agents["conversation"]
    conversation.actions["generation_override"].enabled = True
    conversation.actions["generation_override"].config["format"].value = "chat"
    summarizer = agents["summarizer"]
    summarizer.actions["manage_scene_history"].config["best_fit"].value = False
    return summarizer


def line(i, present):
    return CharacterMessage(message=f"L{i}", source="ai", present=present)


def make_scene(summarizer):
    scene = MockScene()
    both = ["Alice", "Bob"]
    scene.history = [
        line(0, both),
        line(1, both),
        line(2, ["Alice"]),
        line(3, ["Alice"]),
        line(4, both),
        line(5, both),
    ]
    scene.ts = 10000
    return scene


class TestDialogue:
    def test_missed_lines_become_one_gap(self, summarizer):
        scene = make_scene(summarizer)
        result = scene.context_history(budget=5000, perspective="Bob")
        assert result == ["L0", "L1", "(Bob was elsewhere for a while)", "L4", "L5"]

    def test_present_character_sees_everything(self, summarizer):
        scene = make_scene(summarizer)
        assert scene.context_history(budget=5000, perspective="Alice") == [
            "L0",
            "L1",
            "L2",
            "L3",
            "L4",
            "L5",
        ]

    def test_no_perspective_is_unchanged(self, summarizer):
        scene = make_scene(summarizer)
        assert scene.context_history(budget=5000) == [
            "L0",
            "L1",
            "L2",
            "L3",
            "L4",
            "L5",
        ]

    def test_unknown_presence_is_kept(self, summarizer):
        scene = make_scene(summarizer)
        scene.history[2].present = None
        result = scene.context_history(budget=5000, perspective="Bob")
        assert result == [
            "L0",
            "L1",
            "L2",
            "(Bob was elsewhere for a while)",
            "L4",
            "L5",
        ]

    def test_grant_edge_restores_a_line(self, summarizer):
        scene = make_scene(summarizer)
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Bob", target=str(scene.history[3].id), kind="grant"
            )
        ]
        result = scene.context_history(budget=5000, perspective="Bob")
        assert result == [
            "L0",
            "L1",
            "(Bob was elsewhere for a while)",
            "L3",
            "L4",
            "L5",
        ]

    def test_gap_at_the_tail(self, summarizer):
        scene = make_scene(summarizer)
        scene.history = scene.history[:4]
        result = scene.context_history(budget=5000, perspective="Bob")
        assert result == ["L0", "L1", "(Bob was elsewhere for a while)"]

    def test_exempt_message_types_are_never_filtered(self, summarizer):
        scene = make_scene(summarizer)
        scene.history = [
            line(0, ["Alice", "Bob"]),
            ReinforcementMessage(
                message="Bob's mood: tense", present=["Alice"], source="Bob's mood:Bob"
            ),
            ContextInvestigationMessage(
                message="The lamp room is empty.", present=["Alice"], source="narrator"
            ),
            DirectorMessage(
                message="Bob: be curt",
                present=["Alice"],
                source="director",
                meta={"character": "Bob", "action": "actor_instruction"},
            ),
            line(4, ["Alice", "Bob"]),
        ]
        result = scene.context_history(
            budget=5000,
            perspective="Bob",
            keep_director="Bob",
            include_reinforcements=True,
        )
        joined = "\n".join(result)
        assert "elsewhere" not in joined
        assert "tense" in joined and "lamp room" in joined

    def test_best_fit_dialogue_gap(self, summarizer):
        summarizer.actions["manage_scene_history"].config["best_fit"].value = True
        scene = make_scene(summarizer)
        result = scene.context_history(budget=5000, perspective="Bob")
        assert result == ["L0", "L1", "(Bob was elsewhere for a while)", "L4", "L5"]


def pad(label, n=60):
    return label + "." * (n - len(label))


def long_line(i, present, n=50):
    return CharacterMessage(message=pad(f"L{i}", n), source="ai", present=present)


class TestArchived:
    def _scene(self, summarizer):
        scene = MockScene()
        scene.history = [long_line(i, ["Alice", "Bob"]) for i in range(12)]
        scene.archived_history = [
            {
                "id": "a0",
                "text": pad("A0"),
                "ts": 100,
                "start": 0,
                "end": 2,
                "present": ["Alice", "Bob"],
            },
            {
                "id": "a1",
                "text": pad("A1"),
                "ts": 3700,
                "start": 3,
                "end": 5,
                "present": ["Alice"],
            },
            {
                "id": "a2",
                "text": pad("A2"),
                "ts": 7300,
                "start": 6,
                "end": 8,
                "present": ["Alice"],
            },
            {
                "id": "a3",
                "text": pad("A3"),
                "ts": 7400,
                "start": 9,
                "end": 9,
                "present": ["Alice", "Bob"],
            },
        ]
        scene.ts = 7400
        return scene

    def test_missed_entries_collapse_into_one_timed_gap(self, summarizer):
        scene = self._scene(summarizer)
        # dialogue budget 200 holds lines 8-11, so a3 is covered by dialogue and
        # a0..a2 are summaries; Bob missed a1 and a2
        result = scene.context_history(budget=400, perspective="Bob")
        joined = "\n".join(result)
        assert "A1" not in joined and "A2" not in joined
        assert "A0" in joined and "L8" in joined
        # gap = ts of the last missed entry (7300) - ts of the kept entry before it (100)
        assert "(bob was elsewhere for 2 hours)" in joined.lower()
        assert joined.index("A0") < joined.index("elsewhere") < joined.index("L8")

    def test_present_character_keeps_entries(self, summarizer):
        scene = self._scene(summarizer)
        joined = "\n".join(scene.context_history(budget=400, perspective="Alice"))
        assert "A1" in joined and "A2" in joined and "elsewhere" not in joined


class TestLayered:
    def _scene(self, summarizer):
        summarizer.actions["layered_history"].enabled = True
        scene = MockScene()
        scene.history = [long_line(i, ["Alice", "Bob"]) for i in range(24)]
        scene.archived_history = [
            {
                "id": f"a{i}",
                "text": pad(f"A{i}", 20),
                "ts": 100 * (i + 1),
                "start": i * 3,
                "end": i * 3 + 2,
                "present": ["Alice", "Bob"] if i in (0, 1, 4, 5) else ["Alice"],
            }
            for i in range(6)
        ]
        scene.layered_history = [
            [
                {
                    "id": "l0",
                    "text": pad("LA", 20),
                    "ts": 200,
                    "ts_start": 100,
                    "ts_end": 200,
                    "start": 0,
                    "end": 1,
                },
                {
                    "id": "l1",
                    "text": pad("LB", 20),
                    "ts": 400,
                    "ts_start": 300,
                    "ts_end": 400,
                    "start": 2,
                    "end": 3,
                },
                {
                    "id": "l2",
                    "text": pad("LC", 20),
                    "ts": 600,
                    "ts_start": 500,
                    "ts_end": 600,
                    "start": 4,
                    "end": 5,
                },
            ]
        ]
        scene.ts = 600
        return scene

    def test_missed_layer_entry_is_replaced_by_a_gap(self, summarizer):
        scene = self._scene(summarizer)
        # dialogue 300 (lines 18-23), archived 150 (a5 and a4), layer 150:
        # l2 is covered by the archived level, Bob missed both sources of l1
        joined = "\n".join(scene.context_history(budget=600, perspective="Bob"))
        assert "A5" in joined and "A4" in joined
        assert "LC" not in joined
        assert "LB" not in joined
        assert "LA" in joined
        assert "(Bob was elsewhere for" in joined

    def test_layer_entry_with_any_presence_is_kept(self, summarizer):
        scene = self._scene(summarizer)
        # Bob was present for a2 but not a3: the layer entry over both stays
        scene.archived_history[2]["present"] = ["Alice", "Bob"]
        result = scene.context_history(budget=600, perspective="Bob")
        joined = "\n".join(result)
        assert "LB" in joined
        assert "elsewhere" not in [part for part in result if "LB" in part][0]

    def test_gap_survives_a_budget_break_as_one_line(self, summarizer):
        scene = self._scene(summarizer)
        # the archived level breaks on the entry that would carry the gap
        result = scene.context_history(budget=600, perspective="Bob")
        gaps = [part for part in result if part.startswith("(Bob was elsewhere")]
        assert len(gaps) == 1, result
        assert "elsewhere" not in "".join(
            p for p in result if not p.startswith("(Bob was elsewhere")
        )


class TestBestFitSlots:
    def _level(self, summarizer, scene):
        from talemate.agents.summarize.context_history import (
            ContextHistoryMixin,
            ContextHistoryParams,
        )

        params = ContextHistoryParams(perspective="Bob", keep_director=False).bind(
            scene
        )
        return ContextHistoryMixin._best_fit_build_dialogue_level(
            scene, len(scene.history) - 1, params
        )

    def test_gap_sits_in_the_last_slot_of_a_run(self, summarizer):
        scene = MockScene()
        scene.history = [
            line(0, ["Alice", "Bob"]),
            line(1, ["Alice"]),
            line(2, ["Alice"]),
            line(3, ["Alice"]),
            line(4, ["Alice", "Bob"]),
        ]
        level = self._level(summarizer, scene)
        assert level.formatted == [
            "L0",
            "",
            "",
            "(Bob was elsewhere for a while)",
            "L4",
        ]
        assert level.tokens[1] == 0 and level.tokens[3] > 0

    def test_a_blank_slot_does_not_split_a_run(self, summarizer):
        scene = MockScene()
        scene.history = [
            line(0, ["Alice", "Bob"]),
            line(1, ["Alice"]),
            DirectorMessage(
                message="Bob: be curt",
                present=["Alice"],
                source="director",
                meta={"character": "Bob", "action": "actor_instruction"},
            ),
            line(3, ["Alice"]),
            line(4, ["Alice", "Bob"]),
        ]
        level = self._level(summarizer, scene)
        gaps = [f for f in level.formatted if f.startswith("(Bob was elsewhere")]
        assert len(gaps) == 1
        assert level.formatted == [
            "L0",
            "",
            "",
            "(Bob was elsewhere for a while)",
            "L4",
        ]
