import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.character import Character, activate_character, deactivate_character
from talemate.context import ActiveScene, SceneIsLoading
from talemate.instance import get_agent
from talemate.knowledge.perspectives import bind_message_source, set_source_perspectives
from talemate.knowledge.timeline import message_times
from talemate.knowledge.transitions import (
    absence_seconds,
    latest_transition,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["chat", "chat-narrated", "world-editor"])
@pytest.mark.parametrize("best_fit", [False, True])
@pytest.mark.parametrize("seconds", [0, 172800])
@pytest.mark.parametrize("knowledge_source", ["history", "fact", "memory"])
async def test_ui_absence_excludes_player_and_npc_lines_from_return_context(
    scene, monkeypatch, route, best_fit, seconds, knowledge_source
):
    from collections import deque
    from types import SimpleNamespace

    from conftest import client_responses
    from talemate.agents.context import ActiveAgent
    from talemate.agents.director.websocket_handler import DirectorWebsocketHandler
    from talemate.agents.memory.schema import MemoryDocument
    from talemate.game.engine.nodes.core import GraphState
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
    from talemate.game.engine.nodes.ux import EmitElement
    from talemate.game.engine.ux.schema import UXSelection
    from talemate.knowledge.facts import SpanLine, store_facts
    from talemate.knowledge.perspective_models import content_digest
    from talemate.knowledge.presence import presence_metadata
    from talemate.knowledge.schema import ParsedFact
    from talemate.server.world_state_manager import WorldStateManagerPlugin

    scene.knowledge_eligibility = "legacy"
    monkeypatch.setattr(type(scene), "auto_save", property(lambda _: False))
    monkeypatch.setattr(get_agent("memory"), "add_many", AsyncMock(return_value=True))
    monkeypatch.setattr(get_agent("memory"), "_get", lambda *args, **kwargs: [])
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    conversation.actions["character_knowledge"].config[
        "perspective_filter"
    ].value = True
    get_agent("summarizer").actions["manage_scene_history"].config[
        "best_fit"
    ].value = best_fit

    async def submit_narration(node, state, ux_id, scene, timeout_seconds, start_time):
        return UXSelection(ux_id=ux_id, kind="text_input", selected=""), False, False

    monkeypatch.setattr(EmitElement, "wait_for_interaction", submit_narration)
    frames = []
    handler = SimpleNamespace(scene=scene, queue_put=frames.append)
    ensure_registry_loaded()
    scene.nodegraph_state = GraphState()
    router = (
        WorldStateManagerPlugin(handler)
        if route == "world-editor"
        else DirectorWebsocketHandler(handler)
    )
    monkeypatch.setattr(DirectorWebsocketHandler, "sub_handlers", {}, raising=False)
    await type(get_agent("director")).init_nodes(scene, scene.nodegraph_state)
    create_task = asyncio.create_task
    tasks = []

    def track(coro, **kwargs):
        task = create_task(coro, **kwargs)
        tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", track)

    async def dispatch(action, responses):
        tasks.clear()
        queue = deque(responses)
        token = client_responses.set(queue)
        try:
            await router.handle(
                {
                    "type": router.router,
                    "action": action,
                    "character_name": "Nora",
                    "name": "Nora",
                    "never_narrate": route != "chat-narrated",
                }
            )
            if tasks:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            assert not queue
        finally:
            client_responses.reset(token)
        assert not any(frame.get("error") for frame in frames)

    with ActiveScene(scene):
        for name in ["Nora", "Barry Largo", "Elmer"]:
            character = Character(name=name, is_player=name == "Barry Largo")
            actor = (
                scene.Player(character, None)
                if character.is_player
                else Actor(character, conversation)
            )
            await scene.add_actor(actor, commit_to_memory=False)
        await scene.push_history(NarratorMessage("Everyone gathers by the gate."))
        await dispatch(
            "deactivate_character",
            ["Yes", "No", "Nora walks outside."] if route == "chat-narrated" else [],
        )
        assert "Nora" not in scene.active_characters
        assert not scene.character_is_active(scene.get_character("Nora"))
        player_line = CharacterMessage('Barry Largo: "Hello Elmer!"', source="player")
        npc_line = CharacterMessage('Elmer: "Good day Barry."')
        await scene.push_history(player_line)
        await scene.push_history(npc_line)
        assert set(player_line.present) == {"Barry Largo", "Elmer"}
        assert set(npc_line.present) == {"Barry Largo", "Elmer"}
        fact_text = "Barry Largo greeted Elmer at the gate."
        if knowledge_source == "fact":
            facts = await store_facts(
                scene,
                None,
                [ParsedFact(text=fact_text, message_id=player_line.id)],
                0.15,
                lines={
                    player_line.id: SpanLine(
                        message_id=player_line.id,
                        message_digest=content_digest(str(player_line)),
                        present=player_line.present,
                        ts=scene.ts,
                    )
                },
            )
            assert len(facts) == 1
            assert facts[0].message_id == player_line.id
            assert set(facts[0].present) == {"Barry Largo", "Elmer"}
        if seconds:
            await scene.push_history(
                TimePassageMessage(ts=seconds, message="Two days pass.")
            )
        await dispatch(
            "activate_character",
            ["No", "Nora steps back through the gate."]
            if route == "chat-narrated"
            else [],
        )
        assert "Nora" in scene.active_characters
        transition = latest_transition(scene, "Nora")
        assert transition.returning
        assert absence_seconds(scene, transition) == seconds
        await scene.push_history(CharacterMessage('Elmer: "Welcome back, Nora."'))
        conversation.actions["use_long_term_memory"].enabled = (
            knowledge_source == "memory"
        )
        known_memory = "Everyone once painted the garden gate green."
        if knowledge_source == "memory":
            documents = [
                MemoryDocument(
                    str(message),
                    id=str(message.id),
                    raw=str(message),
                    meta={"typ": "history", **presence_metadata(message.present)},
                    distance=0.1,
                )
                for message in (player_line, npc_line)
            ]
            documents.append(
                MemoryDocument(
                    known_memory,
                    id="known-gate-memory",
                    raw=known_memory,
                    meta={
                        "typ": "history",
                        **presence_metadata(["Nora", "Barry Largo", "Elmer"]),
                    },
                    distance=0.2,
                )
            )
            retrieve = Mock(return_value=documents)
            monkeypatch.setattr(get_agent("memory"), "_get", retrieve)
            memories = await conversation.rag_build(scene.get_character("Nora"))
            assert retrieve.called
            assert list(map(str, memories)) == [known_memory]
        else:
            memories = []
        request = AsyncMock(return_value=("", {"answer": "none", "items": []}))
        monkeypatch.setattr(Prompt, "request", request)
        await conversation.memory_pass(scene.get_character("Nora"), memories)
        assert request.call_args.kwargs["vars"]["candidates"] == memories
        get_agent("summarizer").actions["analyze_scene"].enabled = False
        with ActiveAgent(conversation, conversation.build_prompt):
            prompt = await conversation.build_prompt(scene.get_character("Nora"))
            dialogue_prompt = prompt.render()
        histories = [
            scene.context_history(budget=8192, perspective="Nora"),
            request.call_args.kwargs["vars"]["scene_history"],
            [dialogue_prompt],
        ]
        for parts in histories:
            text = "\n".join(parts)
            assert "Hello Elmer!" not in text
            assert "Good day Barry." not in text
            assert "Everyone gathers by the gate." in text
            assert "Welcome back, Nora." in text
            assert text.count("Nora has returned") == 1
        if knowledge_source == "fact":
            absence_lines = await conversation.absence_block(
                scene.get_character("Nora")
            )
            assert len(absence_lines) == 1
            assert fact_text in absence_lines[0]
            assert fact_text not in "\n".join(histories[0])
            assert fact_text not in "\n".join(histories[1])
            assert dialogue_prompt.count(fact_text) == 1
            assert (
                "Nora has not learned any of the following. Do not let Nora act on, "
                "refer to, or react to these:\n- " + absence_lines[0]
            ) in dialogue_prompt
        elif knowledge_source == "memory":
            assert known_memory in dialogue_prompt
        assert "Hello Elmer!" in "\n".join(scene.context_history(budget=8192))


