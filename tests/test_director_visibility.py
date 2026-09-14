import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.agents.director.action_core.exceptions import ActionRejected, ActionFailed
from talemate.agents.director.chat.context import DirectorChatContext
from talemate.agents.director.chat.nodes import DirectorChatAction
from talemate.agents.director.chat.schema import DirectorChat
from talemate.agents.director.action_core import utils as action_utils
from talemate.agents.director.scene_direction.mixin import scene_direction_context
from talemate.agents.director import visibility as assessment
from talemate.agents.director.visibility import (
    VisibilitySelection,
    select_visibility_entries,
)
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.game.engine.nodes.core import GraphContext, GraphState
from talemate.game.engine.nodes.run import FunctionWrapper
from talemate.instance import get_agent
from talemate.knowledge.schema import EntryVisibility
from talemate.world_state import ManualContext
from talemate.scene_message import NarratorMessage
import talemate.agents.director.chat.nodes as chat_nodes
import talemate.game.engine.nodes.logic  # noqa: F401
import talemate.game.engine.nodes.event as event_nodes
import talemate.prompts.base as prompt_base


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.knowledge_eligibility = "perception"
    scene.character_data = {
        "Alice": Character(
            name="Alice",
            base_attributes={"coat": "A blue coat", "secret": "A hidden key"},
            details={"past": "A quiet childhood"},
        ),
        "Bob": Character(name="Bob", base_attributes={"coat": "A red coat"}),
    }
    scene.world_state.manual_context = {
        "Square": ManualContext(
            id="Square", text="A busy public square", meta={"typ": "world_state"}
        ),
        "Vault": ManualContext(
            id="Vault",
            text="A hidden vault beneath the square",
            meta={"typ": "world_state"},
        ),
    }
    get_agent("director").emit_status = AsyncMock()
    return scene


def selection(scope="attributes", **kwargs):
    return VisibilitySelection(
        scope=scope,
        character=None if scope == "world_entries" else "Alice",
        instructions="Assess who knows these entries.",
        **kwargs,
    )


def decision(entry, mode="owner", **kwargs):
    return {
        "context_id": entry.context_id,
        "outcome": "set",
        "reason": "Supported by the author context.",
        "visibility": {"mode": mode, "characters": []},
        **kwargs,
    }


def reply(scene, rows):
    client = get_agent("director").client
    client.send_prompt = AsyncMock(return_value=json.dumps({"decisions": rows}))
    return client.send_prompt


@pytest.mark.parametrize(
    "scope,keys",
    [
        ("attributes", ["coat", "secret"]),
        ("details", ["detail.past"]),
        ("world_entries", ["Vault"]),
    ],
)
@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_each_scope_only_updates_selected_entries(scene, scope, keys, mode):
    scene.knowledge_eligibility = mode
    requested = selection(
        scope, **({"world_entries": ["Vault"]} if scope == "world_entries" else {})
    )
    entries = await select_visibility_entries(scene, requested)
    assert [entry.key for entry in entries] == keys
    send = reply(scene, [decision(entry) for entry in entries])
    director = get_agent("director")
    memory = get_agent("memory")
    revision = memory._audience_state(scene).revision
    with ActiveScene(scene):
        plan = await director.assess_entry_visibility(requested)
        await director.apply_visibility_assessment(plan)
    assert send.await_count == 1
    if mode == "perception":
        assert memory._audience_state(scene).revision > revision
    else:
        assert memory._audience_state(scene).revision == revision
    assert scene.character_data["Bob"].visibility == {}
    assert scene.world_state.manual_context["Square"].visibility.mode == "everyone"
    if scope != "world_entries":
        assert scene.world_state.manual_context["Vault"].visibility.mode == "everyone"
        assert set(scene.character_data["Alice"].visibility) == set(keys)
    else:
        assert scene.character_data["Alice"].visibility == {}


