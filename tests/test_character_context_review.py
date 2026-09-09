from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.agents.summarize.context_history import (
    ContextHistoryParams,
    ContextHistoryPreviewOverrides,
)
from talemate.agents.context import ActiveAgent
from talemate.agents.summarize.websocket_handler import SummarizeWebsocketHandler
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.chronology import DAY
from talemate.knowledge.perspectives import set_source_perspectives, source_reference
from talemate.knowledge.review import character_context_review
from talemate.knowledge.schema import Fact, ParsedFact
from talemate.knowledge.supported_facts import contributions_for_source
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage
from talemate.tale_mate import Actor


@pytest.fixture(params=["legacy", "perception"])
def review_scene(scene, request, monkeypatch):
    scene.knowledge_eligibility = request.param
    scene.ts = 1000 * DAY
    scene.character_data = {}
    scene.actors = []
    for name in ("Alice", "Bob"):
        character = Character(name=name, is_player=name == "Alice")
        scene.character_data[name] = character
        actor = Actor(character, get_agent("conversation"))
        actor.scene = scene
        scene.actors.append(actor)
    scene.active_characters = ["Alice", "Bob"]
    scene.set_intro("An opening secret beneath the sundial.", present=["Alice"])
    for text, audience in (
        ("An early private exchange.", ["Alice"]),
        ("Bob arrives in the square.", ["Alice", "Bob"]),
    ):
        message = NarratorMessage(message=text, present=audience)
        scene.history.append(message)
        if request.param == "perception":
            set_source_perspectives(
                scene,
                "message",
                message.id,
                [{"audience": audience, "status": "ready", "text": text}],
            )
    summ = get_agent("summarizer")
    summ.actions["analyze_scene"].enabled = True
    summ.actions["analyze_scene"].config["for_conversation"].value = True
    monkeypatch.setattr(
        Prompt,
        "request",
        AsyncMock(side_effect=AssertionError("Preview attempted generation")),
    )
    with ActiveScene(scene):
        yield scene


def history_lines(preview):
    return [
        text
        for section in preview["sections"]
        if section["type"] not in ("knowledge", "analysis")
        for text in section["entries"]
    ]


def handler(scene):
    frames = []
    return SummarizeWebsocketHandler(
        SimpleNamespace(scene=scene, queue_put=frames.append)
    ), frames


@pytest.mark.asyncio
async def test_history_guidance_uses_the_conversation_mode(review_scene, monkeypatch):
    conversation = get_agent("conversation")
    cached = AsyncMock(return_value="Cached perspective guidance.")
    monkeypatch.setattr(get_agent("director"), "get_cached_character_guidance", cached)
    collect = Mock(return_value=[])
    monkeypatch.setattr(review_scene, "context_history", collect)
    with ActiveAgent(conversation, conversation.history_context) as context:
        context.state["director__actor_guidance"] = "Current Standard guidance."
        await conversation.history_context(review_scene.character_data["Bob"], 512)
    assert collect.call_args.kwargs["keep_director"] is False
    if review_scene.knowledge_eligibility == "perception":
        cached.assert_awaited_once_with("Bob")
    else:
        cached.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
async def test_character_preview_matches_conversation_history_and_reports_absence(
    review_scene, best_fit
):
    scene = review_scene
    conversation = get_agent("conversation")
    get_agent("summarizer").actions["manage_scene_history"].config[
        "best_fit"
    ].value = best_fit
    plugin, frames = handler(scene)
    await plugin.handle_context_review({"character": "Bob", "request_id": "bob"})
    assert frames[-1]["request_id"] == "bob"
    preview = frames[-1]["data"]
    assert preview["characters"] == ["Alice", "Bob"]
    assert preview["perspective"] == "Bob"
    assert history_lines(preview) == await conversation.history_context(
        scene.character_data["Bob"], 8192
    )
    assert "private exchange" not in "\n".join(history_lines(preview))
    assert "opening secret" not in "\n".join(history_lines(preview))
    assert "Bob arrives" in "\n".join(history_lines(preview))
    assert any(
        item["kind"] == "intro" and item["reason"] == "absent"
        for item in preview["exclusions"]
    )
    expected = (
        "not_in_audience" if scene.knowledge_eligibility == "perception" else "absent"
    )
    assert any(
        item["id"] == scene.history[0].id and item["reason"] == expected
        for item in preview["exclusions"]
    )
    Prompt.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_scene_preview_retains_reader_history_and_no_character_exclusions(
    review_scene,
):
    plugin, frames = handler(review_scene)
    await plugin.handle_context_review({"request_id": "scene"})
    preview = frames[-1]["data"]
    assert preview["perspective"] is None
    assert preview["exclusions"] == []
    assert "private exchange" in "\n".join(history_lines(preview))
    assert "opening secret" in "\n".join(history_lines(preview))
    Prompt.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_overrides_do_not_mutate_scene_settings(review_scene):
    summ = get_agent("summarizer")
    before = summ.actions["manage_scene_history"].model_dump()
    preview = await character_context_review(
        review_scene,
        review_scene.character_data["Alice"],
        ContextHistoryPreviewOverrides(
            max_budget=512, best_fit=False, dialogue_ratio=75
        ),
    )
    assert preview["budget"]["total"] == 512
    assert preview["summary"]["dialogue_ratio"] == 75
    assert preview["summary"]["best_fit"] is False
    assert summ.actions["manage_scene_history"].model_dump() == before


