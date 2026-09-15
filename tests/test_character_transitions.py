import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from talemate.character import Character, activate_character, deactivate_character
from talemate.context import ActiveScene, SceneIsLoading
from talemate.instance import get_agent
from talemate.knowledge.perspectives import bind_message_source, set_source_perspectives
from talemate.knowledge.timeline import message_times
from talemate.knowledge.transitions import (
    absence_seconds,
    latest_transition,
    offscreen_eligible,
    protected_transition,
    record_arrival,
    record_departure,
    render_transition,
)
from talemate.load import _prepare_history
from talemate.prompts import Prompt
from talemate.scene_message import (
    CharacterMessage,
    CharacterTransitionMessage,
    NarratorMessage,
    TimePassageMessage,
)
from talemate.tale_mate import Actor


@pytest.fixture(params=["legacy", "perception"])
def returning_scene(scene, request, activation_signal, monkeypatch):
    scene.knowledge_eligibility = request.param
    monkeypatch.setattr(get_agent("memory"), "add_many", AsyncMock(return_value=True))
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    narrator = get_agent("narrator")
    narrator.actions["offscreen_life"].enabled = False
    activation_signal.connect(narrator.on_character_activated)
    for name in ["Nora", "Mara"]:
        character = Character(name=name)
        actor = Actor(character, conversation)
        actor.scene = scene
        scene.character_data[name] = character
        scene.actors.append(actor)
        scene.active_characters.append(name)
    with ActiveScene(scene):
        yield scene


def add_line(scene, text, present):
    message = NarratorMessage(text, present=present)
    scene.history.append(message)
    bind_message_source(scene, message)
    if scene.knowledge_eligibility == "perception":
        set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {"audience": present, "status": "ready", "text": text},
                *[
                    {"audience": [name], "status": "omitted", "text": None}
                    for name in scene.character_data
                    if name not in present
                ],
            ],
        )
    return message


async def leave_and_return(scene, *, lines=101, seconds=172800):
    add_line(scene, "Nora leaves to inspect the east gate.", ["Nora", "Mara"])
    await deactivate_character(scene, "Nora")
    for i in range(lines):
        add_line(scene, f"Mara keeps private secret {i}.", ["Mara"])
    if seconds:
        scene.history.append(TimePassageMessage(ts=seconds, message="Two days later"))
        scene.fix_time()
    await activate_character(scene, "Nora")
    return latest_transition(scene, "Nora")


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
async def test_first_return_history_has_generic_transition_without_request(
    returning_scene, monkeypatch, best_fit
):
    scene = returning_scene
    request = AsyncMock(side_effect=AssertionError("No model request is allowed"))
    monkeypatch.setattr(Prompt, "request", request)
    summarizer = get_agent("summarizer")
    summarizer.actions["manage_scene_history"].config["best_fit"].value = best_fit
    transition = await leave_and_return(scene)
    text = "\n".join(
        scene.context_history(
            budget=8192,
            perspective="Nora",
            stored_views=scene.knowledge_eligibility == "perception",
        )
    )
    assert "Nora left the scene." in text
    assert "2 Days of scene time passed" in text
    assert "Nora has now returned to the scene." in text
    assert "private secret" not in text
    assert "east gate" not in render_transition(scene, transition)
    assert request.await_count == 0
    assert protected_transition(scene, "Nora") is transition
    assert not transition.supports_perceptions


@pytest.mark.asyncio
async def test_repeated_return_and_time_edit_preserve_independent_records(
    returning_scene,
):
    scene = returning_scene
    first = await leave_and_return(scene, lines=1)
    first.arrival_note = "Her coat is wet."
    await deactivate_character(scene, "Nora")
    add_line(scene, "A second private event.", ["Mara"])
    scene.history.append(TimePassageMessage(ts=3600, message="An hour later"))
    scene.fix_time()
    await activate_character(scene, "Nora")
    second = latest_transition(scene, "Nora")
    assert second.id != first.id
    assert absence_seconds(scene, second) == 3600
    passage = next(
        message for message in scene.history if isinstance(message, TimePassageMessage)
    )
    passage.ts = 259200
    scene.fix_time()
    assert absence_seconds(scene, first) == 259200
    assert absence_seconds(scene, second) == 3600
    assert "Her coat is wet." in render_transition(scene, first)
    assert "Her coat is wet." not in render_transition(scene, second)


@pytest.mark.asyncio
async def test_return_survives_serialization_without_regenerating(returning_scene):
    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    transition.arrival_note = "She sets down her pack."
    transition.offscreen_status = "pending"
    restored = _prepare_history(deepcopy(transition.to_dict()))
    assert isinstance(restored, CharacterTransitionMessage)
    assert restored.id == transition.id
    assert restored.departure_message_id == transition.departure_message_id
    assert restored.arrival_note == transition.arrival_note
    assert restored.offscreen_status == "failed"


@pytest.mark.asyncio
async def test_noop_activation_and_loading_create_nothing(returning_scene):
    scene = returning_scene
    await activate_character(scene, "Nora")
    assert not scene.history
    with SceneIsLoading(scene):
        record_departure(scene, scene.get_character("Nora"))
        assert record_arrival(scene, scene.get_character("Nora")) is None
    assert not scene.history


