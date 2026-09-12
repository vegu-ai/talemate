import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_perception_lifecycle

from test_revision_browsing import standard_revision
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.game.engine.nodes.scene import WaitForInput, GraphState, LoopBreak
from talemate.knowledge.revision_refresh import catch_up_revisions
from talemate.load import _prepare_history
from talemate.scene_message import CharacterMessage, NarratorMessage
from talemate.tale_mate import Actor

perception_setup = test_perception_lifecycle.setup


@pytest.fixture
def submission(scene, monkeypatch, isolate_signals, tmp_path):
    summarizer, conversation, previous = standard_revision(scene)
    scene.actors = [
        Actor(character, None) for character in scene.character_data.values()
    ]
    isolate_signals("push_history", "push_history.after", "game_loop_new_message")
    monkeypatch.setattr(type(scene), "save_dir", property(lambda self: str(tmp_path)))
    monkeypatch.setattr(type(scene), "auto_save", property(lambda self: True))
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(conversation, "finalize_message_avatar", AsyncMock())
    scene.name, scene.filename = "Submission", "submission.json"
    started, release = asyncio.Event(), asyncio.Event()
    order, visible, ready_at_dispatch = [], [], []

    async def extract(*args, **kwargs):
        order.append("refresh-start")
        started.set()
        await asyncio.wait_for(release.wait(), 5)
        order.append("refresh-end")
        return "The key is silver.", []

    async def dispatch(event):
        order.append("dispatch")
        ready_at_dispatch.append(previous.revision_matches_baseline)

    def emit(typ, message, **kwargs):
        if typ in ("character", "narrator"):
            visible.append((message.id, str(message)))
            order.append("visible")

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr("talemate.tale_mate.emit", emit)
    scene.signals["push_history"].connect(dispatch)
    with ActiveScene(scene):
        yield SimpleNamespace(
            scene=scene,
            previous=previous,
            summarizer=summarizer,
            started=started,
            release=release,
            order=order,
            visible=visible,
            ready_at_dispatch=ready_at_dispatch,
            saved=tmp_path / "submission.json",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [CharacterMessage, NarratorMessage])
async def test_player_line_is_visible_and_saved_during_refresh(submission, kind):
    t = submission
    message = kind(message="Alice: I will take the key.", source="player")
    task = asyncio.create_task(t.scene.push_history(message, emit_message=True))
    try:
        await asyncio.wait_for(t.started.wait(), 5)
        assert t.visible == [(message.id, str(message))]
        assert t.scene.history == [t.previous, message]
        saved = json.loads(t.saved.read_text())["history"]
        assert [entry["id"] for entry in saved] == [t.previous.id, message.id]
        assert saved[-1]["message"] == message.message
        assert "dispatch" not in t.order
        assert not task.done()
    finally:
        t.release.set()
        await asyncio.wait_for(task, 5)
    assert t.order == ["visible", "refresh-start", "refresh-end", "dispatch"]
    assert t.ready_at_dispatch == [True]
    await catch_up_revisions(t.scene)
    assert t.visible == [(message.id, str(message))]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError, GenerationCancelled])
