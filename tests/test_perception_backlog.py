import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from _knowledge_step_helpers import push_and_step
from _perception_backlog_helpers import answering
from _perception_response_helpers import excluding_passage
from structlog.testing import capture_logs

import talemate.agents.summarize.perceptions as perceptions
from talemate.agents.summarize.perceptions import (
    analysis_dependents,
    keep_stored_perceptions,
    perception_backlog,
    perception_passages,
    perception_results_current,
    perception_staleness,
    resolve_perception_backlog,
)
from talemate.agents.summarize.websocket_handler import SummarizeWebsocketHandler
from talemate.character import Character, activate_character, deactivate_character
from talemate.context import ActiveScene
from talemate.emit.signals import handlers
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.revision_refresh import (
    catch_up_revisions,
    revision_requires_refresh,
)
from talemate.knowledge.step import knowledge_step
from talemate.regenerate import regenerate
from talemate.tale_mate import Actor
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    Staleness,
    bind_perspective_sources,
    edit_message_view,
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    ReinforcementMessage,
)

NAMES = ("Alice", "Bob", "Carol")


def analysis(cite_knowledge=True, cite_passages=True):
    """A perception answer in which each view cites what it is offered."""

    async def answer(*args, **kwargs):
        context = kwargs["vars"]["context"]
        passage = context["passage"]["provenance"]["message_id"]
        views = [
            {
                "audience": [entry["name"]],
                "status": "ready",
                "text": f"{entry['name']} notices passage {passage}.",
                "knowledge_ids": [item["id"] for item in entry["established_knowledge"]]
                if cite_knowledge
                else [],
                "passage_ids": [
                    item["id"] for item in context["prior_physical_context"]
                ]
                if cite_passages
                else [],
            }
            for entry in context["cast"]
        ]
        text = json.dumps({"views": views})
        return text, {"response": text}

    return answer


@pytest.fixture
def setup(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in NAMES}
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")
    summarizer.actions["perceptions"].config["automatic_repair"].value = False
    request = AsyncMock(side_effect=analysis())
    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.Prompt.request",
        excluding_passage(request),
    )
    with ActiveScene(scene):
        yield scene, summarizer, request


async def story(scene, count=5):
    messages = [
        NarratorMessage(message=f"Line {index}.", source="narrate_scene")
        for index in range(count)
    ]
    for message in messages:
        await push_and_step(scene, message)
    return messages


def older_build(messages):
    """Stored baselines and receipts that the current revision digest no longer matches."""
    for message in messages:
        object.__setattr__(
            message,
            "revision_state",
            message.revision_state.model_copy(
                update={"baseline_digest": "older-build", "phase_receipts": {}}
            ),
        )


def replace_view(message, name, **update):
    knowledge = message.knowledge
    views = tuple(
        view.model_copy(update=update) if name in view.audience else view
        for view in knowledge.views
    )
    object.__setattr__(
        message, "knowledge", knowledge.model_copy(update={"views": views})
    )


def remove_view(message, name):
    knowledge = message.knowledge
    object.__setattr__(
        message,
        "knowledge",
        knowledge.model_copy(
            update={
                "views": tuple(v for v in knowledge.views if name not in v.audience)
            }
        ),
    )


def backlog(scene):
    return perception_backlog(scene, perception_passages(scene))


def texts(messages):
    return [
        {
            view.audience[0]: (view.id, view.revision, view.text)
            for view in m.knowledge.views
        }
        for m in messages
    ]


@pytest.mark.asyncio
async def test_current_history_has_no_backlog(setup):
    scene, _, request = setup
    messages = await story(scene)
    assert request.await_count == 5
    assert [perception_staleness(scene, message) for message in messages] == [None] * 5
    counted = backlog(scene)
    assert (counted.needed, counted.total) == (0, 0)


@pytest.mark.asyncio
async def test_stale_check_names_the_content_digest(setup):
    scene, _, _ = setup
    messages = await story(scene)
    object.__setattr__(messages[2], "message", "Alice: Changed.")
    assert perception_staleness(scene, messages[2]) == Staleness(check="content_digest")


@pytest.mark.asyncio
async def test_stale_check_names_the_missing_audience_view(setup):
    scene, _, _ = setup
    messages = await story(scene)
    remove_view(messages[0], "Bob")
    assert perception_staleness(scene, messages[0]) == Staleness(
        check="missing_audience_view", character="Bob"
    )


@pytest.mark.asyncio
async def test_stale_check_names_the_revision_receipt(setup):
    scene, _, _ = setup
    messages = await story(scene)
    older_build(messages)
    assert perception_staleness(scene, messages[0]) == Staleness(
        check="provenance_revision_receipt", character="Alice", cited=messages[0].id
    )


