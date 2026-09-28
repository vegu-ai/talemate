from unittest.mock import AsyncMock

import pytest

from talemate.agents.summarize.context_history import ContextHistoryParams
from talemate.character import Character
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.history_selection import HistorySelectionPolicy
from talemate.knowledge.perspectives import (
    add_disclosure,
    set_source_perspectives,
    source_reference,
)
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, NarratorMessage


def _publish(scene, message, *, bob=True, text=None):
    views = [{"audience": ["Alice"], "status": "ready", "text": str(message)}]
    if bob:
        views.append(
            {"audience": ["Bob"], "status": "ready", "text": text or str(message)}
        )
    set_source_perspectives(scene, "message", message.id, views)


def _summary(
    scene, identity, text, start, end, sources, *, layer=0, audience=("Alice", "Bob")
):
    entry = {
        "id": identity,
        "text": text,
        "start": start,
        "end": end,
        "ts": 0,
        "ts_start": 0,
        "ts_end": 0,
    }
    target = scene.archived_history if layer == 0 else scene.layered_history[layer - 1]
    target.append(entry)
    set_source_perspectives(
        scene,
        "summary",
        identity,
        [
            {
                "audience": list(audience),
                "status": "ready",
                "text": text,
                "sources": sources,
            }
        ],
        layer=layer,
    )
    return source_reference(scene, "summary", identity, layer=layer)


@pytest.fixture
def perspective_history_scene(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {
        name: Character(name=name, is_player=name == "Alice")
        for name in ("Alice", "Bob")
    }
    scene.active_characters = ["Alice", "Bob"]
    scene.intro = ""
    scene.history = [NarratorMessage(message=f"M{i}") for i in range(12)]
    for message in scene.history:
        message.present = ["Alice", "Bob"]
        _publish(scene, message)
    scene.archived_history = []
    scene.layered_history = [[]]
    summarizer = get_agent("summarizer")
    summarizer.actions["layered_history"].enabled = True
    monkeypatch.setattr(
        Prompt,
        "request",
        AsyncMock(side_effect=AssertionError("history selection requested an LLM")),
    )
    return scene


@pytest.fixture
def fixed_costs(monkeypatch):
    import talemate.knowledge.history_selection as selection

    costs = {}

    def tokens(value):
        return sum(cost for marker, cost in costs.items() if marker in str(value))

    monkeypatch.setattr(selection, "count_tokens", tokens)
    return costs


def _policy(**overrides):
    values = {
        "best_fit": True,
        "min_dialogue": 3,
        "max_dialogue": 250,
        "dialogue_ratio": 50,
        "summary_detail_ratio": 50,
        "enforce_boundary": False,
        "layered_history_available": True,
        "assured_dialogue_num": 0,
        "summary_boundary": 8,
    }
    values.update(overrides)
    return HistorySelectionPolicy(**values)


def _project(scene, budget, policy, **kwargs):
    from talemate.knowledge.context import project_character_history

    result = []
    history = project_character_history(
        scene,
        "Bob",
        budget=budget,
        policy=policy,
        selection_result=result,
        **kwargs,
    )
    return history, result[0]


def test_best_fit_minimum_crosses_summary_boundary_and_counts_ids(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    for message in scene.history:
        _publish(scene, message, text="SAME")
    _summary(
        scene,
        "BASE",
        "BASE",
        0,
        10,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:11]
        ],
    )
    fixed_costs.update(SAME=10, BASE=5)

    history, result = _project(
        scene,
        40,
        _policy(min_dialogue=10, max_dialogue=10, summary_boundary=10),
    )

    assert [line.message_id for line in history] == [
        message.id for message in scene.history[2:]
    ]
    assert result.raw_message_count == 10
    assert result.overflow_tokens == 60
    assert "BASE" not in history
    Prompt.request.assert_not_awaited()


def test_best_fit_minimum_skips_absent_views(perspective_history_scene, fixed_costs):
    scene = perspective_history_scene
    absent = scene.history[9]
    _publish(scene, absent, bob=False)
    _summary(
        scene,
        "BASE",
        "BASE",
        0,
        10,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:11]
        ],
    )
    fixed_costs.update(M=10, BASE=5)

    history, result = _project(
        scene,
        30,
        _policy(min_dialogue=3, max_dialogue=3, summary_boundary=10),
    )

    assert [line.message_id for line in history] == [
        scene.history[8].id,
        scene.history[10].id,
        scene.history[11].id,
    ]
    assert absent.id not in {
        message_id
        for entry in result.entries
        for message_id in entry.covered_message_ids
    }