@pytest.fixture(params=["legacy", "perception"])
def returning_scene(scene, request, monkeypatch):
    scene.knowledge_eligibility = request.param
    monkeypatch.setattr(get_agent("memory"), "add_many", AsyncMock(return_value=True))
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
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
@pytest.mark.parametrize(
    "seconds,absence",
    [(0, "being away"), (None, "being away"), (172800, "2 days away")],
)
async def test_return_prompt_marks_completed_arrival_without_inventing_time(
    returning_scene, seconds, absence
):
    scene = returning_scene
    transition = await leave_and_return(scene, lines=1, seconds=seconds or 0)
    if seconds is None:
        transition.departure_message_id = None
    transition.participants = ["Mara", "Nora"]
    core = f"Nora has returned to the scene after {absence}."
    assert render_transition(scene, transition) == (
        f"{core}\nAlready in the scene when Nora arrived: Mara."
    )
    arrival = add_line(scene, "Nora sets down her pack.", ["Nora", "Mara"])
    add_line(scene, "Mara offers Nora a seat.", ["Nora", "Mara"])
    add_line(scene, "Mara closes the window.", ["Nora", "Mara"])
    transition.arrival_note = "Her coat is wet."
    rendered = render_transition(scene, transition)
    expected = (
        f"{core}\nAlready in the scene when Nora arrived: Mara.\n"
        "After Nora's arrival (already happened):\n"
        "Nora sets down her pack.\nMara offers Nora a seat.\n"
        "Author's arrival note: Her coat is wet."
    )
    assert [line for line in rendered.splitlines() if line] == expected.splitlines()
    assert f"[{arrival.id}]" not in rendered
    assert render_transition(scene, transition, budget=1) == core


