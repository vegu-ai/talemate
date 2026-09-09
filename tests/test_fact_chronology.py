from pathlib import Path
import json
from unittest.mock import AsyncMock

import pytest
from jinja2 import Environment, nodes

from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.absence import absence_facts
from talemate.knowledge.chronology import (
    DAY,
    DEFAULTS,
    chronology_settings,
    fact_age,
    fact_chronology,
    fact_score,
    fact_time,
    ranked_facts,
    ranked_fact_documents,
    render_fact,
)
from talemate.knowledge.facts import parse_facts, previous_facts, store_facts
from talemate.knowledge.graph import facts_about
from talemate.knowledge.schema import Fact, ParsedFact
from talemate.knowledge.standard_analysis import standard_analysis_context
from talemate.knowledge.topics import known_facts
from talemate.prompts import Prompt
from talemate.prompts.extensions import CaptureContextExtension
from talemate.scene_agent_settings import SceneAgentSettings
from talemate.util.time import duration_to_human


@pytest.fixture
def clock_scene(scene):
    scene.ts = 1000 * DAY
    scene.active_characters = []
    assert get_agent("summarizer").scene is scene
    return scene


def ago(scene, identity, days, importance=2, **kwargs):
    fact = Fact(
        id=identity,
        text=f"Event {identity}",
        ts=scene.ts - int(days * DAY),
        importance=importance,
        **kwargs,
    )
    scene.world_state.facts[identity] = fact
    return fact


def test_hug_order_and_exact_decay(clock_scene):
    yesterday = ago(clock_scene, "F1", 1, 3)
    month = ago(clock_scene, "F2", 30, 3)
    yesterday.text = month.text = "Alice hugged Edwin for the first time."
    assert fact_score(clock_scene, yesterday) == pytest.approx(3 / (1 + 1 / 90))
    assert fact_score(clock_scene, month) == pytest.approx(2.25)
    assert ranked_facts(clock_scene, [month, yesterday], limit=1) == [yesterday]


@pytest.mark.parametrize("importance,days", [(1, 2), (2, 14), (3, 90)])
def test_half_life_halves_weight(clock_scene, importance, days):
    assert (
        fact_score(clock_scene, ago(clock_scene, "F1", days, importance))
        == importance / 2
    )


def test_restatement_refreshes_rank_and_marker_without_mutating_fact(clock_scene):
    old = ago(clock_scene, "F1", 30, 3)
    recent = ago(clock_scene, "F2", 1, 3)
    old.last_seen_ts = clock_scene.ts
    before = old.model_dump()
    assert ranked_facts(clock_scene, [recent, old], limit=1) == [old]
    assert fact_age(clock_scene, old) == 0
    assert fact_time(clock_scene, old) == duration_to_human(0)
    assert old.model_dump() == before


def test_tier_cut_precedes_cap_and_includes_present_aliases(clock_scene):
    new = ago(clock_scene, "F1", 2, 1)
    discarded = ago(clock_scene, "F2", 20, 1)
    milestone = ago(clock_scene, "F3", 100, 3)
    present = ago(clock_scene, "F4", 500, 1)
    present.text = "The keeper owns a brass telescope."
    clock_scene.active_characters = ["Edwin"]
    clock_scene.world_state.character_name_mappings = {"Edwin": ["the keeper"]}
    assert fact_chronology(clock_scene, present).eligible
    assert not fact_chronology(clock_scene, discarded).eligible
    assert ranked_facts(clock_scene, [discarded, new, present, milestone]) == [
        milestone,
        new,
        present,
    ]
    assert ranked_facts(clock_scene, [discarded, new, present, milestone], limit=2) == [
        milestone,
        new,
    ]
    assert (
        len(
            ranked_facts(clock_scene, [discarded, new, present, milestone], tiers=False)
        )
        == 4
    )


def test_window_and_floor_are_strict_boundaries(clock_scene):
    fact = ago(clock_scene, "F1", 3, 1)
    settings = {**DEFAULTS, "score_floor": fact_score(clock_scene, fact)}
    assert not fact_chronology(clock_scene, fact, settings).eligible
    fact.last_seen_ts = fact.ts + 1
    assert fact_chronology(clock_scene, fact, settings).recent


