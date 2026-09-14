import asyncio
import json
from collections import deque
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import talemate.game.engine.nodes.load_definitions  # noqa: F401

from _node_test_helpers import run_node
from conftest import client_responses
from talemate.agents.director.action_core import utils
from talemate.agents.context import ActiveAgent
from talemate.agents.director.action_core.exceptions import ActionFailed, ActionRejected
from talemate.agents.director.chat import nodes
from talemate.agents.director.chat.context import DirectorChatContext
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.game.engine.nodes.core import (
    Entry,
    Graph,
    GraphContext,
    GraphState,
    Listen,
)
from talemate.game.engine.nodes.focal import Callback as CallbackNode
from talemate.game.engine.nodes.focal import Focal as FocalNode
from talemate.agents.director.chat.websocket_handler import DirectorChatWebsocketMixin
from talemate.game.engine.nodes.registry import (
    get_node,
    import_talemate_node_definitions,
)
from talemate.game.engine.nodes.run import Function, FunctionWrapper
from talemate.game.focal import Focal, FocalContext
from talemate.game.focal.schema import Call, Callback, State
from talemate.prompts.base import Prompt


def response(*calls):
    return "\n".join("```json\n" + json.dumps(call) + "\n```" for call in calls)


def call(name, **arguments):
    return {"function": name, "arguments": arguments}


async def test_internal_focal_does_not_replace_director_call(director):
    inner = Focal(director.client, [Callback(name="assign_voice", fn=AsyncMock())])

    async def create_character():
        await inner._execute(response(call("assign_voice")), State())

    outer = Focal(
        director.client,
        [Callback(name="create_character", fn=create_character)],
        max_calls=1,
    )
    completed = AsyncMock()
    with FocalContext() as context:
        context.hooks_after_batch.append(completed)
        await outer._execute(
            response(call("create_character"), call("create_character")), State()
        )
    assert outer.state.batch[0].called and not outer.state.batch[0].subcalls
    assert inner.state.calls[0].called
    completed.assert_awaited_once_with(outer.state.batch)


@pytest.mark.parametrize("reason", ["reject", "reject_with_instructions"])
async def test_concurrent_rejections_keep_parallel_results_and_stop_later_work(
    director, reason
):
    entered = set()
    both_entered = asyncio.Event()

    async def query(which):
        entered.add(which)
        if len(entered) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), 1)
        if which == 1:
            raise ActionRejected(
                "query",
                "first",
                reason=reason,
                instructions="Try another source"
                if reason == "reject_with_instructions"
                else "",
            )
        return "second result"

    client = Mock(supports_concurrent_inference=True)
    later = AsyncMock()
    focal = Focal(
        client,
        [
            Callback(name="query", fn=query, concurrent=True),
            Callback(name="later", fn=later),
        ],
    )
    with DirectorChatContext(chat_id="test"), FocalContext():
        if reason == "reject":
            with pytest.raises(ActionRejected):
                await focal._execute(
                    response(
                        call("query", which=1), call("query", which=2), call("later")
                    ),
                    State(),
                )
            later.assert_not_awaited()
            assert focal.state.batch[2].skipped_reason == "aborted"
        else:
            await focal._execute(
                response(call("query", which=1), call("query", which=2), call("later")),
                State(),
            )
            later.assert_awaited_once()
    assert entered == {1, 2}
    assert focal.state.batch[0].skipped_reason == reason
    assert focal.state.batch[1].result == "second result"
    assert all(c is not focal.state.batch[0] for c in focal.state.calls)


@pytest.mark.parametrize(
    "error", [ActionFailed("failed"), GenerationCancelled("cancelled")]
)
async def test_escaping_error_records_failure_and_aborts_even_when_note_hook_fails(
    director, error
):
    focal = Focal(
        director.client, [Callback(name="write", fn=AsyncMock(side_effect=error))]
    )
    with FocalContext() as context:
        context.hooks_after_batch.append(AsyncMock(side_effect=TypeError("bad note")))
        with pytest.raises(type(error)):
            await focal._execute(
                response(call("write", index=1), call("write", index=2)), State()
            )
    assert focal.state.batch[0].error == str(error)
    assert focal.state.batch[0].skipped_reason == (
        "interrupted" if isinstance(error, GenerationCancelled) else "failed"
    )
    assert focal.state.batch[1].skipped_reason == "aborted"