@pytest.mark.parametrize("reassess", [False, True])
async def test_preserves_restrictions_unless_reassessment_requested(scene, reassess):
    alice = scene.character_data["Alice"]
    alice.visibility = {
        "coat": EntryVisibility(mode="owner"),
        "secret": EntryVisibility(mode="list", characters=["Bob"]),
    }
    requested = selection(reassess=reassess)
    entries = await select_visibility_entries(scene, requested)
    send = reply(scene, [decision(entry, "everyone") for entry in entries])
    with ActiveScene(scene):
        director = get_agent("director")
        plan = await director.assess_entry_visibility(requested)
        if reassess:
            await director.apply_visibility_assessment(plan)
            assert alice.visibility == {}
        else:
            assert not plan.proposals
            assert "intentional restriction" in plan.report()
            assert alice.visibility["coat"].mode == "owner"
            assert alice.visibility["secret"].characters == ["Bob"]
    assert send.await_count == int(reassess)


async def test_mixed_uncertain_invalid_missing_and_out_of_scope_preserve_entries(scene):
    alice = scene.character_data["Alice"]
    alice.base_attributes = {
        key: "Public coat and secret key"
        for key in ["mixed", "uncertain", "invalid", "missing", "duplicate", "valid"]
    }
    entries = await select_visibility_entries(scene, selection())
    by_key = {entry.key: entry for entry in entries}
    reply(
        scene,
        [
            decision(by_key["mixed"], outcome="mixed", visibility=None),
            decision(by_key["uncertain"], outcome="uncertain", visibility=None),
            decision(
                by_key["invalid"],
                visibility={"mode": "list", "characters": ["Invented"]},
            ),
            decision(by_key["duplicate"]),
            decision(by_key["duplicate"], "everyone"),
            decision(by_key["valid"]),
            {
                "context_id": "world_entry.manual:Square",
                "outcome": "set",
                "reason": "Unselected",
                "visibility": {"mode": "owner"},
            },
        ],
    )
    with ActiveScene(scene):
        director = get_agent("director")
        plan = await director.assess_entry_visibility(selection())
        report = await director.apply_visibility_assessment(plan)
    assert set(alice.visibility) == {"valid"}
    assert "Split public and private" in report
    assert "missing or duplicate" in report
    assert "outside the assessment scope" in report
    assert scene.world_state.manual_context["Square"].visibility.mode == "everyone"


@pytest.mark.parametrize("change", ["text", "visibility", "cast", "scene"])
async def test_changes_during_assessment_block_application(scene, change, monkeypatch):
    entries = await select_visibility_entries(scene, selection())
    director = get_agent("director")

    async def send(*args, **kwargs):
        if change == "text":
            scene.character_data["Alice"].base_attributes["coat"] = "Edited coat"
        elif change == "visibility":
            scene.character_data["Alice"].visibility["coat"] = EntryVisibility(
                mode="list", characters=["Bob"]
            )
        elif change == "cast":
            scene.character_data["Carol"] = Character(name="Carol")
        else:
            director.scene = MockScene()
        return json.dumps({"decisions": [decision(entry) for entry in entries]})

    monkeypatch.setattr(director.client, "send_prompt", send)
    with ActiveScene(scene), pytest.raises(GenerationCancelled, match="stale"):
        await director.assess_entry_visibility(selection())
    assert "secret" not in scene.character_data["Alice"].visibility


async def test_changes_while_confirmation_pending_and_replay_are_rejected(scene):
    requested = selection("details")
    entries = await select_visibility_entries(scene, requested)
    reply(scene, [decision(entries[0])])
    director = get_agent("director")
    with ActiveScene(scene):
        plan = await director.assess_entry_visibility(requested)
        scene.character_data["Alice"].details["past"] = "Changed past"
        with pytest.raises(GenerationCancelled):
            await director.apply_visibility_assessment(plan)
        plan = await director.assess_entry_visibility(requested)
        await director.apply_visibility_assessment(plan)
        with pytest.raises(GenerationCancelled):
            await director.apply_visibility_assessment(plan)


@pytest.mark.parametrize("invalid", ["empty", "unknown", "too_many", "budget"])
async def test_invalid_or_oversized_selection_makes_no_request(
    scene, invalid, monkeypatch
):
    requested = selection()
    if invalid == "empty":
        requested = selection("world_entries")
    elif invalid == "unknown":
        requested.character = "Missing"
    elif invalid == "too_many":
        scene.character_data["Alice"].base_attributes = {
            f"key{i}": "x" for i in range(33)
        }
    else:
        monkeypatch.setattr(assessment, "count_tokens", lambda value: 100000)
    send = reply(scene, [])
    with ActiveScene(scene), pytest.raises(ValueError):
        await get_agent("director").assess_entry_visibility(requested)
    send.assert_not_awaited()


