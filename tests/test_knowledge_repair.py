"""
No automatic repair: an edit flags what it affects, generation keeps the last
views, and Repair rebuilds in dependency order.
"""

import json
from unittest.mock import AsyncMock

import pytest
from _knowledge_step_helpers import push_and_step
from _perception_response_helpers import excluding_passage
from _perception_story_helpers import analysis, story

import test_perception_lifecycle
from talemate.agents.summarize.perceptions import perception_results_current
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.status import knowledge_sync
from talemate.knowledge.step import knowledge_step, repair_knowledge, repair_passage
from talemate.scene_message import CharacterMessage, NarratorMessage

setup = test_perception_lifecycle.setup


@pytest.fixture
def citing(setup, monkeypatch):
    """Analyses that cite every offered view and passage, so edits cascade."""
    scene, summarizer, _ = setup
    analyzed = []
    answer = analysis()

    async def record(*args, **kwargs):
        analyzed.append(
            kwargs["vars"]["context"]["passage"]["provenance"]["message_id"]
        )
        return await answer(*args, **kwargs)

    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.Prompt.request",
        excluding_passage(record),
    )
    return scene, summarizer, analyzed


def flagged(scene):
    return [
        message.id
        for message in scene.history
        if message.knowledge is not None
        and not perception_results_current(scene, message)
    ]


@pytest.mark.asyncio
async def test_an_edit_flags_without_a_request_and_keeps_the_text(citing):
    scene, _, analyzed = citing
    messages = await story(scene, 4)
    analyzed.clear()
    scene.edit_message(messages[1].id, "Line one, edited.")
    await knowledge_step(scene)
    assert analyzed == []
    assert messages[1].id in flagged(scene)
    assert all(view.stale and view.text for view in messages[1].knowledge.views)
    # the later lines cite it, so they are flagged too
    assert flagged(scene) == [message.id for message in messages[1:]]
    assert knowledge_sync(scene).passages == 3


@pytest.mark.asyncio
async def test_repair_runs_passages_in_story_order(citing):
    scene, _, analyzed = citing
    messages = await story(scene, 4)
    analyzed.clear()
    scene.edit_message(messages[1].id, "Line one, edited.")
    await repair_knowledge(scene)
    assert analyzed == [message.id for message in messages[1:]]
    assert flagged(scene) == []
    assert knowledge_sync(scene).total == 0


@pytest.mark.asyncio
async def test_stop_during_repair_leaves_the_rest_flagged(citing, monkeypatch):
    scene, _, analyzed = citing
    messages = await story(scene, 4)
    analyzed.clear()
    scene.edit_message(messages[1].id, "Line one, edited.")
    answer = analysis()

    async def stop_after_one(*args, **kwargs):
        if analyzed:
            raise GenerationCancelled("Stopped", by_user=True)
        analyzed.append(
            kwargs["vars"]["context"]["passage"]["provenance"]["message_id"]
        )
        return await answer(*args, **kwargs)

    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.Prompt.request",
        excluding_passage(stop_after_one),
    )
    with pytest.raises(GenerationCancelled):
        await repair_knowledge(scene)
    assert analyzed == [messages[1].id]
    assert messages[1].id not in flagged(scene)
    assert flagged(scene) == [message.id for message in messages[2:]]
    for message in messages[2:]:
        assert all(view.text for view in message.knowledge.views)


@pytest.mark.asyncio
async def test_new_lines_are_analyzed_and_build_on_flagged_knowledge(citing):
    scene, _, analyzed = citing
    messages = await story(scene, 2)
    analyzed.clear()
    scene.edit_message(messages[0].id, "Line zero, edited.")
    before = knowledge_sync(scene).passages
    new = NarratorMessage(message="A new line.", source="narrate_scene")
    await push_and_step(scene, new)
    assert analyzed == [new.id]
    # it cites what the characters last knew, so it is out of sync as well
    assert new.id in flagged(scene)
    assert knowledge_sync(scene).passages == before + 1


@pytest.mark.asyncio
async def test_a_regenerated_reply_is_a_new_line(citing):
    scene, _, analyzed = citing
    messages = await story(scene, 2)
    analyzed.clear()
    messages[1].append_version("Line one, regenerated.", "regenerate")
    assert knowledge_sync(scene).passages == 0
    await knowledge_step(scene)
    assert analyzed == [messages[1].id]
    assert flagged(scene) == []