@pytest.mark.asyncio
async def test_immediate_return_has_no_offscreen_request(returning_scene, monkeypatch):
    scene = returning_scene
    get_agent("narrator").actions["offscreen_life"].enabled = True
    request = AsyncMock()
    monkeypatch.setattr(Prompt, "request", request)
    await deactivate_character(scene, "Nora")
    await activate_character(scene, "Nora")
    assert not offscreen_eligible(scene, latest_transition(scene, "Nora"))
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("lines,seconds", [(1, 0), (0, 3600)])
async def test_offscreen_account_is_one_request_without_archive_wait(
    returning_scene, monkeypatch, lines, seconds
):
    scene = returning_scene
    narrator = get_agent("narrator")
    narrator.actions["offscreen_life"].enabled = True
    request = AsyncMock(
        return_value=("", {"response": "Nora repaired her cloak while away."})
    )
    monkeypatch.setattr(Prompt, "request", request)
    transition = await asyncio.wait_for(
        leave_and_return(scene, lines=lines, seconds=seconds), timeout=10
    )
    assert request.await_count == 1
    assert request.call_args.args[0] == "narrator.offscreen-life"
    assert transition.offscreen_status == "ready"
    assert len(scene.world_state.facts) == 1
    fact = scene.world_state.facts[transition.offscreen_fact_id]
    assert fact.source == "offscreen"
    assert fact.message_id is None
    assert fact.present == ["Nora"]
    assert "repaired her cloak" in render_transition(scene, transition)
    assert not scene.archived_history
    other = "\n".join(
        scene.context_history(
            budget=8192,
            perspective="Mara",
            stored_views=scene.knowledge_eligibility == "perception",
        )
    )
    assert "repaired her cloak" not in other


@pytest.mark.asyncio
async def test_unreadable_account_keeps_baseline_without_retry(
    returning_scene, monkeypatch
):
    scene = returning_scene
    get_agent("narrator").actions["offscreen_life"].enabled = True
    request = AsyncMock(return_value=("", {"response": ""}))
    monkeypatch.setattr(Prompt, "request", request)
    transition = await leave_and_return(scene, lines=1)
    assert transition.offscreen_status == "failed"
    assert "Nora has now returned" in render_transition(scene, transition)
    assert request.await_count == 1
    assert not scene.world_state.facts


@pytest.mark.asyncio
async def test_departure_during_generation_discards_account(
    returning_scene, monkeypatch
):
    scene = returning_scene
    get_agent("narrator").actions["offscreen_life"].enabled = True

    async def generate(*args, **kwargs):
        await deactivate_character(scene, "Nora")
        return "", {"response": "This stale account must not be stored."}

    monkeypatch.setattr(Prompt, "request", generate)
    transition = await leave_and_return(scene, lines=1)
    assert transition.offscreen_fact_id is None
    assert not scene.world_state.facts


@pytest.mark.asyncio
async def test_archive_never_extracts_transition_as_story(returning_scene):
    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    add_line(scene, "Nora sets her pack down.", ["Nora", "Mara"])
    add_line(scene, "Mara greets Nora.", ["Nora", "Mara"])
    summarizer = get_agent("summarizer")
    span = summarizer.collect_archive_span(scene)
    assert transition not in span.dialogue_entries
    from talemate.history import span_bindings

    assert transition.id not in span_bindings(scene, [transition])


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
async def test_protected_bridge_precedes_later_context_under_tiny_budget(
    returning_scene, best_fit
):
    scene = returning_scene
    get_agent("summarizer").actions["manage_scene_history"].config[
        "best_fit"
    ].value = best_fit
    transition = await leave_and_return(scene, lines=101)
    add_line(scene, "Mara opens the gate. " * 100, ["Nora", "Mara"])
    text = "\n".join(
        scene.context_history(
            budget=100,
            perspective="Nora",
            stored_views=scene.knowledge_eligibility == "perception",
        )
    )
    assert "Nora has now returned to the scene." in text
    assert (
        text.index("Nora left the scene.") < text.index("Mara opens the gate.")
        if "Mara opens the gate." in text
        else True
    )
    assert protected_transition(scene, "Nora") is transition
    pending = CharacterMessage("Nora: I am back.", history_dispatch_pending=True)
    scene.history.append(pending)
    assert protected_transition(scene, "Nora") is transition
    pending.history_dispatch_pending = False
    assert protected_transition(scene, "Nora") is None


@pytest.mark.asyncio
async def test_arrival_sources_and_account_follow_edits_and_deletion(returning_scene):
    from talemate.knowledge.schema import Fact

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    arrival = add_line(scene, "Mara opens the gate.", ["Nora", "Mara"])
    add_line(scene, "Hidden arrival detail.", ["Mara"])
    assert "Mara opens the gate." in render_transition(scene, transition)
    assert "Hidden arrival detail" not in render_transition(scene, transition)
    scene.world_state.facts["F1"] = Fact(
        id="F1", text="She repaired her coat.", source="offscreen", present=["Nora"]
    )
    transition.offscreen_fact_id = "F1"
    assert "She repaired her coat." in render_transition(scene, transition)
    scene.world_state.facts["F1"].text = "She repaired her pack."
    assert "She repaired her pack." in render_transition(scene, transition)
    del scene.world_state.facts["F1"]
    scene.delete_message(arrival.id)
    assert "repaired" not in render_transition(scene, transition)
    assert "Mara opens" not in render_transition(scene, transition)
    passage = next(
        message for message in scene.history if isinstance(message, TimePassageMessage)
    )
    scene.delete_message(passage.id)
    assert absence_seconds(scene, transition) == 0
    assert "Nora has now returned" in render_transition(scene, transition)


@pytest.mark.asyncio
async def test_rename_and_reset_follow_episode_ownership(returning_scene):
    from talemate.knowledge.rename import rename_knowledge_references

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    rename_knowledge_references(scene, "Nora", "Nora Bell")
    assert transition.character_name == "Nora Bell"
    assert "Nora Bell" in transition.participants
    await deactivate_character(scene, "Mara")
    assert scene.agent_state["conversation"]["character_departures"]
    scene.reset()
    assert not scene.history
    assert not scene.agent_state.get("conversation", {}).get("character_departures")