def test_best_fit_and_ratio_choose_exact_different_levels(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, B=10, L=5)
    bases = []
    for index, (start, end) in enumerate(((0, 2), (3, 5), (6, 8))):
        bases.append(
            _summary(
                scene,
                f"B{index}",
                f"B{index}",
                start,
                end,
                [
                    source_reference(scene, "message", message.id)
                    for message in scene.history[start : end + 1]
                ],
            )
        )
    _summary(scene, "L01", "L01", 0, 1, bases[:2], layer=1)

    best_fit, _ = _project(scene, 50, _policy())
    ratio, ratio_result = _project(
        scene,
        50,
        _policy(best_fit=False, dialogue_ratio=40, summary_detail_ratio=50),
    )
    detailed_ratio, _ = _project(
        scene,
        50,
        _policy(best_fit=False, dialogue_ratio=40, summary_detail_ratio=90),
    )

    assert [str(line).strip() for line in best_fit] == [
        "L01",
        "B2",
        "M9",
        "M10",
        "M11",
    ]
    assert [str(line).strip() for line in ratio] == [
        "L01",
        "B2",
        "M10",
        "M11",
    ]
    assert [str(line).strip() for line in detailed_ratio] == [
        "B1",
        "B2",
        "M10",
        "M11",
    ]
    assert ratio_result.allocations == {
        "dialogue": 20,
        "archived": 15,
        "layer_0": 15,
    }


def test_effective_max_never_defeats_minimum(perspective_history_scene, fixed_costs):
    fixed_costs.update(M=10)
    history, result = _project(
        perspective_history_scene,
        20,
        _policy(min_dialogue=4, max_dialogue=1, summary_boundary=10),
    )
    assert len(history) == result.raw_message_count == 4
    assert result.policy.effective_max_dialogue == 4


def test_preview_and_production_share_policy_result(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, B=10)
    _summary(
        scene,
        "B0",
        "B0",
        0,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:9]
        ],
    )
    summarizer = get_agent("summarizer")
    params = ContextHistoryParams(stored_views=True, perspective="Bob")
    for name, value in {
        "max_budget": 40,
        "best_fit": True,
        "best_fit_min_dialogue": 3,
        "best_fit_max_dialogue": 3,
    }.items():
        summarizer.actions["manage_scene_history"].config[name].value = value

    production = scene.context_history(budget=40, stored_views=True, perspective="Bob")
    preview = summarizer.context_history_preview(scene, budget=40, params=params)
    preview_lines = [
        text for section in preview["sections"] for text in section["entries"]
    ]

    assert preview_lines == production
    assert preview["summary"]["dialogue_messages"] == 3
    assert preview["budget"]["used"] == 40
    Prompt.request.assert_not_awaited()


def test_prefix_excludes_cross_boundary_summary_and_future_sources(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, B=5)
    _summary(
        scene,
        "B0",
        "B0",
        0,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:9]
        ],
    )

    history, result = _project(
        scene,
        100,
        _policy(min_dialogue=0, max_dialogue=20),
        before_message_id=scene.history[5].id,
    )

    assert all(
        line.message_id in {message.id for message in scene.history[:5]}
        for line in history
    )
    assert "B0" not in history
    assert result.raw_message_count == 5


def test_pending_outside_selected_budget_does_not_block(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10)
    set_source_perspectives(
        scene,
        "message",
        scene.history[8].id,
        [{"audience": ["Bob"], "status": "pending"}],
    )

    history, _ = _project(
        scene,
        30,
        _policy(min_dialogue=3, max_dialogue=3, summary_boundary=8),
    )

    assert [line.message_id for line in history] == [
        message.id for message in scene.history[9:]
    ]


def test_pending_inside_minimum_reports_passage(perspective_history_scene, fixed_costs):
    scene = perspective_history_scene
    fixed_costs.update(M=10)
    pending = scene.history[10]
    set_source_perspectives(
        scene,
        "message",
        pending.id,
        [{"audience": ["Bob"], "status": "pending"}],
    )

    with pytest.raises(GenerationCancelled, match="not run yet") as raised:
        _project(
            scene,
            30,
            _policy(min_dialogue=3, max_dialogue=3, summary_boundary=10),
        )

    assert raised.value.message_id == pending.id


