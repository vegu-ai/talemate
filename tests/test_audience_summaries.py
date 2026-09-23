import asyncio
import json
from pathlib import Path
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest
import talemate.emit.async_signals
import talemate.agents.summarize.audience_summaries as audience_summary_module

from talemate.character import Character
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.history import ArchiveEntry, LayeredArchiveEntry
from talemate.instance import get_agent
from talemate.knowledge import context
from talemate.knowledge.context import project_character_history
from talemate.knowledge.summaries import (
    summary_sources,
    summary_inputs,
    summary_coverage,
)
from talemate.load import load_scene_from_data
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage, DirectorMessage
from talemate.tale_mate import Actor, Scene
from talemate.world_state.templates import GenerationOptions

PRIVATE = "Alice hides the sapphire in her boot."
CLAIM = "Alice says the ledger was burned; Bob is uncertain whether to believe her."


def selected(scene, identity, name="Bob", layer=0):
    return select_character_view(
        scene, source_reference(scene, "summary", identity, layer=layer), name
    )


def publish(scene, message, alice, bob):
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": ["Alice"], "status": "ready", "text": alice},
            {
                "audience": ["Bob", "Cara"],
                "status": "ready" if bob else "omitted",
                **({"text": bob} if bob else {}),
            },
        ],
    )


@pytest.fixture
def summary_scene(scene, monkeypatch, request):
    scene.knowledge_eligibility = "perception"
    for name in ("Alice", "Bob", "Cara"):
        character = Character(name=name, is_player=name == "Alice")
        actor = Actor(character, get_agent("conversation"))
        actor.scene = scene
        scene.actors.append(actor)
        scene.character_data[name] = character
    scene.active_characters = ["Alice", "Bob", "Cara"]
    scene.history = [
        CharacterMessage(message="Alice: " + PRIVATE + " " + CLAIM),
        NarratorMessage(message="PRIVATE-WHISPER about the sapphire."),
        NarratorMessage(message="The rain stops."),
        NarratorMessage(message="A separate village rings its bell."),
        CharacterMessage(message="Bob: Recent dialogue."),
    ]
    scene.history[0].present = ["Alice", "Bob", "Cara"]
    scene.history[1].present = ["Alice"]
    publish(scene, scene.history[0], PRIVATE + " " + CLAIM, CLAIM)
    publish(scene, scene.history[1], "Alice hears a PRIVATE-WHISPER.", None)
    for message in scene.history[2:]:
        publish(scene, message, message.message, message.message)
    scene.archived_history = [
        ArchiveEntry(
            id="base-a", text="READER-A " + PRIVATE, start=0, end=1
        ).model_dump(exclude_none=True),
        ArchiveEntry(id="base-b", text="READER-B", start=2, end=2).model_dump(
            exclude_none=True
        ),
        ArchiveEntry(id="base-c", text="READER-C", start=3, end=3).model_dump(
            exclude_none=True
        ),
    ]
    scene.layered_history = [
        [
            LayeredArchiveEntry(
                id="layer-a", text="READER-LAYER", start=0, end=1, ts_start=0, ts_end=0
            ).model_dump(exclude_none=True)
        ]
    ]
    summarizer = get_agent("summarizer")
    summarizer.connect(scene)
    calls = []

    async def summarize(text, **kwargs):
        calls.append((text, kwargs))
        return "Compressed: " + text

    if not getattr(request, "param", False):
        monkeypatch.setattr(summarizer, "summarize", summarize)
        monkeypatch.setattr(summarizer, "summarize_events", summarize)
    monkeypatch.setattr(summarizer, "schedule_audience_summaries", AsyncMock())
    with ActiveScene(scene):
        yield scene, summarizer, calls


async def generate_all(scene, summarizer):
    for entry in scene.archived_history:
        await summarizer.ensure_summary_views(scene, entry["id"])
    await summarizer.ensure_summary_views(scene, "layer-a", 1)


@pytest.mark.asyncio
async def test_mixed_audiences_at_base_and_layered_levels(summary_scene):
    scene, summarizer, calls = summary_scene
    readers = [entry["text"] for entry in scene.archived_history]
    await generate_all(scene, summarizer)
    for identity, layer in [("base-a", 0), ("layer-a", 1)]:
        bob, alice = (
            selected(scene, identity, layer=layer),
            selected(scene, identity, "Alice", layer),
        )
        assert bob.status == alice.status == "ready"
        assert CLAIM in bob.text
        assert PRIVATE not in bob.text
        assert "PRIVATE-WHISPER" not in bob.text
        assert PRIVATE in alice.text
        assert bob.source == selected(scene, identity, "Cara", layer).source
    assert readers == [entry["text"] for entry in scene.archived_history]
    for text, options in calls:
        assert not options["extra_context"]
        assert "READER-" not in text
        if "Bob" in options["audience"]:
            assert PRIVATE not in text
    history = "\n".join(project_character_history(scene, "Bob"))
    assert CLAIM in history
    assert history.count(CLAIM) == 1
    assert "READER-" not in history
    assert PRIVATE not in history


@pytest.mark.asyncio
async def test_source_edit_invalidates_base_and_layer_but_preserves_other_branches(
    summary_scene,
):
    scene, summarizer, calls = summary_scene
    await generate_all(scene, summarizer)
    unaffected = deepcopy(scene.archived_history[1:])
    calls.clear()
    scene.edit_message(scene.history[0].id, "Alice: Corrected reader passage.")
    assert selected(scene, "base-a").status == "pending"
    assert selected(scene, "layer-a", layer=1).status == "pending"
    assert selected(scene, "base-b").status == "ready"
    assert selected(scene, "base-c").status == "ready"
    publish(
        scene,
        scene.history[0],
        "Alice revises her claim.",
        "Alice corrects her earlier claim.",
    )
    fallback = "\n".join(project_character_history(scene, "Bob"))
    assert "Alice corrects her earlier claim." in fallback
    assert CLAIM not in fallback
    assert "READER-" not in fallback
    await summarizer.repair_summary_views(scene)
    assert len(calls) == 4
    assert scene.archived_history[1:] == unaffected
    assert selected(scene, "layer-a", layer=1).status == "ready"


