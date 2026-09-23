import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from _perception_backlog_helpers import answering
from test_perception_backlog import analysis, story
from talemate.character import Character, activate_character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.context import project_character_history
from talemate.knowledge.message_views import message_view
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.perspectives import (
    add_disclosure,
    bind_perspective_sources,
    can_cite_view,
    edit_message_view,
    select_character_view,
    set_source_perspectives,
    source_reference,
    view_staleness,
)
from talemate.load import load_scene_from_data
from talemate.scene_message import CharacterMessage, NarratorMessage


@pytest.mark.parametrize("record_presence", [True, False])
async def test_saved_perspectives_survive_activation_after_reload(
    persistence_scene_factory, monkeypatch, record_presence
):
    scene = persistence_scene_factory()
    scene.name = "Activation fixture"
    scene.project_name = "activation-fixture"
    scene.knowledge_eligibility = "perception"
    scene.character_data = {
        name: Character(name=name) for name in ("Alice", "Bob", "Carol")
    }
    scene.active_characters = ["Alice", "Bob"]
    request = AsyncMock(side_effect=analysis())
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    with ActiveScene(scene):
        messages = await story(scene)
        stored = [message.knowledge.model_dump(mode="json") for message in messages]
        if not record_presence:
            for message in messages:
                message.present = None
                message.mark_revision_committed()
        await scene.save(copy_name="before.json")
    saved_path = Path(scene.full_path)
    saved_data = json.loads(saved_path.read_text())
    assert [item["knowledge"] for item in saved_data["history"]] == stored

    reloaded = persistence_scene_factory()
    request.reset_mock()
    with ActiveScene(reloaded):
        await load_scene_from_data(reloaded, saved_data, name=str(saved_path))
        await activate_character(reloaded, "Carol")
        summarizer = get_agent("summarizer")
        frames = []
        with answering("analyze", frames):
            assert summarizer.check_perception_backlog(reloaded) is None
            await summarizer.ensure_perceptions(reloaded)
        request.assert_not_awaited()
        assert frames == []
        for message, original in zip(reloaded.history[:5], stored, strict=True):
            assert message.knowledge.model_dump(mode="json") == original
            assert message_view(reloaded, message, "Carol").status == "omitted"
            assert message_view(reloaded, message, "Bob").status == "ready"
        await reloaded.save(copy_name="after.json")
    after = json.loads(Path(reloaded.full_path).read_text())
    assert [item["knowledge"] for item in after["history"][:5]] == stored


@pytest.mark.parametrize("present", [["Alice"], [], None])
async def test_recorded_presence_overrides_names_and_active_cast(scene, present):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Carol")}
    scene.active_characters = ["Alice", "Carol"]
    message = CharacterMessage(message="Alice: Carol is away.", present=present)
    scene.history.append(message)
    with ActiveScene(scene):
        reference = set_source_perspectives(scene, "message", message.id, [])
    assert select_character_view(scene, reference, "Carol").status == "omitted"
    assert select_character_view(scene, reference, "Alice").status == (
        "unavailable" if present else "omitted"
    )


async def test_absence_does_not_replace_existing_shared_view(scene):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Carol")}
    scene.active_characters = ["Alice", "Carol"]
    message = CharacterMessage(message="Alice: A bell rings.", present=["Alice"])
    scene.history.append(message)
    with ActiveScene(scene):
        reference = set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {
                    "audience": ["Alice", "Carol"],
                    "status": "ready",
                    "text": "A bell rings.",
                }
            ],
        )
        stored = message.knowledge.model_dump()
        await get_agent("summarizer").ensure_perceptions(scene)
    assert message.knowledge.model_dump() == stored
    assert select_character_view(scene, reference, "Carol").text == "A bell rings."