async def test_shipped_graph_confirm_accept_reject_and_disabled(scene, monkeypatch):
    scene.active = True
    requested = selection("details")
    entries = await select_visibility_entries(scene, requested)
    send = reply(scene, [decision(entries[0])])
    payload = json.loads(
        Path(
            "src/talemate/agents/director/modules/director-action-assess-visibility.json"
        ).read_text()
    )
    confirmations = []
    for enabled, answer in [(True, "reject"), (True, "accept"), (False, "accept")]:
        scene.character_data["Alice"].visibility.clear()
        action = DirectorChatAction(**payload)
        with (
            ActiveScene(scene),
            DirectorChatContext(chat_id="test", confirm_write_actions=enabled),
            GraphContext() as state,
        ):

            def confirm(event, **kwargs):
                if event == "request_action_confirmation":
                    data = kwargs["data"]
                    confirmations.append(data)
                    state.shared[f"_director_chat_action_confirm_{data['id']}"][
                        "decision"
                    ] = "confirm" if answer == "accept" else answer

            monkeypatch.setattr(chat_nodes, "emit", confirm)
            wrapper = FunctionWrapper(action, action, state)
            if answer == "reject":
                with pytest.raises(ActionRejected):
                    await wrapper(**requested.model_dump())
                assert scene.character_data["Alice"].visibility == {}
            else:
                result = await wrapper(**requested.model_dump())
                assert "Updated" in result
                assert (
                    scene.character_data["Alice"].visibility["detail.past"].mode
                    == "owner"
                )
    assert len(confirmations) == 2
    assert all("Proposed" in item["description"] for item in confirmations)
    assert send.await_count == 3


async def test_malformed_json_does_not_trigger_repair_request(scene):
    director = get_agent("director")
    director.client.send_prompt = AsyncMock(return_value="not JSON")
    with ActiveScene(scene), pytest.raises(ValueError, match="invalid JSON"):
        await director.assess_entry_visibility(selection())
    assert director.client.send_prompt.await_count == 1
    assert scene.character_data["Alice"].visibility == {}


@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_noop_graph_does_not_ask_for_confirmation_or_generate(
    scene, mode, monkeypatch
):
    scene.knowledge_eligibility = mode
    scene.character_data["Alice"].visibility["detail.past"] = EntryVisibility(
        mode="owner"
    )
    send = reply(scene, [])
    emit = AsyncMock()
    monkeypatch.setattr(chat_nodes, "emit", emit)
    payload = json.loads(
        Path(
            "src/talemate/agents/director/modules/director-action-assess-visibility.json"
        ).read_text()
    )
    action = DirectorChatAction(**payload)
    with (
        ActiveScene(scene),
        DirectorChatContext(chat_id="test"),
        GraphContext() as state,
    ):
        result = await FunctionWrapper(action, action, state)(
            **selection("details").model_dump()
        )
    assert "Preserved" in result
    send.assert_not_awaited()
    emit.assert_not_called()


async def test_action_is_gated_out_of_background_scene_direction(scene):
    send = reply(scene, [])
    payload = json.loads(
        Path(
            "src/talemate/agents/director/modules/director-action-assess-visibility.json"
        ).read_text()
    )
    action = DirectorChatAction(**payload)
    token = scene_direction_context.set({"in_direction_turn": True})
    try:
        with ActiveScene(scene), GraphContext() as state:
            await FunctionWrapper(action, action, state)(**selection().model_dump())
    finally:
        scene_direction_context.reset(token)
    send.assert_not_awaited()
    assert scene.character_data["Alice"].visibility == {}


async def test_world_context_ids_and_duplicate_selections_are_exact(scene):
    entries = await select_visibility_entries(
        scene, selection("world_entries", world_entries=["Vault"])
    )
    repeated = await select_visibility_entries(
        scene,
        selection("world_entries", world_entries=[entries[0].context_id, "Vault"]),
    )
    assert [entry.key for entry in repeated] == ["Vault"]
    with pytest.raises(ValueError):
        await select_visibility_entries(
            scene,
            selection(
                "world_entries", world_entries=["character.attribute:Alice.coat"]
            ),
        )