@pytest.mark.asyncio
async def test_editing_one_audience_preserves_ready_sibling_summaries(summary_scene):
    scene, summarizer, calls = summary_scene
    await generate_all(scene, summarizer)
    bob = selected(scene, "base-a")
    layered_bob = selected(scene, "layer-a", layer=1)
    calls.clear()
    publish(
        scene, scene.history[0], "Alice remembers a different private detail.", CLAIM
    )
    assert selected(scene, "base-a", "Alice").status == "pending"
    assert selected(scene, "layer-a", "Alice", 1).status == "pending"
    assert selected(scene, "base-a") == bob
    assert selected(scene, "layer-a", layer=1) == layered_bob
    await summarizer.repair_summary_views(scene)
    assert len(calls) == 2
    assert all(options["audience"] == ("Alice",) for _, options in calls)
    assert selected(scene, "base-a") == bob
    assert selected(scene, "layer-a", layer=1) == layered_bob


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed"])
async def test_incomplete_input_never_produces_ready_summary(summary_scene, status):
    scene, summarizer, calls = summary_scene
    message = scene.history[1]
    message.present = ["Alice", "Bob", "Cara"]
    message.mark_revision_committed()
    outputs = [{"audience": ["Alice"], "status": "ready", "text": PRIVATE}]
    if status != "unavailable":
        outputs.append({"audience": ["Bob", "Cara"], "status": status})
    set_source_perspectives(scene, "message", message.id, outputs)
    await generate_all(scene, summarizer)
    assert selected(scene, "base-a").status == "pending"
    assert selected(scene, "layer-a", layer=1).status == "pending"
    assert all("Bob" not in options["audience"] for _, options in calls if CLAIM in _)


@pytest.mark.parametrize("present", [None, [], ["Alice"]])
async def test_recordless_message_only_blocks_present_summary_audiences(
    summary_scene, present
):
    scene, summarizer, calls = summary_scene
    message = NarratorMessage(message="No one hears the distant bell.", present=present)
    scene.history[1] = message
    entry = scene.archived_history[0]
    inputs = summary_inputs(scene, entry, 0)
    for name, summary_input in inputs.items():
        assert summary_input.status == (
            "pending" if name in (present or ()) else "ready"
        )
        assert message.id not in {source.id for source in summary_input.sources}
    await asyncio.wait_for(summarizer.ensure_summary_views(scene, entry["id"]), 2)
    assert selected(scene, entry["id"], "Bob").status == "ready"
    assert selected(scene, entry["id"], "Alice").status == (
        "pending" if present else "ready"
    )
    assert len(calls) == (1 if present else 2)
    assert summarizer._summary_waiting.get(scene, set()) == {
        (0, entry["id"], name) for name in (present or ())
    }
    assert message.knowledge is None


async def test_recordless_omitted_summary_needs_no_request(summary_scene):
    scene, summarizer, calls = summary_scene
    message = NarratorMessage(message="No one hears the distant bell.")
    scene.history[1] = message
    entry = scene.archived_history[0]
    entry.update(start=1, end=1)
    set_source_perspectives(
        scene, "summary", entry["id"], [{"audience": ["Alice"], "status": "pending"}]
    )
    inputs = summary_inputs(scene, entry, 0)
    assert inputs["Alice"].status == "omitted"
    assert inputs["Alice"].sources == ()
    await asyncio.wait_for(summarizer.ensure_summary_views(scene, entry["id"]), 2)
    assert selected(scene, entry["id"], "Alice").status == "omitted"
    assert calls == []
    assert summarizer._summary_waiting.get(scene, set()) == set()
    assert message.knowledge is None


@pytest.mark.asyncio
async def test_omitted_input_is_a_durable_dependency(summary_scene):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    bob_view = next(
        v
        for v in scene.archived_history[0]["knowledge"]["views"]
        if "Bob" in v["audience"]
    )
    assert {dep["id"] for dep in bob_view["sources"]} == {
        m.id for m in scene.history[:2]
    }
    publish(
        scene,
        scene.history[1],
        "Alice hears more.",
        "Bob now hears a public correction.",
    )
    assert selected(scene, "base-a").status == "pending"
    assert selected(scene, "layer-a", layer=1).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_status", ["omitted", "pending", "failed"])
async def test_all_omitted_summary_skips_request_and_is_invalidated(
    summary_scene, stored_status
):
    scene, summarizer, calls = summary_scene
    scene.archived_history[0].update(start=1, end=1)
    set_source_perspectives(
        scene,
        "message",
        scene.history[1].id,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice hears a whisper.",
            },
            {"audience": ["Bob", "Cara"], "status": stored_status},
        ],
    )
    await asyncio.wait_for(summarizer.ensure_summary_views(scene, "base-a"), 2)
    assert selected(scene, "base-a").status == "omitted"
    assert len(calls) == 1
    publish(scene, scene.history[1], "Alice hears more.", "Bob hears it too.")
    assert selected(scene, "base-a").status == "pending"


@pytest.mark.asyncio
async def test_stale_inflight_response_is_discarded(summary_scene, monkeypatch):
    scene, summarizer, _ = summary_scene

    async def changed(text, **kwargs):
        publish(
            scene,
            scene.history[0],
            "Changed private evidence.",
            "Changed public evidence.",
        )
        return "STALE MODEL RESPONSE"

    monkeypatch.setattr(summarizer, "summarize", changed)
    await summarizer.ensure_summary_views(scene, "base-a")
    assert selected(scene, "base-a").status == "pending"
    assert "STALE MODEL RESPONSE" not in str(scene.archived_history[0])