@pytest.mark.asyncio
@pytest.mark.parametrize("participants", [[], ["Nora"]])
async def test_return_prompt_omits_roster_when_nobody_else_was_present(
    returning_scene, participants
):
    transition = await leave_and_return(returning_scene, lines=1)
    transition.participants = participants
    assert render_transition(returning_scene, transition) == (
        "Nora has returned to the scene after 2 days away."
    )


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
    assert "Nora has returned to the scene after 2 days away." in text
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
    restored = _prepare_history(deepcopy(transition.to_dict()))
    assert isinstance(restored, CharacterTransitionMessage)
    assert restored.id == transition.id
    assert restored.kind == "activated"
    assert restored.departure_message_id == transition.departure_message_id
    assert restored.arrival_note == transition.arrival_note
    departure = next(
        message
        for message in scene.history
        if isinstance(message, CharacterTransitionMessage)
        and message.kind == "deactivated"
    )
    assert _prepare_history(deepcopy(departure.to_dict())).kind == "deactivated"


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
@pytest.mark.parametrize("enabled", [True, False])
async def test_activation_and_deactivation_record_entries_in_every_scene(
    returning_scene, monkeypatch, enabled
):
    scene = returning_scene
    if not enabled:
        if scene.knowledge_eligibility != "legacy":
            return
        get_agent("conversation").actions["character_knowledge"].enabled = False
    request = AsyncMock(side_effect=AssertionError("No model request is allowed"))
    monkeypatch.setattr(Prompt, "request", request)
    transition = await leave_and_return(scene, lines=1)
    entries = [
        message
        for message in scene.history
        if isinstance(message, CharacterTransitionMessage)
    ]
    assert [(entry.kind, entry.character_name) for entry in entries] == [
        ("deactivated", "Nora"),
        ("activated", "Nora"),
    ]
    departure, arrival = entries
    assert arrival is transition and arrival.returning
    assert departure.as_format("chat") == ""
    assert bool(arrival.as_format("chat")) == enabled
    assert (protected_transition(scene, "Nora") is arrival) == enabled
    parts = scene.context_history(
        budget=8192,
        perspective="Nora",
        stored_views=scene.knowledge_eligibility == "perception",
    )
    assert all(part.strip() for part in parts)
    assert ("Nora has returned" in "\n".join(parts)) == enabled
    snapshot = scene.snapshot(lines=10, return_as_list=True)
    assert departure not in snapshot
    assert (arrival in snapshot) == enabled
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivated_entry_is_display_only(returning_scene):
    from types import SimpleNamespace
    from talemate.knowledge.transitions import transition_payload
    from talemate.server.scene_message import SceneMessagePlugin

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    add_line(scene, "Mara opens the gate.", ["Nora", "Mara"])
    await deactivate_character(scene, "Nora")
    departure = scene.history[-1]
    add_line(scene, "Mara bolts the gate behind her.", ["Nora", "Mara"])
    assert departure.kind == "deactivated"
    assert latest_transition(scene, "Nora") is transition
    assert protected_transition(scene, "Nora") is None
    assert render_transition(scene, departure) == ""
    text = render_transition(scene, transition)
    assert "Mara opens the gate." in text
    assert "bolts the gate" not in text
    assert transition_payload(scene, departure) == {
        "type": "character_transition",
        "id": departure.id,
        "kind": "deactivated",
        "character": "Nora",
        "color": scene.get_character("Nora").color,
        "transitions_enabled": True,
    }
    frames = []
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))
    await plugin.handle_transition_note({"id": departure.id, "text": "Ignored"})
    assert departure.arrival_note == ""
    assert any(frame.get("error") for frame in frames)