@pytest.mark.asyncio
async def test_archive_transition_does_not_force_a_summary_request(returning_scene):
    scene = returning_scene
    await deactivate_character(scene, "Nora")
    await activate_character(scene, "Nora")
    add_line(scene, "Nora adjusts her pack.", ["Nora", "Mara"])
    add_line(scene, "Mara nods.", ["Nora", "Mara"])
    assert get_agent("summarizer").collect_archive_span(scene).end is None


@pytest.mark.asyncio
async def test_first_actual_dialogue_prompt_contains_bridge_and_preview_agrees(
    returning_scene, monkeypatch
):
    from talemate.agents.context import ActiveAgent
    from talemate.agents.summarize.context_history import ContextHistoryParams

    scene = returning_scene
    conversation = get_agent("conversation")
    summarizer = get_agent("summarizer")
    summarizer.actions["analyze_scene"].enabled = False
    conversation.actions["use_long_term_memory"].enabled = False
    request = AsyncMock(
        side_effect=AssertionError("Return context must not request a model")
    )
    monkeypatch.setattr(Prompt, "request", request)
    await leave_and_return(scene)
    with ActiveAgent(conversation, conversation.build_prompt):
        prompt = await conversation.build_prompt(scene.get_character("Nora"))
        text = prompt.render()
    assert "Nora left the scene." in text
    assert "2 Days of scene time passed" in text
    assert "Nora has now returned to the scene." in text
    assert "private secret" not in text
    assert "Character entry orientation" not in text
    request.assert_not_awaited()
    params = ContextHistoryParams(
        perspective="Nora", stored_views=scene.knowledge_eligibility == "perception"
    )
    actual = scene.context_history(budget=8192, **params.model_dump())
    preview = summarizer.context_history_preview(scene, budget=8192, params=params)
    lines = [line for section in preview["sections"] for line in section["entries"]]
    assert lines == actual


@pytest.mark.asyncio
async def test_standard_summary_layers_descend_across_return_in_chronological_order(
    returning_scene,
):
    if returning_scene.knowledge_eligibility != "legacy":
        return
    from talemate.agents.summarize.context_history import (
        ContextHistoryMixin,
        ContextHistoryParams,
    )

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    arrival = add_line(scene, "Mara opens the gate.", ["Nora", "Mara"])
    scene.archived_history = [
        {
            "id": "H1",
            "start": 0,
            "end": len(scene.history) - 1,
            "text": "Compressed source",
            "ts": scene.ts,
            "present": ["Nora", "Mara"],
        }
    ]
    scene.layered_history = [
        [
            {
                "id": "L1",
                "start": 0,
                "end": 0,
                "text": "Layer source",
                "ts_start": 0,
                "ts_end": scene.ts,
            }
        ]
    ]
    params = ContextHistoryParams(perspective="Nora").bind(scene)
    for entry, layer in [
        (scene.archived_history[0], 0),
        (scene.layered_history[0][0], 1),
        ({"start": 0, "end": 0}, 2),
    ]:
        text = ContextHistoryMixin._transition_summary(scene, entry, layer, params)
        assert (
            text.index("Nora leaves to inspect")
            < text.index("Nora left the scene.")
            < text.index("Mara opens the gate.")
        )
        assert "private secret" not in text
        assert text.count("Nora has now returned") == 1
    params._transition_raw_start = scene.history.index(transition)
    text = ContextHistoryMixin._transition_summary(
        scene, scene.layered_history[0][0], 1, params
    )
    assert "Nora has now returned" not in text
    assert str(arrival) not in text


@pytest.mark.asyncio
async def test_scene_reload_preserves_episode_without_any_request(
    returning_scene, persistence_scene_factory, monkeypatch
):
    from talemate.load import load_scene_from_data

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    transition.arrival_note = "Her boots are wet."
    saved = deepcopy(scene.serialize)
    saved["history"] = [message.to_dict() for message in scene.history]
    restored = persistence_scene_factory()
    request = AsyncMock(side_effect=AssertionError("Reload must not generate"))
    monkeypatch.setattr(Prompt, "request", request)
    await load_scene_from_data(restored, saved)
    copy = latest_transition(restored, "Nora")
    assert copy.id == transition.id
    assert copy.arrival_note == "Her boots are wet."
    assert "2 Days of scene time passed" in copy.as_format("chat")
    assert (
        len([item for item in restored.history if item.typ == "character_transition"])
        == 1
    )
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_memory_write_does_not_publish_an_orphan_account(
    returning_scene, monkeypatch
):
    scene = returning_scene
    narrator = get_agent("narrator")
    narrator.actions["offscreen_life"].enabled = True
    monkeypatch.setattr(
        Prompt,
        "request",
        AsyncMock(return_value=("", {"response": "Nora repaired her coat."})),
    )
    monkeypatch.setattr(
        get_agent("memory"),
        "add_many",
        AsyncMock(side_effect=RuntimeError("Test storage failure")),
    )
    transition = await leave_and_return(scene, lines=1)
    assert transition.offscreen_status == "failed"
    assert transition.offscreen_fact_id is None
    assert not scene.world_state.facts


@pytest.mark.asyncio
async def test_offscreen_template_uses_owned_views_without_requesting_retrieval(
    returning_scene, monkeypatch
):
    scene = returning_scene
    narrator = get_agent("narrator")
    narrator.actions["offscreen_life"].enabled = True
    monkeypatch.setattr(
        narrator,
        "rag_build",
        AsyncMock(
            side_effect=AssertionError(
                "Offscreen Life must not launch AI-assisted retrieval"
            )
        ),
    )
    prompts = []

    async def request(name, *args, **kwargs):
        prompt = Prompt.get(name, vars=kwargs["vars"]).render()
        prompts.append(prompt)
        assert "private secret" not in prompt
        assert "Nora has now returned" in prompt
        return "", {"response": "Nora repaired her coat."}

    monkeypatch.setattr(Prompt, "request", request)
    transition = await leave_and_return(scene, lines=1)
    assert transition.offscreen_status == "ready"
    assert len(prompts) == 1
    narrator.rag_build.assert_not_awaited()