@pytest.mark.asyncio
async def test_empty_response_exposes_retry_and_preserves_reader(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    response = AsyncMock(side_effect=["", "Retried summary.", "Bob summary."])
    monkeypatch.setattr(summarizer, "summarize", response)
    retry = AsyncMock(return_value="retry")
    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", retry)
    original = scene.archived_history[0]["text"]
    await summarizer.ensure_summary_views(scene, "base-a")
    retry.assert_awaited_once()
    assert selected(scene, "base-a", "Alice").text == "Retried summary."
    assert scene.archived_history[0]["text"] == original


@pytest.mark.asyncio
async def test_cancellation_leaves_safe_fallback(summary_scene, monkeypatch):
    scene, summarizer, _ = summary_scene
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(side_effect=GenerationCancelled("cancel"))
    )
    await summarizer.ensure_summary_views(scene, "base-a")
    assert selected(scene, "base-a", "Alice").status == "failed"
    assert PRIVATE not in "\n".join(project_character_history(scene, "Bob"))


@pytest.mark.asyncio
async def test_projection_respects_revision_prefix_and_budget(summary_scene):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    before = "\n".join(
        project_character_history(scene, "Bob", before_message_id=scene.history[2].id)
    )
    assert CLAIM in before
    assert "rain" not in before
    assert "Recent dialogue" not in before
    assert project_character_history(scene, "Bob", budget=0) == []


@pytest.mark.asyncio
async def test_legacy_summary_helper_adds_no_requests_or_records(
    summary_scene, monkeypatch
):
    scene, summarizer, calls = summary_scene
    scene.knowledge_eligibility = "legacy"
    await summarizer.ensure_summary_views(scene, "base-a")
    await summarizer.schedule_audience_summaries(scene)
    assert calls == []
    assert "knowledge" not in scene.archived_history[0]


@pytest.mark.asyncio
async def test_higher_layer_dependencies_keep_exact_layer_identity(summary_scene):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    scene.layered_history.append(
        [
            LayeredArchiveEntry(
                id="layer-b", text="READER-HIGHER", start=0, end=0
            ).model_dump(exclude_none=True)
        ]
    )
    await summarizer.ensure_summary_views(scene, "layer-b", 2)
    view = selected(scene, "layer-b", layer=2)
    assert CLAIM in view.text and PRIVATE not in view.text
    stored = next(
        v
        for v in scene.layered_history[1][0]["knowledge"]["views"]
        if "Bob" in v["audience"]
    )
    assert stored["sources"][0]["layer"] == 1
    assert stored["sources"][0]["id"] == "layer-a"
    scene.edit_message(scene.history[0].id, "Changed.")
    assert selected(scene, "layer-b", layer=2).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["summarize", "summarize_events"])
async def test_existing_summary_templates_receive_only_audience_sources(
    summary_scene, monkeypatch, method
):
    scene, summarizer, _ = summary_scene
    captured = []

    async def request(template, client, kind, vars, **kwargs):
        rendered = Prompt.get(template, vars=vars).render()
        captured.append((rendered, kind))
        return "Alice said the ledger was burned.", {
            "summary": "Alice said the ledger was burned.",
            "cleaned": "Alice said the ledger was burned.",
        }

    monkeypatch.setattr(Prompt, "request", request)
    scene.intro = "UNSAFE-INTRO"
    await getattr(type(summarizer), method)(
        summarizer, CLAIM, audience=("Bob", "Cara"), skip_author_hooks=True
    )
    prompt, kind = captured[0]
    assert kind.startswith("summarize_")
    assert CLAIM in prompt
    assert "UNSAFE-INTRO" not in prompt
    assert "READER-" not in prompt
    assert PRIVATE not in prompt
    assert "Never turn an attributed claim into an unqualified fact" in prompt
    assert "uncertainty and established beliefs" in prompt


@pytest.mark.asyncio
async def test_deleted_summary_does_not_accept_inflight_output(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene

    async def remove(text, **kwargs):
        scene.archived_history.clear()
        return "ORPHAN OUTPUT"

    monkeypatch.setattr(summarizer, "summarize", remove)
    await summarizer.ensure_summary_views(scene, "base-a")
    assert scene.archived_history == []


@pytest.mark.asyncio
@pytest.mark.parametrize("absent_view", [False, True])
async def test_saved_vs_original_dependencies_and_selection_survive_reload(
    summary_scene, tmp_path, monkeypatch, absent_view
):
    scene, summarizer, _ = summary_scene
    if absent_view:
        set_source_perspectives(
            scene,
            "message",
            scene.history[1].id,
            [{"audience": ["Alice"], "status": "ready", "text": PRIVATE}],
        )
    await generate_all(scene, summarizer)
    original = json.loads(scene.json)
    expected = selected(scene, "layer-a", layer=1)
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "set_db", AsyncMock(), raising=False)
    monkeypatch.setattr(memory, "close_db", Mock(), raising=False)
    monkeypatch.setattr(
        memory, "get_document", AsyncMock(return_value={}), raising=False
    )
    await load_scene_from_data(
        scene, deepcopy(original), name="audience-summaries.json"
    )
    await scene.save()
    path = Path(scene.save_dir) / "audience-summaries.json"
    saved = json.loads(path.read_text())
    for saved_message, original_message in zip(
        saved["history"], original["history"], strict=True
    ):
        assert saved_message["knowledge"] == original_message["knowledge"]
        assert saved_message["message"] == original_message["message"]
        assert saved_message["id"] == original_message["id"]
    for key in ("archived_history", "layered_history", "knowledge"):
        assert saved[key] == original[key]
    await load_scene_from_data(scene, saved, name=str(path))
    assert selected(scene, "layer-a", layer=1) == expected
    scene.edit_message(scene.history[0].id, "Edited after reload.")
    assert selected(scene, "base-a").status == "pending"
    assert selected(scene, "layer-a", layer=1).status == "pending"
    assert selected(scene, "base-c").status == "ready"