@pytest.mark.asyncio
async def test_one_passage_repair_leaves_what_was_built_on_it_flagged(citing):
    scene, _, analyzed = citing
    messages = await story(scene, 3)
    analyzed.clear()
    scene.edit_message(messages[0].id, "Line zero, edited.")
    await repair_passage(scene, messages[0])
    assert analyzed == [messages[0].id]
    assert messages[0].revision_matches_baseline
    assert flagged(scene) == [message.id for message in messages[1:]]


@pytest.mark.asyncio
async def test_repair_with_nothing_flagged_sends_no_request(citing):
    scene, _, analyzed = citing
    await story(scene, 3)
    analyzed.clear()
    await repair_knowledge(scene)
    assert analyzed == []
    assert knowledge_sync(scene).total == 0


@pytest.mark.asyncio
async def test_a_passage_rebuilt_without_a_request_still_counts(setup):
    scene, _, request = setup
    # the speaker keeps their own line and the player the full passage
    scene.character_data["Alice"].is_player = True
    line = CharacterMessage(message="Bob: A line in Bob's own words.")
    await push_and_step(scene, line)
    request.reset_mock()
    scene.edit_message(line.id, "Bob: The line, edited.")
    assert knowledge_sync(scene).passages == 1
    await repair_knowledge(scene)
    request.assert_not_awaited()
    assert knowledge_sync(scene).passages == 0


def bounded(answer, analyzed, runaway, limit=6):
    """
    An analysis mock that records each passage and ends a runaway loop with a
    Stop, which the analysis does not take for a failed request.
    """

    async def record(*args, **kwargs):
        analyzed.append(
            kwargs["vars"]["context"]["passage"]["provenance"]["message_id"]
        )
        if len(analyzed) > limit:
            runaway.append(list(analyzed))
            raise GenerationCancelled("analyzed without end", by_user=True)
        return await answer(*args, **kwargs)

    return excluding_passage(record)


@pytest.fixture
def bounded_citing(setup, monkeypatch):
    scene, summarizer, _ = setup
    analyzed = []
    runaway = []
    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.Prompt.request",
        bounded(analysis(), analyzed, runaway),
    )
    yield scene, summarizer, analyzed
    assert runaway == []


@pytest.mark.asyncio
async def test_a_regenerated_reply_on_flagged_knowledge_is_analyzed_once(
    bounded_citing,
):
    scene, _, analyzed = bounded_citing
    messages = await story(scene, 3)
    scene.edit_message(messages[0].id, "Line zero, edited.")
    analyzed.clear()
    messages[2].append_version("Line two, regenerated.", "regenerate")
    await knowledge_step(scene)
    assert analyzed == [messages[2].id]
    # settled, but built on flagged knowledge: counted for Repair
    assert messages[2].revision_matches_baseline
    assert messages[2].id in flagged(scene)
    await knowledge_step(scene)
    assert analyzed == [messages[2].id]


@pytest.mark.asyncio
async def test_one_passage_repair_on_flagged_knowledge_is_analyzed_once(
    bounded_citing,
):
    scene, _, analyzed = bounded_citing
    messages = await story(scene, 3)
    scene.edit_message(messages[0].id, "Line zero, edited.")
    scene.edit_message(messages[1].id, "Line one, edited.")
    analyzed.clear()
    await repair_passage(scene, messages[1])
    assert analyzed == [messages[1].id]
    assert messages[1].revision_matches_baseline
    await repair_knowledge(scene)
    # Repair goes in story order and redoes the passage on what changed
    assert analyzed[1:] == [message.id for message in messages]
    assert flagged(scene) == []


@pytest.mark.asyncio
async def test_retry_of_a_failed_new_line_on_flagged_knowledge_ends(setup, monkeypatch):
    scene, summarizer, _ = setup
    analyzed = []
    runaway = []
    answer = analysis()
    failed = []

    async def fail_once(*args, **kwargs):
        if not failed:
            failed.append(True)
            return "not structured", {"response": "not structured"}
        return await answer(*args, **kwargs)

    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.Prompt.request",
        bounded(fail_once, analyzed, runaway),
    )
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="retry")
    )
    messages = await story(scene, 2)
    scene.edit_message(messages[0].id, "Line zero, edited.")
    analyzed.clear()
    failed.clear()
    new = NarratorMessage(message="A new line.", source="narrate_scene")
    await push_and_step(scene, new)
    assert runaway == []
    assert analyzed == [new.id, new.id]


