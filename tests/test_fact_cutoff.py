"""
Known facts for an extraction come from before its source: an older entry is
never offered, and never supersedes, a fact recorded after it.
"""

import json
from unittest.mock import AsyncMock

import pytest

import test_supported_facts
from talemate.history import ArchiveEntry, HistoryEntry, insert_time_passage
from talemate.knowledge.cutoff import FactCutoff, disclosure_cutoff, span_cutoff
from talemate.knowledge.facts import facts_for_entry, verify_links
from talemate.knowledge.perspectives import add_disclosure, source_reference
from talemate.knowledge.schema import Fact, ParsedFact
from talemate.knowledge.timeline import message_times
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, CharacterTransitionMessage

supported_scene = test_supported_facts.supported_scene
chapter = test_supported_facts.chapter
store = test_supported_facts.store


def test_cutoff_orders_facts_by_position_and_line_less_facts_by_earlier_time():
    cutoff = FactCutoff(
        message_id=10,
        ts=100,
        entry_starts={"early": 5, "late": 12},
        static_entries=frozenset({"static"}),
    )
    assert cutoff.admits(Fact(id="a", text="a", message_id=9, ts=500))
    assert not cutoff.admits(Fact(id="b", text="b", message_id=10, ts=0))
    assert cutoff.admits(Fact(id="c", text="c", archive_id="static", ts=999))
    assert cutoff.admits(Fact(id="d", text="d", archive_id="early", ts=999))
    assert not cutoff.admits(Fact(id="e", text="e", archive_id="late", ts=0))
    # no position: scene time moves only at a time passage, so equal is unknown
    assert cutoff.admits(Fact(id="f", text="f", source="offscreen", ts=99))
    assert not cutoff.admits(Fact(id="g", text="g", source="offscreen", ts=100))
    assert not cutoff.admits(Fact(id="h", text="h", source="manual"))


def test_links_to_facts_the_request_did_not_offer_are_dropped():
    parsed = [
        ParsedFact(text="Kept.", supersedes="F1", restates=None),
        ParsedFact(text="Dropped link.", supersedes="F2"),
        ParsedFact(text="Dropped repeat.", restates="F2"),
    ]
    checked = verify_links(parsed, {"F1"})
    assert [(item.supersedes, item.restates) for item in checked] == [
        ("F1", None),
        (None, None),
        (None, None),
    ]


@pytest.fixture
def standard_scene(supported_scene, monkeypatch):
    scene, summarizer, memory = supported_scene
    scene.knowledge_eligibility = "legacy"
    scene.history = [
        CharacterMessage(message=f"Alice: line {index}", present=["Alice"])
        for index in range(4)
    ]
    times = message_times(scene)
    scene.archived_history = [
        ArchiveEntry(id="static", text="Alice keeps the lighthouse.", ts=0).model_dump(
            exclude_none=True
        ),
        ArchiveEntry(
            id="older", text="Alice lives in the lighthouse.", start=0, end=1, ts=0
        ).model_dump(exclude_none=True),
        ArchiveEntry(
            id="newer", text="Alice moves to the village.", start=2, end=3, ts=0
        ).model_dump(exclude_none=True),
    ]
    newer_line = scene.history[2].id
    scene.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="Alice keeps the lighthouse.",
            subjects=["Alice"],
            archive_id="static",
            ts=0,
        ),
        "F2": Fact(
            id="F2",
            text="Alice moved to the village.",
            subjects=["Alice"],
            archive_id="newer",
            message_id=newer_line,
            ts=times[newer_line],
        ),
    }
    scene.world_state.fact_counter = 2
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    return scene, summarizer


def answer(facts):
    return AsyncMock(return_value=("", {"facts": json.dumps(facts)}))


async def test_older_entry_is_offered_only_earlier_facts_and_cannot_hide_a_newer_one(
    standard_scene, monkeypatch
):
    scene, summarizer = standard_scene
    older_line = scene.history[1].id
    request = answer(
        [
            {
                "text": "Alice lives in the lighthouse.",
                "subjects": ["Alice"],
                "message_id": older_line,
                "supersedes": "F2",
            }
        ]
    )
    monkeypatch.setattr(Prompt, "request", request)
    result = await summarizer.generate_missing_facts(scene)
    assert result["ok"] == 1
    offered = request.call_args.kwargs["vars"]["previous_facts"]
    assert [fact.id for fact in offered] == ["F1"]
    (older,) = facts_for_entry(scene, "older")
    assert older.supersedes is None
    assert all(fact.supersedes != "F2" for fact in scene.world_state.facts.values())


