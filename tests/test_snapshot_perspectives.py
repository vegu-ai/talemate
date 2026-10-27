from _knowledge_step_helpers import push_and_step
import copy
import json
from unittest.mock import DEFAULT, AsyncMock

import pytest

import test_perception_lifecycle as cases
from talemate.character import Character
from talemate.instance import get_agent
from talemate.agents.context import ActiveAgent
from talemate.knowledge.perspectives import add_disclosure, reset_perspectives
from talemate.knowledge.snapshots import (
    snapshot_audience_context,
    snapshot_example,
    snapshot_for,
)
from talemate.load import load_scene_from_data
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage, TimePassageMessage
from talemate.world_state import WorldState

pytestmark = pytest.mark.asyncio
setup = cases.setup
SECRET = "She plans to poison the governor at the hidden refuge."
PUBLIC = "Bob has a bandaged arm."
PRIVATE = f"Bob has a bandaged arm. {SECRET}"


def views(public=PUBLIC, private=PRIVATE):
    return [
        {
            "audience": ["Alice"],
            "status": "ready" if public else "omitted",
            "text": public,
        },
        {
            "audience": ["Bob"],
            "status": "ready" if private else "omitted",
            "text": private,
        },
    ]


def payload():
    return {
        "characters": {
            "Bob": {
                "snapshot": PRIVATE,
                "emotion": "murderous anticipation",
                "mentions": ["Bob"],
                "views": views(),
            }
        },
        "items": {
            "Poison vial": {
                "snapshot": "A lethal poison vial disguised as medicine.",
                "views": views("A bottle of medicine.", "A bottle of poison."),
            }
        },
        "places": {
            "Hidden refuge": {
                "snapshot": "A hidden refuge below the governor's house.",
                "views": views(None, "The hidden refuge below the governor's house."),
            }
        },
        "location": "The hidden refuge below the governor's house.",
        "location_views": views(
            "A dim room.", "The hidden refuge below the governor's house."
        ),
    }


@pytest.fixture
async def prepared(setup, monkeypatch):
    scene, summarizer, request = setup
    message = NarratorMessage(message=PRIVATE)
    request.return_value = cases.result(cases.answer(PUBLIC, PRIVATE))
    await push_and_step(scene, message)
    world = get_agent("world_state")
    monkeypatch.setattr(
        world.actions["update_world_state"].config["inject_as_scene_memory"],
        "value",
        True,
    )
    monkeypatch.setattr(
        summarizer.client,
        "_prompt_generation_error",
        AsyncMock(side_effect=AssertionError("unexpected analysis error")),
    )
    request.reset_mock()

    def capture_inputs(*args, **kwargs):
        if snapshot_request := kwargs.get("vars", {}).get("snapshot_request"):
            snapshot_request.context_history(budget=0)
        return DEFAULT

    request.side_effect = capture_inputs
    return scene, world, request, message


async def apply(prepared, raw=None):
    scene, world, request, _ = prepared
    request.return_value = ("response", payload() if raw is None else raw)
    await world.apply_snapshot_update(scene.world_state)


def render(scene, viewer=None):
    return Prompt.get(
        "common.world-state-snapshot", vars={"scene": scene, "knowledge_viewer": viewer}
    ).render()


@pytest.mark.parametrize("durable", [True, False])
async def test_single_request_scopes_all_snapshot_fields_and_retains_reader(
    prepared, monkeypatch, durable
):
    scene, world, request, _ = prepared
    monkeypatch.setattr(
        world.actions["update_world_state"].config["durable_snapshot"], "value", durable
    )
    await apply(prepared)
    assert request.await_count == 1
    context = request.call_args.kwargs["vars"]["snapshot_audience_context"]
    assert PUBLIC in str(context["cast"][0]) and SECRET not in str(context["cast"][0])
    actor = render(scene, "Alice")
    assert PUBLIC in actor and "bottle of medicine" in actor and "dim room" in actor
    assert (
        "poison" not in actor.lower()
        and "refuge" not in actor
        and "murderous" not in actor
    )
    assert SECRET in render(scene, "Bob")
    reader = render(scene)
    assert SECRET in reader and "murderous" in reader and "Poison Vial" in reader
    monkeypatch.setattr(
        world.actions["update_world_state"].config["inject_as_scene_memory"],
        "value",
        False,
    )
    assert not render(scene, "Alice").strip()


