import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_perception_lifecycle

from test_revision_browsing import standard_revision
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.game.engine.nodes.scene import WaitForInput, GraphState, LoopBreak
from talemate.knowledge.step import knowledge_step
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
    monkeypatch.setattr(conversation, "finalize_message_avatar", AsyncMock())
    scene.name, scene.filename = "Submission", "submission.json"
    started, release = asyncio.Event(), asyncio.Event()
    order, visible, ready_at_dispatch, dispatched = [], [], [], []

    async def cleanup_archive(*args, **kwargs):
        order.append("refresh-start")
        started.set()
        await asyncio.wait_for(release.wait(), 5)
        order.append("refresh-end")
        return True

    async def new_message(event):
        order.append("dispatch")
        dispatched.append(event.message.id)
        ready_at_dispatch.append(previous.revision_matches_baseline)

    def emit(typ, message=None, **kwargs):
        if typ in ("character", "narrator"):
            visible.append((message.id, str(message)))
            order.append("visible")

    cleanup = AsyncMock(side_effect=cleanup_archive)
    monkeypatch.setattr(get_agent("memory"), "delete", cleanup)
    monkeypatch.setattr("talemate.tale_mate.emit", emit)
    scene.signals["game_loop_new_message"].connect(new_message)
    with ActiveScene(scene):
        yield SimpleNamespace(
            scene=scene,
            previous=previous,
            summarizer=summarizer,
            cleanup=cleanup,
            started=started,
            release=release,
            order=order,
            visible=visible,
            ready_at_dispatch=ready_at_dispatch,
            dispatched=dispatched,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [CharacterMessage, NarratorMessage])
async def test_push_runs_no_knowledge_work(submission, kind):
    t = submission
    message = kind(message="Alice: I will take the key.", source="player")
    await asyncio.wait_for(t.scene.push_history(message, emit_message=True), 5)
    assert t.order == ["visible", "dispatch"]
    assert t.visible == [(message.id, str(message))]
    assert t.scene.history == [t.previous, message]
    assert t.ready_at_dispatch == [False]
    t.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_step_refreshes_the_revision_before_the_generation(submission):
    t = submission
    message = CharacterMessage(message="Alice: I will take the key.", source="player")
    await t.scene.push_history(message, emit_message=True)
    t.release.set()
    await asyncio.wait_for(knowledge_step(t.scene), 5)
    assert t.order == ["visible", "dispatch", "refresh-start", "refresh-end"]
    assert t.previous.revision_matches_baseline
    assert t.dispatched == [message.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError, GenerationCancelled])
async def test_failed_step_keeps_the_line_and_the_next_step_retries(submission, error):
    t = submission
    message = CharacterMessage(message="Alice: I will take the key.", source="player")
    await t.scene.push_history(message, emit_message=True)
    t.cleanup.side_effect = error("refresh interrupted")
    with pytest.raises(error, match="refresh interrupted"):
        await knowledge_step(t.scene)
    assert t.scene.history == [t.previous, message]
    assert not t.previous.revision_matches_baseline
    t.cleanup.side_effect = None
    t.cleanup.return_value = True
    await knowledge_step(t.scene)
    assert t.previous.revision_matches_baseline
    assert t.dispatched == [message.id]
    assert t.visible == [(message.id, str(message))]


@pytest.mark.asyncio
async def test_cancelled_step_leaves_the_refresh_to_the_next_step(submission):
    t = submission
    step = asyncio.create_task(knowledge_step(t.scene))
    await asyncio.wait_for(t.started.wait(), 5)
    step.cancel()
    with pytest.raises(asyncio.CancelledError):
        await step
    assert not t.previous.revision_matches_baseline
    t.release.set()
    await asyncio.wait_for(knowledge_step(t.scene), 5)
    assert t.previous.revision_matches_baseline


@pytest.mark.asyncio
async def test_concurrent_steps_refresh_once(submission):
    t = submission
    first = asyncio.create_task(knowledge_step(t.scene))
    await asyncio.wait_for(t.started.wait(), 5)
    second = asyncio.create_task(knowledge_step(t.scene))
    await asyncio.sleep(0)
    assert not second.done()
    t.release.set()
    await asyncio.wait_for(asyncio.gather(first, second), 5)
    assert t.cleanup.await_count == 1
    assert t.previous.revision_matches_baseline


@pytest.mark.asyncio
async def test_history_listener_can_push_another_message(submission):
    t = submission
    player = CharacterMessage(message="Alice: I take the key.", source="player")
    response = NarratorMessage(message="The door opens.")

    async def append_response(event):
        if event.message is player:
            await t.scene.push_history(response, emit_message=True)

    t.scene.signals["game_loop_new_message"].connect(append_response)
    await asyncio.wait_for(t.scene.push_history(player, emit_message=True), 5)
    assert t.scene.history == [t.previous, player, response]
    assert t.visible == [(player.id, str(player)), (response.id, str(response))]
    assert t.dispatched == [player.id, response.id]


@pytest.mark.asyncio
async def test_line_of_a_cancelled_step_is_archived_with_the_next_push(
    submission, monkeypatch
):
    t = submission
    summarizer = get_agent("summarizer")
    summarizer.write_enabled("archive", True)
    summarizer.write_config("archive", "threshold", 1)
    archived_text = []

    async def summarize(text, *args, **kwargs):
        archived_text.append(text)
        return "Alice took the key."

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=summarize))
    monkeypatch.setattr(summarizer, "analyze_dialoge", AsyncMock(return_value=None))
    t.scene.signals["push_history.after"].connect(summarizer.on_push_history)
    t.cleanup.side_effect = GenerationCancelled("backlog question cancelled")
    player = CharacterMessage(message="Alice: I will take the key.", source="player")
    await t.scene.push_history(player, emit_message=True)
    with pytest.raises(GenerationCancelled):
        await knowledge_step(t.scene)
    t.cleanup.side_effect = None
    t.cleanup.return_value = True
    await t.scene.push_history(NarratorMessage(message="The door opens."))
    await t.scene.push_history(NarratorMessage(message="Bob nods."))
    player_index = t.scene.message_index(player.id)
    covered = [
        (entry["start"], entry["end"])
        for entry in t.scene.archived_history
        if entry.get("start") is not None
    ]
    assert any(start <= player_index <= end for start, end in covered)
    assert all(
        later[0] == earlier[1] + 1 for earlier, later in zip(covered, covered[1:])
    )
    assert any("I will take the key." in text for text in archived_text)


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
    await asyncio.wait_for(scene.push_history(message, emit_message=True), 5)
    assert visible == [message.id]
    task = asyncio.create_task(knowledge_step(scene))
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert scene.history[-1] is message
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
    await knowledge_step(scene)
    assert visible == [message.id]
    assert request.await_count == 1
    assert message.knowledge is not None


@pytest.mark.asyncio
async def test_line_is_shown_when_a_push_history_receiver_cancels(submission):
    t = submission

    async def cancel(event):
        raise GenerationCancelled("receiver cancelled")

    t.scene.signals["push_history"].connect(cancel)
    message = CharacterMessage(message="Alice: I take the key.", source="player")
    with pytest.raises(GenerationCancelled):
        await t.scene.push_history(message, emit_message=True)
    assert t.visible == [(message.id, str(message))]
    assert t.scene.history == [t.previous, message]


@pytest.mark.asyncio
async def test_pushed_line_marks_the_scene_unsaved(submission):
    t = submission
    t.scene.saved = True
    message = CharacterMessage(message="Alice: I take the key.", source="player")
    await t.scene.push_history(message, emit_message=True)
    assert t.scene.saved is False