@pytest.mark.asyncio
async def test_arrival_note_endpoint_keeps_automatic_text_read_only(
    returning_scene, monkeypatch
):
    from types import SimpleNamespace
    from talemate.server.scene_message import SceneMessagePlugin

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    frames = []
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))
    await plugin.handle_transition_note(
        {"id": transition.id, "text": "  Her boots are wet.  "}
    )
    assert transition.arrival_note == "Her boots are wet."
    await plugin.handle_edit(
        {"id": transition.id, "text": "No time passed and she never left."}
    )
    assert transition.message == ""
    assert "2 Days" in render_transition(scene, transition)
    assert any(frame.get("error") for frame in frames)


@pytest.mark.asyncio
async def test_changed_arrival_constraints_discard_inflight_account(
    returning_scene, monkeypatch
):
    scene = returning_scene
    get_agent("narrator").actions["offscreen_life"].enabled = True

    async def request(*args, **kwargs):
        latest_transition(scene, "Nora").arrival_note = "She has a broken arm."
        return "", {"response": "Nora arrives in perfect health."}

    monkeypatch.setattr(Prompt, "request", request)
    transition = await leave_and_return(scene, lines=1)
    assert transition.offscreen_status == "failed"
    assert transition.offscreen_fact_id is None
    assert not scene.world_state.facts


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed"])
async def test_unavailable_arrival_view_does_not_break_display_or_reload(
    returning_scene, persistence_scene_factory, status
):
    from types import SimpleNamespace
    from talemate.emit import Emission
    from talemate.exceptions import GenerationCancelled
    from talemate.knowledge.transitions import transition_payload
    from talemate.load import load_scene_from_data
    from talemate.server.websocket_server import WebsocketHandler

    scene = returning_scene
    if scene.knowledge_eligibility != "perception":
        return
    transition = await leave_and_return(scene, lines=1)
    arrival = add_line(scene, "Mara opens the gate.", ["Nora", "Mara"])
    # An author edit leaves a view pending; a failed rebuild leaves it failed.
    scene.edit_message(arrival.id, "Mara closes the gate instead.")
    set_source_perspectives(
        scene,
        "message",
        arrival.id,
        [
            {"audience": ["Nora"], "status": status, "text": None},
            {"audience": ["Mara"], "status": "ready", "text": "Mara opens the gate."},
        ],
    )
    frames = []
    handler = SimpleNamespace(scene=scene, queue_put=frames.append)
    payload = transition_payload(scene, transition)
    assert "Nora has now returned" in payload["text"]
    assert "Mara opens" not in payload["text"]
    WebsocketHandler.handle_character_transition(
        handler, Emission(typ="character_transition", message_object=transition)
    )
    WebsocketHandler.handle_scene_status(handler, Emission(typ="scene_status", data={}))
    await scene.emit_history()
    assert frames[-1]["type"] == "scene_status"
    assert frames[-1]["data"]["character_transitions"][0] == payload
    with pytest.raises(GenerationCancelled):
        render_transition(scene, transition)
    saved = deepcopy(scene.serialize)
    saved["history"] = [message.to_dict() for message in scene.history]
    restored = persistence_scene_factory()
    await load_scene_from_data(restored, saved)
    assert (
        "Nora has now returned"
        in transition_payload(restored, latest_transition(restored, "Nora"))["text"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("creation", ["transfer", "persist", "node"])
async def test_created_inactive_character_first_arrival_is_not_a_return(
    returning_scene, creation, tmp_path, monkeypatch
):
    import json
    from talemate.agents.director.character_management import PersistCharacterRequest
    from talemate.game.engine.nodes.core import GraphContext
    from talemate.game.engine.nodes.scene import MakeCharacter
    from talemate.knowledge.transitions import departures
    from talemate.load import transfer_character

    scene = returning_scene
    request = AsyncMock(
        side_effect=AssertionError("First arrival must not request Offscreen Life")
    )
    monkeypatch.setattr(Prompt, "request", request)
    get_agent("narrator").actions["offscreen_life"].enabled = True
    if creation == "transfer":
        source = tmp_path / "source.json"
        source.write_text(json.dumps({"character_data": {"Ada": {"name": "Ada"}}}))
        await transfer_character(scene, str(source), "Ada")
    elif creation == "persist":
        character = await get_agent("director").persist_character(
            PersistCharacterRequest(
                name="Ada",
                generate=False,
                active=False,
            )
        )
        assert character is not None
    else:
        node = MakeCharacter()
        for key, value in {
            "name": "Ada",
            "color": "#123456",
            "base_attributes": {},
            "is_active": False,
        }.items():
            node.set_property(key, value)
        with GraphContext() as state:
            await node.run(state)
    assert "Ada" not in departures(scene)
    assert "Ada" not in scene.active_characters
    add_line(scene, "The others close the shutters.", ["Nora", "Mara"])
    scene.history.append(TimePassageMessage("An hour passes", ts=3600))
    await activate_character(scene, "Ada")
    transition = latest_transition(scene, "Ada")
    assert not transition.returning
    assert "first time" in render_transition(scene, transition)
    assert not offscreen_eligible(scene, transition)
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["false", "superseded"])
async def test_return_account_uses_current_fact_projection(returning_scene, state):
    from talemate.knowledge.schema import Fact
    from talemate.knowledge.topics import known_bucket

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    fact = Fact(
        id="F1", text="Nora repaired her coat.", source="offscreen", present=["Nora"]
    )
    scene.world_state.facts[fact.id] = fact
    transition.offscreen_fact_id = fact.id
    assert fact.id in {item.id for item in known_bucket(scene, "Nora")}
    assert fact.id not in {item.id for item in known_bucket(scene, "Mara")}
    assert fact.text in render_transition(scene, transition)
    if state == "false":
        fact.false = True
    else:
        scene.world_state.facts["F2"] = Fact(
            id="F2",
            text="The coat was beyond repair.",
            source="offscreen",
            present=["Nora"],
            supersedes="F1",
        )
    assert fact.text not in render_transition(scene, transition)


@pytest.mark.asyncio
async def test_deleted_account_allows_explicit_background_retry(
    returning_scene, monkeypatch
):
    from types import SimpleNamespace
    from talemate.knowledge.schema import Fact
    from talemate.knowledge.transitions import transition_payload
    from talemate.server.scene_message import SceneMessagePlugin

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    scene.world_state.facts["F1"] = Fact(
        id="F1", text="Old account", source="offscreen", present=["Nora"]
    )
    transition.offscreen_fact_id = "F1"
    transition.offscreen_status = "ready"
    del scene.world_state.facts["F1"]
    payload = transition_payload(scene, transition)
    assert payload["offscreen_status"] == "failed"
    assert payload["offscreen_fact_id"] is None
    frames = []
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))
    narrator = get_agent("narrator")
    narrator.actions["offscreen_life"].enabled = True
    started, release = asyncio.Event(), asyncio.Event()

    async def request(*args, **kwargs):
        started.set()
        await release.wait()
        return "", {"response": "Nora mended her pack."}

    monkeypatch.setattr(Prompt, "request", request)
    task = await asyncio.wait_for(
        plugin.handle_retry_offscreen({"id": transition.id}), 1
    )
    await asyncio.wait_for(started.wait(), 1)
    assert not task.done()  # The websocket receive loop is free during the request.
    release.set()
    await task
    assert transition.offscreen_status == "ready"
    assert any(frame.get("action") == "operation_done" for frame in frames)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_regenerate_after_activation_preserves_return_entry(
    returning_scene, monkeypatch, cancel
):
    import importlib
    from talemate.exceptions import GenerationCancelled

    regen = importlib.import_module("talemate.regenerate")
    scene = returning_scene
    transition = await leave_and_return(scene, lines=1, seconds=0)
    target = scene.history[-2]
    assert regen.regenerate_target_message(scene) is target
    assert regen.can_regenerate(scene)
    before = list(scene.history)

    async def regenerate_tail(current_scene):
        assert current_scene.history[-1] is target
        assert transition not in current_scene.history
        if cancel:
            raise GenerationCancelled("Cancelled test generation")
        return [target]

    monkeypatch.setattr(regen, "_regenerate", regenerate_tail)
    if cancel:
        with pytest.raises(GenerationCancelled):
            await regen.regenerate(scene)
    else:
        assert await regen.regenerate(scene) == [target]
    assert scene.history == before
    assert scene.history[-1] is transition