async def run_action(scene, requested, monkeypatch, *, confirm=False, answer="accept"):
    scene.active = True
    payload = json.loads(
        Path(
            "src/talemate/agents/director/modules/director-action-assess-visibility.json"
        ).read_text()
    )
    action = DirectorChatAction(**payload)
    with (
        ActiveScene(scene),
        DirectorChatContext(chat_id="test", confirm_write_actions=confirm),
        GraphContext() as state,
    ):

        def respond(event, **kwargs):
            if event == "request_action_confirmation":
                data = kwargs["data"]
                state.shared[f"_director_chat_action_confirm_{data['id']}"][
                    "decision"
                ] = "confirm" if answer == "accept" else answer

        confirmation = Mock(side_effect=respond)
        monkeypatch.setattr(chat_nodes, "emit", confirmation)
        result = await FunctionWrapper(action, action, state)(**requested)
    return result, confirmation


async def test_readable_detail_question_and_world_name_reach_model_and_report(scene):
    question = "What secret from Alice's past matters most?"
    scene.character_data["Alice"].details = {question: "The old lighthouse."}
    requested = selection("details")
    entries = await select_visibility_entries(scene, requested)
    assert entries[0].payload()["name"] == question
    send = reply(scene, [decision(entries[0])])
    with ActiveScene(scene):
        plan = await get_agent("director").assess_entry_visibility(requested)
    assert question.replace("'", "\\u0027") in send.call_args.args[0].render()
    assert f"Alice: {question}" in plan.report()
    world = (
        await select_visibility_entries(
            scene, selection("world_entries", world_entries=["Vault"])
        )
    )[0]
    assert world.payload()["name"] == "Vault"
    assert world.label == "World entry: Vault"


@pytest.mark.parametrize(
    "visibility",
    [
        {},
        {"characters": []},
        {"audience": "owner"},
        {"mode": "everyone", "extra": True},
        {"mode": "list", "characters": "Bob"},
        None,
    ],
)
async def test_malformed_nested_visibility_never_broadens_restricted_entry(
    scene, visibility
):
    requested = selection("details", reassess=True)
    alice = scene.character_data["Alice"]
    alice.visibility["detail.past"] = EntryVisibility(mode="owner")
    entry = (await select_visibility_entries(scene, requested))[0]
    reply(scene, [decision(entry, visibility=visibility)])
    with ActiveScene(scene):
        plan = await get_agent("director").assess_entry_visibility(requested)
        await get_agent("director").apply_visibility_assessment(plan)
    assert alice.visibility["detail.past"].mode == "owner"
    assert not plan.proposals
    assert "1 decision(s) failed validation" in plan.report()


@pytest.mark.parametrize("value", ["n", "off", "none", "False.", 1, {}, []])
async def test_shipped_graph_rejects_noncanonical_reassess_before_request(
    scene, monkeypatch, value
):
    scene.character_data["Alice"].visibility["detail.past"] = EntryVisibility(
        mode="owner"
    )
    send = reply(scene, [])
    args = selection("details").model_dump() | {"reassess": value}
    with pytest.raises(ActionFailed, match="reassess"):
        await run_action(scene, args, monkeypatch)
    send.assert_not_awaited()
    assert scene.character_data["Alice"].visibility["detail.past"].mode == "owner"


@pytest.mark.parametrize("value", [False, None, "false ", "NO", "0"])
async def test_shipped_graph_canonical_false_preserves_restriction(
    scene, monkeypatch, value
):
    scene.character_data["Alice"].visibility["detail.past"] = EntryVisibility(
        mode="owner"
    )
    send = reply(scene, [])
    result, confirmation = await run_action(
        scene,
        selection("details").model_dump() | {"reassess": value},
        monkeypatch,
        confirm=True,
    )
    assert "Preserved Alice: past" in result
    send.assert_not_awaited()
    confirmation.assert_not_called()


