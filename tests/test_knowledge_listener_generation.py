"""
A listener that asks the narrator, or a handler of a knowledge event that
starts an agent action, completes: nothing in knowledge waits for listeners,
and the knowledge step runs no listener while it holds its lock.
"""

import asyncio
import json

import pytest
from structlog.testing import capture_logs

import talemate.emit.async_signals as async_signals
from talemate.instance import get_agent
from talemate.knowledge.revision_refresh import revision_requires_refresh
from talemate.knowledge.step import knowledge_step, repair_knowledge
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage

import test_perception_audiences
from test_perception_events import edit_through_the_ui

audience_scene = test_perception_audiences.audience_scene


def pending(scene):
    return [
        message.id
        for message in scene.history
        if message.revision_state is not None
        and revision_requires_refresh(scene, message)
    ]


@pytest.fixture
async def flow(audience_scene, monkeypatch, isolate_signals):
    scene, summarizer, request = audience_scene
    perceive = request.side_effect
    narrations = []

    async def answer(uid, *args, **kwargs):
        if uid == "summarizer.perceptions":
            return await perceive(uid, *args, **kwargs)
        # the generation runs with the edit still flagged: no automatic repair
        narrations.append(pending(scene) == [earlier.id])
        return "The rain stops.", {
            "response": "The rain stops.",
            "analysis": "The rain stops.",
            "guidance": "Keep it calm.",
        }

    request.side_effect = answer
    isolate_signals("game_loop_new_message")
    earlier = NarratorMessage(message="The bell rings.")
    await scene.push_history(earlier)
    await knowledge_step(scene)
    await edit_through_the_ui(scene, earlier, "The bell stops.")
    assert pending(scene) == [earlier.id]
    narrator = get_agent("narrator")
    monkeypatch.setattr(
        type(narrator.client), "supports_concurrent_inference", True, raising=False
    )

    def on_player_line(handler):
        async def listener(event):
            if event.message.source == "player":
                await handler()

        scene.signals["game_loop_new_message"].connect(listener)

    async def send_player_line():
        message = CharacterMessage(message="Bob: Is it over?", source="player")
        with capture_logs() as logs:
            await asyncio.wait_for(scene.push_history(message), timeout=10)
        assert not [log for log in logs if log["event"] == "Error in signal receiver"]
        return message

    yield scene, narrator, narrations, on_player_line, send_player_line


def query_prompt():
    return Prompt.get("narrator.narrate-query", vars={})


@pytest.mark.asyncio
async def test_query_scene_from_a_player_line_listener(flow):
    scene, narrator, narrations, on_player_line, send_player_line = flow
    answers = []

    async def query():
        answers.append(query_prompt().query_scene("Is the bell quiet?"))

    on_player_line(query)
    await send_player_line()
    assert answers == ["Question: Is the bell quiet? Answer: The rain stops."]
    assert narrations == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 3])
async def test_concurrent_batch_query_scene_from_a_player_line_listener(flow, count):
    scene, narrator, narrations, on_player_line, send_player_line = flow
    answers = []

    async def query():
        answers.append(
            query_prompt().batch_query_scene(
                [
                    {"id": str(index), "query": "Is the bell quiet?"}
                    for index in range(count)
                ]
            )
        )

    on_player_line(query)
    await send_player_line()
    [result] = answers
    assert sorted(result) == [str(index) for index in range(count)]
    assert narrations == [True] * count


@pytest.mark.asyncio
async def test_scripting_api_narrate_query_from_a_player_line_listener(flow):
    from talemate.game.engine.api.agents.narrator import create as create_api

    scene, narrator, narrations, on_player_line, send_player_line = flow
    api = create_api(scene)
    answers = []

    async def query():
        answers.append(api.narrate_query("Is the bell quiet?"))

    on_player_line(query)
    await send_player_line()
    assert answers == ["The rain stops."]
    assert narrations == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_wait", [0, 5])
async def test_nested_query_in_a_task_of_its_listener(flow, parent_wait):
    scene, narrator, narrations, on_player_line, send_player_line = flow
    started, results = [], []

    async def query():
        task = asyncio.create_task(narrator.narrate_query("Is the bell quiet?"))
        started.append(task)
        if parent_wait:
            results.append(
                await asyncio.wait_for(asyncio.shield(task), timeout=parent_wait)
            )
        else:
            # the nested call outlives its parent's wait
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0)

    on_player_line(query)
    await send_player_line()
    [task] = started
    assert await asyncio.wait_for(task, timeout=10) == "The rain stops."
    assert results == (["The rain stops."] if parent_wait else [])
    # a later generation still catches up on a revision made after the nesting
    earlier = scene.history[0]
    await edit_through_the_ui(scene, earlier, "The bell rings again.")
    assert pending(scene) == [earlier.id]
    later = await asyncio.wait_for(narrator.narrate_query("And now?"), timeout=10)
    assert later == "The rain stops."
    assert narrations == [True, True]