@pytest.mark.asyncio
async def test_stale_check_names_the_knowledge_revision_of_a_cited_passage(setup):
    scene, _, _ = setup
    messages = await story(scene)
    knowledge = messages[1].knowledge
    object.__setattr__(
        messages[1], "knowledge", knowledge.model_copy(update={"revision": 2})
    )
    assert perception_staleness(scene, messages[2]) == Staleness(
        check="provenance_knowledge_revision", character="Alice", cited=messages[1].id
    )


@pytest.mark.asyncio
async def test_stale_check_names_the_content_digest_of_a_cited_passage(setup):
    scene, _, _ = setup
    messages = await story(scene)
    object.__setattr__(messages[1], "message", "Alice: Changed.")
    assert perception_staleness(scene, messages[2]) == Staleness(
        check="provenance_content_digest", character="Alice", cited=messages[1].id
    )


@pytest.mark.asyncio
async def test_stale_check_names_the_stored_status_and_the_dependency(setup):
    scene, _, _ = setup
    messages = await story(scene)
    replace_view(messages[2], "Alice", status="failed", text=None)
    assert perception_staleness(scene, messages[2]) == Staleness(
        check="view_status", character="Alice"
    )
    assert perception_staleness(scene, messages[3]) == Staleness(
        check="dependency", character="Alice", cited=messages[2].id
    )


@pytest.mark.asyncio
async def test_backlog_of_an_older_build_is_keepable(setup):
    scene, _, _ = setup
    messages = await story(scene)
    older_build(messages)
    counted = backlog(scene)
    assert [m.id for m in counted.keepable] == [m.id for m in messages]
    assert (counted.empty, counted.at_risk, counted.total) == ((), (), 5)
    assert counted.checks() == {"provenance_revision_receipt": 5}