def test_maximum_applies_to_best_fit_expansion(perspective_history_scene, fixed_costs):
    scene = perspective_history_scene
    fixed_costs.update(M=5, B=5)
    _summary(
        scene,
        "B0",
        "B0",
        0,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:9]
        ],
    )

    history, result = _project(
        scene,
        100,
        _policy(min_dialogue=3, max_dialogue=4, summary_boundary=8),
    )

    assert [str(line).strip() for line in history] == ["B0", "M9", "M10", "M11"]
    assert result.raw_message_count == 3


def test_disclosure_costs_budget_without_satisfying_minimum(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, Established=7)
    disclosure = add_disclosure(scene, "Bob knows the bell code.", ["Bob"])

    history, result = _project(
        scene,
        37,
        _policy(min_dialogue=3, max_dialogue=3, summary_boundary=8),
    )

    assert [line.message_id for line in history[:3]] == [
        message.id for message in scene.history[9:]
    ]
    assert disclosure.text in history[-1]
    assert result.raw_message_count == 3
    assert result.total_tokens == 37


@pytest.mark.parametrize("budget", [0, 1])
def test_unmet_floor_does_not_overflow_for_disclosure_or_direction(
    perspective_history_scene, fixed_costs, budget
):
    scene = perspective_history_scene
    for message in scene.history:
        _publish(scene, message, bob=False)
    scene.history.append(
        DirectorMessage(
            message="GUIDANCE",
            meta={"character": "Bob"},
        )
    )
    disclosure = add_disclosure(scene, "Bob knows an optional code.", ["Bob"])
    fixed_costs.update(GUIDANCE=5, Established=7)

    history, result = _project(
        scene,
        budget,
        _policy(min_dialogue=5, max_dialogue=5, summary_boundary=10),
        keep_director=True,
    )

    assert history == []
    assert result.raw_message_count == 0
    assert result.total_tokens == result.overflow_tokens == 0
    assert all(
        disclosure.id not in entry.covered_disclosure_ids for entry in result.entries
    )


def test_only_eligible_raw_floor_entries_may_overflow_budget(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    for message in scene.history[:10]:
        _publish(scene, message, bob=False)
    scene.history.append(
        DirectorMessage(
            message="GUIDANCE",
            meta={"character": "Bob"},
        )
    )
    disclosure = add_disclosure(scene, "Bob knows an optional code.", ["Bob"])
    fixed_costs.update(M=10, GUIDANCE=5, Established=7)

    history, result = _project(
        scene,
        0,
        _policy(min_dialogue=5, max_dialogue=5, summary_boundary=10),
        keep_director=True,
    )

    assert [line.message_id for line in history] == [
        message.id for message in scene.history[10:12]
    ]
    assert result.raw_message_count == 2
    assert result.total_tokens == result.overflow_tokens == 20
    assert "GUIDANCE" not in history
    assert all(
        disclosure.id not in entry.covered_disclosure_ids for entry in result.entries
    )


def test_ready_static_archive_view_is_retained(perspective_history_scene, fixed_costs):
    scene = perspective_history_scene
    fixed_costs.update(M=10, STATIC=5)
    scene.archived_history.append({"id": "static", "text": "READER STATIC", "ts": 0})
    set_source_perspectives(
        scene,
        "summary",
        "static",
        [{"audience": ["Bob"], "status": "ready", "text": "STATIC"}],
    )

    history, _ = _project(
        scene,
        35,
        _policy(min_dialogue=3, max_dialogue=3, summary_boundary=8),
    )

    assert [str(line).strip() for line in history] == [
        "STATIC",
        "M9",
        "M10",
        "M11",
    ]


@pytest.mark.parametrize("message_count", [0, 2])
def test_static_archive_survives_all_raw_fast_path_and_larger_budget(
    perspective_history_scene, fixed_costs, message_count
):
    scene = perspective_history_scene
    scene.history = scene.history[:message_count]
    fixed_costs.update(M=10, STATIC=5)
    scene.archived_history.append({"id": "static", "text": "READER STATIC", "ts": 0})
    set_source_perspectives(
        scene,
        "summary",
        "static",
        [{"audience": ["Bob"], "status": "ready", "text": "STATIC"}],
    )
    policy = _policy(
        min_dialogue=0,
        max_dialogue=12,
        summary_boundary=0,
    )

    smaller, _ = _project(scene, 5 + message_count * 10, policy)
    larger, result = _project(scene, 100, policy)

    assert "STATIC" in smaller
    assert "STATIC" in larger
    assert result.raw_message_count == message_count


def test_incomplete_summary_descends_without_reader_fallback(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=5, UNSAFE=1)
    _summary(
        scene,
        "unsafe",
        "UNSAFE-READER-SUMMARY",
        0,
        8,
        [
            source_reference(scene, "message", message.id)
            for index, message in enumerate(scene.history[:9])
            if index != 4
        ],
    )

    history, result = _project(
        scene,
        100,
        _policy(min_dialogue=3, max_dialogue=12, summary_boundary=8),
    )

    assert "UNSAFE-READER-SUMMARY" not in history
    assert scene.history[4].id in {
        message_id
        for entry in result.entries
        for message_id in entry.covered_message_ids
    }


def test_hidden_source_prevents_summary_substitution(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    hidden = scene.history[4]
    hidden.hide()
    fixed_costs.update(M=5, SUMMARY=1)
    _summary(
        scene,
        "summary",
        "SUMMARY",
        0,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:9]
        ],
    )

    history, result = _project(
        scene,
        100,
        _policy(min_dialogue=3, max_dialogue=12, summary_boundary=8),
    )

    assert "SUMMARY" not in history
    assert hidden.id not in {
        message_id
        for entry in result.entries
        for message_id in entry.covered_message_ids
    }