async def test_failed_refresh_retains_input_and_resumes_after_reload(submission, error):
    t = submission
    t.summarizer.summarize.side_effect = error("refresh interrupted")
    message = CharacterMessage(message="Alice: I will take the key.", source="player")
    with pytest.raises(error, match="refresh interrupted"):
        await t.scene.push_history(message, emit_message=True)
    assert t.visible == [(message.id, str(message))]
    saved = json.loads(t.saved.read_text())
    assert [entry["id"] for entry in saved["history"]] == [t.previous.id, message.id]
    t.scene.history = [_prepare_history(entry) for entry in saved["history"]]
    t.previous = t.scene.history[0]
    t.scene.signals["push_history"].receivers.clear()
    dispatched = []

    async def dispatch(event):
        assert t.scene.history[0].revision_matches_baseline
        dispatched.extend(entry.id for entry in event.messages)

    t.scene.signals["push_history"].connect(dispatch)
    t.summarizer.summarize.side_effect = None
    t.summarizer.summarize.return_value = ("The key is silver.", [])
    await catch_up_revisions(t.scene)
    await catch_up_revisions(t.scene)
    assert dispatched == [message.id]
    assert t.visible == [(message.id, str(message))]
    assert [entry["id"] for entry in json.loads(t.saved.read_text())["history"]] == [
        t.previous.id,
        message.id,
    ]


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_lose_or_redisplay_input(submission):
    t = submission
    message = CharacterMessage(message="Alice: I will take the key.", source="player")
    task = asyncio.create_task(t.scene.push_history(message, emit_message=True))
    await asyncio.wait_for(t.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert t.visible == [(message.id, str(message))]
    assert json.loads(t.saved.read_text())["history"][-1]["history_dispatch_pending"]
    t.release.set()
    await asyncio.wait_for(catch_up_revisions(t.scene), 5)
    assert t.ready_at_dispatch == [True]
    assert t.visible == [(message.id, str(message))]
    assert not message.history_dispatch_pending


@pytest.mark.asyncio
async def test_concurrent_catch_up_waits_for_one_dispatch(submission):
    t = submission
    message = CharacterMessage(message="Alice: I will take the key.", source="player")
    dispatch_started, dispatch_release = asyncio.Event(), asyncio.Event()

    async def hold_dispatch(event):
        dispatch_started.set()
        await asyncio.wait_for(dispatch_release.wait(), 5)

    t.scene.signals["push_history"].connect(hold_dispatch)
    task = asyncio.create_task(t.scene.push_history(message, emit_message=True))
    await asyncio.wait_for(t.started.wait(), 5)
    follower = asyncio.create_task(catch_up_revisions(t.scene))
    try:
        t.release.set()
        await asyncio.wait_for(dispatch_started.wait(), 5)
        await asyncio.sleep(0)
        assert not follower.done()
        assert t.ready_at_dispatch == [True]
    finally:
        dispatch_release.set()
        await asyncio.wait_for(asyncio.gather(task, follower), 5)
    assert t.visible == [(message.id, str(message))]
    assert t.order.count("dispatch") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("emit_message", [False, True])
async def test_generated_message_still_waits_before_acceptance(
    submission, emit_message
):
    t = submission
    message = CharacterMessage(message="Bob: I see the key.")
    task = asyncio.create_task(t.scene.push_history(message, emit_message=emit_message))
    try:
        await asyncio.wait_for(t.started.wait(), 5)
        assert t.visible == []
        assert t.scene.history == [t.previous]
    finally:
        t.release.set()
        await asyncio.wait_for(task, 5)
    assert t.ready_at_dispatch == [True]
    assert len(t.visible) == int(emit_message)
    assert t.order[:3] == ["refresh-start", "refresh-end", "dispatch"]


@pytest.mark.asyncio
async def test_player_emit_false_survives_retry_without_presentation(submission):
    t = submission
    message = CharacterMessage(message="Alice: Quietly take the key.", source="player")
    t.summarizer.summarize.side_effect = GenerationCancelled("cancelled")
    with pytest.raises(GenerationCancelled):
        await t.scene.push_history(message, emit_message=False)
    assert t.visible == []
    assert t.scene.history[-1] is message
    t.summarizer.summarize.side_effect = None
    t.summarizer.summarize.return_value = ("The key is silver.", [])
    await catch_up_revisions(t.scene)
    assert t.visible == []
    assert t.ready_at_dispatch == [True]


@pytest.mark.asyncio
async def test_history_listener_can_push_another_message(submission):
    t = submission
    t.release.set()
    player = CharacterMessage(message="Alice: I take the key.", source="player")
    response = NarratorMessage(message="The door opens.")

    async def append_response(event):
        if event.messages == [player]:
            await t.scene.push_history(response, emit_message=True)

    t.scene.signals["push_history"].connect(append_response)
    await asyncio.wait_for(t.scene.push_history(player, emit_message=True), 5)
    assert t.scene.history == [t.previous, player, response]
    assert t.visible == [(player.id, str(player)), (response.id, str(response))]


@pytest.mark.asyncio
async def test_two_accepted_lines_dispatch_in_history_order(submission):
    t = submission
    first = CharacterMessage(message="Alice: I take the key.", source="player")
    second = CharacterMessage(message="Alice: I open the door.", source="player")
    one = asyncio.create_task(t.scene.push_history(first, emit_message=True))
    await asyncio.wait_for(t.started.wait(), 5)
    two = asyncio.create_task(t.scene.push_history(second, emit_message=True))
    try:
        await asyncio.sleep(0)
        assert t.scene.history == [t.previous, first, second]
        assert t.visible == [(first.id, str(first)), (second.id, str(second))]
    finally:
        t.release.set()
        await asyncio.wait_for(asyncio.gather(one, two), 5)
    assert t.ready_at_dispatch == [True, True]
    assert not first.history_dispatch_pending
    assert not second.history_dispatch_pending


@pytest.mark.asyncio
async def test_delayed_learning_uses_accepted_presence_and_preceding_lines(
    submission, monkeypatch
):
    t = submission
    conversation = get_agent("conversation")
    conversation.write_enabled("character_knowledge", True)
    conversation.write_config("character_knowledge", "ledger", True)
    learn = AsyncMock(return_value={})
    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    t.scene.signals["game_loop_new_message"].connect(conversation.on_new_message)
    first = CharacterMessage(message="Alice: I take the key.", source="player")
    second = CharacterMessage(message="Alice: I open the door.", source="player")
    one = asyncio.create_task(t.scene.push_history(first, emit_message=True))
    await asyncio.wait_for(t.started.wait(), 5)
    t.scene.active_characters = ["Alice"]
    two = asyncio.create_task(t.scene.push_history(second, emit_message=True))
    t.release.set()
    await asyncio.wait_for(asyncio.gather(one, two), 5)
    first_calls = [
        call for call in learn.await_args_list if call.kwargs.get("message") is first
    ]
    assert len(first_calls) == 1
    assert first_calls[0].kwargs["present_override"] == ["Alice", "Bob"]
    assert first_calls[0].kwargs["recent_lines_override"] == [str(t.previous)]
    second_calls = [
        call for call in learn.await_args_list if call.kwargs.get("message") is second
    ]
    assert len(second_calls) == 1
    assert second_calls[0].kwargs["recent_lines_override"] == [
        str(t.previous),
        str(first),
    ]


@pytest.mark.asyncio
async def test_commands_wait_for_refresh_before_execution(submission, monkeypatch):
    t = submission
    node = WaitForInput()
    monkeypatch.setattr(
        type(node),
        "get_input_value",
        lambda self, name: {"player_character": None, "prefix": "", "state": None}[
            name
        ],
    )
    monkeypatch.setattr(
        "talemate.game.engine.nodes.scene.wait_for_input",
        AsyncMock(return_value={"message": "!test", "interaction": None}),
    )

    async def execute(text, *, state, **kwargs):
        state["_commands_executed"] = True

    command = AsyncMock(side_effect=execute)
    monkeypatch.setattr(t.scene.commands, "execute", command)
    task = asyncio.create_task(node.run(GraphState()))
    try:
        await asyncio.wait_for(t.started.wait(), 5)
        command.assert_not_awaited()
    finally:
        t.release.set()
        with pytest.raises(LoopBreak):
            await asyncio.wait_for(task, 5)
    command.assert_awaited_once()


@pytest.mark.asyncio
async def test_perception_player_line_is_visible_before_analysis(
    perception_setup, monkeypatch, isolate_signals
):
    scene, summarizer, request = perception_setup
    isolate_signals("push_history", "push_history.after", "game_loop_new_message")
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    visible = []
    monkeypatch.setattr(
        "talemate.tale_mate.emit",
        lambda typ, message, **kwargs: visible.append(message.id)
        if typ == "character"
        else None,
    )
    started, release = asyncio.Event(), asyncio.Event()
    response = request.return_value

    async def analyze(*args, **kwargs):
        started.set()
        await asyncio.wait_for(release.wait(), 5)
        return response

    request.side_effect = analyze
    message = CharacterMessage(message="Alice: Hello.", source="player")
    task = asyncio.create_task(scene.push_history(message, emit_message=True))
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert visible == [message.id]
        assert scene.history[-1] is message
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
    await catch_up_revisions(scene)
    assert visible == [message.id]
    assert request.await_count == 1
    assert message.knowledge is not None