@pytest.mark.asyncio
async def test_base_archive_creation_generates_audience_views(
    summary_scene, monkeypatch
):
    scene, summarizer, calls = summary_scene
    scene.archived_history = []
    scene.layered_history = []
    scene.intro = "SHARED-AUTHOR-INTRO"
    summarizer.actions["archive"].enabled = True
    summarizer.actions["archive"].config["threshold"].value = 1
    monkeypatch.setattr(summarizer, "analyze_dialoge", AsyncMock(return_value=None))

    async def summarize(text, **kwargs):
        calls.append((text, kwargs))
        if not kwargs.get("audience"):
            return "Complete reader summary."
        return text

    monkeypatch.setattr(summarizer, "summarize", summarize)
    assert await summarizer.build_archive(scene)
    entry = scene.archived_history[0]
    await summarizer.repair_summary_views(scene)
    assert entry["text"] == "Complete reader summary."
    assert CLAIM in selected(scene, entry["id"]).text
    assert PRIVATE not in selected(scene, entry["id"]).text
    assert all(
        "SHARED-AUTHOR-INTRO" not in text
        for text, options in calls
        if options.get("audience")
    )


@pytest.mark.asyncio
async def test_layer_commit_creates_views_from_selected_lower_summaries(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    for entry in scene.archived_history:
        await summarizer.ensure_summary_views(scene, entry["id"])
    scene.layered_history = []

    async def summarize(text, **kwargs):
        return text if kwargs.get("audience") else "Brief."

    monkeypatch.setattr(summarizer, "summarize_events", summarize)
    entry = await summarizer._lh_commit_chunk(scene.archived_history[:2], 0, 0, 1, 1)
    await summarizer.repair_summary_views(scene)
    assert entry["text"] == "Brief."
    assert CLAIM in selected(scene, entry["id"], layer=1).text
    assert PRIVATE not in selected(scene, entry["id"], layer=1).text


@pytest.mark.asyncio
async def test_summary_input_keeps_unprefixed_view_speaker(summary_scene):
    scene, summarizer, calls = summary_scene
    publish(scene, scene.history[0], PRIVATE, '"The ledger was burned."')
    await summarizer.ensure_summary_views(scene, "base-a")
    bob_input = next(text for text, options in calls if "Bob" in options["audience"])
    assert 'Alice: "The ledger was burned."' in bob_input
    assert PRIVATE not in bob_input


@pytest.mark.asyncio
async def test_unrelated_edit_does_not_retry_cancelled_summary_branch(
    summary_scene, monkeypatch
):
    scene, summarizer, calls = summary_scene
    await generate_all(scene, summarizer)
    original = summarizer.summarize
    scene.edit_message(scene.history[3].id, "Changed village passage.")
    publish(scene, scene.history[3], "The village is quiet.", "The village is quiet.")
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(side_effect=GenerationCancelled("cancel"))
    )
    await summarizer.ensure_summary_views(scene, "base-c")
    cancelled = deepcopy(scene.archived_history[2])
    monkeypatch.setattr(summarizer, "summarize", original)
    calls.clear()
    publish(scene, scene.history[0], "Alice revises her private recollection.", CLAIM)
    await summarizer.repair_summary_views(scene)
    assert len(calls) == 2
    assert scene.archived_history[2] == cancelled