def test_summary_covers_disclosure_exactly_once(perspective_history_scene, fixed_costs):
    scene = perspective_history_scene
    disclosure = add_disclosure(
        scene,
        "Bob knows the mid-scene code.",
        ["Bob"],
        message_id_boundary=scene.history[4].id,
    )
    fixed_costs.update(M=10, OLDER=5, Established=7)
    sources = [
        source_reference(scene, "message", message.id) for message in scene.history[:9]
    ]
    sources.append(source_reference(scene, "disclosure", disclosure.id))
    _summary(scene, "summary", "OLDER", 0, 8, sources, audience=("Bob",))

    history, result = _project(
        scene,
        35,
        _policy(min_dialogue=3, max_dialogue=3, summary_boundary=8),
    )

    assert [str(line).strip() for line in history] == [
        "OLDER",
        "M9",
        "M10",
        "M11",
    ]
    assert (
        sum(disclosure.id in entry.covered_disclosure_ids for entry in result.entries)
        == 1
    )


@pytest.mark.parametrize("best_fit", [True, False])
def test_disclosure_after_summary_end_is_preserved(
    perspective_history_scene, fixed_costs, best_fit
):
    scene = perspective_history_scene
    disclosure = add_disclosure(
        scene,
        "Bob learns the boundary code.",
        ["Bob"],
        message_id_boundary=scene.history[8].id,
    )
    fixed_costs.update(M=10, BASE=5, Established=7)
    _summary(
        scene,
        "base",
        "BASE",
        0,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:9]
        ],
    )

    history, result = _project(
        scene,
        100,
        _policy(
            best_fit=best_fit,
            min_dialogue=3,
            max_dialogue=3,
            dialogue_ratio=30,
            summary_boundary=8,
        ),
    )

    assert [entry.type for entry in result.entries] == [
        "archived",
        "disclosure",
        "dialogue",
        "dialogue",
        "dialogue",
    ]
    assert sum(disclosure.text in str(part) for part in history) == 1
    assert disclosure.id in result.entries[1].covered_disclosure_ids


@pytest.mark.parametrize("best_fit", [True, False])
def test_summary_start_disclosure_is_not_duplicated(
    perspective_history_scene, fixed_costs, best_fit
):
    scene = perspective_history_scene
    disclosure = add_disclosure(
        scene,
        "Bob knows the newer summary code.",
        ["Bob"],
        message_id_boundary=scene.history[2].id,
    )
    fixed_costs.update(M=10, OLD=5, RECENT=5, Established=7)
    _summary(
        scene,
        "old",
        "OLD",
        0,
        2,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:3]
        ],
    )
    recent_sources = [
        source_reference(scene, "message", message.id) for message in scene.history[3:9]
    ]
    recent_sources.append(source_reference(scene, "disclosure", disclosure.id))
    _summary(
        scene,
        "recent",
        "RECENT",
        3,
        8,
        recent_sources,
        audience=("Bob",),
    )

    _, result = _project(
        scene,
        100,
        _policy(
            best_fit=best_fit,
            min_dialogue=3,
            max_dialogue=3,
            dialogue_ratio=30,
            summary_boundary=8,
        ),
    )

    assert (
        sum(disclosure.id in entry.covered_disclosure_ids for entry in result.entries)
        == 1
    )
    assert all(entry.type != "disclosure" for entry in result.entries)


