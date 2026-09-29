import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import talemate.emit.async_signals as async_signals
import talemate.game.engine.nodes.load_definitions  # noqa: F401

from _node_test_helpers import run_node
from talemate.agents.director.action_core import utils
from talemate.agents.director.action_core.exceptions import ActionRejected
from talemate.agents.director.chat.context import DirectorChatContext
from talemate.agents.director.chat.nodes import DirectorChatActionConfirm
from talemate.agents.director.chat import nodes
from talemate.agents.director.chat.websocket_handler import (
    ConfirmActionPayload,
    DirectorChatWebsocketMixin,
)
from talemate.game.engine.nodes.core import GraphState
from talemate.game.focal import Focal, FocalContext
from talemate.game.focal.schema import Callback, State

ACTION = [{"name": "update_context", "instructions": "change"}]
CORRECTION = {"function": "write", "arguments": {}, "instructions": "Use blue"}


@pytest.fixture
def handler(scene):
    scene.nodegraph_state = GraphState()
    scene.active = True

    class Handler(DirectorChatWebsocketMixin):
        pass

    handler = Handler()
    handler.scene = scene
    handler.websocket_handler = SimpleNamespace(queue_put=Mock())
    return handler


@pytest.mark.parametrize("decision", ["confirm", "reject", "reject_with_instructions"])
async def test_confirmation_protocol(scene, director, handler, monkeypatch, decision):
    chat = director.chat_create()
    requests = []
    replies = []

    def emit(typ, *, data, **kwargs):
        if typ == "request_action_confirmation":
            requests.append(data)
            replies.append(
                asyncio.create_task(
                    handler.handle_confirm_action(
                        {**data, "decision": decision, "instructions": "Use blue"}
                    )
                )
            )

    monkeypatch.setattr(nodes, "emit", emit)
    node = DirectorChatActionConfirm()

    def bind(state):
        state.shared = scene.nodegraph_state.shared

    with DirectorChatContext(chat_id=chat.id):
        for _ in range(2):
            if decision == "confirm":
                result = await run_node(
                    node,
                    scene=scene,
                    inputs={"state": "pending write"},
                    state_setup=bind,
                )
                assert result["accepted"] == "pending write"
            else:
                with pytest.raises(ActionRejected) as exc:
                    await run_node(
                        node,
                        scene=scene,
                        inputs={"state": "pending write"},
                        state_setup=bind,
                    )
                assert exc.value.reason == (
                    "reject" if decision == "reject" else "reject_with_instructions"
                )
                if decision == "reject_with_instructions":
                    assert exc.value.instructions == "Use blue"
    await asyncio.gather(*replies)
    assert requests[0]["id"] != requests[1]["id"]
    assert not scene.nodegraph_state.shared


async def test_timeout_cleans_up_and_reports_reason(
    scene, director, handler, monkeypatch
):
    monkeypatch.setattr(
        type(director), "chat_action_confirm_timeout", property(lambda _: -1)
    )
    emitted = Mock()
    monkeypatch.setattr(nodes, "emit", emitted)
    with DirectorChatContext(chat_id="chat"):
        with pytest.raises(ActionRejected) as exc:
            await run_node(
                DirectorChatActionConfirm(), scene=scene, inputs={"state": "write"}
            )
    assert exc.value.reason == "timed_out"
    assert emitted.call_args.kwargs["data"]["decision"] == "timed_out"


async def test_stale_duplicate_and_wrong_chat_replies_do_not_change_pending(handler):
    state = handler.scene.nodegraph_state
    state.shared["_director_chat_action_confirm_new"] = {
        "chat_id": "correct",
        "decision": "waiting",
        "instructions": "",
    }
    await handler.handle_confirm_action(
        {"chat_id": "correct", "id": "old", "decision": "confirm"}
    )
    await handler.handle_confirm_action(
        {"chat_id": "wrong", "id": "new", "decision": "confirm"}
    )
    assert state.shared["_director_chat_action_confirm_new"]["decision"] == "waiting"
    await handler.handle_confirm_action(
        {"chat_id": "correct", "id": "new", "decision": "reject"}
    )
    await handler.handle_confirm_action(
        {"chat_id": "correct", "id": "new", "decision": "confirm"}
    )
    assert state.shared["_director_chat_action_confirm_new"]["decision"] == "reject"
    with pytest.raises(ValueError, match="Instructions are required"):
        ConfirmActionPayload(
            chat_id="correct",
            id="new",
            decision="reject_with_instructions",
            instructions="  ",
        )