@pytest.mark.asyncio
async def test_summary_repair_is_scheduled_off_the_callers_receive_loop(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    scene.edit_message(scene.history[0].id, "An edited passage.")
    release = asyncio.Event()

    async def repair(scene):
        await release.wait()
        summarizer._summary_dirty[scene].clear()

    monkeypatch.setattr(summarizer, "repair_summary_views", repair)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    await asyncio.wait_for(
        type(summarizer).schedule_audience_summaries(summarizer, scene), 0.5
    )
    task = summarizer._summary_rebuild_tasks[scene]
    assert not task.done()
    release.set()
    await task


@pytest.mark.asyncio
async def test_oversize_layer_falls_back_to_fitting_base_views(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    monkeypatch.setattr(context, "count_tokens", len)
    monkeypatch.setattr(
        type(scene), "conversation_format", property(lambda self: "chat")
    )
    outputs = deepcopy(scene.layered_history[0][0]["knowledge"]["views"])
    for output in outputs:
        output.pop("revision")
        if "Bob" in output["audience"]:
            output["text"] = "OVERSIZE " * 100
    set_source_perspectives(scene, "summary", "layer-a", outputs, layer=1)
    expected = [
        selected(scene, identity).text for identity in ("base-a", "base-b", "base-c")
    ]
    expected.append(scene.history[4].message)
    budget = sum(map(len, expected))
    projected = project_character_history(scene, "Bob", budget=budget)
    assert projected == expected
    assert sum(map(len, projected)) <= budget
    assert not any("OVERSIZE" in text or "READER-" in text for text in projected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prose",
    [
        "Alice suspects:\nBob stole the ledger.",
        'Alice says:\n"The ledger burned."\nBob is unsure.',
        "Bob believes Alice.",
        "Bob fled.",
    ],
)
async def test_layered_request_preserves_short_attribution_lines(
    summary_scene, monkeypatch, prose
):
    _, summarizer, _ = summary_scene
    monkeypatch.setattr(
        Prompt, "request", AsyncMock(return_value=(prose, {"cleaned": prose}))
    )
    result = await type(summarizer).summarize_events(
        summarizer, CLAIM, audience=("Bob",), skip_author_hooks=True
    )
    assert result == prose


@pytest.mark.asyncio
async def test_empty_layered_chunk_reaches_retry(summary_scene, monkeypatch):
    scene, summarizer, _ = summary_scene
    for entry in scene.archived_history:
        await summarizer.ensure_summary_views(scene, entry["id"])
    monkeypatch.setattr(
        summarizer,
        "summarize_events",
        AsyncMock(side_effect=["", "Alice summary.", "Bob summary."]),
    )
    retry = AsyncMock(return_value="retry")
    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", retry)
    await summarizer.ensure_summary_views(scene, "layer-a", 1)
    retry.assert_awaited_once()
    assert selected(scene, "layer-a", layer=1).text == "Bob summary."


@pytest.mark.asyncio
async def test_joining_cast_builds_partial_layer_and_drains_queue(summary_scene):
    scene, summarizer, calls = summary_scene
    for message in scene.history[:2]:
        outputs = []
        for view in message.knowledge.views:
            value = view.model_dump(exclude={"revision"})
            value["audience"] = [name for name in view.audience if name != "Cara"]
            outputs.append(value)
        set_source_perspectives(scene, "message", message.id, outputs)
    await generate_all(scene, summarizer)
    cara = selected(scene, "layer-a", "Cara", 1)
    assert cara.status == "ready"
    assert "rain" in cara.text
    assert CLAIM not in cara.text and PRIVATE not in cara.text
    assert "Cara" not in summary_inputs(scene, scene.archived_history[0], 0)
    await summarizer.repair_summary_views(scene)
    assert not summarizer._summary_dirty[scene]
    before = len(calls)
    await type(summarizer).schedule_audience_summaries(summarizer, scene)
    assert scene not in summarizer._summary_rebuild_tasks
    assert len(calls) == before
    outputs = deepcopy(scene.archived_history[0]["knowledge"]["views"])
    for output in outputs:
        output.pop("revision")
    outputs.append(
        {
            "audience": ["Cara"],
            "status": "ready",
            "text": "Cara learns Alice made a claim.",
        }
    )
    set_source_perspectives(scene, "summary", "base-a", outputs)
    assert selected(scene, "layer-a", "Cara", 1).status == "pending"


@pytest.mark.asyncio
async def test_partial_base_keeps_absence_dependency_in_restored_summary_records(
    summary_scene,
):
    scene, summarizer, _ = summary_scene
    set_source_perspectives(
        scene,
        "message",
        scene.history[1].id,
        [{"audience": ["Alice"], "status": "ready", "text": PRIVATE}],
    )
    await generate_all(scene, summarizer)
    assert selected(scene, "base-a").status == "ready"
    saved = json.loads(scene.json)
    assert (
        saved["archived_history"][0]["knowledge"]
        == scene.archived_history[0]["knowledge"]
    )
    scene.archived_history = deepcopy(saved["archived_history"])
    scene.layered_history = deepcopy(saved["layered_history"])
    assert selected(scene, "layer-a", layer=1).status == "ready"
    publish(scene, scene.history[1], PRIVATE, "Bob hears new evidence.")
    assert selected(scene, "base-a").status == "pending"
    assert selected(scene, "layer-a", layer=1).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["generation", "dialog"])
async def test_cancelled_group_does_not_abandon_sibling(
    summary_scene, monkeypatch, cancel
):
    scene, summarizer, _ = summary_scene

    async def respond(text, **kwargs):
        if kwargs["audience"] == ("Alice",):
            if cancel == "generation":
                raise GenerationCancelled("cancel")
            return ""
        return "Bob still recalls Alice's uncertain claim."

    monkeypatch.setattr(summarizer, "summarize", respond)
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="cancel")
    )
    await summarizer.ensure_summary_views(scene, "base-a")
    assert selected(scene, "base-a", "Alice").status == "failed"
    assert selected(scene, "base-a").status == "ready"
    assert selected(scene, "base-a", "Cara").status == "ready"
    assert not summarizer._summary_dirty[scene]


@pytest.mark.asyncio
async def test_edit_does_not_restart_cancelled_sibling_group(
    summary_scene, monkeypatch
):
    scene, summarizer, calls = summary_scene
    await generate_all(scene, summarizer)
    publish(scene, scene.history[0], PRIVATE + CLAIM, "Bob's changed memory.")
    original = summarizer.summarize
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(side_effect=GenerationCancelled("cancel"))
    )
    await summarizer.ensure_summary_views(scene, "base-a")
    failed = selected(scene, "base-a")
    monkeypatch.setattr(summarizer, "summarize", original)
    calls.clear()
    publish(
        scene,
        scene.history[0],
        "Alice changes her recollection.",
        "Bob's changed memory.",
    )
    await summarizer.repair_summary_views(scene)
    assert selected(scene, "base-a") == failed
    assert selected(scene, "base-a", "Alice").status == "ready"
    assert all(options["audience"] == ("Alice",) for _, options in calls)
    assert not summarizer._summary_dirty[scene]


@pytest.mark.asyncio
async def test_discarded_result_requeues_and_converges(summary_scene, monkeypatch):
    scene, summarizer, _ = summary_scene
    original = summarizer.summarize
    first = True

    async def respond(text, **kwargs):
        nonlocal first
        if first:
            first = False
            publish(
                scene,
                scene.history[0],
                "Alice corrects her account.",
                "Bob hears Alice's correction.",
            )
            return "STALE RESPONSE"
        return await original(text, **kwargs)

    monkeypatch.setattr(summarizer, "summarize", respond)
    await summarizer.queue_summary_views(scene, "base-a")
    await summarizer.repair_summary_views(scene)
    assert selected(scene, "base-a").status == "ready"
    assert "correction" in selected(scene, "base-a").text
    assert "STALE RESPONSE" not in str(scene.archived_history[0])
    assert not summarizer._summary_dirty[scene]