@pytest.mark.parametrize("stale_kind", ["dependency", "provenance", "digest"])
async def test_absent_stale_ready_view_is_omitted_without_weakening_citations(
    scene, monkeypatch, stale_kind
):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Carol")}
    scene.active_characters = ["Alice", "Carol"]
    evidence = NarratorMessage(message="The bell rings.")
    message = NarratorMessage(
        message="The bell still rings.",
        present=None if stale_kind == "digest" else ["Alice"],
    )
    scene.history.extend([evidence, message])
    request = AsyncMock()
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    with ActiveScene(scene):
        output = {"audience": ["Carol"], "status": "ready", "text": "I hear the bell."}
        if stale_kind == "dependency":
            disclosure = add_disclosure(scene, "A bell rings.", ["Carol"])
            output["sources"] = [source_reference(scene, "disclosure", disclosure.id)]
        elif stale_kind == "provenance":
            output["passage_provenance"] = [
                {
                    "message_id": evidence.id,
                    "content_digest": content_digest(evidence.perception_text),
                }
            ]
        reference = set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {"audience": ["Alice"], "status": "ready", "text": "I hear the bell."},
                output,
            ],
        )
        pinned = select_character_view(scene, reference, "Carol").source
        assert can_cite_view(scene, pinned, "Carol")
        if stale_kind == "dependency":
            scene.knowledge = scene.knowledge.model_copy(update={"disclosures": ()})
        else:
            object.__setattr__(
                message if stale_kind == "digest" else evidence,
                "message",
                "The room is silent.",
            )
        stored = message.knowledge.model_dump()
        summarizer = get_agent("summarizer")
        assert summarizer.check_perception_backlog(scene) is None
        await summarizer.ensure_perceptions(scene)
        assert select_character_view(scene, reference, "Carol").status == "omitted"
        assert view_staleness(scene, reference, "Carol") is None
        assert project_character_history(scene, "Carol") == []
        assert select_character_view(scene, pinned, "Carol").status == "pending"
        assert not can_cite_view(scene, pinned, "Carol")
        assert not can_cite_view(scene, reference, "Carol")
        scene.archived_history = [{"id": "absent-summary", "text": "Reader summary."}]
        summary = set_source_perspectives(
            scene,
            "summary",
            "absent-summary",
            [{"audience": ["Carol"], "status": "omitted", "sources": [reference]}],
        )
        assert select_character_view(scene, summary, "Carol").status == "omitted"
    request.assert_not_awaited()
    assert message.knowledge.model_dump() == stored


@pytest.mark.parametrize("present", [None, []])
@pytest.mark.parametrize("status", ["ready", "pending", "failed"])
async def test_no_presence_requires_no_analysis_and_keeps_stored_views(
    scene, monkeypatch, present, status
):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Carol")}
    scene.active_characters = ["Alice", "Carol"]
    message = CharacterMessage(message="Alice: Carol is away.", present=present)
    scene.history.append(message)
    request = AsyncMock()
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    with ActiveScene(scene):
        reference = set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {
                    "audience": ["Alice"],
                    "status": status,
                    "text": "An existing view." if status == "ready" else None,
                }
            ],
        )
        stored = message.knowledge.model_dump()
        await get_agent("summarizer").ensure_perceptions(scene)
    request.assert_not_awaited()
    assert message.knowledge.model_dump() == stored
    assert select_character_view(scene, reference, "Carol").status == "omitted"
    assert select_character_view(scene, reference, "Alice").status == (
        "ready" if status == "ready" else "omitted"
    )
    history = project_character_history(scene, "Alice")
    assert bool(history) == (status == "ready")


@pytest.mark.parametrize("status", ["pending", "failed"])
async def test_noncurrent_absent_view_does_not_block_generation(
    scene, monkeypatch, status
):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {
        name: Character(name=name) for name in ("Alice", "Bob", "Carol")
    }
    scene.active_characters = list(scene.character_data)
    message = CharacterMessage(message="Alice: A bell rings.", present=["Alice", "Bob"])
    scene.history.append(message)
    request = AsyncMock()
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    with ActiveScene(scene):
        reference = set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {
                    "audience": ["Alice", "Bob"],
                    "status": "ready",
                    "text": "A bell rings.",
                },
                {"audience": ["Carol"], "status": status},
            ],
        )
        stored = message.knowledge.model_dump()
        summarizer = get_agent("summarizer")
        assert summarizer.check_perception_backlog(scene) is None
        await summarizer.ensure_perceptions(scene)
        assert select_character_view(scene, reference, "Carol").status == "omitted"
        assert project_character_history(scene, "Carol") == []
        assert project_character_history(scene, "Bob")
    request.assert_not_awaited()
    assert message.knowledge.model_dump() == stored