def test_disclosure_survives_raw_suffix_cut_through_summary(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    disclosure = add_disclosure(
        scene,
        "Bob learns a code inside the raw suffix.",
        ["Bob"],
        message_id_boundary=scene.history[8].id,
    )
    fixed_costs.update(M=10, BASE=5, Established=7)
    _summary(
        scene,
        "base",
        "BASE",
        0,
        10,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:11]
        ],
    )

    history, result = _project(
        scene,
        100,
        _policy(min_dialogue=5, max_dialogue=5, summary_boundary=10),
    )

    assert "BASE" not in history
    assert result.raw_message_count == 5
    assert sum(disclosure.text in str(part) for part in history) == 1


def test_external_summary_boundary_disclosure_does_not_block_expansion(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, BASE=1, LAYER=1, Established=5)
    bases = []
    for index, (start, end) in enumerate(((0, 2), (3, 5), (6, 8))):
        bases.append(
            _summary(
                scene,
                f"base-{index}",
                f"BASE-{index}",
                start,
                end,
                [
                    source_reference(scene, "message", message.id)
                    for message in scene.history[start : end + 1]
                ],
            )
        )
    _summary(scene, "layer", "LAYER", 0, 2, bases, layer=1)
    disclosure = add_disclosure(
        scene,
        "Bob learns an external boundary fact.",
        ["Bob"],
        message_id_boundary=scene.history[8].id,
    )

    _, result = _project(
        scene,
        1000,
        _policy(
            min_dialogue=3,
            max_dialogue=12,
            summary_boundary=8,
            layered_history_available=True,
        ),
    )

    assert result.raw_message_count == 12
    assert [
        entry.message_id for entry in result.entries if entry.message_id is not None
    ] == [message.id for message in scene.history]
    disclosure_index = next(
        index
        for index, entry in enumerate(result.entries)
        if disclosure.id in entry.covered_disclosure_ids
    )
    assert result.entries[disclosure_index - 1].message_id == scene.history[8].id
    assert result.entries[disclosure_index + 1].message_id == scene.history[9].id


@pytest.mark.parametrize("include_layer", [False, True], ids=("base", "layer"))
@pytest.mark.parametrize(
    "position",
    [
        pytest.param(3, id="first-base-start"),
        pytest.param(4, id="base-interior"),
        pytest.param(5, id="base-end"),
        pytest.param(6, id="second-base-start"),
        pytest.param(8, id="second-base-end"),
        pytest.param(9, id="external-end-boundary"),
    ],
)
def test_disclosure_interval_boundaries_allow_ample_best_fit_expansion(
    perspective_history_scene, fixed_costs, include_layer, position
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, BASE=1, LAYER=1, Established=5)
    disclosure = add_disclosure(
        scene,
        f"Bob learns a fact at position {position}.",
        ["Bob"],
        message_id_boundary=scene.history[position - 1].id,
    )
    bases = []
    for index, (start, end) in enumerate(((0, 2), (3, 5), (6, 8))):
        sources = [
            source_reference(scene, "message", message.id)
            for message in scene.history[start : end + 1]
        ]
        if start <= position <= end:
            sources.append(source_reference(scene, "disclosure", disclosure.id))
        bases.append(
            _summary(
                scene,
                f"base-{index}",
                f"BASE-{index}",
                start,
                end,
                sources,
                audience=("Bob",),
            )
        )
    if include_layer:
        _summary(
            scene,
            "layer",
            "LAYER",
            0,
            2,
            bases,
            layer=1,
            audience=("Bob",),
        )

    _, result = _project(
        scene,
        1000,
        _policy(
            min_dialogue=3,
            max_dialogue=12,
            summary_boundary=8,
            layered_history_available=include_layer,
        ),
    )

    assert result.raw_message_count == 12
    assert result.total_tokens == 125
    assert [
        entry.message_id for entry in result.entries if entry.message_id is not None
    ] == [message.id for message in scene.history]
    assert (
        sum(disclosure.id in entry.covered_disclosure_ids for entry in result.entries)
        == 1
    )
    disclosure_index = next(
        index
        for index, entry in enumerate(result.entries)
        if disclosure.id in entry.covered_disclosure_ids
    )
    assert (
        result.entries[disclosure_index - 1].message_id
        == scene.history[position - 1].id
    )
    assert result.entries[disclosure_index + 1].message_id == scene.history[position].id