@pytest.mark.asyncio
@pytest.mark.parametrize("best_fit", [False, True])
@pytest.mark.parametrize("budget", [600, 800, 1000, 1500])
@pytest.mark.parametrize("long_prelude", [False, True])
async def test_real_archive_cuts_keep_silent_return_chronological(
    returning_scene, best_fit, budget, long_prelude
):
    from talemate.knowledge.transitions import summary_message_span
    from talemate.agents.summarize.context_history import ContextHistoryParams

    scene = returning_scene
    if scene.knowledge_eligibility != "legacy":
        return
    summarizer = get_agent("summarizer")
    summarizer.actions["manage_scene_history"].config["best_fit"].value = best_fit
    if long_prelude:
        for i in range(10):
            add_line(
                scene,
                f"Earlier jointly witnessed passage {i}. "
                + "The old tower stood beyond the river. " * 10,
                ["Nora", "Mara"],
            )
    # Presence cuts put the skipped return into the preceding absence entry.
    transition = await leave_and_return(scene, lines=3, seconds=0)
    for i in range(8):
        add_line(
            scene,
            f"After return, Mara reports station {i}. "
            + "The lamp burns steadily. " * 8,
            ["Nora", "Mara"],
        )
    scene.history.append(TimePassageMessage("A minute passes", ts=60))
    add_line(scene, "Latest visible moment.", ["Nora", "Mara"])
    for i in range(5):
        span = summarizer.collect_archive_span(scene)
        if span.end is None:
            break
        scene.archived_history.append(
            {
                "id": f"H{i}",
                "start": span.start,
                "end": span.end,
                "text": "After return, Mara reports all stations."
                if i == 2
                else f"Earlier chapter {i}",
                "ts": message_times(scene)[scene.history[span.end].id],
                "present": span.dialogue_entries[0].present,
            }
        )
    index = next(i for i, item in enumerate(scene.history) if item is transition)
    owners = [
        entry
        for entry in scene.archived_history
        if (span := summary_message_span(scene, entry, 0))
        and span[0] <= index <= span[1]
    ]
    assert len(owners) == 1
    assert scene.archived_history[-1]["end"] > index
    parts = scene.context_history(budget=budget, perspective="Nora")
    assert all(part.strip() for part in parts)
    text = "\n".join(parts)
    assert text.count("(Nora did not witness") <= 1
    assert text.count("Nora has now returned") == 1
    assert "After return, Mara reports" in text
    assert text.index("Nora has now returned") < text.index(
        "After return, Mara reports"
    )
    assert "Latest visible moment" in text
    preview = summarizer.context_history_preview(
        scene, budget, params=ContextHistoryParams(perspective="Nora")
    )
    preview_parts = [
        line for section in preview["sections"] for line in section["entries"]
    ]
    assert all(part.strip() for part in preview_parts)
    preview_text = "\n".join(preview_parts)
    assert preview_text.count("(Nora did not witness") <= 1
    assert preview_text.count("Nora has now returned") == 1
    assert preview_text.index("Nora has now returned") < preview_text.index(
        "After return, Mara reports"
    )