@pytest.mark.parametrize(
    "wrapper",
    [
        "{}",
        "```json\n{}\n```",
        "```\n{}\n```",
        "```JSON\n{}\n```",
        "```json\n{}\n```\nAssessment complete.",
        "Assessment follows:\n{}",
        "```json\n{}",
        "```json\n{}\n```\n```json\n{{}}\n```",
        "{},",
    ],
)
async def test_project_json_extraction_accepts_local_wrappers_without_repair_request(
    scene, wrapper
):
    requested = selection("details")
    entry = (await select_visibility_entries(scene, requested))[0]
    raw = json.dumps({"decisions": [decision(entry)]})
    if wrapper == "{},":
        raw = raw[:-1] + ",}"
    else:
        raw = wrapper.format(raw)
    director = get_agent("director")
    director.client.send_prompt = AsyncMock(return_value=raw)
    with ActiveScene(scene):
        plan = await director.assess_entry_visibility(requested)
        await director.apply_visibility_assessment(plan)
    assert scene.character_data["Alice"].visibility["detail.past"].mode == "owner"
    assert director.client.send_prompt.await_count == 1


async def test_attributes_match_authored_memory_and_knowledge_target_exclusions(scene):
    alice = scene.character_data["Alice"]
    alice.base_attributes = {
        "name": "Alice",
        "SCENARIO_CONTEXT": "setting",
        "_internal": "scaffolding",
        "coat": "blue",
    }
    entries = await select_visibility_entries(scene, selection())
    assert [entry.key for entry in entries] == ["coat"]
    ids = {doc["id"] for doc in alice.memory_documents()}
    targets = {target.id for target in scene.world_state_manager.knowledge_targets()}
    for key in ("name", "SCENARIO_CONTEXT", "_internal"):
        assert f"Alice.{key}" not in ids | targets
    send = reply(scene, [decision(entries[0])])
    with ActiveScene(scene):
        plan = await get_agent("director").assess_entry_visibility(selection())
        await get_agent("director").apply_visibility_assessment(plan)
    assert set(alice.visibility) == {"coat"}
    assert "scaffolding" not in send.call_args.args[0].render()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("vault", ["Vault"]),
        (" Vault ", [" Vault "]),
        ("` Vault `", [" Vault "]),
        ("Square, Vault", ["Square", "Vault"]),
        ("North, Square", ["North, Square"]),
        ("Chapter 1: Arrival, Vault", ["Chapter 1: Arrival", "Vault"]),
        ("world_entry.manual:North, Square", ["North, Square"]),
    ],
)
async def test_world_name_resolution_uses_ranked_matches_and_comma_lists(
    scene, value, expected
):
    for name in (" Vault ", "North, Square", "Chapter 1: Arrival"):
        scene.world_state.manual_context[name] = ManualContext(
            id=name, text="A place", meta={"typ": "world_state"}
        )
    entries = await select_visibility_entries(
        scene, selection("world_entries", world_entries=[value])
    )
    assert [entry.key for entry in entries] == expected


async def test_unknown_world_name_has_actionable_diagnostic(scene):
    with pytest.raises(
        assessment.VisibilityAssessmentError,
        match="world_entries:.*not an existing world entry",
    ):
        await select_visibility_entries(
            scene, selection("world_entries", world_entries=["Unknown place"])
        )


async def test_measured_prompt_honors_xml_and_dedupe(scene, monkeypatch):
    director = get_agent("director")
    monkeypatch.setattr(
        type(director.client), "section_format", property(lambda _: "xml")
    )
    monkeypatch.setattr(
        type(director.client), "dedupe_enabled", property(lambda _: True)
    )
    dedupe = Mock(wraps=prompt_base.dedupe_string)
    monkeypatch.setattr(prompt_base, "dedupe_string", dedupe)
    send = reply(scene, [])
    with ActiveScene(scene):
        await director.assess_entry_visibility(selection())
    dedupe.assert_called()
    prompt = send.call_args.args[0]
    assert prompt.sectioning_handler == "xml"
    assert prompt.dedupe_enabled is True
    assert "<AUTHOR_REQUEST>" in prompt.render()
    assert "## Author request" not in prompt.render()