def test_ratio_does_not_charge_raw_disclosure_to_summary_allocation(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, OLD=55, NEW=1, Established=5)
    _summary(
        scene,
        "old",
        "OLD",
        0,
        2,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:3]
        ],
    )
    _summary(
        scene,
        "new",
        "NEW",
        3,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[3:9]
        ],
    )
    disclosure = add_disclosure(
        scene,
        "Bob learns a raw-window boundary fact.",
        ["Bob"],
        message_id_boundary=scene.history[8].id,
    )

    history, result = _project(
        scene,
        100,
        _policy(
            best_fit=False,
            dialogue_ratio=40,
            summary_detail_ratio=50,
            summary_boundary=8,
            layered_history_available=False,
        ),
    )

    assert [str(part).strip() for part in history[:2]] == ["OLD", "NEW"]
    assert result.total_tokens == 91
    assert result.raw_message_count == 3
    assert (
        sum(disclosure.id in entry.covered_disclosure_ids for entry in result.entries)
        == 1
    )


@pytest.mark.parametrize("best_fit", [True, False])
@pytest.mark.parametrize("include_intro_dependency", [False, True])
def test_intro_admission_uses_audience_summary_dependencies(
    perspective_history_scene,
    fixed_costs,
    best_fit,
    include_intro_dependency,
):
    scene = perspective_history_scene
    scene.intro = "OPENING"
    scene.intro_present = ["Bob"]
    set_source_perspectives(
        scene,
        "intro",
        "intro",
        [{"audience": ["Bob"], "status": "ready", "text": "OPENING"}],
    )
    fixed_costs.update(M=10, BASE=5, OPENING=4)
    sources = [
        source_reference(scene, "message", message.id) for message in scene.history[:9]
    ]
    if include_intro_dependency:
        sources.append(source_reference(scene, "intro", "intro"))
    _summary(scene, "base", "BASE", 0, 8, sources, audience=("Bob",))
    scene.archived_history[0]["intro_included"] = True

    _, result = _project(
        scene,
        100,
        _policy(
            best_fit=best_fit,
            min_dialogue=3,
            max_dialogue=3,
            dialogue_ratio=30,
            summary_boundary=8,
        ),
    )

    assert sum(entry.type == "intro" for entry in result.entries) == (
        0 if include_intro_dependency else 1
    )


@pytest.mark.parametrize("best_fit", [True, False])
@pytest.mark.parametrize("include_intro_dependency", [False, True])
def test_layered_intro_coverage_follows_recursive_audience_dependencies(
    perspective_history_scene,
    fixed_costs,
    best_fit,
    include_intro_dependency,
):
    scene = perspective_history_scene
    scene.intro = "OPENING"
    scene.intro_present = ["Bob"]
    set_source_perspectives(
        scene,
        "intro",
        "intro",
        [{"audience": ["Bob"], "status": "ready", "text": "OPENING"}],
    )
    fixed_costs.update(M=10, BASE=20, LAYER=5, OPENING=4)
    bases = []
    for index, (start, end) in enumerate(((0, 2), (3, 5), (6, 8))):
        sources = [
            source_reference(scene, "message", message.id)
            for message in scene.history[start : end + 1]
        ]
        if index == 0 and include_intro_dependency:
            sources.append(source_reference(scene, "intro", "intro"))
        bases.append(
            _summary(
                scene,
                f"base-{index}",
                f"BASE-{index}",
                start,
                end,
                sources,
                audience=("Bob",),
            )
        )
    scene.archived_history[0]["intro_included"] = True
    _summary(
        scene,
        "layer",
        "LAYER",
        0,
        1,
        bases[:2],
        layer=1,
        audience=("Bob",),
    )

    _, result = _project(
        scene,
        40 if best_fit else 100,
        _policy(
            best_fit=best_fit,
            min_dialogue=3,
            max_dialogue=3,
            dialogue_ratio=30,
            summary_detail_ratio=50,
            summary_boundary=8,
        ),
    )

    assert any(entry.type == "layer" for entry in result.entries)
    assert sum(entry.type == "intro" for entry in result.entries) == (
        0 if include_intro_dependency else 1
    )