@pytest.mark.asyncio
async def test_perception_listener_of_a_step_can_query(flow):
    scene, narrator, narrations, on_player_line, send_player_line = flow
    answers = []

    async def after(emission):
        answers.append(
            await asyncio.wait_for(narrator.narrate_query("Quiet?"), timeout=10)
        )

    async_signals.get("agent.summarization.perceptions.after").connect(after)
    try:
        await send_player_line()
        # Repair analyzes the edited passage and the new line
        await asyncio.wait_for(repair_knowledge(scene), timeout=10)
    finally:
        async_signals.get("agent.summarization.perceptions.after").disconnect(after)
    assert answers == ["The rain stops.", "The rain stops."]
    assert pending(scene) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["scene_analysis", "director_action"])
async def test_perception_listener_can_start_a_director_action(
    flow, monkeypatch, action
):
    from unittest.mock import AsyncMock, Mock

    from talemate.agents.context import ActiveAgent
    from talemate.agents.director.action_core import utils as action_utils
    from talemate.agents.director.chat.nodes import DirectorChatAction
    from talemate.game.engine.nodes.core import GraphState

    scene, narrator, narrations, on_player_line, send_player_line = flow
    summarizer = get_agent("summarizer")
    summarizer.actions["analyze_scene"].enabled = True
    director = get_agent("director")
    bob = scene.get_character("Bob")
    node = DirectorChatAction()
    monkeypatch.setattr(action_utils, "get_node", lambda registry: lambda: node)
    wrapper = AsyncMock(return_value="executed")
    wrapper.get_argument_nodes = AsyncMock(return_value=[])
    monkeypatch.setattr(action_utils, "FunctionWrapper", lambda *args: wrapper)
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared["_director_chat_actions"] = {
        "direct_actor": "test/action"
    }
    answer = Prompt.request.side_effect

    async def chosen_action(uid, *args, **kwargs):
        if uid == "director.chat-execute-actions":
            call = {
                "function": "direct_actor",
                "arguments": {"character": "Bob", "direction": "Stay calm."},
            }
            return "```json\n" + json.dumps(call) + "\n```", {}
        return await answer(uid, *args, **kwargs)

    Prompt.request.side_effect = chosen_action
    started = []

    async def after(emission):
        async with asyncio.timeout(10):
            if action == "scene_analysis":
                started.append(
                    await summarizer.analyze_scene_for_next_action("conversation", bob)
                )
            else:
                with ActiveAgent(director, after):
                    started.append(
                        await action_utils.execute_actions(
                            director.client,
                            scene,
                            [{"name": "direct_actor"}],
                            [],
                            Mock(return_value="result"),
                        )
                    )

    async_signals.get("agent.summarization.perceptions.after").connect(after)
    try:
        with capture_logs() as logs:
            await send_player_line()
            await asyncio.wait_for(repair_knowledge(scene), timeout=20)
    finally:
        async_signals.get("agent.summarization.perceptions.after").disconnect(after)
    assert not [log for log in logs if log["event"] == "Error in signal receiver"]
    assert len(started) == 2 and all(started)


@pytest.mark.asyncio
async def test_a_line_whose_analysis_failed_waits_for_repair(flow):
    from talemate.agents.summarize.perceptions import perception_results_current

    scene, narrator, narrations, on_player_line, send_player_line = flow
    answer = Prompt.request.side_effect
    failed = []

    async def provider_error_once(uid, *args, **kwargs):
        if uid == "summarizer.perceptions" and not failed:
            failed.append(uid)
            raise RuntimeError("provider error")
        return await answer(uid, *args, **kwargs)

    Prompt.request.side_effect = provider_error_once
    line = await send_player_line()
    with pytest.raises(Exception):
        await asyncio.wait_for(knowledge_step(scene), timeout=10)
    assert failed
    await asyncio.wait_for(knowledge_step(scene), timeout=10)
    assert not perception_results_current(scene, line)
    await asyncio.wait_for(repair_knowledge(scene), timeout=10)
    assert pending(scene) == []
    assert perception_results_current(scene, line)


@pytest.mark.asyncio
async def test_graph_listener_query_scene_on_a_player_line(flow):
    import talemate.game.engine.nodes.core as core

    scene, narrator, narrations, on_player_line, send_player_line = flow
    answers = []

    class QueryScene(core.Node):
        def setup(self):
            self.add_input("state")

        async def run(self, state):
            event = state.data["event"]
            if event.message.source == "player":
                answers.append(query_prompt().query_scene("Is the bell quiet?"))

    listener = core.Listen(id="player-line-listener")
    entry, action = core.Entry(), QueryScene()
    listener.add_node(entry)
    listener.add_node(action)
    listener.connect(entry.get_output_socket("state"), action.get_input_socket("state"))
    scene.nodegraph_state = core.GraphState()
    scene.signals["game_loop_new_message"].connect(listener.execute_from_event)
    await send_player_line()
    assert answers == ["Question: Is the bell quiet? Answer: The rain stops."]
    assert narrations == [True]