def add_fact(
    scene, identity, text, *, audience=("Alice", "Bob"), age=0, supersedes=None
):
    fact = Fact(
        id=identity,
        text=text,
        present=list(audience),
        subjects=["sextant"],
        ts=scene.ts - age * DAY,
        importance=1,
        supersedes=supersedes,
    )
    if scene.knowledge_eligibility == "perception":
        message = NarratorMessage(message=text, present=list(audience))
        scene.history.append(message)
        ts = scene.ts
        scene.ts = fact.ts
        set_source_perspectives(
            scene,
            "message",
            message.id,
            [{"audience": audience, "status": "ready", "text": text}],
        )
        source = source_reference(scene, "message", message.id)
        fact.contributions = contributions_for_source(
            scene,
            source,
            audience,
            [
                ParsedFact(
                    text=text, importance=1, subjects=["sextant"], supersedes=supersedes
                )
            ],
        )
        scene.ts = ts
    scene.world_state.facts[identity] = fact
    return fact


@pytest.mark.asyncio
async def test_fact_audience_chronology_and_supersession_exclusions(review_scene):
    scene = review_scene
    add_fact(scene, "F1", "A private fact.", audience=("Alice",))
    add_fact(scene, "F2", "A stale routine fact.", age=500)
    add_fact(scene, "F3", "The sextant was in the drawer.")
    add_fact(scene, "F4", "The sextant is in the bag.", supersedes="F3")
    preview = await character_context_review(scene, scene.character_data["Bob"])
    excluded = {
        item["id"]: item["reason"]
        for item in preview["exclusions"]
        if item["kind"] == "fact"
    }
    assert excluded == {
        "F1": "not_in_audience",
        "F2": "chronology_floor",
        "F3": "superseded",
    }
    facts = next(
        item
        for item in preview["sections"]
        if item["label"] == "Known facts (eligible)"
    )
    text = "\n".join(facts["entries"])
    assert "[F4]" in text and "formerly:" in text
    assert "[F1]" not in text and "[F2]" not in text and "[F3]" not in text
    assert any(
        item["type"] == "analysis" and item["entries"] for item in preview["sections"]
    )
    Prompt.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_inactive_character_fails_with_correlated_error(review_scene):
    review_scene.active_characters.remove("Bob")
    plugin, frames = handler(review_scene)
    await plugin.handle(
        {"action": "context_review", "character": "Bob", "request_id": "inactive"}
    )
    assert frames[-1]["request_id"] == "inactive"
    assert "active character" in frames[-1]["error"]["message"]
    Prompt.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_scene_failure_is_correlated():
    plugin, frames = handler(None)
    await plugin.handle_context_review({"request_id": "none"})
    assert frames[-1]["request_id"] == "none"
    assert frames[-1]["error"]["message"] == "No scene loaded"


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
async def test_preview_preserves_intro_order_when_first_archive_excludes_it(
    scene, best_fit
):
    scene.character_data = {"Alice": Character(name="Alice")}
    scene.active_characters = ["Alice"]
    scene.set_intro("Opening evidence.")
    scene.history = [
        NarratorMessage(message=f"Moment {i}: " + "garden " * 100, present=["Alice"])
        for i in range(12)
    ]
    scene.archived_history = [
        {
            "id": "first",
            "text": "Earlier shared events.",
            "start": 0,
            "end": 8,
            "ts": 0,
            "present": ["Alice"],
            "intro_included": False,
        }
    ]
    summ = get_agent("summarizer")
    summ.actions["manage_scene_history"].config["max_budget"].value = 600
    summ.actions["manage_scene_history"].config["best_fit"].value = best_fit
    conversation = get_agent("conversation")
    actual = await conversation.history_context(scene.character_data["Alice"], 600)
    preview = await conversation.history_context(
        scene.character_data["Alice"], 600, preview=True
    )
    assert "Earlier shared events" in "\n".join(actual)
    assert history_lines(preview) == actual


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
@pytest.mark.parametrize("intro_included", [False, True])
async def test_opening_witness_keeps_budgeted_intro_when_first_archive_is_private(
    scene, best_fit, intro_included
):
    from talemate.util import count_tokens

    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    scene.set_intro(
        "The opening witness knows the sundial secret. " * 8, present=["Alice", "Bob"]
    )
    scene.history = [
        NarratorMessage(
            message="A lengthy exchange in the gardens. " * 100,
            present=["Bob"] if i < 10 else ["Alice"],
        )
        for i in range(30)
    ]
    scene.archived_history = [
        {
            "id": "opening",
            "text": "Bob's private opening summary.",
            "start": 0,
            "end": 9,
            "ts": 0,
            "present": ["Bob"],
            "intro_included": intro_included,
        },
        {
            "id": "later",
            "text": "Alice's later shared summary.",
            "start": 10,
            "end": 19,
            "ts": 0,
            "present": ["Alice"],
        },
    ]
    config = get_agent("summarizer").actions["manage_scene_history"].config
    for name, value in {
        "best_fit": best_fit,
        "best_fit_min_dialogue": 0,
        "enforce_boundary": True,
        "max_budget": 180,
    }.items():
        config[name].value = value
    conversation = get_agent("conversation")
    actual = await conversation.history_context(scene.character_data["Alice"], 180)
    preview = await conversation.history_context(
        scene.character_data["Alice"], 180, preview=True
    )
    assert scene.get_intro(perspective="Alice") in actual
    assert "Bob's private" not in "\n".join(actual)
    assert "Alice's later" in "\n".join(actual)
    assert count_tokens(actual) <= 180
    assert history_lines(preview) == actual


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
async def test_oversized_intro_is_reported_instead_of_overrunning_budget(
    scene, best_fit
):
    from talemate.util import count_tokens

    scene.character_data = {"Alice": Character(name="Alice")}
    scene.active_characters = ["Alice"]
    scene.set_intro("The introduction is far too long for this budget. " * 50)
    config = get_agent("summarizer").actions["manage_scene_history"].config
    config["best_fit"].value = best_fit
    config["best_fit_min_dialogue"].value = 0
    preview = await character_context_review(
        scene,
        scene.character_data["Alice"],
        ContextHistoryPreviewOverrides(max_budget=50),
    )
    assert count_tokens(history_lines(preview)) <= 50
    assert any(
        item["kind"] == "intro" and item["reason"] == "budget"
        for item in preview["exclusions"]
    )