@pytest.mark.asyncio
async def test_new_lines_are_offered_every_flagged_view(citing):
    from talemate.agents.summarize.perceptions import perception_context

    scene, _, _ = citing
    messages = await story(scene, 3)
    scene.edit_message(messages[0].id, "Line zero, edited.")
    # the later lines cite the edited one: a chain of flagged views
    assert flagged(scene) == [message.id for message in messages]
    new = NarratorMessage(message="A new line.", source="narrate_scene")
    await scene.push_history(new)
    context = perception_context(scene, new)
    offered = {
        entry["name"]: {item["source"]["id"] for item in entry["established_knowledge"]}
        for entry in context["cast"]
    }
    every = {message.id for message in messages}
    assert offered == {"Alice": every, "Bob": every}


@pytest.mark.asyncio
async def test_a_stop_leaves_a_new_line_new(setup, monkeypatch):
    scene, _, request = setup
    request.side_effect = GenerationCancelled("Stopped", by_user=True)
    line = NarratorMessage(message="A bell rings.", source="narrate_scene")
    with pytest.raises(GenerationCancelled):
        await push_and_step(scene, line)
    assert all(view.status == "pending" for view in line.knowledge.views)
    assert knowledge_sync(scene).passages == 0
    request.side_effect = None
    request.reset_mock()
    await knowledge_step(scene)
    request.assert_awaited_once()
    assert flagged(scene) == []


@pytest.mark.asyncio
async def test_a_failed_regenerated_reply_waits_for_repair(setup, monkeypatch):
    scene, summarizer, request = setup
    line = NarratorMessage(message="A bell rings.", source="narrate_scene")
    await push_and_step(scene, line)
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="ignore")
    )
    line.append_version("The bell rings twice.", "regenerate")
    good = request.return_value
    request.return_value = ("not structured", {"response": "not structured"})
    request.reset_mock()
    with pytest.raises(GenerationCancelled):
        await knowledge_step(scene)
    assert request.await_count == 1
    assert knowledge_sync(scene).passages == 1
    await knowledge_step(scene)
    assert request.await_count == 1
    request.return_value = good
    await repair_knowledge(scene)
    assert request.await_count == 2
    assert knowledge_sync(scene).passages == 0


@pytest.mark.asyncio
async def test_ignore_during_repair_goes_on_with_the_rest(setup, monkeypatch):
    scene, summarizer, request = setup
    lines = await story(scene, 3)
    for line in lines[:2]:
        scene.edit_message(line.id, f"{line.message} Edited.")
    good = request.return_value

    async def first_fails(*args, **kwargs):
        passage = kwargs["vars"]["context"]["passage"]["provenance"]["message_id"]
        if passage == lines[0].id:
            return "not structured", {"response": "not structured"}
        return good

    request.side_effect = first_fails
    request.reset_mock()
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="ignore")
    )
    await repair_knowledge(scene)
    assert lines[1].id not in flagged(scene)
    assert lines[0].id in flagged(scene)


def test_a_flagged_output_still_needs_its_citations_to_resolve(setup):
    from talemate.knowledge.perspective_models import SourceReference
    from talemate.knowledge.perspectives import set_source_perspectives

    scene, _, _ = setup
    line = NarratorMessage(message="A bell rings.")
    scene.history.append(line)
    missing = SourceReference(kind="message", id=999999, revision=1)
    with pytest.raises(ValueError):
        set_source_perspectives(
            scene,
            "message",
            line.id,
            [
                {
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": "Alice hears it.",
                    "stale": True,
                    "sources": [missing],
                }
            ],
        )


@pytest.mark.asyncio
async def test_repair_after_a_cited_line_is_deleted(citing):
    scene, _, analyzed = citing
    messages = await story(scene, 3)
    analyzed.clear()
    scene.delete_message(messages[0].id)
    assert knowledge_sync(scene).passages == 2
    await repair_knowledge(scene)
    assert analyzed == [message.id for message in messages[1:]]
    assert knowledge_sync(scene).total == 0


@pytest.mark.asyncio
async def test_a_regenerate_after_a_cited_line_is_deleted(citing):
    scene, _, analyzed = citing
    messages = await story(scene, 3)
    analyzed.clear()
    scene.delete_message(messages[0].id)
    messages[2].append_version("Line two, regenerated.", "regenerate")
    await knowledge_step(scene)
    assert analyzed == [messages[2].id]
    assert messages[2].revision_state.status == "clean"
    assert messages[2].id not in flagged(scene)


@pytest.mark.asyncio
async def test_repair_after_a_cited_disclosure_is_removed(citing):
    from talemate.knowledge.perspectives import add_disclosure, remove_disclosure

    scene, _, analyzed = citing
    await story(scene, 1)
    disclosure = add_disclosure(scene, "The vault code is 1234.", ("Alice", "Bob"))
    line = NarratorMessage(message="A new line.", source="narrate_scene")
    await push_and_step(scene, line)
    cited = {source.id for view in line.knowledge.views for source in view.sources}
    assert disclosure.id in cited
    analyzed.clear()
    remove_disclosure(scene, disclosure.id)
    assert line.id in flagged(scene)
    await repair_knowledge(scene)
    assert analyzed == [line.id]
    assert knowledge_sync(scene).total == 0