async def test_cancellation_records_queries_waiting_for_concurrency_slot(director):
    entered = asyncio.Event()

    async def query(which):
        entered.set()
        await asyncio.Event().wait()

    focal = Focal(
        Mock(supports_concurrent_inference=True),
        [Callback(name="query", fn=query, concurrent=True)],
        max_concurrent=1,
    )
    with FocalContext():
        task = asyncio.create_task(
            focal._execute(
                response(call("query", which=1), call("query", which=2)), State()
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(focal.state.batch) == 2
    assert all(c.skipped_reason == "interrupted" for c in focal.state.batch)
    assert not focal.state.calls


@pytest.mark.parametrize("cancel", ["interrupt", "shutdown", "clear", "delete"])
async def test_confirmation_wait_cancels_for_scene_and_chat_lifecycle(
    scene, director, monkeypatch, cancel
):
    scene.active = True
    scene.nodegraph_state = GraphState()
    chat = director.chat_create()

    async def during_wait(_):
        if cancel == "interrupt":
            scene.interrupt_signal.set_result(None)
        elif cancel == "shutdown":
            scene.active = False
        elif cancel == "clear":
            director.chat_clear(chat.id)
        else:
            director.chat_delete(chat.id)

    monkeypatch.setattr(nodes.asyncio, "sleep", during_wait)
    emitted = Mock()
    monkeypatch.setattr(nodes, "emit", emitted)
    with DirectorChatContext(chat_id=chat.id), pytest.raises(GenerationCancelled):
        await run_node(
            nodes.DirectorChatActionConfirm(),
            scene=scene,
            inputs={"state": "write"},
            state_setup=lambda state: setattr(
                state, "shared", scene.nodegraph_state.shared
            ),
        )
    assert not any(
        key.startswith("_director_chat_action_confirm_")
        for key in scene.nodegraph_state.shared
    )
    assert emitted.call_args.kwargs["data"]["decision"] == "interrupted"


async def test_confirmation_received_during_final_sleep_wins_over_timeout(
    scene, director, monkeypatch
):
    scene.active = True
    state_holder = {}
    clock = [0.0]
    monkeypatch.setattr(nodes.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        type(director), "chat_action_confirm_timeout", property(lambda _: 1)
    )
    monkeypatch.setattr(nodes, "emit", Mock())

    async def final_sleep(_):
        pending = next(iter(state_holder["state"].shared.values()))
        pending["decision"] = "confirm"
        clock[0] = 2.0

    monkeypatch.setattr(nodes.asyncio, "sleep", final_sleep)
    with DirectorChatContext(chat_id="test"):
        result = await run_node(
            nodes.DirectorChatActionConfirm(),
            scene=scene,
            inputs={"state": "write"},
            state_setup=lambda state: state_holder.update(state=state),
        )
    assert result["accepted"] == "write"


async def test_report_budget_exemption_comes_from_metadata_not_name(scene):
    import_talemate_node_definitions()
    with ActiveScene(scene), GraphContext() as state:
        report = get_node("agents/director/chat/agentReportIssue")()
        wrapper = FunctionWrapper(report, report, state)
        assert not (await wrapper.ai_callback("renamed_report")).counts_toward_budget
        result = await run_node(
            CallbackNode(),
            scene=scene,
            inputs={"fn": wrapper, "name": "report_problem"},
        )
        assert not result["callback"].counts_toward_budget
        ordinary = Function()
        ordinary_wrapper = FunctionWrapper(ordinary, ordinary, state)
        result = await run_node(
            CallbackNode(),
            scene=scene,
            inputs={"fn": ordinary_wrapper, "name": "report_issue"},
        )
        assert result["callback"].counts_toward_budget


async def test_report_is_visible_outside_chat(scene, monkeypatch):
    emitted = Mock()
    monkeypatch.setattr(nodes, "emit", emitted)
    result = await run_node(
        nodes.ReportIssueOutput(),
        scene=scene,
        inputs={"message": "Avatar cannot be generated"},
    )
    assert result["message"] == "Avatar cannot be generated"
    assert emitted.call_args.args == ("status",)
    assert emitted.call_args.kwargs["message"] == result["message"]


async def test_execute_actions_offers_report_at_budget_boundary_and_only_posts_own_results(
    scene, director, monkeypatch
):
    scene.active = True
    scene.nodegraph_state = GraphState()
    import_talemate_node_definitions()
    await utils.init_action_nodes(scene, scene.nodegraph_state)
    chat = director.chat_create()

    async def request(self, *args, **kwargs):
        assert "report_issue" in self.callbacks
        assert not self.callbacks["report_issue"].counts_toward_budget
        self.callbacks["update_gamestate"].fn = AsyncMock(return_value="applied")
        return await self._execute(
            response(
                *(call("update_gamestate", instructions=str(i)) for i in range(4)),
                call("report_issue", task="remaining work", issue="budget reached"),
            ),
            State(),
        )

    monkeypatch.setattr(Focal, "request", request)
    with ActiveScene(scene), DirectorChatContext(chat_id=chat.id):
        await director._chat_execute_actions(chat.id, [{"name": "update_gamestate"}])
    messages = director.chat_get(chat.id).messages
    reports = [
        m for m in messages if m.type == "action_result" and m.name == "report_issue"
    ]
    assert len(reports) == 1 and "budget reached" in reports[0].result
    assert any(
        m.type == "batch_result" and "over_budget" in m.message for m in messages
    )


async def test_inner_report_is_in_enclosing_result_only(scene, director):
    scene.active = True
    scene.nodegraph_state = GraphState()
    import_talemate_node_definitions()
    await utils.init_action_nodes(scene, scene.nodegraph_state)
    chat = director.chat_create()
    token = client_responses.set(
        deque(
            [
                response(call("update_context", instructions="inspect task")),
                response(
                    call(
                        "report_issue",
                        task="create character",
                        issue="Missing description",
                    )
                ),
            ]
        )
    )
    try:
        with ActiveScene(scene), DirectorChatContext(chat_id=chat.id):
            await director._chat_execute_actions(chat.id, [{"name": "update_context"}])
    finally:
        client_responses.reset(token)
    results = [
        m for m in director.chat_get(chat.id).messages if m.type == "action_result"
    ]
    assert [m.name for m in results] == ["update_context"]
    assert "Missing description" in results[0].result


async def test_update_context_world_changes_rejection_is_not_a_success(
    scene, director, monkeypatch
):
    scene.active = True
    scene.nodegraph_state = GraphState()
    import_talemate_node_definitions()
    await utils.init_action_nodes(scene, scene.nodegraph_state)
    chat = director.chat_create()

    async def reject(self, state):
        raise ActionRejected(
            "world_changes",
            "proposed world edit",
            reason="reject_with_instructions",
            instructions="Keep the old harbor",
        )

    monkeypatch.setattr(
        get_node("agents/director/chat/instructWorldUpdates"), "run", reject
    )
    token = client_responses.set(
        deque(
            [
                response(call("update_context", instructions="change harbor")),
                response(call("world_changes", instructions="change harbor")),
            ]
        )
    )
    try:
        with ActiveScene(scene), DirectorChatContext(chat_id=chat.id):
            corrections = await director._chat_execute_actions(
                chat.id, [{"name": "update_context"}]
            )
    finally:
        client_responses.reset(token)
    results = [
        m.result
        for m in director.chat_get(chat.id).messages
        if m.type == "action_result"
    ]
    assert results and all("world_changes` SUCCESS" not in result for result in results)
    assert corrections[0]["function"] == "world_changes"
    note = director.chat_get(chat.id).messages[-1]
    assert note.type == "batch_result"
    assert "update_context" in note.message and "world_changes" in note.message
    assert "Keep the old harbor" in note.message
    assert note.applied_count == 1  # The enclosing update_context call completed.
    assert note.not_applied_count == 1  # Its nested world_changes call was skipped.


async def test_batch_note_serializes_yaml_dates_and_template_renders_corrections(
    scene, director, monkeypatch
):
    scene.nodegraph_state = GraphState()
    chat = director.chat_create()

    async def execute(**kwargs):
        await kwargs["on_batch_complete"](
            [
                Call(
                    name="write",
                    arguments={"day": date(2026, 9, 14)},
                    skipped_reason="reject_with_instructions",
                    rejection_instructions="Use tomorrow",
                )
            ]
        )

    monkeypatch.setattr(utils, "execute_actions", execute)
    corrections = await director._chat_execute_actions(chat.id, [])
    note = director.chat_get(chat.id).messages[-1]
    assert note.type == "batch_result" and "2026-09-14" in note.message
    assert corrections[0]["arguments"]["day"] == "2026-09-14"
    with ActiveScene(scene), ActiveAgent(director, director.chat_generate_next):
        variables = await utils.build_prompt_vars(
            scene=scene,
            client=director.client,
            history_for_prompt=[note],
            scene_snapshot="",
            budgets=director._create_chat_budgets(),
            enable_analysis=False,
            scene_context_ratio=0.5,
            history_trim_fn=lambda history, budget: history,
            extra_vars={
                "rejected_calls": corrections,
                "director_history_trim": lambda history, budget: history,
            },
            mode="chat",
        )
        rendered = Prompt.get("director.chat", variables).render()
    assert "User corrections for rejected calls" in rendered
    assert "Use tomorrow" in rendered and "They were NOT applied" in rendered
    assert "[action batch outcomes]" in rendered
    assert "you must evaluate the action result" in rendered


@pytest.mark.parametrize("route", ["instruct", "event", "internal"])
async def test_graph_focal_inherits_only_within_callback_scope(
    scene, director, monkeypatch, route
):
    parent = Call(name="create_image")
    handlers = []

    async def request(self, **kwargs):
        handlers.append(self)
        await self._execute(
            response(call("choose", item=1), call("choose", item=2)), State()
        )
        return "response"

    monkeypatch.setattr(Focal, "request", request)
    if route == "internal":
        graph = json.loads(
            Path(
                "src/talemate/agents/visual/modules/determine-visual-references.json"
            ).read_text()
        )
        definition = next(
            node
            for node in graph["nodes"].values()
            if node["registry"] == "focal/Focal"
        )
        node = FocalNode(**definition)
    else:
        node = FocalNode()
    node.set_property("state", "ready")
    node.set_property("agent", director)
    node.set_property("template", "test")
    node.set_property("callbacks", [Callback(name="choose", fn=AsyncMock())])
    module = Listen() if route == "event" else Graph()
    entry = Entry()
    module.add_node(entry)
    module.add_node(node)
    module.connect(entry.outputs[0], node.inputs[0])
    with ActiveScene(scene), GraphContext() as outer, FocalContext() as context:
        outer.data["__focal_call"] = parent
        context.batch_owner = Focal(director.client, [])
        if route == "event":
            await module.execute_from_event(object())
        else:
            await module.execute(outer)
    assert len(handlers) == 1
    assert handlers[0].state.batch[1].skipped_reason == "over_budget"
    if route == "instruct":
        assert parent.subcalls == handlers[0].state.batch
    else:
        assert not parent.subcalls


@pytest.mark.parametrize("operation", ["clear", "delete", "interrupt"])
async def test_cancelled_batch_does_not_restore_discarded_chat(
    scene, director, monkeypatch, operation
):
    scene.active = True
    scene.nodegraph_state = GraphState()
    chat = director.chat_create()
    logged = Mock()
    monkeypatch.setattr("talemate.game.focal.log.exception", logged)

    async def cancel(_):
        if operation == "clear":
            director.chat_clear(chat.id)
        elif operation == "delete":
            director.chat_delete(chat.id)
        else:
            scene.interrupt()

    monkeypatch.setattr(nodes.asyncio, "sleep", cancel)

    async def write():
        await run_node(
            nodes.DirectorChatActionConfirm(),
            scene=scene,
            inputs={"state": "write"},
            state_setup=lambda state: setattr(
                state, "shared", scene.nodegraph_state.shared
            ),
        )

    async def execute(**kwargs):
        with FocalContext() as context:
            context.hooks_after_batch.append(kwargs["on_batch_complete"])
            focal = Focal(director.client, [Callback(name="write", fn=write)])
            await focal._execute(response(call("write")), State())

    monkeypatch.setattr(utils, "execute_actions", execute)
    with DirectorChatContext(chat_id=chat.id), pytest.raises(GenerationCancelled):
        await director._chat_execute_actions(chat.id, [])
    current = director.chat_get(chat.id)
    if operation == "delete":
        assert current is None
    elif operation == "clear":
        assert len(current.messages) == 1
        assert current.messages[0].type == "text"
        assert current.messages[0].message == director._chat_initial_message()
    else:
        assert sum(m.type == "batch_result" for m in current.messages) == 1
        assert "interrupted" in current.messages[-1].message
    logged.assert_not_called()


@pytest.mark.parametrize("cancelled", [True, False])
async def test_chat_task_done_handles_cancel_latch_and_preserves_real_failures(
    scene, monkeypatch, cancelled
):
    handler = DirectorChatWebsocketMixin()
    handler.scene = scene
    done = asyncio.Event()
    frames = []

    def queue(frame):
        frames.append(frame)
        done.set()

    handler.websocket_handler = SimpleNamespace(queue_put=queue)
    logged = Mock()
    monkeypatch.setattr(
        "talemate.agents.director.chat.websocket_handler.log.error", logged
    )

    async def fail():
        if cancelled:
            scene.interrupt()
            raise GenerationCancelled("interrupted", by_user=True)
        raise RuntimeError("real failure")

    task = asyncio.create_task(fail())
    handler._attach_task_done_callback(task, "test")
    with pytest.raises(GenerationCancelled if cancelled else RuntimeError):
        await task
    await asyncio.wait_for(done.wait(), 1)
    assert frames == [{"type": "director", "action": "chat_done", "chat_id": "test"}]
    if cancelled:
        assert not scene.cancel_requested
        logged.assert_not_called()
    else:
        logged.assert_called_once()
        assert isinstance(logged.call_args.kwargs["error"], RuntimeError)