@pytest.mark.parametrize(
    "reason", ["over_budget", "reject", "timed_out", "reject_with_instructions"]
)
async def test_chat_renders_one_note_with_actual_batch_outcomes(
    scene, director, monkeypatch, reason
):
    scene.nodegraph_state = GraphState()
    chat = director.chat_create()
    applied = []

    async def write(value):
        if value == 2 and reason != "over_budget":
            raise ActionRejected(
                "write",
                "second",
                reason=reason,
                instructions="Use blue" if reason == "reject_with_instructions" else "",
            )
        applied.append(value)

    async def execute(**kwargs):
        focal = Focal(
            director.client,
            [Callback(name="write", fn=write)],
            max_calls=1 if reason == "over_budget" else 5,
        )
        with FocalContext() as context:
            context.hooks_after_batch.append(kwargs["on_batch_complete"])
            await focal._execute(
                "\n".join(
                    "```json\n"
                    + json.dumps({"function": "write", "arguments": {"value": i}})
                    + "\n```"
                    for i in range(1, 6)
                ),
                State(),
            )

    monkeypatch.setattr(utils, "execute_actions", execute)
    if reason in ("reject", "timed_out"):
        with pytest.raises(ActionRejected) as exc:
            await director._chat_execute_actions(chat.id, [{"name": "test"}])
        assert exc.value.chat_reported
    else:
        corrections = await director._chat_execute_actions(chat.id, [{"name": "test"}])
        assert len(corrections) == (1 if reason == "reject_with_instructions" else 0)
    notes = [
        m.message
        for m in director.chat_get(chat.id).messages
        if m.message.startswith("Action batch results")
    ]
    assert len(notes) == 1
    assert "Applied:" in notes[0] and "Not applied:" in notes[0]
    assert reason in notes[0]
    assert all(f'"value": {i}' in notes[0] for i in range(1, 6))
    assert applied == ([1, 3, 4, 5] if reason == "reject_with_instructions" else [1])
    note = director.chat_get(chat.id).messages[-1]
    assert note.applied_count == len(applied)
    assert note.not_applied_count == 5 - len(applied)
    serialized = director._serialize_chat_message(note.model_dump())
    assert serialized.applied_count == note.applied_count
    assert serialized.not_applied_count == note.not_applied_count


async def test_user_corrections_get_one_followup_per_round_even_with_iteration_limit(
    scene, director, monkeypatch
):
    scene.active = True
    chat = director.chat_create()
    director.chat_update_title(chat.id, "Test")
    correction = {
        "function": "write",
        "arguments": {"value": 2},
        "instructions": "Use blue",
    }
    execute = AsyncMock(side_effect=[[correction], [correction], []])
    monkeypatch.setattr(director, "_chat_execute_actions", execute)
    monkeypatch.setattr(
        type(director), "chat_auto_iterations_limit", property(lambda _: 1)
    )
    monkeypatch.setattr(
        director, "_chat_compact_if_needed", AsyncMock(return_value=False)
    )
    calls = []

    async def build(**kwargs):
        return dict(kwargs["extra_vars"])

    async def request(**kwargs):
        calls.append(kwargs["prompt_vars"].copy())
        return (
            ("Working", [{"name": "update_context", "instructions": "correct"}], "")
            if len(calls) < 4
            else ("Done", [], "")
        )

    monkeypatch.setattr(utils, "build_prompt_vars", build)
    monkeypatch.setattr(utils, "request_and_parse", request)
    await director.chat_generate_next(chat.id)
    assert execute.await_count == 3
    assert len(calls) == 4
    assert calls[1]["rejected_calls"] == [correction]
    assert calls[2]["rejected_calls"] == [correction]
    assert calls[3]["rejected_calls"] == []


@pytest.mark.parametrize(
    "responses, rejections, expected",
    [
        pytest.param(
            [
                ("On it: rendering the harbour.", ACTION),
                ("On it: rendering\n the harbour.  ", []),
            ],
            [[]],
            ["On it: rendering the harbour."],
            id="closing_follow_up_repeats_batch_intro",
        ),
        pytest.param(
            [
                ("On it: rendering the harbour.", ACTION),
                ("The image is rendering.", []),
            ],
            [[]],
            ["On it: rendering the harbour.", "The image is rendering."],
            id="different_follow_up",
        ),
        pytest.param(
            [("Working.", ACTION), ("Next step.", ACTION), ("Working.", [])],
            [[], []],
            ["Working.", "Next step.", "Working."],
            id="repeat_of_an_earlier_round",
        ),
        pytest.param(
            [("Working.", ACTION), ("Working.", ACTION), ("Done.", [])],
            [[], []],
            ["Working.", "Working.", "Done."],
            id="repeat_that_opens_its_own_batch",
        ),
        pytest.param(
            [("Working.", ACTION), (None, ACTION), ("Working.", [])],
            [[], []],
            ["Working.", "Working."],
            id="action_only_second_batch",
        ),
        pytest.param(
            [("Working.", ACTION), ("Applying it.", ACTION), ("Applying it.", [])],
            [[CORRECTION], [CORRECTION]],
            ["Working.", "Applying it.", "Applying it."],
            id="reply_to_second_correction",
        ),
    ],
)
async def test_follow_up_is_skipped_only_when_it_restates_its_batch_intro(
    scene, director, monkeypatch, responses, rejections, expected
):
    scene.active = True
    chat = director.chat_create()
    director.chat_update_title(chat.id, "Test")
    history_before = len(chat.messages)
    monkeypatch.setattr(
        director, "_chat_execute_actions", AsyncMock(side_effect=rejections)
    )
    monkeypatch.setattr(
        director, "_chat_compact_if_needed", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        type(director), "chat_auto_iterations_limit", property(lambda _: 5)
    )
    replies = iter(responses)

    async def build(**kwargs):
        return {}

    async def request(**kwargs):
        text, actions = next(replies)
        return text, actions, ""

    monkeypatch.setattr(utils, "build_prompt_vars", build)
    monkeypatch.setattr(utils, "request_and_parse", request)
    on_update = AsyncMock()
    await director.chat_generate_next(chat.id, on_update=on_update)

    sent = [m.message for call in on_update.await_args_list for m in call.args[1]]
    stored = [m.message for m in director.chat_get(chat.id).messages[history_before:]]
    assert sent == expected
    assert stored == expected
    assert next(replies, None) is None