@pytest.mark.parametrize(
    "change",
    [
        "snapshot",
        "emotion",
        "location",
        "invalid_views",
        "missing_audience",
        "injected_proof",
    ],
)
async def test_delta_never_reuses_broader_views_for_new_content(prepared, change):
    scene, _, _, _ = prepared
    await apply(prepared)
    raw = {"characters": {"Bob": {"snapshot": "A new secret."}}}
    if change == "emotion":
        raw = {"characters": {"Bob": {"emotion": "private motive"}}}
    elif change == "location":
        raw = {"location": "Secret new location."}
    elif change == "invalid_views":
        raw["characters"]["Bob"]["views"] = views()
        raw["characters"]["Bob"]["views"][0]["audience"] = ["Nobody"]
    elif change == "missing_audience":
        raw["characters"]["Bob"]["views"] = views()[1:]
    elif change == "injected_proof":
        raw["characters"]["Bob"]["perspectives"] = scene.world_state.characters[
            "Bob"
        ].perspectives.model_dump()
    await apply(prepared, raw)
    projected = snapshot_for(scene, "Alice")
    if change == "location":
        assert projected["location"] is None
        assert projected["characters"] == [PUBLIC]
    else:
        assert not projected["characters"]
        assert scene.world_state.characters["Bob"].snapshot


async def test_durable_mentions_omissions_and_explicit_view_change(prepared):
    scene, _, _, _ = prepared
    await apply(prepared)
    prior = scene.world_state.characters["Bob"].perspectives
    await apply(prepared, {"characters": {"Bob": {"mentions": ["the patient"]}}})
    assert scene.world_state.characters["Bob"].perspectives == prior
    await apply(prepared, {"characters": {"Bob": {"views": views(None, PRIVATE)}}})
    assert not snapshot_for(scene, "Alice")["characters"]
    assert snapshot_for(scene, "Bob")["characters"] == [PRIVATE]
    await apply(prepared, {"characters": {"Bob": None}, "location": None})
    assert not snapshot_for(scene, "Bob")["characters"]
    assert snapshot_for(scene, "Bob")["location"] is None


async def test_snapshot_reset_removes_location_classification(prepared):
    scene, _, _, _ = prepared
    await apply(prepared)
    scene.world_state.reset()
    assert scene.world_state.location_perspectives is None
    assert not scene.world_state.characters


@pytest.mark.parametrize("status", ["pending", "failed", "omitted"])
async def test_nonready_views_never_fall_back(prepared, status):
    scene, _, _, _ = prepared
    raw = payload()
    raw["characters"]["Bob"]["views"][0] = {
        "audience": ["Alice"],
        "status": status,
        "text": None,
    }
    await apply(prepared, raw)
    assert not snapshot_for(scene, "Alice")["characters"]
    assert SECRET in render(scene)


@pytest.mark.parametrize(
    "change", ["source_edit", "delete", "reset", "canonical_edit", "rename", "remove"]
)
async def test_stale_views_omit_without_reader_fallback(prepared, change):
    scene, _, _, message = prepared
    await apply(prepared)
    if change == "source_edit":
        message.message += " Changed."
    elif change == "delete":
        scene.pop_history(typ=message.typ, id=message.id)
    elif change == "reset":
        scene.history = []
        reset_perspectives(scene)
    elif change == "canonical_edit":
        scene.world_state.characters["Bob"].emotion = "A changed private emotion"
    elif change == "rename":
        scene.character_data["Alice"].rename("Alicia")
    else:
        await scene.remove_character(
            scene.character_data["Alice"], purge_from_memory=False
        )
        scene.world_state.validate_snapshot_audiences(scene.character_data)
    viewer = (
        "Alicia" if change == "rename" else "Bob" if change == "remove" else "Alice"
    )
    characters = snapshot_for(scene, viewer)["characters"]
    if change == "source_edit":
        # an edit flags the cited view; the snapshot keeps the last known view
        assert characters == ["Bob has a bandaged arm."]
    else:
        assert not characters
    assert SECRET in render(scene)