async def test_regenerate_entry_offers_only_earlier_facts(standard_scene, monkeypatch):
    scene, summarizer = standard_scene
    request = AsyncMock(
        return_value=(
            "SUMMARY: Alice lives in the lighthouse.",
            {"summary": "Alice lives in the lighthouse.", "facts": "[]"},
        )
    )
    monkeypatch.setattr(Prompt, "request", request)
    stored = scene.archived_history[1]
    await summarizer.summarize_with_facts(ArchiveEntry(**stored))
    assert request.call_args.args[0] == "summarizer.summarize-dialogue"
    offered = request.call_args.kwargs["vars"]["previous_facts"]
    assert [fact.id for fact in offered] == ["F1"]


async def test_newest_entry_still_sees_every_earlier_fact(standard_scene, monkeypatch):
    scene, summarizer = standard_scene
    scene.world_state.facts.pop("F2")
    request = answer([])
    monkeypatch.setattr(Prompt, "request", request)
    newest = HistoryEntry(**scene.archived_history[2], index=2, layer=0)
    assert await summarizer.regenerate_facts(newest) == "ok"
    offered = request.call_args.kwargs["vars"]["previous_facts"]
    assert [fact.id for fact in offered] == ["F1"]
    assert request.call_args.kwargs["vars"]["summary"] == "Alice moves to the village."