@pytest.mark.asyncio
async def test_activation_omits_five_absent_passages_without_requests(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    stored = [message.knowledge for message in messages]
    assert all(message.present == ["Alice", "Bob"] for message in messages)
    request.reset_mock()

    await activate_character(scene, "Carol")
    counted = backlog(scene)
    assert (counted.needed, counted.total) == (0, 0)
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    request.assert_not_awaited()
    assert frames == []
    assert [message.knowledge for message in messages] == stored
    for message in messages:
        view = select_character_view(
            scene, source_reference(scene, "message", message.id), "Carol"
        )
        assert (view.status, view.text) == ("omitted", None)

    later = CharacterMessage(message="Carol: I am here now.")
    await push_and_step(scene, later)
    assert later.present == ["Alice", "Bob", "Carol"]
    request.assert_awaited_once()
    assert (
        select_character_view(
            scene, source_reference(scene, "message", later.id), "Carol"
        ).status
        == "ready"
    )
    assert [message.knowledge for message in messages] == stored

    await deactivate_character(scene, "Carol")
    absent = await story(scene)
    request.reset_mock()
    await activate_character(scene, "Carol")
    with answering("analyze", frames):
        await knowledge_step(scene)
    request.assert_not_awaited()
    assert frames == []
    assert (
        select_character_view(
            scene, source_reference(scene, "message", later.id), "Carol"
        ).status
        == "ready"
    )
    assert all(
        select_character_view(
            scene, source_reference(scene, "message", message.id), "Carol"
        ).status
        == "omitted"
        for message in absent
    )


@pytest.mark.asyncio
async def test_upper_bound_counts_the_cascade_of_a_rewritten_passage(setup):
    scene, summarizer, request = setup
    request.side_effect = analysis(cite_knowledge=False)
    messages = await story(scene)
    knowledge = messages[0].knowledge
    object.__setattr__(
        messages[0],
        "knowledge",
        knowledge.model_copy(update={"content_digest": content_digest("Alice: Old.")}),
    )
    counted = backlog(scene)
    assert [m.id for m in counted.keepable] == [messages[0].id]
    assert [m.id for m in counted.at_risk] == [m.id for m in messages[1:]]
    assert counted.total == 5
    before = request.await_count
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert [frame["perceptions"]["total"] for frame in frames] == [5]
    assert request.await_count - before == 5


@pytest.mark.asyncio
async def test_upper_bound_skips_views_that_an_analysis_keeps(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    replace_view(messages[4], "Bob", status="failed", text=None)
    counted = backlog(scene)
    assert ([m.id for m in counted.empty], counted.at_risk) == ([messages[4].id], ())


@pytest.mark.parametrize("status", ["ready", "pending", "failed"])
@pytest.mark.parametrize("later_present", [False, True])
async def test_backlog_skips_absent_dependents_but_propagates_to_present(
    setup, status, later_present
):
    scene, summarizer, request = setup
    scene.active_characters = ["Alice"]
    root = (await story(scene, count=1))[0]
    edit_message_view(scene, root.id, "Carol", "I hear Alice.")
    carol = select_character_view(
        scene, source_reference(scene, "message", root.id), "Carol"
    )
    dependent = NarratorMessage(message="Alice remembers.", present=["Alice"])
    scene.history.append(dependent)
    set_source_perspectives(
        scene,
        "message",
        dependent.id,
        [
            {"audience": ["Alice"], "status": "ready", "text": "I remember."},
            {
                "audience": ["Carol"],
                "status": "ready",
                "text": "I remember Alice.",
                "sources": [carol.source],
            },
        ],
    )
    if later_present:
        later = NarratorMessage(message="Carol recalls it too.", present=["Carol"])
        scene.history.append(later)
        inherited = select_character_view(
            scene, source_reference(scene, "message", dependent.id), "Carol"
        )
        set_source_perspectives(
            scene,
            "message",
            later.id,
            [
                {
                    "audience": ["Carol"],
                    "status": "ready",
                    "text": "I recall it too.",
                    "sources": [inherited.source],
                }
            ],
        )
    replace_view(root, "Alice", status="failed", text=None)
    if status != "ready":
        replace_view(root, "Carol", status=status, text=None)
    counted = backlog(scene)
    assert counted.at_risk == ()
    expected_requests = 1 + (later_present and status != "ready")
    assert counted.total == expected_requests
    assert analysis_dependents(
        scene, perception_passages(scene), [root], read=PerspectiveReadContext(scene)
    ) == ((later,) if later_present and status != "ready" else ())
    request.reset_mock()
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert frames == []
    assert request.await_count == expected_requests
    assert [
        call.kwargs["vars"]["context"]["passage"]["provenance"]["message_id"]
        for call in request.await_args_list
    ] == ([root.id, later.id] if expected_requests == 2 else [root.id])


@pytest.mark.asyncio
async def test_keep_makes_stored_views_current_without_a_request(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    stored = texts(messages)
    cited = [len(view.sources) for view in messages[4].knowledge.views]
    older_build(messages)
    counted = backlog(scene)
    before = request.await_count

    keep_stored_perceptions(scene, [*counted.keepable, *counted.empty])

    assert all(perception_results_current(scene, message) for message in messages)
    assert texts(messages) == stored
    assert [len(view.sources) for view in messages[4].knowledge.views] == cited
    await knowledge_step(scene)
    assert request.await_count == before

    saved = [message.model_dump() for message in scene.history]
    scene.history = [NarratorMessage.model_validate(entry) for entry in saved]
    bind_perspective_sources(scene)
    assert all(perception_results_current(scene, message) for message in scene.history)


@pytest.mark.asyncio
async def test_keep_accepts_a_changed_text_without_a_revision_change(setup):
    scene, _, request = setup
    messages = await story(scene)
    revision = messages[0].knowledge.revision
    object.__setattr__(messages[0], "message", "Alice: Changed.")
    keep_stored_perceptions(scene, list(backlog(scene).keepable))
    assert messages[0].knowledge.content_digest == content_digest("Alice: Changed.")
    assert messages[0].knowledge.revision == revision
    assert all(perception_results_current(scene, message) for message in messages)


@pytest.mark.asyncio
async def test_keep_fills_in_only_the_missing_views(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    stored = texts(messages)
    older_build(messages)
    for message in messages:
        remove_view(message, "Bob")
    counted = backlog(scene)
    before = request.await_count

    keep_stored_perceptions(scene, [*counted.keepable, *counted.empty])
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)

    assert [
        (frame["perceptions"]["empty"], frame["perceptions"]["at_risk"])
        for frame in frames
    ] == [(5, 0)]
    assert request.await_count - before == 5
    assert [
        {name: value for name, value in views.items() if name != "Bob"}
        for views in texts(messages)
    ] == [
        {name: value for name, value in views.items() if name != "Bob"}
        for views in stored
    ]
    assert all(perception_results_current(scene, message) for message in messages)


@pytest.mark.asyncio
async def test_keep_removes_a_citation_it_cannot_make_current(setup):
    scene, _, _ = setup
    messages = await story(scene)
    replace_view(messages[2], "Alice", status="failed", text=None)
    counted = backlog(scene)
    assert [m.id for m in counted.empty] == [messages[2].id]

    keep_stored_perceptions(scene, [*counted.keepable, *counted.empty])

    alice = next(v for v in messages[3].knowledge.views if "Alice" in v.audience)
    assert messages[2].id not in {dependency.id for dependency in alice.sources}
    assert perception_results_current(scene, messages[3])
    assert perception_staleness(scene, messages[2]) == Staleness(
        check="view_status", character="Alice"
    )


FRAME_KEYS = {"request_id", "perceptions", "summaries"}
PERCEPTION_KEYS = {
    "needed",
    "keepable",
    "empty",
    "new",
    "at_risk",
    "total",
    "requests",
    "keep_total",
    "keep_requests",
}


@pytest.mark.asyncio
async def test_gate_asks_before_a_large_backlog_and_analyze_runs_it(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    older_build(messages)
    before = request.await_count
    frames = []
    with capture_logs() as logs, answering("analyze", frames):
        await knowledge_step(scene)
    assert [set(frame) for frame in frames] == [FRAME_KEYS]
    assert frames[0]["summaries"] is None
    assert set(frames[0]["perceptions"]) == PERCEPTION_KEYS
    assert frames[0]["perceptions"] == {
        "needed": 5,
        "keepable": 5,
        "empty": 0,
        "new": 0,
        "at_risk": 0,
        "total": 5,
        "requests": 5,
        "keep_total": 0,
        "keep_requests": 0,
    }
    assert request.await_count - before == 5
    summary = next(entry for entry in logs if entry["event"] == "perception backlog")
    assert summary["checks"] == {"provenance_revision_receipt": 5}
    passages = [e for e in logs if e["event"] == "perception backlog passage"]
    assert [(e["message_id"], e["check"]) for e in passages] == [
        (message.id, "provenance_revision_receipt") for message in messages
    ]
    needed = [e for e in logs if e["event"] == "perception analysis needed"]
    assert (needed[0]["message_id"], needed[0]["check"], needed[0]["cited"]) == (
        messages[0].id,
        "provenance_revision_receipt",
        messages[0].id,
    )
    assert all(perception_results_current(scene, message) for message in messages)


@pytest.mark.asyncio
async def test_gate_keep_accepts_the_stored_views_with_zero_requests(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    stored = texts(messages)
    older_build(messages)
    before = request.await_count
    frames = []
    with capture_logs() as logs, answering("keep", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    assert request.await_count == before
    assert texts(messages) == stored
    assert all(perception_results_current(scene, message) for message in messages)
    assert [
        e["message_id"] for e in logs if e["event"] == "perception backlog passage"
    ] == [message.id for message in messages]


@pytest.mark.asyncio
async def test_gate_cancel_stops_without_a_request_or_a_perception_write(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    older_build(messages)
    knowledge = [message.knowledge for message in messages]
    before = request.await_count
    frames = []
    with answering("cancel", frames), pytest.raises(GenerationCancelled) as caught:
        await knowledge_step(scene)
    assert caught.value.by_user
    assert len(frames) == 1
    assert request.await_count == before
    assert [message.knowledge for message in messages] == knowledge
    # the refresh the question interrupted is still pending
    assert all(revision_requires_refresh(scene, message) for message in messages)
    assert perceptions._perception_backlog_futures == {}


@pytest.mark.asyncio
async def test_backlog_of_three_runs_without_a_question(setup):
    scene, summarizer, request = setup
    messages = await story(scene, count=3)
    older_build(messages)
    before = request.await_count
    frames = []
    with answering(None, frames):
        await knowledge_step(scene)
    assert frames == []
    assert request.await_count - before == 3


@pytest.mark.asyncio
async def test_new_passages_of_a_generation_count_toward_the_question(setup):
    scene, _, request = setup
    frames = []
    with answering("analyze", frames):
        await push_and_step(
            scene,
            [CharacterMessage(message=f"Alice: Line {index}.") for index in range(6)],
        )
    assert [
        (frame["perceptions"]["needed"], frame["perceptions"]["new"])
        for frame in frames
    ] == [(6, 6)]
    assert request.await_count == 6


@pytest.mark.asyncio
async def test_a_generation_counts_its_own_passage_with_the_backlog(setup):
    scene, _, request = setup
    messages = await story(scene, count=3)
    older_build(messages)
    before = request.await_count
    frames = []
    with answering("analyze", frames):
        await push_and_step(scene, CharacterMessage(message="Alice: A new line."))
    assert [
        (f["perceptions"]["needed"], f["perceptions"]["new"], f["perceptions"]["total"])
        for f in frames
    ] == [(4, 1, 4)]
    assert request.await_count - before == 4


@pytest.mark.asyncio
async def test_request_bound_counts_the_repair_attempt(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    older_build(messages)
    summarizer.actions["perceptions"].config["automatic_repair"].value = True
    frames = []
    with answering("cancel", frames), pytest.raises(GenerationCancelled):
        await knowledge_step(scene)
    assert [
        (frame["perceptions"]["total"], frame["perceptions"]["requests"])
        for frame in frames
    ] == [(5, 10)]


@pytest.mark.asyncio
async def test_keep_bound_counts_the_cascade_of_the_empty_passages(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    older_build(messages)
    replace_view(messages[1], "Alice", status="failed", text=None)
    counted = backlog(scene)
    assert [m.id for m in counted.empty] == [messages[1].id]
    assert [m.id for m in counted.empty_at_risk] == [m.id for m in messages[2:]]
    assert counted.keep_total == 4
    before = request.await_count
    frames = []
    with answering("keep", frames):
        await knowledge_step(scene)
    assert [frame["perceptions"]["keep_total"] for frame in frames] == [4]
    assert request.await_count - before <= 4
    assert all(perception_results_current(scene, message) for message in messages)


@pytest.mark.asyncio
async def test_nothing_to_analyze_still_honours_a_cancel(setup):
    scene, summarizer, request = setup
    await story(scene)
    scene.cancel_requested = True
    with pytest.raises(GenerationCancelled) as caught:
        await knowledge_step(scene)
    assert caught.value.by_user
    scene.cancel_requested = False
    with pytest.raises(GenerationCancelled):
        await summarizer.ensure_perceptions(scene, still_current=lambda: False)


@pytest.mark.asyncio
async def test_revision_catch_up_asks_once_and_keep_commits(setup):
    scene, _, request = setup
    messages = await story(scene)
    older_build(messages)
    before = request.await_count
    frames = []
    with answering("keep", frames):
        await catch_up_revisions(scene)
    assert len(frames) == 1
    assert request.await_count == before
    assert all(message.revision_matches_baseline for message in messages)


@pytest.mark.asyncio
async def test_gate_asks_again_when_a_run_grows_past_the_confirmed_count(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    messages = await story(scene, count=8)
    older_build(messages)
    counted = perceptions.perception_backlog
    calls = []

    def under_counted(scene, passages, **kwargs):
        calls.append(passages)
        backlog = counted(scene, passages, **kwargs)
        if len(calls) > 1:
            return backlog
        return perceptions.PerceptionBacklog(
            keepable=backlog.keepable[:4],
            empty=(),
            at_risk=(),
            empty_at_risk=(),
            staleness=backlog.staleness,
        )

    monkeypatch.setattr(perceptions, "perception_backlog", under_counted)
    before = request.await_count
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert [frame["perceptions"]["needed"] for frame in frames] == [4, 4]
    assert request.await_count - before == 8


@pytest.mark.asyncio
async def test_interrupt_ends_the_question_and_closes_the_dialog(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    older_build(messages)
    frames, closed = [], []

    def close(emission):
        closed.append(emission.data)

    handlers["perception_backlog_closed"].connect(close)
    try:
        with answering(None, frames):
            task = asyncio.create_task(knowledge_step(scene))
            while not frames:
                await asyncio.sleep(0.01)
            scene.interrupt()
            with pytest.raises(GenerationCancelled) as caught:
                await task
    finally:
        handlers["perception_backlog_closed"].disconnect(close)
    assert caught.value.by_user
    assert closed == [{"request_id": frames[0]["request_id"]}]
    assert perceptions._perception_backlog_futures == {}


@pytest.mark.asyncio
async def test_websocket_answer_resolves_the_question(setup):
    scene, summarizer, _ = setup
    messages = await story(scene)
    older_build(messages)
    frames = []
    with answering(None, frames):
        task = asyncio.create_task(knowledge_step(scene))
        while not frames:
            await asyncio.sleep(0.01)
        await SummarizeWebsocketHandler.handle_perception_backlog_response(
            None, {"request_id": frames[0]["request_id"], "decision": "keep"}
        )
        await task
    assert all(perception_results_current(scene, message) for message in messages)


class GenerationStarted(Exception):
    pass


def stop_at_the_reply_request(request, monkeypatch, reached):
    """Perception requests answer as usual; the first other request stops the test."""
    analyze = request.side_effect

    async def routed(template, *args, **kwargs):
        if template == "summarizer.perceptions":
            return await analyze(template, *args, **kwargs)
        reached.append(template)
        raise GenerationStarted()

    request.side_effect = routed

    async def build_prompt(*args, **kwargs):
        reached.append("conversation")
        raise GenerationStarted()

    monkeypatch.setattr(get_agent("conversation"), "build_prompt", build_prompt)


def with_actor(scene):
    actor = Actor(scene.character_data["Alice"], get_agent("conversation"))
    actor.scene = scene
    scene.actors.append(actor)
    return actor


@pytest.mark.asyncio
async def test_converse_asks_before_the_reply_request(setup, monkeypatch):
    scene, _, request = setup
    actor = with_actor(scene)
    messages = await story(scene, count=4)
    older_build(messages)
    reached = []
    stop_at_the_reply_request(request, monkeypatch, reached)
    before = request.await_count
    frames = []
    with answering("cancel", frames), pytest.raises(GenerationCancelled):
        await get_agent("conversation").converse(actor)
    assert [
        (f["perceptions"]["needed"], f["perceptions"]["new"], f["perceptions"]["total"])
        for f in frames
    ] == [(4, 0, 4)]
    assert reached == []
    assert request.await_count == before

    frames = []
    with answering("keep", frames), pytest.raises(GenerationStarted):
        await get_agent("conversation").converse(actor)
    assert len(frames) == 1
    assert reached == ["conversation"]
    assert request.await_count == before


@pytest.mark.asyncio
async def test_narrate_query_counts_no_passage(setup, monkeypatch):
    scene, _, request = setup
    messages = await story(scene, count=3)
    older_build(messages)
    reached = []
    stop_at_the_reply_request(request, monkeypatch, reached)
    frames = []
    with answering(None, frames), pytest.raises(GenerationStarted):
        await get_agent("narrator").narrate_query("What is the weather?")
    assert frames == []
    assert reached == ["narrator.narrate-query"]


@pytest.mark.asyncio
async def test_parallel_narrator_calls_ask_once_and_a_cancel_stops_them_all(
    setup, monkeypatch
):
    scene, _, request = setup
    messages = await story(scene)
    older_build(messages)
    reached = []
    stop_at_the_reply_request(request, monkeypatch, reached)
    before = request.await_count
    frames = []
    narrator = get_agent("narrator")
    with answering(None, frames):
        calls = asyncio.gather(
            *(narrator.narrate_query(f"Query {index}") for index in range(3)),
            return_exceptions=True,
        )
        async with asyncio.timeout(5):
            while not frames:
                await asyncio.sleep(0.01)
        resolve_perception_backlog(frames[0]["request_id"], "cancel")
        results = await asyncio.wait_for(calls, 5)
    assert len(frames) == 1
    assert [type(result) for result in results] == [GenerationCancelled] * 3
    assert reached == []
    assert request.await_count == before


@pytest.mark.asyncio
async def test_a_stop_ends_the_approval(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    older_build(messages)
    frames = []
    with answering("analyze", frames):
        await summarizer._approve_perception_backlog(
            scene,
            cancel_sequence=scene.cancel_sequence,
            cancels_at_entry=0,
        )
    assert summarizer._approved(scene) == {message.id for message in messages}
    scene.interrupt()
    scene.cancel_requested = False
    assert summarizer._approved(scene) == set()
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert len(frames) == 2


@pytest.mark.asyncio
async def test_one_answer_covers_the_backlog_of_a_step(setup):
    scene, summarizer, request = setup
    messages = await story(scene)
    older_build(messages)
    before = request.await_count
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    assert request.await_count - before == 5
    assert summarizer._approved(scene) == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["cancel", "stop"])
async def test_regenerate_cancel_asks_once_and_restores_the_tracker_message(
    setup, answer
):
    scene, summarizer, request = setup
    with_actor(scene)
    messages = await story(scene)
    older_build(messages)
    tracker = ReinforcementMessage(message="Alice is tired.", source="tracker")
    scene.history.append(tracker)
    history = list(scene.history)
    before = request.await_count
    frames = []

    def respond(emission):
        frames.append(emission.data)
        if answer == "cancel":
            resolve_perception_backlog(emission.data["request_id"], "cancel")
        else:
            asyncio.get_running_loop().call_soon(scene.interrupt)

    handlers["perception_backlog"].connect(respond)
    try:
        with pytest.raises(GenerationCancelled):
            await regenerate(scene)
    finally:
        handlers["perception_backlog"].disconnect(respond)
        scene.cancel_requested = False
    assert len(frames) == 1
    assert (frames[0]["perceptions"]["needed"], frames[0]["perceptions"]["new"]) == (
        4,
        0,
    )
    assert scene.history == history
    assert request.await_count == before


def record_dispatch(scene):
    dispatched = []

    async def listen(event):
        dispatched.append(event.message.id)

    scene.signals["game_loop_new_message"].connect(listen)
    return dispatched


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line",
    [
        NarratorMessage(message="Rain starts to fall.", source="director"),
        CharacterMessage(message="Alice: Is that rain?", source="player"),
    ],
    ids=["narration", "player"],
)
async def test_a_cancelled_step_leaves_the_pushed_line_to_the_next_step(
    setup, isolate_signals, line
):
    scene, summarizer, request = setup
    isolate_signals("game_loop_new_message")
    messages = await story(scene)
    older_build(messages)
    line = line.model_copy(deep=True)
    dispatched = record_dispatch(scene)
    await scene.push_history(line)
    assert dispatched == [line.id]
    frames = []
    with answering("cancel", frames), pytest.raises(GenerationCancelled):
        await knowledge_step(scene)
    assert len(frames) == 1
    assert frames[0]["perceptions"]["new"] == 1
    assert scene.history[-1] is line

    with answering("keep", frames):
        await knowledge_step(scene)
    assert len(frames) == 2
    assert all(message.revision_matches_baseline for message in messages)
    assert perception_results_current(scene, line)
    assert dispatched == [line.id]


@pytest.mark.asyncio
async def test_keep_in_a_step_leaves_nothing_for_the_next_step(setup):
    scene, _, request = setup
    messages = await story(scene)
    older_build(messages)
    narration = NarratorMessage(message="Rain starts to fall.", source="director")
    frames = []
    with answering("keep", frames):
        await push_and_step(scene, narration)
    assert len(frames) == 1
    assert scene.history[-1] is narration
    assert all(message.revision_matches_baseline for message in messages)
    before = request.await_count
    await knowledge_step(scene)
    assert request.await_count == before
    assert all(perception_results_current(scene, message) for message in scene.history)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["converse", "regenerate", "push"])
@pytest.mark.parametrize("player_analysis", [False, True])
async def test_a_generation_counts_pushed_lines_but_not_its_own_reply(
    setup, monkeypatch, operation, player_analysis
):
    scene, summarizer, request = setup
    scene.character_data["Bob"].is_player = True
    summarizer.actions["perceptions"].config["analyze_player"].value = player_analysis
    actor = with_actor(scene)
    messages = await story(scene, count=3)
    target = CharacterMessage(message="Alice: Hello.")
    if operation == "regenerate":
        await scene.push_history(target)
    older_build(messages)
    reached, frames = [], []
    stop_at_the_reply_request(request, monkeypatch, reached)
    before = request.await_count
    asks = operation == "push" and player_analysis
    with answering("cancel" if asks else None, frames):
        if asks:
            with pytest.raises(GenerationCancelled):
                await push_and_step(scene, target)
        elif operation == "converse":
            with pytest.raises(GenerationStarted):
                await get_agent("conversation").converse(actor)
        elif operation == "regenerate":
            await regenerate(scene)
        else:
            await push_and_step(scene, target)
    if asks:
        assert [
            (
                frame["perceptions"]["needed"],
                frame["perceptions"]["new"],
                frame["perceptions"]["total"],
            )
            for frame in frames
        ] == [(4, 1, 4)]
        assert request.await_count == before
    else:
        assert frames == []
        assert request.await_count == before + 3
        assert reached == ([] if operation == "push" else ["conversation"])


@pytest.mark.asyncio
async def test_one_question_covers_a_revision_and_the_new_lines(setup):
    scene, _, request = setup
    messages = await story(scene, count=2)
    older_build(messages[:1])
    lines = [NarratorMessage(message=f"New line {index}.") for index in range(4)]
    await scene.push_history(lines)
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    assert frames[0]["perceptions"]["new"] == 4
    assert all(perception_results_current(scene, line) for line in lines)
    assert messages[0].revision_matches_baseline


@pytest.mark.asyncio
async def test_new_lines_an_answer_approved_are_not_counted_again(setup):
    from talemate.knowledge.backlog import counting_new_lines

    scene, summarizer, request = setup
    messages = await story(scene, count=2)
    older_build(messages)
    lines = [NarratorMessage(message=f"New line {index}.") for index in range(4)]
    await scene.push_history(lines)
    new_lines = {line.id: summarizer.perception_requests(scene, line) for line in lines}
    frames = []
    with (
        summarizer.backlog_approvals(scene),
        counting_new_lines(scene, new_lines),
        answering("analyze", frames),
    ):
        # one check for each refresh of the step
        for _ in messages:
            await summarizer._approve_perception_backlog(
                scene,
                cancel_sequence=scene.cancel_sequence,
                cancels_at_entry=0,
            )
    assert [
        (frame["perceptions"]["needed"], frame["perceptions"]["new"])
        for frame in frames
    ] == [(6, 4)]


async def built_summaries(scene, summarizer, monkeypatch, passages):
    """One built summary entry per passage in `passages`; returns the summary calls."""
    from talemate.history import ArchiveEntry

    scene.archived_history = [
        ArchiveEntry(
            id=f"entry-{index}",
            text="READER",
            start=scene.history.index(message),
            end=scene.history.index(message),
        ).model_dump(exclude_none=True)
        for index, message in enumerate(passages)
    ]
    calls = []

    async def summarize(text, **kwargs):
        calls.append(kwargs.get("audience"))
        return "Summary."

    summarizer.connect(scene)

    monkeypatch.setattr(summarizer, "summarize", summarize)
    for entry in scene.archived_history:
        await summarizer.ensure_summary_views(scene, entry["id"])
    return calls


def summaries_ready(scene):
    return all(
        select_character_view(
            scene, source_reference(scene, "summary", entry["id"]), name
        ).status
        in ("ready", "omitted")
        for entry in scene.archived_history
        for name in ("Alice", "Bob")
    )


@pytest.mark.asyncio
async def test_one_question_covers_perceptions_and_the_summaries_they_change(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    messages = await story(scene)
    await built_summaries(scene, summarizer, monkeypatch, messages)
    assert summaries_ready(scene)
    older_build(messages)
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    assert frames[0]["perceptions"]["needed"] == 5
    summaries = frames[0]["summaries"]
    assert (summaries["rebuild"]["entries"], summaries["rebuild"]["layers"]) == (5, [0])
    # Keep keeps the perspectives, so nothing invalidates the summaries
    assert (summaries["keep"]["keepable"], summaries["keep"]["keep_total"]) == (0, 0)
    assert summaries_ready(scene)
    assert not summarizer._summary_dirty[scene]


@pytest.mark.asyncio
async def test_keep_in_the_combined_question_keeps_perceptions_and_summaries(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    messages = await story(scene)
    calls = await built_summaries(scene, summarizer, monkeypatch, messages)
    older_build(messages)
    before, built = request.await_count, len(calls)
    frames = []
    with answering("keep", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    assert frames[0]["summaries"]["keep"]["keep_requests"] == 0
    assert request.await_count == before
    assert len(calls) == built
    assert summaries_ready(scene)


@pytest.mark.asyncio
async def test_a_large_summary_backlog_asks_with_a_small_perception_backlog(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    messages = await story(scene)
    await built_summaries(scene, summarizer, monkeypatch, [messages[-1]] * 4)
    older_build(messages[-1:])
    frames = []
    with answering("analyze", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    assert frames[0]["perceptions"]["needed"] == 1
    assert frames[0]["summaries"]["rebuild"]["entries"] == 4
    assert summaries_ready(scene)


def lacking_carol(messages):
    """Record Carol as present, so each passage lacks her perspective."""
    for message in messages:
        object.__setattr__(message, "present", [*message.present, "Carol"])


@pytest.mark.asyncio
async def test_the_first_check_of_a_step_approves_every_pending_analysis(
    setup, monkeypatch
):
    # two checks of one step: the second finds everything approved
    scene, summarizer, request = setup
    messages = await story(scene, count=6)
    await built_summaries(scene, summarizer, monkeypatch, messages[2:])
    lacking_carol(messages)
    frames = []
    with summarizer.backlog_approvals(scene), answering("analyze", frames):
        for _ in range(2):
            await summarizer._approve_perception_backlog(
                scene, cancel_sequence=scene.cancel_sequence, cancels_at_entry=0
            )
    assert len(frames) == 1
    assert frames[0]["perceptions"]["needed"] == 6
    assert frames[0]["summaries"]["rebuild"]["entries"] == 4


@pytest.mark.asyncio
async def test_keep_rebuilds_a_queued_summary_over_a_passage_that_is_analyzed(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    messages = await story(scene)
    target = messages[-1]
    calls = await built_summaries(scene, summarizer, monkeypatch, [target] * 4)
    # the stored summaries survive, but are out of date and queued
    object.__setattr__(
        target,
        "knowledge",
        target.knowledge.model_copy(update={"revision": target.knowledge.revision + 1}),
    )
    for entry in scene.archived_history:
        await summarizer.queue_summary_views(scene, entry["id"])
    lacking_carol([target])
    built = len(calls)
    frames = []
    with answering("keep", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    keep = frames[0]["summaries"]["keep"]
    assert (keep["keepable"], keep["keep_total"]) == (0, 4)
    assert len(calls) > built
    assert summaries_ready(scene)


@pytest.mark.asyncio
async def test_keep_rebuilds_a_queued_layer_over_an_entry_that_is_rebuilt(
    setup, monkeypatch
):
    from talemate.history import LayeredArchiveEntry

    scene, summarizer, request = setup
    messages = await story(scene)
    target = messages[-1]
    calls = await built_summaries(scene, summarizer, monkeypatch, [target] * 4)
    monkeypatch.setattr(summarizer, "summarize_events", summarizer.summarize)
    scene.layered_history = [
        [
            LayeredArchiveEntry(
                id="parent", text="READER-LAYER", start=0, end=3, ts_start=0, ts_end=0
            ).model_dump(exclude_none=True)
        ]
    ]
    await summarizer.ensure_summary_views(scene, "parent", 1)
    # the passage and the base entries change without an invalidation, so
    # every stored summary survives, out of date and queued
    object.__setattr__(
        target,
        "knowledge",
        target.knowledge.model_copy(update={"revision": target.knowledge.revision + 1}),
    )
    for entry in scene.archived_history:
        entry["knowledge"]["revision"] += 1
        await summarizer.queue_summary_views(scene, entry["id"])
    await summarizer.queue_summary_views(scene, "parent", 1)
    lacking_carol([target])
    built = len(calls)
    frames = []
    with answering("keep", frames):
        await knowledge_step(scene)
    assert len(frames) == 1
    keep = frames[0]["summaries"]["keep"]
    assert (keep["keepable"], keep["keep_total"]) == (0, 5)
    assert len(calls) > built + 4
    assert summaries_ready(scene)
    parent = source_reference(scene, "summary", "parent", layer=1)
    assert all(
        select_character_view(scene, parent, name).status == "ready"
        for name in ("Alice", "Bob")
    )