async def test_reload_preserves_views_and_rejects_unresolved_audiences(
    prepared, monkeypatch
):
    scene, _, _, _ = prepared
    await apply(prepared)
    saved = json.loads(scene.json)
    monkeypatch.setattr(get_agent("memory"), "set_db", AsyncMock())
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    await load_scene_from_data(scene, saved, name="snapshots.json")
    assert PUBLIC in render(scene, "Alice") and SECRET not in render(scene, "Alice")
    bad = copy.deepcopy(saved)
    bad["world_state"]["characters"]["Bob"]["perspectives"]["views"][0]["audience"] = [
        "Unknown"
    ]
    with pytest.raises(ValueError, match="Unresolved snapshot audience"):
        await load_scene_from_data(scene, bad, name="bad-snapshot.json")


async def test_disclosures_and_inflight_source_edits_are_checked(prepared):
    scene, _, request, message = prepared
    add_disclosure(scene, audience=["Alice"], text="The bottle is medicine.")
    context = snapshot_audience_context(scene, 4096)
    assert "The bottle is medicine" in str(context["cast"][0])

    async def change_during_request(*args, **kwargs):
        kwargs["vars"]["snapshot_request"].context_history(budget=0)
        message.message += " Changed during generation."
        return "response", payload()

    request.side_effect = change_during_request
    await prepared[1].apply_snapshot_update(scene.world_state)
    assert not snapshot_for(scene, "Alice")["characters"]
    # A response based on the replaced source cannot publish even reader data.
    assert not render(scene).strip()
    assert scene.world_state.snapshot_provenance is None


async def test_scene_switch_cannot_apply_snapshot_to_new_scene(prepared, monkeypatch):
    scene, world, request, _ = prepared
    old = scene.world_state.model_dump()

    async def switch_scene(*args, **kwargs):
        kwargs["vars"]["snapshot_request"].context_history(budget=0)
        monkeypatch.setattr(world, "scene", object())
        return "response", payload()

    request.side_effect = switch_scene
    await world.apply_snapshot_update(scene.world_state)
    assert scene.world_state.model_dump() == old


async def test_legacy_uses_reader_fields_and_has_no_audience_context(
    prepared, monkeypatch
):
    scene, _, request, _ = prepared
    scene.knowledge_eligibility = "legacy"
    await apply(prepared)
    assert request.call_args.kwargs["vars"]["snapshot_audience_context"] is None
    assert SECRET in render(scene, "Alice")
    dumped = scene.world_state.model_dump()
    assert "location_perspectives" not in dumped
    assert "perspectives" not in dumped["characters"]["Bob"]


async def test_unclassified_intro_and_time_cut_stay_hidden(prepared):
    scene, _, _, _ = prepared
    await apply(prepared)
    scene.history.append(TimePassageMessage(message="A day passes."))
    await apply(prepared)
    assert not snapshot_for(scene, "Alice")["characters"]
    assert not snapshot_for(scene, "Alice")["location"]
    scene.world_state = WorldState()
    scene.history = []
    scene.knowledge = None
    scene.intro = "Bob has a bandaged arm and a secret plan."
    await apply(prepared)
    assert not snapshot_for(scene, "Alice")["characters"]
    assert not snapshot_for(scene, "Alice")["location"]


@pytest.mark.parametrize("durable", [True, False])
@pytest.mark.parametrize("data_format", ["json", "yaml"])
async def test_generation_prompt_includes_evidence_and_complete_replacements(
    prepared, monkeypatch, data_format, durable
):
    _, world, request, _ = prepared
    monkeypatch.setattr(
        world.actions["update_world_state"].config["durable_snapshot"], "value", durable
    )
    await apply(prepared)
    monkeypatch.setattr(world.actions["use_long_term_memory"], "enabled", False)
    prompt = Prompt.get(
        "world_state.request-world-state-v2", vars=request.call_args.kwargs["vars"]
    )
    prompt.data_format_type = data_format
    with ActiveAgent(world, world.request_world_state):
        rendered = prompt.render()
    assert "ESTABLISHED AUDIENCE KNOWLEDGE" in rendered
    assert "location_views" in rendered and "audience" in rendered
    assert "bandaged arm" in rendered
    assert "COMPLETE character-facing replacement" in rendered
    if durable:
        assert "Omitted entities retain their existing state" in rendered
        assert "Every included entity carries a complete" in rendered
    else:
        assert "Omitted entities are removed" in rendered
        assert "Do not send audience-only entries" in rendered
        assert "Omitted entities retain their existing state" not in rendered
        assert "entity drop" not in rendered