@pytest.mark.parametrize("reassess", [True, "yes"])
async def test_shipped_graph_reassess_list_audience_confirmed_and_editor_synced(
    scene, monkeypatch, reassess
):
    alice = scene.character_data["Alice"]
    alice.visibility["detail.past"] = EntryVisibility(mode="owner")
    requested = selection("details", reassess=True)
    entry = (await select_visibility_entries(scene, requested))[0]
    reply(
        scene,
        [
            decision(
                entry,
                visibility={"mode": "list", "characters": [" bob ", "BOB", "alice"]},
            )
        ],
    )
    sync = Mock()
    monkeypatch.setattr(event_nodes, "emit", sync)
    result, confirmation = await run_action(
        scene,
        requested.model_dump() | {"reassess": reassess},
        monkeypatch,
        confirm=True,
    )
    assert alice.visibility["detail.past"] == EntryVisibility(
        mode="list", characters=["Bob", "Alice"]
    )
    request = next(
        call
        for call in confirmation.call_args_list
        if call.args[0] == "request_action_confirmation"
    )
    assert "Alice: past" in request.kwargs["data"]["description"]
    assert "only Alice (owner) → Alice (owner), Bob" in result
    sync.assert_called_once_with(
        "world_state_manager", kwargs={"action": "sync"}, websocket_passthrough=True
    )


async def test_rejected_or_unchanged_graph_does_not_sync_editor(scene, monkeypatch):
    entry = (await select_visibility_entries(scene, selection("details")))[0]
    reply(scene, [decision(entry)])
    sync = Mock()
    monkeypatch.setattr(event_nodes, "emit", sync)
    with pytest.raises(ActionRejected):
        await run_action(
            scene,
            selection("details").model_dump(),
            monkeypatch,
            confirm=True,
            answer="reject",
        )
    reply(scene, [])
    await run_action(scene, selection("details").model_dump(), monkeypatch)
    sync.assert_not_called()


async def test_report_shows_replaced_list_and_ownerless_nobody(scene):
    scene.character_data["Carol"] = Character(name="Carol")
    scene.world_state.manual_context["Vault"].visibility = EntryVisibility(
        mode="list", characters=["Bob"]
    )
    requested = selection("world_entries", world_entries=["Vault"], reassess=True)
    entry = (await select_visibility_entries(scene, requested))[0]
    reply(
        scene, [decision(entry, visibility={"mode": "list", "characters": ["Carol"]})]
    )
    with ActiveScene(scene):
        plan = await get_agent("director").assess_entry_visibility(requested)
    assert "World entry: Vault" in plan.report()
    assert "Bob → Carol" in plan.report()
    assert entry.known_by(EntryVisibility(mode="owner")) == "nobody"


async def test_specific_invalid_decision_diagnostics_are_reported_and_logged(
    scene, monkeypatch
):
    requested = selection("details")
    entry = (await select_visibility_entries(scene, requested))[0]
    warning = Mock()
    monkeypatch.setattr(assessment.log, "warning", warning)
    for visibility, diagnostic in [
        (None, "missing visibility"),
        ({"mode": "owner", "characters": ["Bob"]}, "only list mode"),
        (
            {"mode": "list", "characters": ["Missing"]},
            "Character `Missing` does not exist",
        ),
        ({"mode": "list"}, "must name existing"),
    ]:
        reply(scene, [decision(entry, visibility=visibility)])
        with ActiveScene(scene):
            plan = await get_agent("director").assess_entry_visibility(requested)
        assert diagnostic in plan.report()
    assert warning.call_count == 4


async def test_null_phase_and_unrelated_context_changes_do_not_cancel_confirmed_plan(
    scene,
):
    scene.intent_state.phase = None
    requested = selection("details")
    entry = (await select_visibility_entries(scene, requested))[0]
    reply(scene, [decision(entry)])
    with ActiveScene(scene):
        director = get_agent("director")
        plan = await director.assess_entry_visibility(requested)
        scene.description = "Updated author context"
        scene.history.append(NarratorMessage(message="A new public passage."))
        scene.ts = "PT1H"
        scene.character_data = dict(reversed(list(scene.character_data.items())))
        await director.apply_visibility_assessment(plan)
    assert scene.character_data["Alice"].visibility["detail.past"].mode == "owner"


async def test_bound_counts_only_eligible_entries_and_empty_entries_make_no_request(
    scene,
):
    alice = scene.character_data["Alice"]
    alice.base_attributes = {f"attr{i}": "private" for i in range(40)}
    alice.base_attributes["empty"] = "  "
    alice.visibility = {f"attr{i}": EntryVisibility(mode="owner") for i in range(36)}
    entries = await select_visibility_entries(scene, selection())
    send = reply(
        scene,
        [
            decision(entry)
            for entry in entries
            if entry.key in {f"attr{i}" for i in range(36, 40)}
        ],
    )
    with ActiveScene(scene):
        plan = await get_agent("director").assess_entry_visibility(selection())
    assert len(plan.proposals) == 4
    assert "no content to assess" in plan.report()
    assert send.await_count == 1
    alice.base_attributes = {"empty": "  "}
    send.reset_mock()
    with ActiveScene(scene):
        plan = await get_agent("director").assess_entry_visibility(selection())
    send.assert_not_awaited()