def cast_of(request):
    return [
        [entry["name"] for entry in call.kwargs["vars"]["context"]["cast"]]
        for call in request.await_args_list
    ]


@pytest.mark.asyncio
async def test_a_stop_with_a_player_in_the_cast_leaves_the_line_new(setup):
    scene, _, request = setup
    # the player's view needs no request; it is not stored by a stopped analysis
    scene.character_data["Alice"].is_player = True
    request.side_effect = GenerationCancelled("Stopped", by_user=True)
    line = NarratorMessage(message="A bell rings.", source="narrate_scene")
    with pytest.raises(GenerationCancelled):
        await push_and_step(scene, line)
    statuses = {view.audience[0]: view.status for view in line.knowledge.views}
    assert statuses == {"Alice": "pending", "Bob": "pending"}
    assert knowledge_sync(scene).passages == 0
    request.side_effect = None
    request.reset_mock()
    await knowledge_step(scene)
    assert cast_of(request) == [["Bob"]]
    assert flagged(scene) == []


@pytest.mark.asyncio
async def test_a_stop_during_the_fix_up_request_leaves_the_line_new(setup):
    answer, result = test_perception_lifecycle.answer, test_perception_lifecycle.result
    scene, summarizer, request = setup
    summarizer.actions["perceptions"].config["automatic_repair"].value = True
    only_alice = json.loads(answer())
    only_alice["views"] = only_alice["views"][:1]
    request.side_effect = [
        result(json.dumps(only_alice)),
        GenerationCancelled("Stopped", by_user=True),
    ]
    line = NarratorMessage(message="Alice: Hello.", source="narrate_scene")
    with pytest.raises(GenerationCancelled):
        await push_and_step(scene, line)
    statuses = {view.audience[0]: view.status for view in line.knowledge.views}
    assert statuses == {"Alice": "pending", "Bob": "pending"}
    assert knowledge_sync(scene).passages == 0
    request.side_effect = None
    request.return_value = result()
    request.reset_mock()
    await knowledge_step(scene)
    assert cast_of(request) == [["Alice", "Bob"]]
    assert flagged(scene) == []


@pytest.mark.asyncio
async def test_a_stop_during_a_repair_leaves_a_failed_line_failed(setup, monkeypatch):
    scene, summarizer, request = setup
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="ignore")
    )
    good = request.return_value
    request.return_value = ("not structured", {"response": "not structured"})
    line = NarratorMessage(message="A bell rings.", source="narrate_scene")
    with pytest.raises(GenerationCancelled):
        await push_and_step(scene, line)
    assert {view.status for view in line.knowledge.views} == {"failed"}
    assert knowledge_sync(scene).passages == 1
    request.side_effect = GenerationCancelled("Stopped", by_user=True)
    with pytest.raises(GenerationCancelled):
        await repair_knowledge(scene)
    assert {view.status for view in line.knowledge.views} == {"failed"}
    assert knowledge_sync(scene).passages == 1
    request.side_effect = None
    request.return_value = good
    request.reset_mock()
    await knowledge_step(scene)
    request.assert_not_awaited()


def failing_on(passage_id, analyzed):
    """Citing analyses, except that one passage's answer is never valid."""
    answer = analysis()

    async def request(*args, **kwargs):
        passage = kwargs["vars"]["context"]["passage"]["provenance"]["message_id"]
        analyzed.append(passage)
        if passage == passage_id:
            return "not structured", {"response": "not structured"}
        return await answer(*args, **kwargs)

    return excluding_passage(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count,edited,failing",
    [
        # a later edited passage settles first in its own revision
        (3, (0, 1), 0),
        # the failing passage is not edited, but is in every later prefix
        (4, (0, 2, 3), 1),
    ],
)
async def test_ignore_is_asked_once_per_repair(
    citing, monkeypatch, count, edited, failing
):
    scene, summarizer, _ = citing
    messages = await story(scene, count)
    for index in edited:
        scene.edit_message(messages[index].id, f"Line {index}, edited.")
    analyzed = []
    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.Prompt.request",
        failing_on(messages[failing].id, analyzed),
    )
    dialog = AsyncMock(return_value="ignore")
    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", dialog)
    await repair_knowledge(scene)
    assert dialog.await_count == 1
    assert analyzed.count(messages[failing].id) == 1
    assert len(analyzed) == len(set(analyzed))
    assert messages[failing].id in flagged(scene)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["regenerate", "continue"])