@pytest.mark.asyncio
async def test_preview_includes_all_eligible_facts_and_marks_false_and_budget(
    review_scene,
):
    scene = review_scene
    for index in range(30):
        add_fact(scene, f"F{index}", f"The sextant record {index} is known.")
    scene.world_state.facts["F0"].false = True
    preview = await character_context_review(
        scene,
        scene.character_data["Bob"],
        ContextHistoryPreviewOverrides(max_budget=4000),
    )
    facts = next(
        section
        for section in preview["sections"]
        if section["label"] == "Known facts (eligible)"
    )
    assert len(facts["entries"]) == 30
    assert all(line.startswith("- [") for line in facts["entries"])
    assert any("[F0] (known to be false)" in line for line in facts["entries"]) is (
        scene.knowledge_eligibility == "legacy"
    )
    small = await character_context_review(
        scene,
        scene.character_data["Bob"],
        ContextHistoryPreviewOverrides(max_budget=90),
    )
    included = next(
        section
        for section in small["sections"]
        if section["label"] == "Known facts (eligible)"
    )["entries"]
    assert len(included) + small["exclusion_counts"]["budget"] == 30
    assert (
        len([item for item in small["exclusions"] if item["reason"] == "budget"]) <= 20
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
async def test_archive_and_layer_exclusions_come_from_history_selectors(
    review_scene, best_fit
):
    scene = review_scene
    archive = {
        "id": "private-archive",
        "text": "Bob's private archived moment.",
        "start": 0,
        "end": 1,
        "ts": 0,
        "present": ["Bob"],
    }
    layer = {
        "id": "private-layer",
        "text": "Bob's private chapter.",
        "start": 0,
        "end": 0,
        "ts_start": 0,
        "ts_end": 0,
        "present": ["Bob"],
    }
    scene.archived_history = [archive]
    scene.layered_history = [[layer]]
    get_agent("summarizer").actions["layered_history"].enabled = True
    if scene.knowledge_eligibility == "perception":
        set_source_perspectives(
            scene,
            "summary",
            archive["id"],
            [{"audience": ["Bob"], "status": "ready", "text": archive["text"]}],
        )
        set_source_perspectives(
            scene,
            "summary",
            layer["id"],
            [{"audience": ["Bob"], "status": "ready", "text": layer["text"]}],
            layer=1,
        )
    preview = await character_context_review(
        scene,
        scene.character_data["Alice"],
        ContextHistoryPreviewOverrides(best_fit=best_fit),
    )
    missing = {(item["kind"], item["id"]): item for item in preview["exclusions"]}
    reason = (
        "not_in_audience" if scene.knowledge_eligibility == "perception" else "absent"
    )
    assert missing["archived", "private-archive"]["reason"] == reason
    assert missing["layer", "private-layer"]["reason"] == reason
    assert missing["layer", "private-layer"]["layer"] == 0
    assert "Bob's private" not in "\n".join(history_lines(preview))


@pytest.mark.asyncio
async def test_character_preview_uses_client_window_and_bounds_exclusion_samples(
    review_scene, monkeypatch
):
    scene = review_scene
    conversation = get_agent("conversation")
    monkeypatch.setattr(
        type(conversation.client), "max_token_length", property(lambda self: 2048)
    )
    for i in range(45):
        add_fact(scene, f"F{i}", "A long private fact. " * 100, audience=("Alice",))
    preview = await character_context_review(
        scene, scene.character_data["Bob"], ContextHistoryPreviewOverrides(max_budget=0)
    )
    assert preview["budget"]["total"] == 2048
    assert preview["exclusion_counts"]["not_in_audience"] >= 45
    assert (
        len(
            [
                item
                for item in preview["exclusions"]
                if item["reason"] == "not_in_audience"
            ]
        )
        == 20
    )
    assert all(len(item["text"]) <= 500 for item in preview["exclusions"])


@pytest.fixture
def standard_opening_scene(scene):
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    scene.set_intro("The sundial hides an emerald key. " * 8, present=["Alice", "Bob"])
    scene.history = [
        NarratorMessage(
            message="A lengthy exchange in the gardens. " * 100,
            present=["Alice", "Bob"],
        )
        for _ in range(30)
    ]
    scene.archived_history = [
        {"id": "note", "text": "A manual history note.", "ts": 0},
        {
            "id": "opening",
            "text": scene.intro,
            "start": 0,
            "end": 9,
            "ts": 0,
            "present": ["Alice", "Bob"],
            "intro_included": True,
        },
        {
            "id": "later",
            "text": "Later events in the gardens.",
            "start": 10,
            "end": 19,
            "ts": 0,
            "present": ["Alice", "Bob"],
        },
    ]
    return scene


def standard_history(scene, best_fit, budget, perspective="Alice", min_dialogue=0):
    summarizer = get_agent("summarizer")
    config = summarizer.actions["manage_scene_history"].config
    for name, value in {
        "best_fit": best_fit,
        "best_fit_min_dialogue": min_dialogue,
        "enforce_boundary": True,
        "max_budget": budget,
        "dialogue_ratio": 50,
    }.items():
        config[name].value = value
    params = ContextHistoryParams(perspective=perspective, assured_dialogue_num=0)
    actual = scene.context_history(budget=budget, **params.model_dump())
    preview = summarizer.context_history_preview(scene, budget=budget, params=params)
    assert history_lines(preview) == actual
    return actual


@pytest.mark.parametrize("best_fit", [False, True])
def test_manual_note_before_opening_summary_does_not_duplicate_intro(
    standard_opening_scene, best_fit
):
    scene = standard_opening_scene
    actual = standard_history(scene, best_fit, 300)
    assert "Later events" in "\n".join(actual)
    assert "\n".join(actual).count("The sundial hides") == 8


@pytest.mark.parametrize("best_fit", [False, True])
def test_shifted_layer_after_manual_note_does_not_claim_opening(
    standard_opening_scene, best_fit
):
    scene = standard_opening_scene
    scene.archived_history[1].update(text="Bob's private opening.", present=["Bob"])
    scene.archived_history[2]["text"] = "Later events. " * 200
    scene.archived_history.append(
        {
            "id": "latest",
            "text": "Latest events. " * 200,
            "start": 20,
            "end": 24,
            "ts": 0,
            "present": ["Alice"],
        }
    )
    scene.layered_history = [
        [
            {
                "id": "later-layer",
                "text": "A chapter covering only later events.",
                "start": 2,
                "end": 3,
                "ts_start": 0,
                "ts_end": 0,
                "present": ["Alice"],
            }
        ]
    ]
    get_agent("summarizer").actions["layered_history"].enabled = True
    actual = standard_history(scene, best_fit, 300)
    assert "A chapter covering only later events." in "\n".join(actual)
    assert scene.get_intro(perspective="Alice") in actual


@pytest.mark.parametrize("best_fit", [False, True])
def test_selected_opening_summary_releases_entire_intro_allocation(
    standard_opening_scene, best_fit
):
    scene = standard_opening_scene
    scene.archived_history = scene.archived_history[:2]
    scene.history = scene.history[:10] + [
        NarratorMessage(
            message=f"Recent exchange {i} about the gardens and the long journey ahead.",
            present=["Alice", "Bob"],
        )
        for i in range(30)
    ]
    actual = standard_history(scene, best_fit, 500, min_dialogue=5)
    assert "\n".join(actual).count("The sundial hides") == 8
    # The selected summary already contains the opening. Its separate source
    # must not take away any of the dialogue that fits without that source.
    scene.intro = ""
    without_separate_intro = standard_history(scene, best_fit, 500, min_dialogue=5)
    assert actual == without_separate_intro


@pytest.mark.parametrize("best_fit", [False, True])
@pytest.mark.parametrize("perspective", [None, "Alice"])
def test_unscoped_opening_requires_no_selected_summary(
    standard_opening_scene, best_fit, perspective
):
    scene = standard_opening_scene
    scene.archived_history[1]["text"] = "An oversized opening summary. " * 300
    actual = standard_history(scene, best_fit, 300, perspective=perspective)
    assert "Later events" in "\n".join(actual)
    assert (scene.get_intro(perspective=perspective) in actual) is (
        perspective is not None
    )
    scene.archived_history = []
    scene.history = []
    assert scene.get_intro(perspective=perspective) in standard_history(
        scene, best_fit, 300, perspective=perspective
    )


@pytest.fixture
def history_token_probe(scene, monkeypatch):
    import talemate.agents.summarize.context_history as history_module

    scene.character_data = {"Alice": Character(name="Alice")}
    scene.active_characters = ["Alice"]
    costs = {}

    def tokens(value):
        if isinstance(value, list):
            return sum(tokens(item) for item in value)
        return sum(cost for marker, cost in costs.items() if marker in str(value))

    monkeypatch.setattr(history_module, "count_tokens", tokens)
    return scene, costs, tokens


@pytest.mark.parametrize("best_fit,budget", [(False, 200), (True, 180)])
def test_opening_survives_when_reduced_pass_selects_its_summary(
    history_token_probe, best_fit, budget
):
    scene, costs, tokens = history_token_probe
    costs.update(OPENING=100, FIRST=50, LATEST=50, SUMMARY=20)
    scene.set_intro("OPENING", present=["Alice"])
    scene.history = [
        NarratorMessage(message=text, present=["Alice"]) for text in ("FIRST", "LATEST")
    ]
    scene.archived_history = [
        {
            "id": "opening",
            "text": "SUMMARY",
            "start": 0,
            "end": 0,
            "ts": 0,
            "present": ["Alice"],
            "intro_included": True,
        }
    ]
    actual = standard_history(scene, best_fit, budget)
    assert "SUMMARY" in "\n".join(actual)
    assert "LATEST" in "\n".join(actual)
    assert tokens(actual) == 70


def test_unscoped_best_fit_expanded_dialogue_counts_as_context(history_token_probe):
    scene, costs, tokens = history_token_probe
    costs.update(
        OPENING=10,
        ANCIENT=500,
        FIRST=20,
        SECOND=20,
        LATEST=20,
        OLD_SUMMARY=50,
        RECENT_SUMMARY=20,
    )
    scene.set_intro("OPENING", present=["Alice"])
    scene.history = [
        NarratorMessage(message=text, present=["Alice"])
        for text in ("ANCIENT", "FIRST", "SECOND", "LATEST")
    ]
    scene.archived_history = [
        {
            "id": "old",
            "text": "OLD_SUMMARY",
            "start": 0,
            "end": 0,
            "ts": 0,
            "present": ["Alice"],
        },
        {
            "id": "recent",
            "text": "RECENT_SUMMARY",
            "start": 1,
            "end": 2,
            "ts": 0,
            "present": ["Alice"],
        },
    ]
    actual = standard_history(scene, True, 80, perspective=None)
    text = "\n".join(actual)
    assert "OPENING" not in text
    assert "SUMMARY" not in text
    assert all(marker in text for marker in ("FIRST", "SECOND", "LATEST"))
    assert tokens(actual) == 60