def test_layered_history_availability_changes_selected_level(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, B=10, L=5)
    bases = []
    for index, (start, end) in enumerate(((0, 2), (3, 5), (6, 8))):
        bases.append(
            _summary(
                scene,
                f"B{index}",
                f"B{index}",
                start,
                end,
                [
                    source_reference(scene, "message", message.id)
                    for message in scene.history[start : end + 1]
                ],
            )
        )
    _summary(scene, "L01", "L01", 0, 1, bases[:2], layer=1)

    layered, _ = _project(scene, 50, _policy())
    base_only, _ = _project(scene, 50, _policy(layered_history_available=False))

    assert "L01" in layered
    assert "L01" not in base_only
    assert [str(line).strip() for line in base_only[:2]] == ["B1", "B2"]


def test_blocked_newer_expansion_constrains_lower_layer_detail(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    for index, message in enumerate(scene.history):
        _publish(scene, message, text="CHEAP" if index < 3 else "COSTLY")
    fixed_costs.update(CHEAP=1, COSTLY=10, OLD=1, MIDDLE=20, NEW=20, RECENT=1)
    _summary(
        scene,
        "old",
        "OLD",
        0,
        2,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:3]
        ],
    )
    middle = _summary(
        scene,
        "middle",
        "MIDDLE",
        3,
        5,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[3:6]
        ],
    )
    newest = _summary(
        scene,
        "new",
        "NEW",
        6,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[6:9]
        ],
    )
    _summary(
        scene,
        "recent",
        "RECENT",
        1,
        2,
        [middle, newest],
        layer=1,
    )

    history, _ = _project(
        scene,
        40,
        _policy(min_dialogue=3, max_dialogue=12, summary_boundary=8),
    )

    assert [str(line).strip() for line in history] == [
        "OLD",
        "RECENT",
        "COSTLY",
        "COSTLY",
        "COSTLY",
    ]


def test_ratio_boundary_uses_assured_recent_character_message_count(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10)

    enforced, _ = _project(
        scene,
        100,
        _policy(
            best_fit=False,
            dialogue_ratio=50,
            enforce_boundary=True,
            assured_dialogue_num=0,
        ),
    )
    open_boundary, _ = _project(
        scene,
        100,
        _policy(best_fit=False, dialogue_ratio=50, enforce_boundary=False),
    )

    assert [line.message_id for line in enforced] == [
        message.id for message in scene.history[8:]
    ]
    assert [line.message_id for line in open_boundary] == [
        message.id for message in scene.history[7:]
    ]


@pytest.mark.parametrize("budget", [0, 1])
def test_best_fit_zero_minimum_respects_tiny_budget(
    perspective_history_scene, fixed_costs, budget
):
    fixed_costs.update(M=10)
    history, result = _project(
        perspective_history_scene,
        budget,
        _policy(min_dialogue=0, max_dialogue=3, summary_boundary=8),
    )
    assert history == []
    assert result.total_tokens == result.overflow_tokens == 0


def test_best_fit_returns_all_available_when_minimum_cannot_be_met(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    for message in scene.history[:10]:
        _publish(scene, message, bob=False)
    fixed_costs.update(M=10)

    history, result = _project(
        scene,
        0,
        _policy(min_dialogue=5, max_dialogue=5, summary_boundary=10),
    )

    assert [line.message_id for line in history] == [
        message.id for message in scene.history[10:]
    ]
    assert result.raw_message_count == 2
    assert result.overflow_tokens == 20


def test_maximum_can_drop_live_detail_and_keep_older_summary(
    perspective_history_scene, fixed_costs
):
    scene = perspective_history_scene
    fixed_costs.update(M=10, OLDER=5)
    _summary(
        scene,
        "older",
        "OLDER",
        0,
        8,
        [
            source_reference(scene, "message", message.id)
            for message in scene.history[:9]
        ],
    )

    history, result = _project(
        scene,
        100,
        _policy(min_dialogue=0, max_dialogue=2, summary_boundary=8),
    )

    assert [str(line).strip() for line in history] == ["OLDER", "M10", "M11"]
    assert result.raw_message_count == 2