async def test_real_chat_action_graph_preserves_applied_changes_and_reports_rejection(
    scene, director, handler, monkeypatch
):
    from conftest import client_responses
    from collections import deque
    from talemate.context import ActiveScene
    from talemate.game.engine.nodes.registry import import_talemate_node_definitions

    import_talemate_node_definitions()
    await utils.init_action_nodes(scene, scene.nodegraph_state)
    chat = director.chat_create()
    pending_replies = []
    confirmations = []

    def emit(typ, *, data, **kwargs):
        if typ != "request_action_confirmation":
            return
        confirmations.append(data)
        decision = "confirm" if len(confirmations) == 1 else "reject_with_instructions"
        pending_replies.append(
            asyncio.create_task(
                handler.handle_confirm_action(
                    {**data, "decision": decision, "instructions": "Use blue"}
                )
            )
        )

    monkeypatch.setattr(nodes, "emit", emit)
    changes = []

    async def changed(event):
        changes.append((event.path, event.value, event.previous_value))

    async_signals.get("game_state.changed").connect(changed)
    response = "\n".join(
        "```json\n"
        + json.dumps(
            {"function": "update_gamestate", "arguments": {"instructions": text}}
        )
        + "\n```"
        for text in ("Set color red", "Set color green")
    )
    responses = deque()
    token = client_responses.set(responses)
    with ActiveScene(scene), DirectorChatContext(chat_id=chat.id):
        responses.extend(
            [
                response,
                '```json\n{"color": "red"}\n```',
                '```json\n{"color": "green"}\n```',
            ]
        )
        corrections = await director._chat_execute_actions(
            chat.id,
            [{"name": "update_gamestate", "instructions": "Set red then green"}],
        )
    client_responses.reset(token)
    await asyncio.gather(*pending_replies)
    for _ in range(5):
        await asyncio.sleep(0)
    async_signals.get("game_state.changed").disconnect(changed)
    assert len(confirmations) == 2
    assert scene.game_state.variables["color"] == "red"
    # the module writes through the game state write path
    assert changes == [("color", "red", None)]
    assert corrections == [
        {
            "function": "update_gamestate",
            "arguments": {"instructions": "Set color green"},
            "reason": "reject_with_instructions",
            "instructions": "Use blue",
        }
    ]
    notes = [
        m
        for m in director.chat_get(chat.id).messages
        if m.type == "batch_result" and m.message.startswith("Action batch results")
    ]
    assert len(notes) == 1
    assert "Set color red" in notes[0].message and "Set color green" in notes[0].message


async def test_confirmation_finished_uses_registered_emitter(scene, director):
    from talemate.emit.signals import handlers

    scene.active = True
    emitted = []
    pending = {}

    def confirm(emission):
        pending["state"].shared["_director_chat_action_confirm_" + emission.data["id"]][
            "decision"
        ] = "confirm"

    def finished(emission):
        emitted.append(emission)

    handlers["request_action_confirmation"].connect(confirm)
    handlers["action_confirmation_finished"].connect(finished)
    try:
        with DirectorChatContext(chat_id="test"):
            result = await run_node(
                DirectorChatActionConfirm(),
                scene=scene,
                inputs={"state": "write"},
                state_setup=lambda state: pending.update(state=state),
            )
        assert result["accepted"] == "write"
        assert len(emitted) == 1
        assert emitted[0].websocket_passthrough
        assert emitted[0].data["decision"] == "confirm"
    finally:
        handlers["request_action_confirmation"].disconnect(confirm)
        handlers["action_confirmation_finished"].disconnect(finished)