def test_name_substrings_do_not_keep_old_facts(clock_scene):
    clock_scene.active_characters = ["Ann"]
    fact = ago(clock_scene, "F1", 100, 1)
    fact.text = "The banner was blue."
    assert not fact_chronology(clock_scene, fact).eligible
    fact.subjects = ["Ann"]
    assert fact_chronology(clock_scene, fact).eligible


def test_unknown_and_future_times(clock_scene):
    unknown = Fact(id="F1", text="An undated fact")
    future = Fact(id="F2", text="A future timestamp", ts=clock_scene.ts + DAY)
    assert fact_time(clock_scene, unknown) == "Time unknown"
    assert fact_score(clock_scene, unknown) == 2
    assert fact_age(clock_scene, future) == 0
    assert fact_time(clock_scene, future) == "Recently"


@pytest.mark.parametrize("days", [0, 1, 21, 30, 365])
def test_marker_uses_shared_duration_format(clock_scene, days):
    fact = ago(clock_scene, "F1", days)
    assert (
        render_fact(clock_scene, fact)
        == f"[F1] ({duration_to_human(days * DAY)}) Event F1"
    )


@pytest.mark.parametrize("overridable", [True, False])
def test_settings_defaults_and_scene_overrides(clock_scene, overridable):
    assert chronology_settings(clock_scene) == DEFAULTS
    get_agent("summarizer").actions["fact_chronology"].config[
        "recent_window"
    ].scene_overridable = overridable
    clock_scene.agent_overrides = SceneAgentSettings.model_validate(
        {
            "filepath": "/tmp/chronology-agent-settings.json",
            "agents": {
                "summarizer": {
                    "actions": {
                        "fact_chronology": {
                            "config": {
                                "recent_window": {"value": 7},
                                "score_floor": {"value": 1},
                            }
                        }
                    }
                }
            },
        }
    )
    assert chronology_settings(clock_scene) == {
        **DEFAULTS,
        "recent_window": 7 if overridable else 3,
        "score_floor": 1,
    }
    assert (
        get_agent("summarizer").actions["fact_chronology"].config["recent_window"].value
        == 3
    )


def test_memory_projection_uses_only_supported_freshness(clock_scene):
    canonical = ago(clock_scene, "F1", 30, 3, last_seen_ts=clock_scene.ts)
    canonical.text = "PRIVATE RESTATEMENT"
    projected = MemoryDocument(
        "public account",
        {
            "typ": "fact",
            "knowledge_index": True,
            "knowledge_id": "F1",
            "ts": clock_scene.ts - 30 * DAY,
            "importance": 3,
        },
        "view-F1",
        "public account",
    )
    result = ranked_fact_documents(clock_scene, [projected])
    assert str(result[0]) == "(1 Month ago) public account"
    assert result[0].raw == "public account"
    assert "PRIVATE" not in str(result)
    projected.meta["importance"] = 1
    assert ranked_fact_documents(clock_scene, [projected]) == []


@pytest.mark.asyncio
async def test_cached_memory_rerenders_and_cuts_without_a_request(
    clock_scene, monkeypatch
):
    fact = ago(clock_scene, "F1", 1, 1)
    agent = get_agent("conversation")
    clock_scene.rag_cache = {}
    request = AsyncMock()
    monkeypatch.setattr(Prompt, "request", request)
    doc = MemoryDocument(fact.text, {"typ": "fact"}, fact.id, fact.text)
    with ActiveScene(clock_scene):
        await agent.rag_set_cache([doc])
        assert str((await agent.rag_get_cache())[0]) == "(1 Day ago) Event F1"
        clock_scene.ts += 20 * DAY
        assert await agent.rag_get_cache() == []
        fact.last_seen_ts = clock_scene.ts
        assert str((await agent.rag_get_cache())[0]) == "(Recently) Event F1"
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_selectors_share_cut_and_preserve_access(clock_scene, monkeypatch):
    clock_scene.character_data = {"Bob": Character(name="Bob")}
    old = ago(clock_scene, "F1", 30, 3, present=["Bob"])
    fresh = ago(clock_scene, "F2", 1, 3, present=["Bob"])
    stale = ago(clock_scene, "F3", 30, 1, present=["Bob"])
    unknown = ago(clock_scene, "F4", 1, 3, present=[])
    request = AsyncMock()
    monkeypatch.setattr(Prompt, "request", request)
    assert facts_about(clock_scene, "Event", character="Bob") == [fresh, old]
    assert previous_facts(clock_scene, limit=4) == [unknown, fresh, old, stale]
    known, total = known_facts(clock_scene, "Bob", limit=4)
    assert [fact.id for fact in known] == [fresh.id, old.id]
    assert total == 3
    with ActiveScene(clock_scene):
        assert await absence_facts(clock_scene, "Bob") == [unknown]
        context = await standard_analysis_context(
            clock_scene, clock_scene.character_data["Bob"], 1000
        )
    assert render_fact(clock_scene, fresh) in context["text"]
    assert render_fact(clock_scene, unknown) in context["text"]
    assert stale.text not in context["text"]
    request.assert_not_awaited()