@pytest.mark.asyncio
async def test_offscreen_prompt_measures_sheet_and_scopes_static_inputs(
    returning_scene, monkeypatch
):
    from talemate.util import count_tokens

    scene = returning_scene
    await leave_and_return(scene, lines=1)
    nora = scene.get_character("Nora")
    nora.description = "Nora carries a map and studies every road. " * 200
    scene.description = "A journey through the mountain passes."
    viewers = []

    def snapshot(viewer=None):
        viewers.append(viewer)
        return {
            "location": "Nora's known camp"
            if viewer == "Nora"
            else "Mara's secret refuge",
            "characters": [],
            "items": [],
            "places": [],
        }

    monkeypatch.setattr(
        type(scene.world_state),
        "snapshot_for",
        lambda self, viewer=None: snapshot(viewer),
    )
    get_agent("world_state").actions["update_world_state"].config[
        "inject_as_scene_memory"
    ].value = True
    prompt = Prompt.get(
        "narrator.offscreen-life",
        vars={
            "scene": scene,
            "character": nora,
            "max_tokens": 4096,
            "response_length": 192,
            "known_facts": [],
            "elapsed": "2 Days",
            "extra_instructions": "",
        },
    ).render()
    assert count_tokens(prompt) + 192 <= 4096
    assert prompt.count("Nora has now returned") == 1
    assert "mountain passes" in prompt
    assert "Nora's known camp" in prompt
    assert "secret refuge" not in prompt
    assert viewers == ["Nora"]


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_enabled", [False, True])
async def test_custom_standard_filter_controls_recording_and_offscreen(
    returning_scene, monkeypatch, filter_enabled
):
    scene = returning_scene
    if scene.knowledge_eligibility != "legacy":
        return
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].config[
        "perspective_filter"
    ].value = filter_enabled
    get_agent("narrator").actions["offscreen_life"].enabled = True
    request = AsyncMock(return_value=("", {"response": "Nora checked the road."}))
    monkeypatch.setattr(Prompt, "request", request)
    transition = await leave_and_return(scene, lines=1)
    assert (transition is not None) == filter_enabled
    assert request.await_count == int(filter_enabled)


@pytest.mark.asyncio
async def test_offscreen_keeps_evidence_catchup_without_generation_hooks(
    returning_scene, monkeypatch
):
    from talemate.agents.narrator import _narration
    from talemate.agents.context import ActiveAgent
    import talemate.emit.async_signals as signals
    import talemate.knowledge.revision_refresh as revisions

    scene = returning_scene
    narrator = get_agent("narrator")
    calls = []

    async def catchup(current):
        assert current is scene
        calls.append("revisions")

    async def perceptions(current):
        assert current is scene
        calls.append("perceptions")

    async def generate(*args, **kwargs):
        calls.append("generate")
        return "result"

    monkeypatch.setattr(revisions, "catch_up_revisions", catchup)
    monkeypatch.setattr(get_agent("summarizer"), "ensure_perceptions", perceptions)
    hooks = [AsyncMock() for _ in range(3)]
    for name, hook in zip(
        ["before_generate", "inject_instructions", "generated"], hooks
    ):
        monkeypatch.setattr(signals.get(f"agent.narrator.{name}"), "send", hook)
    with ActiveAgent(narrator, generate):
        assert (
            await _narration(
                narrator,
                generate,
                (),
                {},
                emit_generated=False,
                run_generation_hooks=False,
            )
            == "result"
        )
    assert calls == (
        ["revisions", "perceptions", "generate"]
        if scene.knowledge_eligibility == "perception"
        else ["revisions", "generate"]
    )
    for hook in hooks:
        hook.assert_not_awaited()


@pytest.mark.asyncio
async def test_world_editor_activation_keeps_websocket_free(
    returning_scene, monkeypatch
):
    from types import SimpleNamespace
    from talemate.server.world_state_manager import WorldStateManagerPlugin

    scene = returning_scene
    add_line(scene, "Nora leaves the gate.", ["Nora", "Mara"])
    await deactivate_character(scene, "Nora")
    add_line(scene, "Mara closes the shutters.", ["Mara"])
    get_agent("narrator").actions["offscreen_life"].enabled = True
    started, release = asyncio.Event(), asyncio.Event()

    async def request(*args, **kwargs):
        started.set()
        await release.wait()
        return "", {"response": "Nora checked the road."}

    monkeypatch.setattr(Prompt, "request", request)
    frames = []
    plugin = WorldStateManagerPlugin(
        SimpleNamespace(scene=scene, queue_put=frames.append)
    )
    task = await asyncio.wait_for(plugin.handle_activate_character({"name": "Nora"}), 1)
    await asyncio.wait_for(started.wait(), 1)
    assert not task.done()
    release.set()
    await task
    assert latest_transition(scene, "Nora").offscreen_status == "ready"
    assert any(frame.get("action") == "character_activated" for frame in frames)


