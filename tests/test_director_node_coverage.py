"""
agent.director.chat.batch_complete and the call outcome outputs of Unpack AI
Function Call.
"""

import pytest

import talemate.emit.async_signals as async_signals
from _node_test_helpers import run_node
from talemate.agents.director.action_core import utils
from talemate.agents.director.chat.mixin import DirectorChatBatchEmission
from talemate.game.engine.nodes.core import GraphState
from talemate.game.engine.nodes.focal import UnpackCall
from talemate.game.focal.schema import Call


@pytest.fixture
def batches():
    received = []

    async def handler(emission):
        received.append(emission)

    signal = async_signals.get("agent.director.chat.batch_complete")
    signal.connect(handler)
    yield received
    signal.disconnect(handler)


def run_batch(monkeypatch, calls):
    async def execute(**kwargs):
        await kwargs["on_batch_complete"](calls)

    monkeypatch.setattr(utils, "execute_actions", execute)


async def test_batch_with_a_rejection(scene, director, monkeypatch, batches):
    scene.nodegraph_state = GraphState()
    chat = director.chat_create()
    child = Call(name="set_title", arguments={"title": "x"}, called=True)
    run_batch(
        monkeypatch,
        [
            Call(name="write", arguments={"value": 1}, called=True, subcalls=[child]),
            Call(
                name="write",
                arguments={"value": 2},
                skipped_reason="reject_with_instructions",
                rejection_instructions="Use blue",
            ),
            Call(name="write", arguments={"value": 3}, skipped_reason="aborted"),
        ],
    )
    await director._chat_execute_actions(chat.id, [])

    [emission] = batches
    assert isinstance(emission, DirectorChatBatchEmission)
    assert emission.agent is director
    assert emission.chat_id == chat.id
    assert emission.applied == [
        {
            "function": "write",
            "arguments": {"value": 1},
            "applied": True,
            "subcalls": [
                {"function": "set_title", "arguments": {"title": "x"}, "applied": True}
            ],
        }
    ]
    assert [c["reason"] for c in emission.not_applied] == [
        "reject_with_instructions",
        "aborted",
    ]
    assert emission.rejections == [
        {
            "function": "write",
            "arguments": {"value": 2},
            "reason": "reject_with_instructions",
            "instructions": "Use blue",
        }
    ]
    assert (emission.applied_count, emission.not_applied_count) == (2, 2)


async def test_fully_applied_batch_is_sent_without_a_chat_note(
    scene, director, monkeypatch, batches
):
    scene.nodegraph_state = GraphState()
    chat = director.chat_create()
    before = len(director.chat_get(chat.id).messages)
    run_batch(monkeypatch, [Call(name="write", arguments={"value": 1}, called=True)])
    await director._chat_execute_actions(chat.id, [])

    [emission] = batches
    assert emission.not_applied == [] and emission.rejections == []
    assert len(director.chat_get(chat.id).messages) == before


async def test_discarded_chat_sends_nothing(scene, director, monkeypatch, batches):
    scene.nodegraph_state = GraphState()
    chat = director.chat_create()

    async def execute(**kwargs):
        director.chat_delete(chat.id)
        await kwargs["on_batch_complete"](
            [Call(name="write", arguments={}, skipped_reason="reject")]
        )

    monkeypatch.setattr(utils, "execute_actions", execute)
    await director._chat_execute_actions(chat.id, [])
    assert batches == []


async def test_unpack_call_outcomes():
    child = Call(name="set_title", called=True)
    call = Call(
        name="write",
        skipped_reason="reject_with_instructions",
        rejection_instructions="Use blue",
        subcalls=[child],
    )
    out = await run_node(UnpackCall(), inputs={"call": call})
    assert out["skipped_reason"] == "reject_with_instructions"
    assert out["rejection_instructions"] == "Use blue"
    assert out["subcalls"] == [child]
    assert out["called"] is False

    plain = await run_node(UnpackCall(), inputs={"call": Call(name="x", called=True)})
    assert plain["skipped_reason"] is None
    assert plain["rejection_instructions"] == ""
    assert plain["subcalls"] == []