FACT_INPUTS = {
    "previous_facts",
    "absence",
    "facts",
    "known_facts",
    "absence_facts",
    "fact",
}


def fact_templates():
    paths = Path("src/talemate/prompts/templates")
    environment = Environment(extensions=[CaptureContextExtension])
    return [
        str(path.relative_to(paths).with_suffix("")).replace("/", ".")
        for path in sorted(paths.rglob("*.jinja2"))
        if any(
            node.name in FACT_INPUTS and node.ctx == "load"
            for node in environment.parse(path.read_text()).find_all(nodes.Name)
        )
    ]


@pytest.mark.parametrize("template", fact_templates())
@pytest.mark.parametrize("audience", [False, True])
def test_every_fact_template_renders_markers(clock_scene, template, audience):
    fact = ago(clock_scene, "F1", 21, 3)
    variables = dict(
        scene=clock_scene,
        speaker="Alice",
        listeners="Bob",
        line="Alice: Hello.",
        recent_lines=[],
        absence={"Bob": [fact]},
        establish_facts=True,
        previous_facts=[fact],
        facts=[fact],
        known_facts=[fact],
        absence_facts=[fact],
        fact=fact,
        dialogue="Alice: Hello.",
        max_tokens=8192,
        num_extra_context=0,
        extra_context=[],
        summarization_method="balanced",
        extract_facts=True,
        audience_summary=("Alice", "Bob") if audience else None,
    )
    with ActiveScene(clock_scene):
        rendered = Prompt.get(template, vars=variables).render()
    lines = [line for line in rendered.splitlines() if fact.text in line]
    assert lines
    assert all(fact_time(clock_scene, fact) in line for line in lines), (
        template,
        lines,
    )
    if template in {"conversation.knowledge-ledger", "summarizer.summarize-dialogue"}:
        extraction_line = f"Fact: {fact.text} | Record age (metadata, do not copy): {fact_time(clock_scene, fact)}"
        assert extraction_line in rendered
        assert "Do not copy it into extracted facts." in rendered


@pytest.mark.parametrize("parse", [True, False])
@pytest.mark.parametrize(
    "marked,text",
    [
        ("(1 Month ago) Edwin owns the lighthouse.", "Edwin owns the lighthouse."),
        (
            "(Long ago) the lighthouse keeper drowned.",
            "(Long ago) the lighthouse keeper drowned.",
        ),
        (
            "(Two years ago) Mara left the island.",
            "(Two years ago) Mara left the island.",
        ),
        (
            "(Years ago) Edwin promised never to return.",
            "(Years ago) Edwin promised never to return.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_copied_record_age_cannot_enter_stored_text(
    clock_scene, monkeypatch, parse, marked, text
):
    parsed = (
        parse_facts(json.dumps([{"text": marked}]))
        if parse
        else [ParsedFact(text=marked)]
    )
    if parse:
        assert parsed[0].text == text
    monkeypatch.setattr(
        "talemate.knowledge.facts._near_duplicate", AsyncMock(return_value=None)
    )
    write = AsyncMock()
    monkeypatch.setattr(get_agent("memory"), "add_many", write)
    stored = await store_facts(clock_scene, "archive", [], clock_scene.ts, parsed, 0.15)
    assert stored[0].text == text
    assert write.await_args.args[0][0]["text"] == text


@pytest.mark.parametrize("days,importance", [(3, 1), (42, 2), (450, 3)])
def test_default_cut_days_and_zero_floor_off(clock_scene, days, importance):
    fact = ago(clock_scene, "F1", days, importance)
    assert not fact_chronology(clock_scene, fact).eligible
    assert fact_chronology(clock_scene, fact, {**DEFAULTS, "score_floor": 0}).eligible