@pytest.mark.asyncio
async def test_activation_payload_is_a_summary_without_prompt_text(returning_scene):
    from talemate.knowledge.transitions import transition_payload

    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    transition.arrival_note = "Her boots are wet."
    payload = transition_payload(scene, transition)
    assert "text" not in payload
    assert payload["kind"] == "activated"
    assert payload["color"] == scene.get_character("Nora").color
    assert payload["transitions_enabled"] is True
    assert payload["returning"] is True
    assert payload["absence_seconds"] == 172800
    assert payload["absence"] == "2 days"
    assert payload["participants"] == transition.participants
    assert set(payload["participants"]) == {"Nora", "Mara"}
    assert payload["arrival_note"] == "Her boots are wet."
    assert payload["available"] is True

    immediate = transition_payload(
        scene, await leave_and_return(scene, lines=0, seconds=0)
    )
    assert immediate["absence_seconds"] == 0
    assert immediate["absence"] is None

    scene.character_data["Ada"] = Character(name="Ada")
    await activate_character(scene, "Ada")
    first = transition_payload(scene, latest_transition(scene, "Ada"))
    assert first["returning"] is False
    assert first["absence_seconds"] is None
    assert first["absence"] is None


@pytest.mark.asyncio
async def test_immediate_return_requires_no_generation(returning_scene, monkeypatch):
    scene = returning_scene
    request = AsyncMock()
    monkeypatch.setattr(Prompt, "request", request)
    await deactivate_character(scene, "Nora")
    await activate_character(scene, "Nora")
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("lines,seconds", [(1, 0), (0, 3600), (3, 172800)])
async def test_return_records_absence_without_generating_or_storing_facts(
    returning_scene, monkeypatch, lines, seconds
):
    from talemate.knowledge.transitions import transition_payload

    scene = returning_scene
    request = AsyncMock(side_effect=AssertionError("Return must not generate"))
    monkeypatch.setattr(Prompt, "request", request)
    transition = await leave_and_return(scene, lines=lines, seconds=seconds)
    assert transition.returning
    assert absence_seconds(scene, transition) == seconds
    assert not scene.world_state.facts
    assert set(transition_payload(scene, transition)) == {
        "type",
        "id",
        "kind",
        "character",
        "color",
        "transitions_enabled",
        "returning",
        "absence_seconds",
        "absence",
        "participants",
        "arrival_note",
        "available",
    }
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_world_editor_return_completes_without_generation(
    returning_scene, monkeypatch
):
    from types import SimpleNamespace
    from talemate.server.world_state_manager import WorldStateManagerPlugin

    scene = returning_scene
    frames = []
    plugin = WorldStateManagerPlugin(
        SimpleNamespace(scene=scene, queue_put=frames.append)
    )
    request = AsyncMock(side_effect=AssertionError("Return must not generate"))
    monkeypatch.setattr(Prompt, "request", request)
    await plugin.handle_deactivate_character({"name": "Nora"})
    add_line(scene, "Mara closes the shutters.", ["Mara"])
    task = await plugin.handle_activate_character({"name": "Nora"})
    await asyncio.wait_for(task, timeout=10)
    assert latest_transition(scene, "Nora").returning
    assert any(frame.get("action") == "character_activated" for frame in frames)
    assert not scene.world_state.facts
    request.assert_not_awaited()


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
    assert "Nora has returned to the scene" in text
    assert (
        text.index("Nora has returned to the scene")
        < text.index("Mara opens the gate.")
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
async def test_arrival_sources_follow_edits_and_deletion(returning_scene):
    scene = returning_scene
    transition = await leave_and_return(scene, lines=1)
    arrival = add_line(scene, "Mara opens the gate.", ["Nora", "Mara"])
    add_line(scene, "Hidden arrival detail.", ["Mara"])
    assert "Mara opens the gate." in render_transition(scene, transition)
    assert "Hidden arrival detail" not in render_transition(scene, transition)
    scene.delete_message(arrival.id)
    assert "Mara opens" not in render_transition(scene, transition)
    passage = next(
        message for message in scene.history if isinstance(message, TimePassageMessage)
    )
    scene.delete_message(passage.id)
    assert absence_seconds(scene, transition) == 0
    assert "Nora has returned" in render_transition(scene, transition)


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
    assert "Nora has returned to the scene after 2 days away." in text
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
            < text.index("Nora has returned to the scene")
            < text.index("Mara opens the gate.")
        )
        assert "private secret" not in text
        assert text.count("Nora has returned") == 1
    params._transition_raw_start = scene.history.index(transition)
    text = ContextHistoryMixin._transition_summary(
        scene, scene.layered_history[0][0], 1, params
    )
    assert "Nora has returned" not in text
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
    assert "after 2 days away" in copy.as_format("chat")
    assert [
        item.kind for item in restored.history if item.typ == "character_transition"
    ] == ["deactivated", "activated"]
    request.assert_not_awaited()


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
    assert "2 days" in render_transition(scene, transition)
    assert any(frame.get("error") for frame in frames)


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
    assert payload["returning"]
    assert payload["absence"] == "2 days"
    assert "text" not in payload
    WebsocketHandler.handle_character_transition(
        handler, Emission(typ="character_transition", message_object=transition)
    )
    WebsocketHandler.handle_scene_status(handler, Emission(typ="scene_status", data={}))
    await scene.emit_history()
    assert frames[-1]["type"] == "scene_status"
    assert frames[-1]["data"]["character_transitions"][-1] == payload
    with pytest.raises(GenerationCancelled):
        render_transition(scene, transition)
    saved = deepcopy(scene.serialize)
    saved["history"] = [message.to_dict() for message in scene.history]
    restored = persistence_scene_factory()
    await load_scene_from_data(restored, saved)
    assert transition_payload(restored, latest_transition(restored, "Nora"))[
        "returning"
    ]


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
        side_effect=AssertionError("First arrival must not request generation")
    )
    monkeypatch.setattr(Prompt, "request", request)
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
    assert not any(
        isinstance(message, CharacterTransitionMessage)
        and message.character_name == "Ada"
        for message in scene.history
    )
    add_line(scene, "The others close the shutters.", ["Nora", "Mara"])
    scene.history.append(TimePassageMessage("An hour passes", ts=3600))
    await activate_character(scene, "Ada")
    transition = latest_transition(scene, "Ada")
    assert not transition.returning
    assert "first time" in render_transition(scene, transition)
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_character_from_a_released_scene_returns_without_a_departure_record(
    returning_scene,
):
    from talemate.knowledge.transitions import departures, transition_payload

    scene = returning_scene
    line = CharacterMessage("Nora: I will check the east gate.")
    scene.history.append(line)
    bind_message_source(scene, line)
    with SceneIsLoading(scene):
        await deactivate_character(scene, "Nora")
    assert "Nora" not in departures(scene)
    assert line.present is None
    scene.history.append(TimePassageMessage(ts=3600, message="An hour later"))
    scene.fix_time()
    await activate_character(scene, "Nora")
    transition = latest_transition(scene, "Nora")
    assert transition.returning
    assert transition.departure_message_id == line.id
    assert absence_seconds(scene, transition) == 3600
    payload = transition_payload(scene, transition)
    assert payload["returning"] is True
    assert payload["absence"] == "1 hour"


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
    assert text.count("(Nora was away") <= 1
    assert text.count("Nora has returned") == 1
    assert "After return, Mara reports" in text
    assert text.index("Nora has returned") < text.index("After return, Mara reports")
    assert "Latest visible moment" in text
    preview = summarizer.context_history_preview(
        scene, budget, params=ContextHistoryParams(perspective="Nora")
    )
    preview_parts = [
        line for section in preview["sections"] for line in section["entries"]
    ]
    assert all(part.strip() for part in preview_parts)
    preview_text = "\n".join(preview_parts)
    assert preview_text.count("(Nora was away") <= 1
    assert preview_text.count("Nora has returned") == 1
    assert preview_text.index("Nora has returned") < preview_text.index(
        "After return, Mara reports"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_enabled", [False, True])
async def test_custom_standard_filter_controls_bridge(
    returning_scene, monkeypatch, filter_enabled
):
    from talemate.knowledge.transitions import transition_payload

    scene = returning_scene
    if scene.knowledge_eligibility != "legacy":
        return
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].config[
        "perspective_filter"
    ].value = filter_enabled
    request = AsyncMock(return_value=("", {"response": "Nora checked the road."}))
    monkeypatch.setattr(Prompt, "request", request)
    transition = await leave_and_return(scene, lines=1)
    assert transition.returning
    request.assert_not_awaited()
    assert bool(render_transition(scene, transition)) == filter_enabled
    payload = transition_payload(scene, transition)
    assert payload["transitions_enabled"] == filter_enabled


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
        assert text.count("Nora has returned") == 1
        boundary = text.index("Nora has returned")
        assert "PRE-" not in text[boundary:]
        # The bridge's grounded arrival excerpt can itself contain POST-0.
        assert "POST-" not in text[:boundary]
        assert "LATEST" in text
        assert text.count("(Nora was away") <= 1


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
        assert text.count("Nora has returned") == 1
        assert text.count("(Nora was away") <= 1
        if not best_fit:
            assert text.count("(Nora was away") == 1
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
        assert text.count("Nora has returned") == 1
        assert text.count("(Nora was away") <= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "passage,nora_seconds,ada_seconds",
    [
        ("after_both", 7200, 7200),
        ("between", 7200, 0),
        ("before_both", 0, 0),
    ],
)
async def test_each_return_measures_absence_from_its_own_departure(
    returning_scene, passage, nora_seconds, ada_seconds
):
    from talemate.history import insert_time_passage_after_message

    scene = returning_scene
    ada = Character(name="Ada")
    actor = Actor(ada, get_agent("conversation"))
    actor.scene = scene
    scene.character_data["Ada"] = ada
    scene.actors.append(actor)
    scene.active_characters.append("Ada")
    gather = add_line(scene, "Everyone gathers at the gate.", ["Nora", "Mara", "Ada"])
    await deactivate_character(scene, "Nora")
    nora_departure = scene.history[-1]
    await deactivate_character(scene, "Ada")
    anchor = {
        "after_both": scene.history[-1],
        "between": nora_departure,
        "before_both": gather,
    }[passage]
    insert_time_passage_after_message(scene, anchor.id, 2, "hours")
    await activate_character(scene, "Nora")
    add_line(scene, "Nora greets Mara.", ["Nora", "Mara"])
    add_line(scene, "Mara answers Nora.", ["Nora", "Mara"])
    await activate_character(scene, "Ada")
    assert absence_seconds(scene, latest_transition(scene, "Nora")) == nora_seconds
    assert absence_seconds(scene, latest_transition(scene, "Ada")) == ada_seconds
    text = "\n".join(
        scene.context_history(
            budget=8192,
            perspective="Ada",
            stored_views=scene.knowledge_eligibility == "perception",
        )
    )
    assert text.count("Ada has returned to the scene") == 1
    assert ("after 2 hours away." if ada_seconds else "after being away.") in text
    assert text.count("was away") == (
        1 if scene.knowledge_eligibility == "legacy" else 0
    )