@pytest.mark.parametrize("budget", [2048, 4096, 8192])
async def test_real_budget_supports_small_clients(scene, monkeypatch, budget):
    director = get_agent("director")
    monkeypatch.setattr(
        type(director.client), "max_token_length", property(lambda _: budget)
    )
    send = reply(scene, [])
    with ActiveScene(scene):
        await director.assess_entry_visibility(selection("details"))
    prompt = send.call_args.args[0]
    reserved = int(send.call_args.kwargs["kind"].split("_")[-1])
    assert assessment.count_tokens(prompt.render()) + reserved <= budget
    assert prompt.response_length_mod == 0


async def test_fixed_context_budget_failure_is_not_blame_on_selection(
    scene, monkeypatch
):
    director = get_agent("director")
    monkeypatch.setattr(
        type(director.client), "max_token_length", property(lambda _: 512)
    )
    send = reply(scene, [])
    with (
        ActiveScene(scene),
        pytest.raises(
            assessment.VisibilityAssessmentError,
            match="fixed assessment instructions and story context",
        ),
    ):
        await director.assess_entry_visibility(selection("details"))
    send.assert_not_awaited()


@pytest.mark.parametrize(
    "requested",
    [
        dict(scope="attributes", character="Alice", world_entries=["Vault"]),
        dict(scope="world_entries", character="Alice", world_entries=["Vault"]),
    ],
)
async def test_selector_conflicts_are_rejected_without_generation(
    scene, monkeypatch, requested
):
    send = reply(scene, [])
    with pytest.raises(ActionFailed, match="world_entries|character"):
        await run_action(
            scene, requested | {"instructions": "Assess visibility"}, monkeypatch
        )
    send.assert_not_awaited()


async def test_graph_validation_failure_reaches_real_chat_caller(scene, monkeypatch):
    scene.nodegraph_state = GraphState()
    director = get_agent("director")
    director._chat_save(DirectorChat(id="test", title="Assessment", messages=[]))
    monkeypatch.setattr(action_utils, "build_prompt_vars", AsyncMock(return_value={}))
    monkeypatch.setattr(
        action_utils,
        "request_and_parse",
        AsyncMock(
            side_effect=[
                (None, [{"name": "assess_visibility", "instructions": "Assess"}], ""),
                (None, [], ""),
            ]
        ),
    )

    async def execute(**kwargs):
        await run_action(
            scene, selection("details").model_dump() | {"reassess": "off"}, monkeypatch
        )

    monkeypatch.setattr(action_utils, "execute_actions", execute)
    send = reply(scene, [])
    with ActiveScene(scene), DirectorChatContext(chat_id="test"):
        chat = await director.chat_generate_next("test")
    failures = [
        message
        for message in chat.messages
        if getattr(message, "status", None) == "error"
    ]
    assert len(failures) == 1
    assert "reassess" in failures[0].result
    assert "scope" not in failures[0].result
    send.assert_not_awaited()


@pytest.mark.parametrize(
    "reason, audience",
    [
        ("Only Alice knows the symbol }.", None),
        ("Marked with { in the text.", None),
        ("Known by the named character.", "Bob [,]"),
    ],
)
async def test_valid_json_strings_are_preserved(scene, reason, audience):
    requested = selection("details")
    if audience:
        scene.character_data[audience] = Character(name=audience)
    entry = (await select_visibility_entries(scene, requested))[0]
    visibility = (
        {"mode": "list", "characters": [audience]}
        if audience
        else {"mode": "owner", "characters": []}
    )
    send = reply(scene, [decision(entry, reason=reason, visibility=visibility)])
    with ActiveScene(scene):
        director = get_agent("director")
        plan = await director.assess_entry_visibility(requested)
        await director.apply_visibility_assessment(plan)
    assert plan.proposals[0][2] == reason
    assert scene.character_data["Alice"].visibility["detail.past"] == EntryVisibility(
        **visibility
    )
    assert send.await_count == 1