async def test_no_cast_passage_is_omitted_before_and_after_hand_edit(
    scene, monkeypatch
):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {"Alice": Character(name="Alice")}
    scene.active_characters = []
    message = NarratorMessage(message="Alice hears a bell.")
    request = AsyncMock()
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    with ActiveScene(scene):
        await scene.push_history(message)
        assert message.present is None
        assert message.knowledge is None
        await activate_character(scene, "Alice")
        assert message_view(scene, message, "Alice").status == "omitted"
        transition_history = project_character_history(scene, "Alice")
        assert transition_history == ["Alice has entered the scene for the first time."]
        edit_message_view(scene, message.id, "Alice", "I hear the bell.")
        assert "I hear the bell." in "\n".join(
            project_character_history(scene, "Alice")
        )
        scene.edit_message(message.id, "The room is silent.")
        stored = message.knowledge.model_dump()
        summarizer = get_agent("summarizer")
        for _ in range(3):
            await summarizer.ensure_perceptions(scene)
            assert project_character_history(scene, "Alice") == transition_history
        assert summarizer.check_perception_backlog(scene) is None
        assert message_view(scene, message, "Alice").status == "omitted"
        assert (
            select_character_view(
                scene, source_reference(scene, "message", message.id), "Alice"
            ).status
            == "omitted"
        )
    request.assert_not_awaited()
    assert message.knowledge.model_dump() == stored


@pytest.mark.parametrize("view_origin", ["typed", "cleared", "saved"])
async def test_editing_passage_with_absent_view_repairs_present_character(
    scene, monkeypatch, view_origin
):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Carol")}
    scene.active_characters = ["Alice"]
    message = CharacterMessage(message="Alice: A bell rings.")
    request = AsyncMock(side_effect=analysis())
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    with ActiveScene(scene):
        await scene.push_history(message)
        scene.active_characters.append("Carol")
        assert message.present == ["Alice"]
        absent = message_view(scene, message, "Carol")
        assert absent.status == "omitted" and absent.editable
        if view_origin == "saved":
            # Earlier builds analyzed active characters even when absent. Load
            # that stored shape, including provenance, through the saved model.
            outputs = [
                v.model_dump(exclude={"revision"}) for v in message.knowledge.views
            ]
            outputs.append({**outputs[0], "id": None, "audience": ["Carol"]})
            set_source_perspectives(scene, "message", message.id, outputs)
            message = CharacterMessage.model_validate_json(message.model_dump_json())
            scene.history = [message]
            bind_perspective_sources(scene)
        else:
            edit_message_view(scene, message.id, "Carol", "I hear the bell.")
            if view_origin == "cleared":
                edit_message_view(scene, message.id, "Carol", "")
        carol = next(v for v in message.knowledge.views if "Carol" in v.audience)
        assert carol.passage_provenance
        scene.edit_message(message.id, "Alice: The room is silent.")
        assert all(v.status == "pending" for v in message.knowledge.views)
        request.reset_mock()
        summarizer = get_agent("summarizer")
        await asyncio.wait_for(summarizer.ensure_perceptions(scene), 2)
        request.assert_awaited_once()
        assert message.revision_feature_current("perceptions")
        assert [
            entry["name"]
            for entry in request.call_args.kwargs["vars"]["context"]["cast"]
        ] == ["Alice"]
        reference = source_reference(scene, "message", message.id)
        assert select_character_view(scene, reference, "Alice").status == "ready"
        assert message_view(scene, message, "Carol").status == "omitted"
        retained = next(v for v in message.knowledge.views if v.id == carol.id)
        assert retained.audience == carol.audience
        assert retained.status == "pending"
        assert retained.text is None
        assert retained.sources == retained.passage_provenance == ()
        assert f"Alice notices passage {message.id}." in "\n".join(
            project_character_history(scene, "Alice")
        )
        assert project_character_history(scene, "Carol") == []
        await summarizer.ensure_perceptions(scene)
        request.assert_awaited_once()
