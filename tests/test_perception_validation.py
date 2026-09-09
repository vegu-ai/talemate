import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from talemate.agents.summarize.perceptions import (
    PerceptionValidationError,
    parse_perceptions,
)
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.config.schema import Agent as AgentConfig
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.perspectives import set_source_perspectives
from talemate.scene_message import CharacterMessage, NarratorMessage


def response(names=("Alice", "Bob")):
    return {
        "views": [
            {
                "audience": [name],
                "status": "ready",
                "text": f"{name} hears a bell.",
                "knowledge_ids": [],
                "passage_ids": [],
                "evidence_spans": [],
            }
            for name in names
        ]
    }


def result(payload):
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    return text, {"response": text}


@pytest.fixture
def analysis(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")
    request = AsyncMock(return_value=result(response()))
    dialog = AsyncMock(return_value="cancel")
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", dialog)
    with ActiveScene(scene):
        yield scene, summarizer, request, dialog


def test_unknown_audiences_duplicates_and_host_fields_keep_first_valid_views():
    payload = response()
    original = payload["views"][0]["text"]
    payload["views"][0].update(
        id="invented", sources=["invalid"], passage_provenance=[False]
    )
    payload["activation"] = ["Carol"]
    payload["views"].extend(
        [
            {"audience": ["Carol"], "status": "nonsense"},
            {"audience": ["Alice"], "status": "ready", "text": "Replacement"},
            None,
        ]
    )
    with capture_logs() as logs:
        views = parse_perceptions(json.dumps(payload), ("Alice", "Bob"))
    assert len(views) == 2
    assert views[0].text == original
    assert views[0].id is None
    assert views[0].sources == ()
    assert views[0].passage_provenance == ()
    assert {entry["event"] for entry in logs} >= {
        "dropping duplicate perception view",
        "dropping unrequested perception audience",
    }


@pytest.mark.parametrize("field", ["passage_ids", "knowledge_ids", "evidence_spans"])
@pytest.mark.parametrize(
    "citations", [None, "13", {}, [True], [13.0], [None], [{}], [[]], "absent"]
)
def test_unreadable_citations_require_repair_and_warn(field, citations):
    payload = response()
    if citations == "absent":
        payload["views"][0].pop(field)
    else:
        payload["views"][0][field] = citations
    with capture_logs() as logs, pytest.raises(PerceptionValidationError) as error:
        parse_perceptions(json.dumps(payload), ("Alice", "Bob"))
    assert field in str(error.value)
    assert [view.audience for view in error.value.views] == [("Bob",)]
    assert any(
        entry.get("audience") == "Alice"
        and entry.get("field") == field
        and entry["log_level"] == "warning"
        for entry in logs
    )


async def test_wrongly_typed_offered_id_repairs_dependency_and_edit_invalidates(
    analysis,
):
    scene, _, request, dialog = analysis
    prior = NarratorMessage(message="A bell rings.")
    await scene.push_history(prior)
    message = NarratorMessage(message="Alice remembers the bell.")
    broken, repaired = response(), response(("Alice",))
    broken["views"][0]["passage_ids"] = [str(prior.id)]
    repaired["views"][0]["passage_ids"] = [prior.id]
    request.reset_mock()
    request.side_effect = [result(broken), result(repaired)]
    await scene.push_history(message)
    assert request.await_count == 2
    assert [
        entry["name"] for entry in request.call_args.kwargs["vars"]["context"]["cast"]
    ] == ["Alice"]
    alice = next(
        view for view in message.knowledge.views if view.audience == ("Alice",)
    )
    assert [p.message_id for p in alice.passage_provenance] == [message.id, prior.id]
    scene.edit_message(prior.id, "The bell was silent.")
    assert (
        next(
            view for view in message.knowledge.views if view.audience == ("Alice",)
        ).status
        == "pending"
    )
    dialog.assert_not_awaited()


@pytest.mark.parametrize("mode", [None, "legacy", "perception"])
def test_perception_off_value_is_present_in_persisted_settings_payload(
    analysis, monkeypatch, mode
):
    scene, summarizer, _, _ = analysis
    summarizer.actions["perceptions"].config["automatic_repair"].value = False
    if mode is None:
        monkeypatch.delattr(summarizer, "scene")
    else:
        scene.knowledge_eligibility = mode
    payload = summarizer.sanitized_action_config
    saved = AgentConfig(actions=payload)
    reloaded = AgentConfig.model_validate_json(saved.model_dump_json())
    assert reloaded.actions["perceptions"].config["automatic_repair"].value is False
    assert payload["perceptions"]["description"]
    assert payload["perceptions"]["config"]["automatic_repair"]["note_on_value"][True][
        "text"
    ]


def test_missing_audience_error_retains_valid_sibling_and_reason():
    payload = response()
    payload["views"][1]["text"] = " "
    with pytest.raises(PerceptionValidationError, match="Bob") as error:
        parse_perceptions(json.dumps(payload), ("Alice", "Bob"))
    assert "complete replacement text" in str(error.value)
    assert [view.audience for view in error.value.views] == [("Alice",)]


def test_invalid_duplicate_does_not_hide_later_valid_view():
    payload = response()
    payload["views"].insert(0, {"audience": ["Alice"], "status": "pending"})
    views = parse_perceptions(json.dumps(payload), ("Alice", "Bob"))
    assert views[0].text == "Alice hears a bell."


@pytest.mark.parametrize("text", [None, "", "not JSON", "{}", '{"views": null}'])
def test_unreadable_response_has_actionable_validation_error(text):
    with pytest.raises(PerceptionValidationError):
        parse_perceptions(text, ("Alice", "Bob"))


async def test_self_citation_is_silent_and_releases_dependents(analysis):
    scene, summarizer, request, dialog = analysis
    prior = [
        NarratorMessage(message="A door opens."),
        NarratorMessage(message="A bell rings."),
    ]
    scene.history.extend(prior)
    message = CharacterMessage(message="Alice: Hello.")
    payload = response()
    for view in payload["views"]:
        view["passage_ids"] = [message.id, message.id]
    request.return_value = result(payload)
    downstream = AsyncMock()
    scene.signals["push_history.after"].connect(downstream)
    with capture_logs() as logs:
        await scene.push_history(message)
    downstream.assert_awaited_once()
    request.assert_awaited_once()
    dialog.assert_not_awaited()
    assert not [entry for entry in logs if "citation" in entry["event"]]
    for view in message.knowledge.views:
        assert view.status == "ready"
        assert [p.message_id for p in view.passage_provenance] == [message.id]


async def test_mixed_citations_resolve_only_audiences_offered_sources(analysis):
    scene, _, request, dialog = analysis
    prior = CharacterMessage(message="Alice: Earlier.")
    await scene.push_history(prior)
    message = NarratorMessage(message="A bell rings.")
    payload = response()
    payload["views"][0]["knowledge_ids"] = ["K0-0", "K1-0", "K0-0", "invented"]
    payload["views"][0]["passage_ids"] = [prior.id, message.id, 999999, prior.id]
    payload["views"][1].update(
        status="omitted", text=None, passage_ids=[prior.id, 999999]
    )
    request.return_value = result(payload)
    with capture_logs() as logs:
        await scene.push_history(message)
    alice, bob = message.knowledge.views
    assert len(alice.sources) == 1
    assert alice.sources[0].view_id == prior.knowledge.views[0].id
    assert [p.message_id for p in alice.passage_provenance] == [message.id, prior.id]
    assert bob.status == "omitted"
    assert [p.message_id for p in bob.passage_provenance] == [message.id, prior.id]
    dropped = [
        entry
        for entry in logs
        if entry["event"] == "dropping unoffered perception citation"
    ]
    assert {(entry["audience"], entry["citation"]) for entry in dropped} == {
        ("Alice", "K1-0"),
        ("Alice", "invented"),
        ("Alice", 999999),
        ("Bob", 999999),
    }
    assert all(
        entry["log_level"] == "warning" and entry["source_id"] == message.id
        for entry in dropped
    )
    dialog.assert_not_awaited()


@pytest.mark.parametrize("missing", ["audience", "evidence_spans"])
async def test_repair_requests_only_missing_audience_and_preserves_valid_prose(
    analysis,
    missing,
):
    scene, summarizer, request, dialog = analysis
    assert summarizer.resolve_config("perceptions", "automatic_repair") is True
    repaired = response()
    repaired["views"][0]["text"] = "Unwanted replacement."
    broken = response(("Alice",)) if missing == "audience" else response()
    if missing == "evidence_spans":
        broken["views"][1].pop("evidence_spans")
    request.side_effect = [result(broken), result(repaired)]
    message = NarratorMessage(message="A bell rings.")
    await scene.push_history(message)
    assert request.await_count == 2
    repair_vars = request.await_args.kwargs["vars"]
    assert "Bob" in repair_vars["validation_error"]
    assert [entry["name"] for entry in repair_vars["context"]["cast"]] == ["Bob"]
    assert {view.audience[0]: view.text for view in message.knowledge.views} == {
        "Alice": "Alice hears a bell.",
        "Bob": "Bob hears a bell.",
    }
    dialog.assert_not_awaited()


@pytest.mark.parametrize("repair, count", [(False, 1), (True, 2)])
async def test_failed_repair_is_bounded_and_dialog_preserves_valid_views(
    analysis, repair, count
):
    scene, summarizer, request, dialog = analysis
    summarizer.actions["perceptions"].config["automatic_repair"].value = repair
    request.return_value = result(response(("Alice",)))
    message = NarratorMessage(message="A bell rings.")
    downstream = AsyncMock()
    scene.signals["push_history.after"].connect(downstream)
    with pytest.raises(GenerationCancelled):
        await scene.push_history(message)
    assert request.await_count == count
    dialog.assert_awaited_once()
    assert "Missing valid perceptions for: Bob" in dialog.await_args.args[0]
    assert {view.audience[0]: view.status for view in message.knowledge.views} == {
        "Alice": "ready",
        "Bob": "failed",
    }
    downstream.assert_not_awaited()


async def test_transport_error_is_shown_without_validation_repair(analysis):
    scene, _, request, dialog = analysis
    request.side_effect = RuntimeError("Model unavailable")
    with pytest.raises(GenerationCancelled):
        await scene.push_history(NarratorMessage(message="A bell rings."))
    request.assert_awaited_once()
    assert "Reason: Model unavailable" in dialog.await_args.args[0]


async def test_cancelled_repair_preserves_valid_views_and_propagates(analysis):
    scene, _, request, dialog = analysis
    request.side_effect = [
        result(response(("Alice",))),
        GenerationCancelled("cancelled"),
    ]
    message = NarratorMessage(message="A bell rings.")
    with pytest.raises(GenerationCancelled):
        await scene.push_history(message)
    assert {view.audience[0]: view.status for view in message.knowledge.views} == {
        "Alice": "ready",
        "Bob": "failed",
    }
    dialog.assert_not_awaited()


async def test_edit_during_repair_discards_all_old_views(analysis):
    scene, _, request, dialog = analysis
    message = NarratorMessage(message="Old bell.")

    async def respond(*args, **kwargs):
        if request.await_count == 1:
            return result(response(("Alice",)))
        if request.await_count == 2:
            scene.edit_message(message.id, "New bell.")
            return result(response(("Bob",)))
        payload = response()
        for view in payload["views"]:
            view["text"] = "New bell."
        return result(payload)

    request.side_effect = respond
    await asyncio.wait_for(scene.push_history(message), 3)
    assert request.await_count == 3
    assert {view.text for view in message.knowledge.views} == {"New bell."}
    dialog.assert_not_awaited()


async def test_repair_preserves_existing_shared_audience_view(analysis):
    scene, summarizer, request, dialog = analysis
    scene.character_data["Carol"] = Character(name="Carol")
    scene.active_characters.append("Carol")
    message = NarratorMessage(message="A bell rings.")
    scene.history.append(message)
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {
                "audience": ["Alice", "Bob"],
                "status": "ready",
                "text": "They hear the bell.",
            },
            {"audience": ["Carol"], "status": "failed"},
        ],
    )
    shared = message.knowledge.views[0]
    request.return_value = result(response(("Carol",)))
    await summarizer.ensure_perceptions(scene)
    request.assert_awaited_once()
    assert message.knowledge.views[0] == shared
    assert message.knowledge.views[1].audience == ("Carol",)
    assert message.knowledge.views[1].status == "ready"
    dialog.assert_not_awaited()