@pytest.mark.asyncio
async def test_mid_repair_edit_is_processed_without_another_trigger(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    publish(scene, scene.history[0], "Alice revises her account.", CLAIM)
    original = summarizer.summarize
    first = True

    async def respond(text, **kwargs):
        nonlocal first
        if first:
            first = False
            publish(scene, scene.history[3], "A new bell.", "A new bell.")
            await type(summarizer).schedule_audience_summaries(summarizer, scene)
        return await original(text, **kwargs)

    monkeypatch.setattr(summarizer, "summarize", respond)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    await type(summarizer).schedule_audience_summaries(summarizer, scene)
    await summarizer._summary_rebuild_tasks[scene]
    assert "new bell" in selected(scene, "base-c").text
    assert not summarizer._summary_dirty[scene]


@pytest.mark.asyncio
async def test_pending_inputs_wait_without_busy_repair_and_wake_on_readiness(
    summary_scene,
):
    scene, summarizer, calls = summary_scene
    set_source_perspectives(
        scene,
        "message",
        scene.history[0].id,
        [{"audience": ["Alice", "Bob", "Cara"], "status": "pending"}],
    )
    await summarizer.queue_summary_views(scene, "base-a")
    await summarizer.repair_summary_views(scene)
    assert not calls
    assert not summarizer._summary_dirty[scene]
    assert summarizer._summary_waiting[scene]
    await type(summarizer).schedule_audience_summaries(summarizer, scene)
    assert scene not in summarizer._summary_rebuild_tasks
    publish(scene, scene.history[0], PRIVATE, CLAIM)
    await summarizer.repair_summary_views(scene)
    assert selected(scene, "base-a").status == "ready"
    assert not summarizer._summary_waiting[scene]


@pytest.mark.asyncio
async def test_hidden_source_never_enters_new_summary_and_old_summary_descends(
    summary_scene,
):
    scene, summarizer, calls = summary_scene
    await generate_all(scene, summarizer)
    scene.history[0].hide()
    assert scene.history[0] not in summary_sources(scene, scene.archived_history[0], 0)
    hidden = project_character_history(scene, "Bob")
    assert all(CLAIM not in part for part in hidden)
    shown = project_character_history(scene, "Bob", show_hidden=True)
    assert selected(scene, "layer-a", layer=1).text in shown
    scene.archived_history[0].pop("knowledge")
    calls.clear()
    await summarizer.ensure_summary_views(scene, "base-a")
    assert all(CLAIM not in text for text, _ in calls)
    assert selected(scene, "base-a").status == "omitted"


@pytest.mark.asyncio
async def test_director_inside_summary_span_is_retained_on_request(summary_scene):
    scene, summarizer, _ = summary_scene
    scene.history.insert(
        1,
        DirectorMessage(
            message="Bob: Remember the promise.", meta={"character": "Bob"}
        ),
    )
    scene.archived_history[0]["end"] += 1
    for entry in scene.archived_history[1:]:
        entry["start"] += 1
        entry["end"] += 1
    await generate_all(scene, summarizer)
    assert selected(scene, "layer-a", layer=1).text in project_character_history(
        scene, "Bob"
    )
    projected = project_character_history(scene, "Bob", keep_director=True)
    assert selected(scene, "layer-a", layer=1).text not in projected
    assert any("Remember the promise" in part for part in projected)


@pytest.mark.asyncio
async def test_deleted_message_does_not_shift_summary_over_another_passage(
    summary_scene,
):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    unaffected = selected(scene, "base-b")
    scene.delete_message(scene.history[0].id)
    projected = project_character_history(scene, "Bob")
    assert selected(scene, "base-b") == unaffected
    assert unaffected.text in projected
    assert sum("rain stops" in part for part in projected) == 1
    assert sum("village rings" in part for part in projected) == 1
    assert sum("Recent dialogue" in part for part in projected) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["summarize", "summarize_events"])
@pytest.mark.parametrize("skip", [True, False])
async def test_author_hooks_are_explicit_at_request_boundary(
    summary_scene, monkeypatch, method, skip
):
    _, summarizer, _ = summary_scene
    before = AsyncMock()
    after = AsyncMock()
    monkeypatch.setattr(
        talemate.emit.async_signals.get("agent.summarization.summarize.before"),
        "send",
        before,
    )
    monkeypatch.setattr(
        talemate.emit.async_signals.get("agent.summarization.summarize.after"),
        "send",
        after,
    )
    monkeypatch.setattr(
        Prompt,
        "request",
        AsyncMock(return_value=(CLAIM, {"summary": CLAIM, "cleaned": CLAIM})),
    )
    await getattr(type(summarizer), method)(
        summarizer, CLAIM, audience=("Bob",), skip_author_hooks=skip
    )
    assert before.await_count == after.await_count == (0 if skip else 1)