async def test_perspective_rebuild_offers_only_facts_from_earlier_sources(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    _, early = chapter(scene, "Alice found the key.", ts=10)
    _, middle = chapter(scene, "Alice hid the key.", ts=20)
    _, late = chapter(scene, "Alice lost the key.", ts=30)
    await store(scene, early, ("Alice",), "Alice found the key.", subjects=["key"])
    await store(scene, late, ("Alice",), "Alice lost the key.", subjects=["key"])
    request = answer([])
    monkeypatch.setattr(Prompt, "request", request)
    assert await summarizer.rebuild_supported_facts(scene, [middle]) == "ok"
    offered = request.call_args.kwargs["vars"]["previous_facts"]
    assert [fact.text for fact in offered] == ["Alice found the key."]


def test_span_and_disclosure_cutoffs(supported_scene):
    scene, _, _ = supported_scene
    first, _ = test_supported_facts.passage(scene, "Alice sees the key.", ts=10)
    second, _ = test_supported_facts.passage(scene, "Alice takes the key.", ts=20)
    assert span_cutoff(scene, [None, second.id, first.id]) == FactCutoff(
        message_id=first.id, ts=10
    )
    # an input without a message line starts at the entry
    entry_start = scene.history.index(first)
    assert span_cutoff(scene, [None], start=entry_start) == FactCutoff(
        message_id=first.id, ts=10
    )
    assert span_cutoff(scene, [None]).message_id == 0
    disclosure = add_disclosure(scene, "Alice owns the key.", ("Bob",))
    cutoff = disclosure_cutoff(scene, disclosure)
    assert cutoff.message_id == disclosure.message_id_boundary + 1
    assert cutoff.order == disclosure.acquired.order
    assert cutoff.admits(Fact(id="x", text="x", message_id=second.id, ts=20))


async def test_standard_offscreen_fact_after_an_older_entry_at_the_same_time(
    standard_scene, monkeypatch
):
    scene, summarizer = standard_scene
    scene.world_state.facts["F3"] = Fact(
        id="F3",
        text="Alice spent the night at the harbour.",
        subjects=["Alice"],
        source="offscreen",
        present=["Alice"],
        ts=0,
    )
    scene.world_state.fact_counter = 3
    older_line = scene.history[1].id
    request = answer(
        [
            {
                "text": "Alice stays in the lighthouse.",
                "subjects": ["Alice"],
                "message_id": older_line,
                "supersedes": "F3",
            }
        ]
    )
    monkeypatch.setattr(Prompt, "request", request)
    assert (await summarizer.generate_missing_facts(scene))["ok"] == 1
    offered = request.call_args.kwargs["vars"]["previous_facts"]
    assert [fact.id for fact in offered] == ["F1"]
    assert all(fact.supersedes != "F3" for fact in scene.world_state.facts.values())


async def test_disclosure_given_after_an_older_chapter_at_the_same_time(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    before = add_disclosure(scene, "The lamp is old.", ("Alice",))
    await store(
        scene,
        source_reference(scene, "disclosure", before.id),
        ("Alice",),
        "The lamp is old.",
        subjects=["lamp"],
    )
    _, older = chapter(scene, "Alice finds a key.", ts=10)
    chapter(scene, "Alice keeps the key.", ts=10)
    after = add_disclosure(scene, "The key belongs to Bob.", ("Alice",))
    await store(
        scene,
        source_reference(scene, "disclosure", after.id),
        ("Alice",),
        "The key belongs to Bob.",
        subjects=["key"],
    )
    request = answer([])
    monkeypatch.setattr(Prompt, "request", request)
    assert await summarizer.rebuild_supported_facts(scene, [older]) == "ok"
    offered = request.call_args.kwargs["vars"]["previous_facts"]
    assert [fact.text for fact in offered] == ["The lamp is old."]


async def test_disclosure_only_audience_input_gets_the_entry_cutoff(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    early, _ = chapter(scene, "Alice finds a key.", ts=10)
    middle, _ = chapter(scene, "Alice hides the key.", ts=10)
    late, _ = chapter(scene, "Alice loses the key.", ts=10)
    heard = add_disclosure(
        scene, "Bob hears that Alice hid a key.", ("Bob",), message_id_boundary=early.id
    )
    later = add_disclosure(
        scene, "Bob hears that the key is lost.", ("Bob",), message_id_boundary=late.id
    )
    for disclosure in (heard, later):
        await store(
            scene,
            source_reference(scene, "disclosure", disclosure.id),
            ("Bob",),
            disclosure.text,
            subjects=["key"],
        )
    request = AsyncMock(
        return_value=("SUMMARY: Bob heard.", {"summary": "Bob heard.", "facts": "[]"})
    )
    monkeypatch.setattr(Prompt, "request", request)
    await summarizer.ensure_summary_views(
        scene, f"chapter-{middle.id}", audiences=["Bob"]
    )
    values = request.call_args.kwargs["vars"]
    assert values["audience_summary"] == ("Bob",)
    assert "Bob hears that Alice hid a key." in values["dialogue"]
    assert [fact.text for fact in values["previous_facts"]] == [
        "Bob hears that Alice hid a key."
    ]


async def test_offered_earlier_link_is_kept_in_a_long_perspectives_scene(
    supported_scene, monkeypatch
):
    scene, summarizer, _ = supported_scene
    sources = []
    for index in range(35):
        _, source = chapter(scene, f"Alice notes lamp {index}.", ts=10)
        await store(scene, source, ("Alice",), f"Alice noted lamp {index}.")
        sources.append(source)
    target = sources[4]
    offered_ids = []

    async def request(*args, **kwargs):
        offered = kwargs["vars"]["previous_facts"]
        offered_ids.extend(fact.id for fact in offered)
        link = next(fact.id for fact in offered if fact.text == "Alice noted lamp 1.")
        return "", {
            "facts": json.dumps(
                [{"text": "Alice replaced lamp 4.", "supersedes": link}]
            )
        }

    monkeypatch.setattr(Prompt, "request", AsyncMock(side_effect=request))
    assert await summarizer.rebuild_supported_facts(scene, [target]) == "ok"
    assert len(offered_ids) == 4
    link = next(
        fact.id
        for fact in scene.world_state.facts.values()
        if fact.text == "Alice noted lamp 1."
    )
    (replaced,) = [
        fact
        for fact in scene.world_state.facts.values()
        if fact.text == "Alice replaced lamp 4."
    ]
    assert replaced.contributions[0].supersedes == link


@pytest.fixture
def return_scene(supported_scene, monkeypatch):
    scene, summarizer, memory = supported_scene
    scene.knowledge_eligibility = "legacy"

    def line(text):
        return CharacterMessage(message=f"Alice: {text}", present=["Alice", "Bob"])

    scene.history = [
        line("the lamp is lit"),
        line("Bob leaves for the mainland"),
        line("the storm comes"),
        line("the storm passes"),
        CharacterTransitionMessage(
            character_name="Bob", returning=True, offscreen_fact_id="F1"
        ),
        line("welcome back, Bob"),
        line("tell me about the mainland"),
    ]
    scene.archived_history = [
        ArchiveEntry(id=identity, text=text, start=start, end=end, ts=0).model_dump(
            exclude_none=True
        )
        for identity, text, start, end in (
            ("older", "Bob leaves for the mainland.", 0, 1),
            ("newer", "A storm passes.", 2, 3),
            ("after", "Bob is back.", 5, 6),
        )
    ]
    scene.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="Bob sold his boat on the mainland.",
            subjects=["Bob"],
            source="offscreen",
            present=["Bob"],
            ts=0,
        )
    }
    scene.world_state.fact_counter = 1
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    return scene, summarizer


async def offered_for(scene, summarizer, identity, monkeypatch):
    request = answer([])
    monkeypatch.setattr(Prompt, "request", request)
    index, stored = next(
        (index, stored)
        for index, stored in enumerate(scene.archived_history)
        if stored["id"] == identity
    )
    assert (
        await summarizer.regenerate_facts(HistoryEntry(**stored, index=index, layer=0))
        == "ok"
    )
    return [fact.id for fact in request.call_args.kwargs["vars"]["previous_facts"]]


async def test_offscreen_fact_is_placed_at_its_return_transition(
    return_scene, monkeypatch
):
    scene, summarizer = return_scene
    assert await offered_for(scene, summarizer, "after", monkeypatch) == ["F1"]
    assert await offered_for(scene, summarizer, "older", monkeypatch) == []
    insert_time_passage(scene, 0, 1, "hours")
    assert message_times(scene)[scene.history[1].id] == 3600
    assert scene.world_state.facts["F1"].ts == 0
    assert await offered_for(scene, summarizer, "older", monkeypatch) == []
