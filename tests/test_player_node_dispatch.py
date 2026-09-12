import asyncio
import json
from types import SimpleNamespace

import pytest

import test_player_submission
import talemate.game.engine.nodes.core as core
from talemate.emit.async_signals import AsyncSignal
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.revision_refresh import catch_up_revisions
from talemate.scene_message import CharacterMessage

submission = test_player_submission.submission


@pytest.fixture
def node_dispatch(submission, monkeypatch):
    t = submission
    now = [100.0]
    monkeypatch.setattr(core, "time", SimpleNamespace(time=lambda: now[0]))
    started, release = asyncio.Event(), asyncio.Event()
    attempts, successes = [], []
    fail_first = [True]

    class TransientAction(core.Node):
        def setup(self):
            self.add_input("state")

        async def run(self, state):
            attempts.append(state.data["event"])
            if fail_first[0] and len(attempts) == 1:
                started.set()
                await release.wait()
                raise RuntimeError("transient node failure")
            successes.append(state.data["event"])

    listener = core.Listen(id="recoverable-listener")
    entry, action = core.Entry(), TransientAction()
    listener.add_node(entry)
    listener.add_node(action)
    listener.connect(entry.get_output_socket("state"), action.get_input_socket("state"))
    t.scene.nodegraph_state = core.GraphState()
    return SimpleNamespace(
        submission=t,
        listener=listener,
        now=now,
        started=started,
        release=release,
        attempts=attempts,
        successes=successes,
        fail_first=fail_first,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_cooldown_retry_keeps_real_node_work_pending(node_dispatch, queued):
    n = node_dispatch
    t = n.submission
    t.release.set()
    await catch_up_revisions(t.scene)
    t.scene.signals["game_loop_new_message"].connect(n.listener.execute_from_event)
    message = CharacterMessage(message="Alice: Continue.", source="player")
    first = asyncio.create_task(t.scene.push_history(message, emit_message=True))
    await asyncio.wait_for(n.started.wait(), 5)
    retry = None
    if queued:
        retry = asyncio.create_task(catch_up_revisions(t.scene))
        await asyncio.sleep(0)
        assert not retry.done()
    n.release.set()
    with pytest.raises(RuntimeError, match="transient node failure"):
        await first
    n.now[0] = 100.2
    if retry is None:
        retry = asyncio.create_task(catch_up_revisions(t.scene))
    outcome = await asyncio.gather(retry, return_exceptions=True)
    assert message.history_dispatch_pending
    assert isinstance(outcome[0], GenerationCancelled)
    assert len(n.attempts) == 1
    assert n.successes == []
    saved = json.loads(t.saved.read_text())["history"][-1]
    assert saved["history_dispatch_pending"]
    assert not any(
        "recoverable-listener" in key for key in saved["history_dispatch_completed"]
    )
    n.now[0] = 103.0
    await catch_up_revisions(t.scene)
    await catch_up_revisions(t.scene)
    assert len(n.attempts) == 2
    assert len(n.successes) == 1
    assert not message.history_dispatch_pending
    assert t.visible == [(message.id, str(message))]


@pytest.mark.asyncio
async def test_ordinary_delivery_preserves_real_node_cooldown(node_dispatch):
    n = node_dispatch
    signal = AsyncSignal("ordinary")
    signal.connect(n.listener.execute_from_event)
    n.release.set()
    first = await signal.send(None)
    assert len(first) == 1
    assert isinstance(first[0][1], RuntimeError)
    n.now[0] = 100.2
    assert await signal.send(None) == []
    assert len(n.attempts) == 1
    assert n.successes == []
    assert n.listener._failed is None
    n.now[0] = 103.0
    assert await signal.send(None) == []
    assert len(n.attempts) == 2
    assert len(n.successes) == 1


@pytest.mark.asyncio
async def test_unavailable_graph_state_does_not_complete_node_dispatch(node_dispatch):
    n = node_dispatch
    t = n.submission
    t.release.set()
    await catch_up_revisions(t.scene)
    t.scene.nodegraph_state = None
    t.scene.signals["game_loop_new_message"].connect(n.listener.execute_from_event)
    message = CharacterMessage(message="Alice: Continue.", source="player")
    outcome = await asyncio.gather(
        t.scene.push_history(message), return_exceptions=True
    )
    assert message.history_dispatch_pending
    assert isinstance(outcome[0], GenerationCancelled)
    assert n.attempts == []
    t.scene.nodegraph_state = core.GraphState()
    n.fail_first[0] = False
    await catch_up_revisions(t.scene)
    assert len(n.successes) == 1
    assert not message.history_dispatch_pending