@pytest.mark.asyncio
async def test_audience_failure_cannot_interrupt_reader_finalization(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    scene.archived_history = []
    scene.layered_history = []
    scene.ts = 999
    summarizer.actions["archive"].enabled = True
    summarizer.actions["archive"].config["threshold"].value = 1
    monkeypatch.setattr(summarizer, "analyze_dialoge", AsyncMock(return_value=None))

    async def respond(text, **kwargs):
        if not kwargs.get("audience"):
            return "Reader summary."
        raise GenerationCancelled("audience cancelled")

    monkeypatch.setattr(summarizer, "summarize", respond)
    after = AsyncMock()
    status = Mock()
    monkeypatch.setattr(
        talemate.emit.async_signals.get("agent.summarization.after_build_archive"),
        "send",
        after,
    )
    monkeypatch.setattr(scene, "emit_status", status)
    assert await summarizer.build_archive(scene)
    after.assert_awaited_once()
    status.assert_called_once()
    assert scene.archived_history[0]["ts"] == 0
    assert scene.ts == 999
    assert "facts_status" not in scene.archived_history[0]
    await summarizer.repair_summary_views(scene)
    assert selected(scene, scene.archived_history[0]["id"]).status == "failed"
    assert scene.archived_history[0]["text"] == "Reader summary."


@pytest.mark.asyncio
async def test_layer_queued_before_children_retains_inactive_audience(summary_scene):
    scene, summarizer, _ = summary_scene
    scene.active_characters = ["Alice", "Bob"]
    await summarizer.queue_summary_views(scene, "layer-a", 1)
    await summarizer.repair_summary_views(scene)
    assert (1, "layer-a", "Cara") in summarizer._summary_waiting[scene]
    for entry in scene.archived_history:
        await summarizer.queue_summary_views(scene, entry["id"])
    await summarizer.repair_summary_views(scene)
    assert selected(scene, "layer-a", "Cara", 1).status == "ready"
    assert not summarizer._summary_dirty[scene]
    assert not summarizer._summary_waiting[scene]


@pytest.mark.asyncio
async def test_cancelled_layer_does_not_stop_reader_chunk_commits(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    for entry in scene.archived_history:
        await summarizer.ensure_summary_views(scene, entry["id"])
    scene.layered_history = []

    async def respond(text, **kwargs):
        if kwargs.get("audience"):
            raise GenerationCancelled("cancel audience")
        return "Reader chunk."

    monkeypatch.setattr(summarizer, "summarize_events", respond)
    first = await summarizer._lh_commit_chunk(scene.archived_history[:2], 0, 0, 1, 2)
    second = await summarizer._lh_commit_chunk(scene.archived_history[2:], 0, 2, 2, 2)
    await summarizer.repair_summary_views(scene)
    assert [entry["text"] for entry in scene.layered_history[0]] == [
        "Reader chunk.",
        "Reader chunk.",
    ]
    assert selected(scene, first["id"], layer=1).status == "failed"
    assert selected(scene, second["id"], layer=1).status == "failed"


@pytest.mark.asyncio
async def test_repair_continues_after_bounded_batch(summary_scene, monkeypatch):
    scene, summarizer, _ = summary_scene
    monkeypatch.setattr(
        summarizer,
        "schedule_audience_summaries",
        type(summarizer).schedule_audience_summaries.__get__(summarizer),
    )
    count = 0

    async def respond(text, **kwargs):
        nonlocal count
        if kwargs["audience"] == ("Alice",):
            count += 1
            if count <= 9:
                publish(
                    scene, scene.history[0], f"Alice corrects detail {count}.", CLAIM
                )
        return text

    monkeypatch.setattr(summarizer, "summarize", respond)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    await summarizer.queue_summary_views(scene, "base-a")
    await type(summarizer).schedule_audience_summaries(summarizer, scene)

    async def complete():
        while True:
            await summarizer._summary_rebuild_tasks[scene]
            await asyncio.sleep(0)
            if not summarizer._summary_dirty[scene]:
                return

    await asyncio.wait_for(complete(), 2)
    assert count == 10
    assert selected(scene, "base-a", "Alice").status == "ready"
    assert scene.attempt_auto_save.await_count == 1


@pytest.mark.asyncio
async def test_background_queue_keeps_generation_options(summary_scene):
    scene, summarizer, calls = summary_scene
    options = GenerationOptions()
    await summarizer.queue_summary_views(scene, "base-a", generation_options=options)
    await summarizer.repair_summary_views(scene)
    assert calls and all(kwargs["generation_options"] is options for _, kwargs in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("summary_scene", [True], indirect=True)
async def test_real_cancel_poll_clears_scene_flag_before_sibling(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    scene.active = True
    sent = []
    interrupted = asyncio.Event()

    async def generate(prompt, parameters, kind):
        sent.append(prompt)
        if len(sent) == 1:
            scene.cancel_requested = True
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()
        return "SUMMARY: Bob remembers Alice's unverified claim."

    async def send_prompt(prompt, kind="conversation", **kwargs):
        result = await summarizer.client._cancelable_generate(prompt, {}, kind)
        if isinstance(result, GenerationCancelled):
            raise result
        return result

    monkeypatch.setattr(summarizer.client, "generate", generate, raising=False)
    monkeypatch.setattr(summarizer.client, "send_prompt", send_prompt)
    await asyncio.wait_for(summarizer.ensure_summary_views(scene, "base-a"), 2)
    assert interrupted.is_set()
    assert not scene.cancel_requested
    assert len(sent) == 2
    assert "This is a record for Alice " in str(sent[0])
    assert "This is a record for Bob, Cara " in str(sent[1])
    assert selected(scene, "base-a", "Alice").status == "failed"
    assert selected(scene, "base-a").status == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden_index", [0, 1, 2])
async def test_summary_built_while_hidden_does_not_consume_revealed_passage(
    summary_scene, hidden_index
):
    scene, summarizer, _ = summary_scene
    scene.archived_history = [
        ArchiveEntry(id="visible", text="READER", start=0, end=2).model_dump(
            exclude_none=True
        )
    ]
    scene.layered_history = [
        [
            LayeredArchiveEntry(
                id="visible-layer", text="READER-LAYER", start=0, end=0
            ).model_dump(exclude_none=True)
        ]
    ]
    hidden = scene.history[hidden_index]
    publish(scene, hidden, "HIDDEN-DETAIL.", "HIDDEN-DETAIL.")
    hidden.hide()
    assert hidden not in summary_sources(scene, scene.archived_history[0], 0)
    await summarizer.ensure_summary_views(scene, "visible")
    await summarizer.ensure_summary_views(scene, "visible-layer", 1)
    assert "HIDDEN-DETAIL" not in selected(scene, "visible").text
    assert "HIDDEN-DETAIL" not in "\n".join(project_character_history(scene, "Bob"))
    shown = project_character_history(scene, "Bob", show_hidden=True)
    assert sum("HIDDEN-DETAIL" in text for text in shown) == 1
    hidden.unhide()
    revealed = project_character_history(scene, "Bob")
    assert sum("HIDDEN-DETAIL" in text for text in revealed) == 1
    assert "READER" not in "\n".join(revealed)


@pytest.mark.asyncio
@pytest.mark.parametrize("excluded", ["director", "hidden"])
@pytest.mark.parametrize("position", [0, 1, 2])
async def test_deleted_uncited_message_cannot_widen_summary(
    summary_scene, excluded, position
):
    scene, summarizer, _ = summary_scene
    if excluded == "director":
        message = DirectorMessage(message="An instruction.", meta={"character": "Bob"})
    else:
        message = NarratorMessage(message="A hidden event.")
        message.hide()
    scene.history.insert(position, message)
    if excluded == "hidden":
        publish(scene, message, message.message, message.message)
    scene.archived_history[0]["end"] = 2
    for entry in scene.archived_history[1:]:
        entry["start"] += 1
        entry["end"] += 1
    await generate_all(scene, summarizer)
    before = "\n".join(project_character_history(scene, "Bob"))
    scene.delete_message(message.id)
    after = "\n".join(project_character_history(scene, "Bob"))
    for projected in (before, after):
        assert projected.count("ledger was burned") == 1
        assert projected.count("rain stops") == 1
        assert projected.count("village rings") == 1
        assert projected.count("Recent dialogue") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["summary", "perception"])
async def test_final_batch_waiter_runs_from_every_repair_entry(
    summary_scene, monkeypatch, entry_point
):
    scene, summarizer, _ = summary_scene
    monkeypatch.setattr(audience_summary_module, "MAX_SUMMARY_REPAIR_PASSES", 1)
    monkeypatch.setattr(
        summarizer,
        "schedule_audience_summaries",
        type(summarizer).schedule_audience_summaries.__get__(summarizer),
    )
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    await summarizer.ensure_summary_views(scene, "base-b")
    await summarizer.ensure_summary_views(scene, "layer-a", 1)
    assert summarizer._summary_waiting[scene]
    summarizer._summary_dirty.setdefault(scene, set()).update(
        (0, "base-a", name) for name in ("Alice", "Bob", "Cara")
    )
    if entry_point == "summary":
        await summarizer.schedule_audience_summaries(scene)
    else:
        monkeypatch.setattr(summarizer, "ensure_perceptions", AsyncMock())
        perception_task = await summarizer.rebuild_perceptions(scene)
        await perception_task
    task = summarizer._summary_rebuild_tasks[scene]
    await asyncio.wait_for(task, 2)
    assert selected(scene, "layer-a", layer=1).status == "ready"
    assert selected(scene, "layer-a", "Alice", 1).status == "ready"
    assert not summarizer._summary_dirty[scene]
    assert not summarizer._summary_waiting[scene]


@pytest.mark.asyncio
async def test_work_queued_during_autosave_stays_in_retained_task(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    monkeypatch.setattr(
        summarizer,
        "schedule_audience_summaries",
        type(summarizer).schedule_audience_summaries.__get__(summarizer),
    )
    saves = 0
    tasks = []

    async def save():
        nonlocal saves
        saves += 1
        tasks.append(asyncio.current_task())
        if saves == 1:
            publish(scene, scene.history[0], "Alice corrects her claim.", CLAIM)
            await summarizer.queue_summary_views(scene, "base-a")

    monkeypatch.setattr(scene, "attempt_auto_save", save)
    await summarizer.queue_summary_views(scene, "base-a")
    task = summarizer._summary_rebuild_tasks[scene]
    await asyncio.wait_for(task, 2)
    assert saves == 2
    assert tasks == [task, task]
    assert not summarizer._summary_dirty[scene]
    assert "Alice corrects her claim" in selected(scene, "base-a", "Alice").text


@pytest.mark.parametrize("older_count", [0, 200, 2000])
@pytest.mark.parametrize("limit", ["messages", "budget", "prefix"])
def test_projection_selects_only_the_requested_window(
    summary_scene, monkeypatch, older_count, limit
):
    scene, _, _ = summary_scene
    template = scene.history[-1]
    scene.history[:0] = [
        CharacterMessage(message=template.message, knowledge=template.knowledge)
        for _ in range(older_count)
    ]
    scene.archived_history = []
    scene.layered_history = []
    selector = Mock(wraps=context.select_character_view)
    monkeypatch.setattr(context, "select_character_view", selector)
    options = {"max_messages": 1}
    expected = scene.history[-1]
    if limit == "budget":
        options = {"budget": 0}
    elif limit == "prefix":
        options["before_message_id"] = scene.history[-1].id
        expected = scene.history[-2]
    projected = project_character_history(scene, "Bob", **options)
    assert bool(projected) is (limit != "budget")
    assert [call.args[1].id for call in selector.call_args_list] == [expected.id]


@pytest.mark.asyncio
async def test_covered_summaries_do_not_reselect_each_passage(
    summary_scene, monkeypatch
):
    scene, summarizer, _ = summary_scene
    await generate_all(scene, summarizer)
    expected = project_character_history(scene, "Bob")
    selector = Mock(wraps=context.select_character_view)
    monkeypatch.setattr(context, "select_character_view", selector)
    assert project_character_history(scene, "Bob") == expected
    messages = [
        call.args[1].id
        for call in selector.call_args_list
        if call.args[1].kind == "message"
    ]
    assert messages == [scene.history[-1].id]


@pytest.mark.parametrize("names", [("Alice", "Bob"), ("Bob", "Alice")])
def test_coverage_cache_can_be_shared_between_characters(summary_scene, names):
    scene, _, _ = summary_scene
    expected = {"Alice": scene.history[0].id, "Bob": scene.history[2].id}
    outputs = []
    for name, identity in expected.items():
        view = select_character_view(
            scene, source_reference(scene, "message", identity), name
        )
        outputs.append(
            {
                "audience": [name],
                "status": "ready",
                "text": view.text,
                "sources": [view.source],
            }
        )
    set_source_perspectives(scene, "summary", "base-a", outputs)
    read = PerspectiveReadContext(scene)
    reference = source_reference(scene, "summary", "base-a", read=read)
    cache = {}
    for name in (*names, *names):
        assert summary_coverage(reference, name, read=read, cache=cache) == frozenset(
            (expected[name],)
        )


def test_history_projection_resolves_protected_return_once(summary_scene, monkeypatch):
    from talemate.knowledge import transitions

    spy = Mock(wraps=transitions.protected_transition)
    monkeypatch.setattr(transitions, "protected_transition", spy)
    scene, _, _ = summary_scene
    result = project_character_history(scene, "Bob")
    assert result
    spy.assert_called_once_with(scene, "Bob")