async def test_arc_expand_narrative_perspective_does_not_select_snapshot_viewer(
    prepared, monkeypatch
):
    scene, _, _, _ = prepared
    await apply(prepared)
    narrator = get_agent("narrator")
    monkeypatch.setattr(narrator.actions["use_long_term_memory"], "enabled", False)
    prompt = Prompt.get(
        "narrator.arc-expand",
        vars={
            "scene": scene,
            "max_tokens": 4096,
            "beats": [],
            "following_beats": [],
            "preceding_text": "",
            "perspective": "Third person, past tense.",
            "director_notes": "",
            "extra_instructions": "",
            "response_length": 4096,
            "arc_info": None,
            "close_arc": False,
        },
    )
    with ActiveAgent(narrator, narrator.narrate_scene):
        rendered = prompt.render()
    assert SECRET in rendered


async def test_wholesale_views_only_keeps_named_reader_content_and_drops_omissions(
    prepared, monkeypatch
):
    scene, world, _, _ = prepared
    await apply(prepared)
    monkeypatch.setattr(
        world.actions["update_world_state"].config["durable_snapshot"], "value", False
    )
    await apply(
        prepared,
        {
            "characters": {"Bob": {"views": views(None, PRIVATE)}},
            "items": {
                "Poison vial": {"views": views("Medicine bottle.", "Poison bottle.")}
            },
        },
    )
    assert scene.world_state.characters["Bob"].snapshot == PRIVATE
    assert "lethal poison" in scene.world_state.items["Poison Vial"].snapshot
    assert snapshot_for(scene, "Bob")["characters"] == [PRIVATE]
    assert not snapshot_for(scene, "Alice")["characters"]
    assert not scene.world_state.places
    assert SECRET in render(scene)


@pytest.mark.parametrize("durable", [True, False])
async def test_examples_never_assign_facts_to_real_cast(prepared, durable):
    scene, _, _, _ = prepared
    context = snapshot_audience_context(scene, 4096)
    context["cast"][1]["established_knowledge"] = []
    example = snapshot_example(context, durable)
    entity = next(iter(example["characters"].values()))
    assert not set(scene.character_data) & example["characters"].keys()
    for key in ("snapshot", "emotion", "mentions"):
        assert all(name not in str(entity[key]) for name in scene.character_data)
    assert entity["views"][1]["status"] == "omitted"
    assert all(
        name not in str(view["text"])
        for name in scene.character_data
        for view in entity["views"]
    )
    assert bool(example["items"]) == durable
    if not durable:
        assert example["places"] == {}


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "unknown",
        "extra",
        "unexpected_key",
        "duplicate",
        "mixed_unknown",
        "host_evidence",
    ],
)
async def test_invalid_assignment_does_not_discard_other_audiences(prepared, bad):
    scene, _, _, _ = prepared
    raw = payload()
    entries = raw["characters"]["Bob"]["views"]
    if bad == "missing":
        entries.pop()
    elif bad == "unknown":
        entries[1]["audience"] = ["Nobody"]
    elif bad == "extra":
        entries.append({"audience": ["Nobody"], "status": "ready", "text": PRIVATE})
    elif bad == "unexpected_key":
        entries[1]["unexpected"] = True
    elif bad == "duplicate":
        entries.append(copy.deepcopy(entries[1]))
    elif bad == "mixed_unknown":
        entries[1]["audience"].append("Nobody")
    else:
        entries[1]["id"] = "model-invented-proof"
    await apply(prepared, raw)
    assert snapshot_for(scene, "Alice")["characters"] == [PUBLIC]
    assert snapshot_for(scene, "Bob")["characters"] == (
        [PRIVATE] if bad == "extra" else []
    )
    assert SECRET in render(scene)


async def test_inactive_unmentioned_cast_does_not_consume_evidence_budget(prepared):
    scene, _, request, _ = prepared
    original = snapshot_audience_context(scene, 4096)
    for number in range(30):
        name = f"Retired {number}"
        scene.character_data[name] = Character(name=name)
    assert snapshot_audience_context(scene, 4096) == original
    scene.history[-1].message += " Retired 4 is mentioned."
    await apply(prepared)
    cast = request.call_args.kwargs["vars"]["snapshot_audience_context"]["cast"]
    assert {item["name"] for item in cast} == {"Alice", "Bob", "Retired 4"}