@pytest.mark.parametrize("change", ["edit", "delete", "edit the reply"])
async def test_a_kept_regenerated_reply_is_only_flagged_by_a_later_change(
    citing, change, source
):
    scene, _, analyzed = citing
    messages = await story(scene, 3)
    messages[2].append_version("Line two, regenerated.", source)
    await knowledge_step(scene)
    assert messages[2].revision_matches_baseline
    analyzed.clear()
    if change == "edit":
        scene.edit_message(messages[0].id, "Line zero, edited.")
    elif change == "delete":
        scene.delete_message(messages[0].id)
    else:
        scene.edit_message(messages[2].id, "Line two, edited by hand.")
    count = knowledge_sync(scene).passages
    await knowledge_step(scene)
    assert analyzed == []
    assert knowledge_sync(scene).passages == count
    assert messages[2].id in flagged(scene)


@pytest.mark.asyncio
async def test_a_stop_adds_no_view_for_an_audience_that_had_none(setup):
    scene, _, request = setup
    (line,) = await story(scene, 1)
    # Bob was removed from the scene and added back: no view for him yet
    knowledge = line.knowledge
    object.__setattr__(
        line,
        "knowledge",
        knowledge.model_copy(
            update={
                "views": tuple(
                    view for view in knowledge.views if "Bob" not in view.audience
                )
            }
        ),
    )
    assert knowledge_sync(scene).passages == 1
    request.reset_mock()
    request.side_effect = GenerationCancelled("Stopped", by_user=True)
    with pytest.raises(GenerationCancelled):
        await repair_knowledge(scene)
    assert [view.audience for view in line.knowledge.views] == [("Alice",)]
    assert knowledge_sync(scene).passages == 1
    request.side_effect = None
    request.reset_mock()
    await knowledge_step(scene)
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_line_stays_failed_after_a_restart_and_a_stop(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="ignore")
    )
    good = request.return_value
    request.return_value = ("not structured", {"response": "not structured"})
    line = NarratorMessage(message="A bell rings.", source="narrate_scene")
    with pytest.raises(GenerationCancelled):
        await push_and_step(scene, line)
    assert knowledge_sync(scene).passages == 1

    async def restart_then_stop(*args, **kwargs):
        if request.await_count == 1:
            # the analysis inputs change while the request runs
            scene.intent_state.intent = "A new story direction."
            return good
        raise GenerationCancelled("Stopped", by_user=True)

    request.reset_mock()
    request.side_effect = restart_then_stop
    with pytest.raises(GenerationCancelled):
        await repair_knowledge(scene)
    assert request.await_count == 2
    assert {view.status for view in line.knowledge.views} == {"failed"}
    assert knowledge_sync(scene).passages == 1
    request.side_effect = None
    request.reset_mock()
    await knowledge_step(scene)
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stopped_new_line_is_repaired_after_what_it_builds_on(
    setup, monkeypatch
):
    scene, _, _ = setup
    analyzed = []
    stop = []
    answer = analysis()

    async def request(*args, **kwargs):
        if stop:
            raise GenerationCancelled("Stopped", by_user=True)
        analyzed.append(
            kwargs["vars"]["context"]["passage"]["provenance"]["message_id"]
        )
        return await answer(*args, **kwargs)

    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.Prompt.request",
        excluding_passage(request),
    )
    messages = await story(scene, 4)
    stop.append(True)
    new = NarratorMessage(message="A new line.", source="narrate_scene")
    with pytest.raises(GenerationCancelled):
        await push_and_step(scene, new)
    stop.clear()
    analyzed.clear()
    scene.edit_message(messages[1].id, "Line one, edited.")
    await repair_knowledge(scene)
    assert analyzed == [message.id for message in messages[1:]] + [new.id]
    assert knowledge_sync(scene).total == 0


@pytest.mark.asyncio
async def test_a_line_whose_only_audience_was_removed_waits_for_repair(setup):
    scene, _, request = setup
    (line,) = await story(scene, 1)
    # every audience was removed and added back: the views are gone
    object.__setattr__(
        line, "knowledge", line.knowledge.model_copy(update={"views": ()})
    )
    assert knowledge_sync(scene).passages == 1
    request.reset_mock()
    await knowledge_step(scene)
    request.assert_not_awaited()
    assert knowledge_sync(scene).passages == 1
    await repair_knowledge(scene)
    request.assert_awaited_once()
    assert knowledge_sync(scene).passages == 0