@pytest.mark.asyncio
async def test_revision_saved_receiver_during_a_refresh_can_query(flow, monkeypatch):
    from talemate.changelog import emit_revision_event

    scene, narrator, narrations, on_player_line, send_player_line = flow
    answers = []

    async def save():
        await emit_revision_event("scene.revision_saved", scene, "save")

    async def saved(event):
        answers.append(
            await asyncio.wait_for(narrator.narrate_query("Saved?"), timeout=10)
        )

    monkeypatch.setattr(scene, "attempt_auto_save", save)
    signal = async_signals.get("scene.revision_saved")
    signal.connect(saved)
    try:
        # the receivers run after the step, before it returns
        await asyncio.wait_for(repair_knowledge(scene), timeout=10)
    finally:
        signal.disconnect(saved)
    assert answers == ["The rain stops.", "The rain stops."]
    assert pending(scene) == []


@pytest.mark.asyncio
async def test_a_step_waits_for_a_step_that_is_still_saving(flow, monkeypatch):
    scene, narrator, narrations, on_player_line, send_player_line = flow
    earlier = scene.history[0]
    saves, last_save, release = [], asyncio.Event(), asyncio.Event()

    async def save():
        saves.append(earlier.revision_matches_baseline)
        if earlier.revision_matches_baseline:
            last_save.set()
            await release.wait()
            raise RuntimeError("disk full")

    monkeypatch.setattr(scene, "attempt_auto_save", save)
    first = asyncio.create_task(repair_knowledge(scene))
    await asyncio.wait_for(last_save.wait(), timeout=10)
    assert pending(scene) == []
    second = asyncio.create_task(repair_knowledge(scene))
    await asyncio.sleep(0.05)
    assert not second.done()
    release.set()
    results = await asyncio.wait_for(
        asyncio.gather(first, second, return_exceptions=True), timeout=10
    )
    assert [type(result) for result in results] == [RuntimeError, RuntimeError]
    assert pending(scene) == [earlier.id]


@pytest.mark.asyncio
async def test_config_changed_during_a_step_is_sent_after_release(
    flow, isolate_signals
):
    from talemate.config import get_config
    from talemate.knowledge.step import _locks

    scene, narrator, narrations, on_player_line, send_player_line = flow
    changed, follow = isolate_signals("config.changed", "config.changed.follow")
    answer = Prompt.request.side_effect
    received, sent = [], []

    async def receiver(config):
        # a receiver that saves the config or starts a step must not run
        # under the step's lock
        received.append(_locks[scene].locked())

    async def change_config_once(uid, *args, **kwargs):
        if uid == "summarizer.perceptions" and not sent:
            sent.append(uid)
            await get_config().set_dirty()
            assert received == []
        return await answer(uid, *args, **kwargs)

    changed.connect(receiver)
    follow.connect(receiver)
    Prompt.request.side_effect = change_config_once
    await send_player_line()
    await asyncio.wait_for(knowledge_step(scene), timeout=10)
    assert received == [False, False]


@pytest.mark.asyncio
async def test_the_step_builds_new_summaries_and_repair_settles_the_edit(
    audience_scene, monkeypatch
):
    from talemate.history import ArchiveEntry
    from talemate.knowledge.revision_scope import in_revision_phase

    scene, summarizer, request = audience_scene
    lines = [NarratorMessage(message=f"Line {index}.") for index in range(5)]
    for line in lines:
        await scene.push_history(line)
        await knowledge_step(scene)
    await edit_through_the_ui(scene, lines[0], "Line zero, edited.")
    assert pending(scene) == [lines[0].id]
    scene.archived_history = [
        ArchiveEntry(
            id=f"entry-{index}", text="READER", start=index, end=index
        ).model_dump(exclude_none=True)
        for index in range(1, 5)
    ]

    async def summarize(text, **kwargs):
        return "Compressed: " + text

    monkeypatch.setattr(summarizer, "summarize", summarize)
    for index in range(1, 5):
        await summarizer.queue_summary_views(scene, f"entry-{index}")
    ensure = summarizer.ensure_summary_views
    built = []

    async def recorded(scene, identity, layer=0, **kwargs):
        requested = await ensure(scene, identity, layer, **kwargs)
        if requested:
            built.append((identity, in_revision_phase(scene)))
        return requested

    monkeypatch.setattr(summarizer, "ensure_summary_views", recorded)
    await asyncio.wait_for(knowledge_step(scene), timeout=10)
    # the new entries are built; the edit stays flagged
    assert pending(scene) == [lines[0].id]
    assert len(built) == 4
    assert not any(refreshing for _, refreshing in built)
    assert not summarizer._summary_dirty[scene]
    await asyncio.wait_for(repair_knowledge(scene), timeout=10)
    assert pending(scene) == []