@pytest.mark.parametrize("location", [{"name": "The refuge"}, ["The refuge"], 3])
async def test_malformed_location_cannot_authorize_new_views(prepared, location):
    scene, _, _, _ = prepared
    await apply(prepared)
    previous = scene.world_state.location
    await apply(
        prepared,
        {
            "location": location,
            "location_views": views("Private new location.", PRIVATE),
        },
    )
    assert scene.world_state.location == previous
    assert scene.world_state.location_perspectives is None
    assert snapshot_for(scene, "Alice")["location"] is None


async def test_host_validation_does_not_establish_semantic_support(prepared):
    scene, _, _, _ = prepared
    raw = payload()
    raw["characters"]["Bob"]["views"][0]["text"] = (
        "An unsupported assertion from the generating model."
    )
    await apply(prepared, raw)
    assert snapshot_for(scene, "Alice")["characters"] == [
        "An unsupported assertion from the generating model."
    ]


async def test_omitted_stale_entity_does_not_recover_on_refresh(prepared, monkeypatch):
    scene, world, _, message = prepared
    await apply(prepared)
    prior = scene.world_state.characters["Bob"].perspectives
    monkeypatch.setattr(
        world.actions["update_world_state"].config["eviction_threshold"], "value", 0
    )
    message.message += " Changed."
    for _ in range(4):
        await apply(prepared, {})
    assert scene.world_state.characters["Bob"].perspectives == prior
    # flagged by the edit, the last view stays readable until a repair
    assert snapshot_for(scene, "Alice")["characters"] == ["Bob has a bandaged arm."]
    assert SECRET in render(scene)


async def manual_add(prepared, entity):
    scene, world, request, message = prepared
    request.return_value = ("response", {"entity": entity})
    return await world.add_snapshot_entity(message.id, "poison vial")


async def test_manual_entity_scopes_views_per_audience(prepared):
    scene, _, request, _ = prepared
    result = await manual_add(
        prepared,
        {
            "resolved": True,
            "kind": "item",
            "name": "Poison vial",
            "snapshot": "A lethal poison vial disguised as medicine.",
            "mentions": ["bandaged arm"],
            "views": views("A bottle of medicine.", "A bottle of poison."),
        },
    )
    assert result.resolved is True
    assert scene.world_state.items["Poison Vial"].manual is True
    assert request.call_args.kwargs["vars"]["snapshot_audience_context"] is not None
    alice = render(scene, "Alice")
    assert "bottle of medicine" in alice and "poison" not in alice.lower()
    assert "bottle of poison" in render(scene, "Bob")
    assert "disguised as medicine" in render(scene)


async def test_manual_entity_without_views_stays_reader_only(prepared):
    scene, _, _, _ = prepared
    await manual_add(
        prepared,
        {
            "resolved": True,
            "kind": "item",
            "name": "Poison vial",
            "snapshot": "A lethal poison vial disguised as medicine.",
            "mentions": ["bandaged arm"],
        },
    )
    assert not render(scene, "Alice").strip()
    assert not render(scene, "Bob").strip()
    assert "disguised as medicine" in render(scene)


@pytest.mark.parametrize("data_format", ["json", "yaml"])
async def test_manual_add_prompt_carries_the_audience_rules(
    prepared, monkeypatch, data_format
):
    _, world, request, _ = prepared
    await manual_add(
        prepared,
        {
            "resolved": True,
            "kind": "item",
            "name": "Poison vial",
            "snapshot": "A lethal poison vial disguised as medicine.",
            "mentions": ["bandaged arm"],
            "views": views("A bottle of medicine.", "A bottle of poison."),
        },
    )
    monkeypatch.setattr(world.actions["use_long_term_memory"], "enabled", False)
    prompt = Prompt.get(
        "world_state.add-snapshot-entity", vars=request.call_args.kwargs["vars"]
    )
    prompt.data_format_type = data_format
    with ActiveAgent(world, world.add_snapshot_entity):
        rendered = prompt.render()
    assert "Audience replacements:" in rendered
    assert "COMPLETE character-facing replacement" in rendered
    assert "Alice" in rendered and "Bob" in rendered
    assert "bandaged arm" in rendered