@pytest.mark.asyncio
async def test_return_render_checks_only_account_and_possible_successors(
    returning_scene, monkeypatch
):
    from time import perf_counter
    from types import SimpleNamespace
    from unittest.mock import Mock
    from talemate.knowledge import revision_browsing
    from talemate.knowledge.schema import Fact
    from talemate.server.websocket_server import WebsocketHandler

    scene = returning_scene
    for i in range(10):
        transition = await leave_and_return(scene, lines=39, seconds=0)
        fact = Fact(
            id=f"F{i}",
            text=f"Nora mended item {i}.",
            source="offscreen",
            present=["Nora"],
        )
        scene.world_state.facts[fact.id] = fact
        transition.offscreen_fact_id = fact.id
    for i in range(10, 200):
        scene.world_state.facts[f"F{i}"] = Fact(id=f"F{i}", text=f"Other fact {i}")
    checked = Mock(wraps=revision_browsing.stale_archive_ids)
    monkeypatch.setattr(revision_browsing, "stale_archive_ids", checked)
    frames = []
    handler = SimpleNamespace(scene=scene, queue_put=frames.append)
    emission = SimpleNamespace(message="test", status="idle", data={})
    started = perf_counter()
    WebsocketHandler.handle_scene_status(handler, emission)
    elapsed = perf_counter() - started
    print(
        f"status {scene.knowledge_eligibility}: {len(scene.history)} messages / 200 facts / 10 returns: {elapsed:.4f}s, {checked.call_count} source scans"
    )
    assert len(frames[0]["data"]["character_transitions"]) == 10
    assert checked.call_count == 10
    assert all(
        "During the absence:" in item["text"]
        for item in frames[0]["data"]["character_transitions"]
    )

    for message in scene.history:
        if isinstance(message, CharacterTransitionMessage):
            message.offscreen_fact_id = None
    checked.reset_mock()
    frames.clear()
    WebsocketHandler.handle_scene_status(handler, emission)
    checked.assert_not_called()
    assert all(
        "During the absence:" not in item["text"]
        for item in frames[0]["data"]["character_transitions"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query", ["facts_about", "current_state", "relationship_timeline"]
)
async def test_owner_fact_queries_accept_offscreen_accounts(returning_scene, query):
    from talemate.knowledge import graph
    from talemate.knowledge.schema import Fact

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    for i in range(2):
        fact = Fact(
            id=f"F{i}",
            text=f"Nora remembered Mara {i}.",
            source="offscreen",
            present=["Nora"],
            ts=i,
        )
        scene.world_state.facts[fact.id] = fact
    transition.offscreen_fact_id = "F1"
    fn = getattr(graph, query)
    args = (
        (scene, "Nora", "Mara") if query == "relationship_timeline" else (scene, "Nora")
    )
    owned = fn(*args, character="Nora")
    if query == "current_state":
        assert owned.id == "F1"
        assert fn(*args, character="Mara") is None
    else:
        assert {fact.id for fact in owned} == {"F0", "F1"}
        assert fn(*args, character="Mara") == []
        if query == "relationship_timeline":
            assert [fact.id for fact in owned] == ["F0", "F1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("returning_scene", ["legacy"], indirect=True)
@pytest.mark.parametrize("best_fit", [False, True])
@pytest.mark.parametrize("ratio", [30, 50, 75])
@pytest.mark.parametrize("budget", [550, 650, 750, 1500, 3000])
async def test_layered_real_archive_cuts_render_return_once(
    returning_scene, best_fit, ratio, budget
):
    from talemate.agents.summarize.context_history import ContextHistoryParams

    scene = returning_scene
    summarizer = get_agent("summarizer")
    config = summarizer.actions["manage_scene_history"].config
    config["best_fit"].value = best_fit
    config["dialogue_ratio"].value = ratio
    config["summary_detail_ratio"].value = 50
    summarizer.actions["layered_history"].enabled = True
    for i in range(8):
        for j in range(3):
            add_line(
                scene,
                f"PRE-{i}-{j} " + "The old tower stood beyond the river. " * 8,
                ["Nora", "Mara"],
            )
        if i < 7:
            scene.history.append(TimePassageMessage("A minute passes", ts=60))
    transition = await leave_and_return(scene, lines=3, seconds=0)
    for i in range(6):
        for j in range(3):
            add_line(
                scene,
                f"POST-{i}-{j} "
                + "Mara reports the station and its steady light. " * 8,
                ["Nora", "Mara"],
            )
        scene.history.append(TimePassageMessage("A minute passes", ts=60))
    add_line(scene, "LATEST visible moment.", ["Nora", "Mara"])
    for i in range(20):
        span = summarizer.collect_archive_span(scene)
        if span.end is None:
            break
        marker = "PRE" if i < 8 else "ABSENCE" if i == 8 else "POST"
        scene.archived_history.append(
            {
                "id": f"H{i}",
                "start": span.start,
                "end": span.end,
                "text": f"{marker}-{i} "
                + "The chapter records the changing state of the station. " * 3,
                "ts": message_times(scene)[scene.history[span.end].id],
                "present": span.dialogue_entries[0].present,
            }
        )
    assert len(scene.archived_history) == 15
    assert scene.history[scene.archived_history[8]["end"]] is transition
    scene.layered_history = [
        [
            {
                "id": f"L{i}",
                "start": start,
                "end": end,
                "text": f"LAYER-{i} compressed chapter.",
                "ts_start": 0,
                "ts_end": 0,
            }
            for i, (start, end) in enumerate([(0, 3), (4, 8), (9, 12)])
        ]
    ]
    parts = scene.context_history(budget=budget, perspective="Nora")
    preview = summarizer.context_history_preview(
        scene, budget, params=ContextHistoryParams(perspective="Nora")
    )
    preview_parts = [
        part for section in preview["sections"] for part in section["entries"]
    ]
    for selected in (parts, preview_parts):
        assert all(part.strip() for part in selected)
        text = "\n".join(selected)
        assert text.count("Nora has now returned") == 1
        boundary = text.index("Nora has now returned")
        assert "PRE-" not in text[boundary:]
        # The bridge's grounded arrival excerpt can itself contain POST-0.
        assert "POST-" not in text[:boundary]
        assert "LATEST" in text
        assert text.count("(Nora did not witness") <= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("returning_scene", ["legacy"], indirect=True)
@pytest.mark.parametrize("best_fit", [False, True])
@pytest.mark.parametrize("split_absence", [False, True])
async def test_real_absence_expansion_adds_no_empty_part_or_second_gap(
    returning_scene, best_fit, split_absence
):
    from talemate.agents.summarize.context_history import ContextHistoryParams

    scene = returning_scene
    summarizer = get_agent("summarizer")
    summarizer.actions["manage_scene_history"].config["best_fit"].value = best_fit
    add_line(
        scene,
        "PRE departure. " + "A long jointly witnessed farewell. " * 400,
        ["Nora", "Mara"],
    )
    await deactivate_character(scene, "Nora")
    for i in range(3):
        add_line(scene, f"PRIVATE absence {i}.", ["Mara"])
    await activate_character(scene, "Nora")
    add_line(scene, "POST arrival.", ["Nora", "Mara"])
    add_line(scene, "LATEST moment.", ["Nora", "Mara"])
    threshold = summarizer.actions["archive"].config["threshold"]
    original_threshold = threshold.value
    for i in range(4):
        threshold.value = 1 if split_absence and i == 1 else original_threshold
        span = summarizer.collect_archive_span(scene)
        if span.end is None:
            break
        scene.archived_history.append(
            {
                "id": f"H{i}",
                "start": span.start,
                "end": span.end,
                "text": f"SUM-{i}",
                "ts": message_times(scene)[scene.history[span.end].id],
                "present": span.dialogue_entries[0].present,
            }
        )
    threshold.value = original_threshold
    assert len(scene.archived_history) == (3 if split_absence else 2)
    parts = scene.context_history(budget=1500, perspective="Nora")
    preview = summarizer.context_history_preview(
        scene, 1500, params=ContextHistoryParams(perspective="Nora")
    )
    for selected in (
        parts,
        [part for section in preview["sections"] for part in section["entries"]],
    ):
        assert all(part.strip() for part in selected)
        text = "\n".join(selected)
        assert text.count("Nora has now returned") == 1
        assert text.count("(Nora did not witness") <= 1
        if not best_fit:
            assert text.count("(Nora did not witness") == 1
        assert "PRIVATE" not in text

    if split_absence:
        params = ContextHistoryParams(perspective="Nora").bind(scene)
        dialogue, _, _ = summarizer._context_history_collect_dialogue(
            scene, 750, params
        )
        layer = {
            "id": "L-absence",
            "start": 1,
            "end": 2,
            "text": "PRIVATE compressed absence",
            "ts_start": 0,
            "ts_end": 0,
        }
        expanded = summarizer._transition_summary(
            scene, layer, 1, params, prev_boundary=2
        )
        assert expanded is not None and not expanded
        layers, _, _ = summarizer._context_history_collect_layer(
            [layer], scene.ts, 750, 2, scene=scene, layer_index=0, params=params
        )
        assert layers == []
        text = "\n".join([*layers, *dialogue])
        assert text.count("Nora has now returned") == 1
        assert text.count("(Nora did not witness") <= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        "false_successor",
        "private_successor",
        "stale_successor",
        "visible_successor",
        "stale_account",
        "wrong_owner",
        "wrong_source",
    ],
)
async def test_targeted_account_resolution_matches_current_projection(
    returning_scene, state
):
    from talemate.knowledge.chronology import ranked_facts
    from talemate.knowledge.schema import Fact
    from talemate.knowledge.topics import known_bucket

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    account = Fact(
        id="F1", text="Nora repaired her coat.", source="offscreen", present=["Nora"]
    )
    successor = Fact(
        id="F2",
        text="Nora replaced her coat.",
        source="offscreen",
        present=["Nora"],
        supersedes="F1",
    )
    scene.world_state.facts = {"F1": account, "F2": successor}
    transition.offscreen_fact_id = "F1"
    if state == "false_successor":
        successor.false = True
    elif state == "private_successor":
        successor.present = ["Mara"]
    elif state == "stale_successor":
        successor.message_id = -999
    elif state == "stale_account":
        account.message_id = -999
    elif state == "wrong_owner":
        account.present = ["Mara"]
    elif state == "wrong_source":
        account.source = "manual"
    visible = {
        fact.id
        for fact in ranked_facts(
            scene, known_bucket(scene, "Nora"), character="Nora", tiers=False
        )
        if not fact.false
    }
    expected = (
        "F1" in visible
        and account.source == "offscreen"
        and account.present == ["Nora"]
    )
    assert (account.text in render_transition(scene, transition)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("returning_scene", ["legacy"], indirect=True)
@pytest.mark.parametrize(
    "rule,expected",
    [
        ("block_account", False),
        ("block_successor", True),
        ("allow_private_successor", False),
    ],
)
async def test_targeted_account_respects_standard_knowledge_edges(
    returning_scene, rule, expected
):
    from talemate.knowledge.schema import Fact, KnowledgeEdge
    from talemate.knowledge.transitions import offscreen_account

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    account = Fact(
        id="F1", text="Nora repaired her coat.", source="offscreen", present=["Nora"]
    )
    successor = Fact(
        id="F2",
        text="Nora replaced her coat.",
        source="offscreen",
        present=["Nora"],
        supersedes="F1",
    )
    scene.world_state.facts = {"F1": account, "F2": successor}
    transition.offscreen_fact_id = "F1"
    if rule == "block_account":
        successor.supersedes = None
        edge = KnowledgeEdge(character="Nora", target="F1", kind="revoke")
    elif rule == "block_successor":
        edge = KnowledgeEdge(character="Nora", target="F2", kind="revoke")
    else:
        successor.present = ["Mara"]
        edge = KnowledgeEdge(character="Nora", target="F2", kind="grant")
    scene.world_state.knowledge.append(edge)
    assert (offscreen_account(scene, transition) is account) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("returning_scene", ["perception"], indirect=True)
async def test_offscreen_account_with_missing_owner_is_unavailable(returning_scene):
    from talemate.knowledge.schema import Fact
    from talemate.knowledge.transitions import offscreen_account

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    scene.world_state.facts["F1"] = Fact(
        id="F1", text="Nora mended her coat.", source="offscreen", present=["Nora"]
    )
    transition.offscreen_fact_id = "F1"
    del scene.character_data["Nora"]
    assert offscreen_account(scene, transition) is None
