import asyncio
import json
from pathlib import Path
from talemate.regenerate import regenerate
from talemate.tale_mate import Actor
from talemate.server.scene_message import SceneMessagePlugin
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from talemate.agents.summarize.perceptions import parse_perceptions, perception_context
from talemate.character import Character
from talemate.client.base import _generation_error_futures, resolve_generation_error
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.perspectives import (
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.scene_message import CharacterMessage, DirectorMessage, NarratorMessage


CASES = json.loads(
    (Path(__file__).parent / "data/perceptions/passages.json").read_text()
)


def answer(alice="Alice says hello.", bob="Bob hears Alice say hello."):
    return json.dumps(
        {
            "views": [
                {
                    "audience": [name],
                    "knowledge_ids": [],
                    "passage_ids": [],
                    "status": "ready" if text else "omitted",
                    "text": text,
                }
                for name, text in (("Alice", alice), ("Bob", bob))
            ]
        }
    )


def result(text=None):
    text = answer() if text is None else text
    try:
        data = json.loads(text)
        for view in data.get("views", []):
            view.setdefault("knowledge_ids", [])
            view.setdefault("passage_ids", [])
        text = json.dumps(data)
    except (ValueError, AttributeError):
        pass
    return text, {"response": text}


@pytest.fixture
def setup(scene, monkeypatch):
    monkeypatch.setenv("TALEMATE_DEV_CHARACTER_KNOWLEDGE", "1")
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")
    request = AsyncMock(return_value=result())
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    with ActiveScene(scene):
        yield scene, summarizer, request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,source",
    [
        (CharacterMessage, "ai"),
        (CharacterMessage, "player"),
        (NarratorMessage, "narrate_scene"),
    ],
)
async def test_finalized_source_kinds_and_no_duplicate_processing(setup, kind, source):
    scene, summarizer, request = setup
    message = kind(message="Alice: Hello.", source=source)
    before = message.message
    active = scene.active_characters.copy()
    await scene.push_history(message)
    acquired = message.knowledge.acquired
    views = message.knowledge.views
    await summarizer.finalize_perceptions(scene, [message])
    await summarizer.ensure_perceptions(scene)
    assert request.await_count == 1
    assert scene.history == [message]
    assert message.message == before
    assert scene.active_characters == active
    assert message.knowledge.acquired == acquired
    assert message.knowledge.views == views
    assert (
        select_character_view(
            scene, source_reference(scene, "message", message.id), "Bob"
        ).text
        == "Bob hears Alice say hello."
    )


@pytest.mark.asyncio
async def test_editor_finalization_precedes_analysis_and_archive(setup):
    scene, summarizer, request = setup
    summarizer.actions["archive"].enabled = False
    order = []

    async def edit(event):
        order.append("edit")
        event.messages[0].message = "Alice: Polished."

    async def analyze(*args, **kwargs):
        order.append("perception")
        assert kwargs["vars"]["context"]["passage"]["text"] == "Alice: Polished."
        return result()

    async def after(event):
        order.append("after")
        assert event.messages[0].knowledge.views[0].status == "ready"

    scene.signals["push_history"].connect(edit)
    scene.signals["push_history.after"].connect(after)
    request.side_effect = analyze
    await scene.push_history(CharacterMessage(message="Alice: Draft."))
    assert order == ["edit", "perception", "after"]


@pytest.mark.asyncio
@pytest.mark.parametrize("gate,mode", [("0", "perception"), ("1", "legacy")])
async def test_no_new_requests_outside_mode(setup, monkeypatch, gate, mode):
    scene, summarizer, request = setup
    monkeypatch.setenv("TALEMATE_DEV_CHARACTER_KNOWLEDGE", gate)
    scene.knowledge_eligibility = mode
    message = CharacterMessage(message="Alice: Hello.")
    await scene.push_history(message)
    await summarizer.ensure_perceptions(scene)
    request.assert_not_awaited()
    assert message.knowledge is None


@pytest.mark.asyncio
async def test_no_historical_or_director_backfill(setup):
    scene, summarizer, request = setup
    old = CharacterMessage(message="Alice: Old untracked history.")
    scene.history.append(old)
    await scene.push_history(
        DirectorMessage(message="Alice should speak next.", source="Alice")
    )
    await summarizer.ensure_perceptions(scene)
    request.assert_not_awaited()
    assert old.knowledge is None


@pytest.mark.asyncio
async def test_concurrent_waiters_share_source_analysis(setup):
    scene, summarizer, request = setup
    started, release = asyncio.Event(), asyncio.Event()

    async def analyze(*args, **kwargs):
        started.set()
        await release.wait()
        return result()

    request.side_effect = analyze
    message = CharacterMessage(message="Alice: Hello.")
    task = asyncio.create_task(scene.push_history(message))
    await started.wait()
    waiting = asyncio.create_task(summarizer.ensure_perceptions(scene))
    await asyncio.sleep(0)
    assert not waiting.done()
    release.set()
    await asyncio.gather(task, waiting)
    assert request.await_count == 1
    assert len(scene.history) == 1


@pytest.mark.asyncio
async def test_batch_analysis_is_ordered_and_every_passage_registered(setup):
    scene, summarizer, request = setup
    messages = [
        CharacterMessage(message="Alice: First."),
        NarratorMessage(message="Then a bell rings."),
    ]
    await scene.push_history(messages)
    assert request.await_count == 2
    context = request.await_args_list[1].kwargs["vars"]["context"]
    assert (
        context["cast"][1]["established_knowledge"][0]["text"]
        == "Bob hears Alice say hello."
    )
    assert [message.knowledge.acquired.order for message in messages] == [1, 2]


@pytest.mark.parametrize(
    "payload",
    [
        "not JSON",
        "{}",
        '{"views": []}',
        '{"views": [{"audience": ["Alice"], "status": "ready", "text": ""}]}',
        '{"views": [{"audience": ["Alice", "Bob"], "status": "ready", "text": "Shared"}]}',
        answer().replace('"Bob"', '"Alice"'),
        answer().replace('"Bob"', '"Carol"'),
        answer().replace('"ready"', '"pending"'),
        answer().replace('"views":', '"activation": [], "views":'),
        answer().replace('"status":', '"id": "invented", "status":'),
    ],
)
def test_reject_invalid_analysis(payload):
    with pytest.raises(ValueError):
        parse_perceptions(payload, ("Alice", "Bob"))


def test_accept_complete_views_and_explicit_omission():
    views = parse_perceptions(
        "```json\n" + answer(bob=None) + "\n```", ("Alice", "Bob")
    )
    assert views[0].text == "Alice says hello."
    assert views[1].status == "omitted"
    assert views[1].text is None


async def wait_for_dialog():
    async with asyncio.timeout(3):
        while not _generation_error_futures:
            await asyncio.sleep(0.01)
    return next(iter(_generation_error_futures))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [ValueError("transport failed"), result("malformed")]
)
async def test_visible_retry_blocks_then_resumes_without_duplicate(setup, failure):
    scene, summarizer, request = setup
    request.side_effect = [failure, result()]
    message = CharacterMessage(message="Alice: Hello.")
    downstream = AsyncMock()
    scene.signals["push_history.after"].connect(downstream)
    task = asyncio.create_task(scene.push_history(message))
    try:
        rid = await wait_for_dialog()
        assert not task.done()
        assert {view.status for view in message.knowledge.views} == {"failed"}
        downstream.assert_not_awaited()
        acquisition = message.knowledge.acquired
        identities = [view.id for view in message.knowledge.views]
        resolve_generation_error(rid, "retry")
        await asyncio.wait_for(task, 3)
        downstream.assert_awaited_once()
        assert request.await_count == 2
        assert scene.history == [message]
        assert message.knowledge.acquired == acquisition
        assert [view.id for view in message.knowledge.views] == identities
        assert {view.status for view in message.knowledge.views} == {"ready"}
    finally:
        task.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "ignore"])
async def test_dialog_cannot_bypass_failed_analysis(setup, action):
    scene, summarizer, request = setup
    request.return_value = result("malformed")
    message = CharacterMessage(message="Alice: Hello.")
    task = asyncio.create_task(scene.push_history(message))
    try:
        rid = await wait_for_dialog()
        resolve_generation_error(rid, action)
        with pytest.raises(GenerationCancelled):
            await asyncio.wait_for(task, 3)
        assert scene.history == [message]
        assert {view.status for view in message.knowledge.views} == {"failed"}
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_edit_discards_inflight_response_and_analyzes_latest_revision(setup):
    scene, summarizer, request = setup
    started, release = asyncio.Event(), asyncio.Event()

    async def analyze(*args, **kwargs):
        if request.await_count == 1:
            started.set()
            await release.wait()
            return result(answer("Stale private thought.", "Stale public speech."))
        assert kwargs["vars"]["context"]["passage"]["text"] == "Alice: Revised."
        return result(answer("Alice says revised.", "Bob hears revised."))

    request.side_effect = analyze
    message = CharacterMessage(message="Alice: Original.")
    task = asyncio.create_task(scene.push_history(message))
    await started.wait()
    acquired = message.knowledge.acquired
    revision = message.knowledge.revision
    scene.edit_message(message.id, "Alice: Revised.")
    release.set()
    await asyncio.wait_for(task, 3)
    assert request.await_count == 2
    assert message.knowledge.revision == revision + 1
    assert message.knowledge.acquired == acquired
    assert message.knowledge.views[1].text == "Bob hears revised."


@pytest.mark.asyncio
async def test_deleted_source_discards_inflight_result(setup):
    scene, summarizer, request = setup
    started, release = asyncio.Event(), asyncio.Event()

    async def analyze(*args, **kwargs):
        started.set()
        await release.wait()
        return result()

    request.side_effect = analyze
    message = CharacterMessage(message="Alice: Hello.")
    task = asyncio.create_task(scene.push_history(message))
    await started.wait()
    scene.delete_message(message.id)
    release.set()
    with pytest.raises(GenerationCancelled, match="removed or reset"):
        await asyncio.wait_for(task, 3)
    assert request.await_count == 1
    assert scene.history == []


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", ["conversation", "narrator"])
async def test_failed_perceptions_block_actor_generation(
    setup, monkeypatch, agent_name
):
    scene, summarizer, request = setup
    message = CharacterMessage(message="Alice: Hello.")
    scene.history.append(message)
    set_source_perspectives(
        scene, "message", message.id, [{"audience": ["Alice"], "status": "failed"}]
    )
    request.side_effect = GenerationCancelled("cancelled")
    agent = get_agent(agent_name)
    send = AsyncMock()
    monkeypatch.setattr(agent.client, "send_prompt", send)
    with pytest.raises(GenerationCancelled):
        if agent_name == "conversation":
            await agent.converse(
                SimpleNamespace(character=scene.character_data["Alice"])
            )
        else:
            await agent.narrate_scene()
    send.assert_not_awaited()


def test_prompt_context_separates_reader_from_prior_knowledge(setup):
    scene, summarizer, request = setup
    previous = CharacterMessage(message="Alice: Secret thought. Public hello.")
    message = NarratorMessage(message="A bell rings.")
    scene.history.extend([previous, message])
    set_source_perspectives(
        scene,
        "message",
        previous.id,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Secret thought. Public hello.",
            },
            {"audience": ["Bob"], "status": "ready", "text": "Public hello."},
        ],
    )
    context = perception_context(scene, message)
    assert "Secret thought" in context["prior_physical_context"][0]["text"]
    assert context["cast"][1]["established_knowledge"][0]["text"] == "Public hello."


def test_new_mode_replaces_legacy_ledger(setup):
    scene, summarizer, request = setup
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].config["ledger"].value = True
    assert conversation.knowledge_ledger is False
    scene.knowledge_eligibility = "legacy"
    assert conversation.knowledge_ledger is True


@pytest.mark.asyncio
async def test_cancelled_passage_is_emitted_without_releasing_dependents(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    emitted = []
    monkeypatch.setattr(
        "talemate.tale_mate.emit",
        lambda *args, **kwargs: emitted.append((args, kwargs)),
    )
    request.side_effect = GenerationCancelled("cancelled")
    after = AsyncMock()
    scene.signals["push_history.after"].connect(after)
    message = CharacterMessage(message="Alice: Preserved reader prose.")
    with pytest.raises(GenerationCancelled):
        await scene.push_history(message)
    assert any(
        args[0] == "character" and kwargs["message"] is message
        for args, kwargs in emitted
    )
    assert message.message == "Alice: Preserved reader prose."
    after.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed"])
async def test_saved_incomplete_source_resumes_without_backfill(setup, status):
    scene, summarizer, request = setup
    old = CharacterMessage(message="Alice: Old untracked prose.")
    message = CharacterMessage(message="Alice: Hello.")
    scene.history.extend([old, message])
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [{"audience": [name], "status": status} for name in scene.character_data],
    )
    saved = message.model_dump()
    scene.history[1] = CharacterMessage.model_validate(saved)
    await summarizer.ensure_perceptions(scene)
    assert old.knowledge is None
    assert request.await_count == 1
    assert scene.history[1].knowledge.acquired == message.knowledge.acquired


@pytest.mark.asyncio
async def test_edit_while_retry_dialog_is_open_uses_latest_source(setup):
    scene, summarizer, request = setup
    request.side_effect = [result("malformed"), result(answer("Revised.", "Revised."))]
    message = CharacterMessage(message="Alice: Original.")
    task = asyncio.create_task(scene.push_history(message))
    try:
        rid = await wait_for_dialog()
        scene.edit_message(message.id, "Alice: Revised.")
        resolve_generation_error(rid, "retry")
        await asyncio.wait_for(task, 3)
        assert (
            request.await_args.kwargs["vars"]["context"]["passage"]["text"]
            == "Alice: Revised."
        )
        assert message.knowledge.revision == 2
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_regeneration_analyzes_only_final_version_in_original_slot(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    scene.actors.append(Actor(scene.character_data["Alice"], get_agent("conversation")))
    message = CharacterMessage(message="Alice: Original.")
    await scene.push_history(message)
    identity = (message.id, message.knowledge.acquired)
    monkeypatch.setattr(
        "talemate.regenerate._regenerate_inplace",
        AsyncMock(
            return_value=[
                ("Alice: Raw.", "regenerate"),
                ("Alice: Polished.", "revision"),
            ]
        ),
    )
    await regenerate(scene)
    assert len(scene.history) == 1
    assert (message.id, message.knowledge.acquired) == identity
    assert request.await_count == 2
    assert (
        request.await_args.kwargs["vars"]["context"]["passage"]["text"]
        == "Alice: Polished."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
async def test_analytical_fixtures_persist_supported_views(setup, case):
    scene, summarizer, request = setup
    scene.character_data = {
        name: Character(name=name, description=description)
        for name, description in case["cast"].items()
    }
    scene.active_characters = ["Alice"]
    scene.history.append(NarratorMessage(message=case["prior"]))
    cls = CharacterMessage if case["kind"] == "character" else NarratorMessage
    message = cls(
        message=case["passage"], present=case["present"], source=case["source"]
    )
    request.return_value = result(
        json.dumps({"views": [v for v in case["views"] if v["audience"][0] != "Dan"]})
    )
    await scene.push_history(message)
    reference = source_reference(scene, "message", message.id)
    for expected in case["views"]:
        if expected["audience"] == ["Dan"]:
            continue
        view = select_character_view(scene, reference, expected["audience"][0])
        assert view.status == expected["status"]
        assert view.text == expected["text"]
    assert scene.active_characters == ["Alice"]
    assert message.message == case["passage"]
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_shared_prompt_renders_without_additional_requests(scene, monkeypatch):
    monkeypatch.setenv("TALEMATE_DEV_CHARACTER_KNOWLEDGE", "1")
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    client = get_agent("summarizer").client
    send = AsyncMock(return_value=answer(bob=None))
    monkeypatch.setattr(client, "send_prompt", send)
    with ActiveScene(scene):
        await scene.push_history(
            CharacterMessage(message="Alice: *A private thought.*")
        )
    send.assert_awaited_once()
    prompt = str(send.await_args.args[0])
    assert "Do not continue the story" in prompt
    assert "no authority to activate or deactivate" in prompt
    assert "Alice: *A private thought.*" in prompt
    assert scene.history[0].knowledge.views[1].status == "omitted"


@pytest.mark.asyncio
async def test_prior_view_invalidation_rebuilds_only_affected_sibling(setup):
    scene, summarizer, request = setup
    first = CharacterMessage(message="Alice: First.")
    second = CharacterMessage(message="Alice: Second.")
    await scene.push_history(first)
    used = json.loads(answer())
    used["views"][0]["knowledge_ids"] = ["K0-0"]
    used["views"][1]["knowledge_ids"] = ["K1-0"]
    request.return_value = result(json.dumps(used))
    await scene.push_history(second)
    bob = second.knowledge.views[1]
    assert bob.sources[0].view_id == first.knowledge.views[1].id
    set_source_perspectives(
        scene,
        "message",
        first.id,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice's revised understanding.",
            },
            first.knowledge.views[1].model_dump(exclude={"revision"}),
        ],
    )
    assert second.knowledge.views[0].status == "pending"
    assert second.knowledge.views[1] == bob
    request.return_value = result(
        answer("Alice's rebuilt view.", "Discard this unrelated rewrite.")
    )
    await summarizer.ensure_perceptions(scene)
    assert request.await_count == 3
    assert (
        next(view for view in second.knowledge.views if view.audience == ("Bob",))
        == bob
    )
    assert (
        next(
            view for view in second.knowledge.views if view.audience == ("Alice",)
        ).text
        == "Alice's rebuilt view."
    )


@pytest.mark.asyncio
async def test_reset_discards_inflight_result_without_recreating_records(setup):
    scene, summarizer, request = setup
    started, release = asyncio.Event(), asyncio.Event()

    async def analyze(*args, **kwargs):
        started.set()
        await release.wait()
        return result()

    request.side_effect = analyze
    message = NarratorMessage(message="The bell rings.")
    task = asyncio.create_task(scene.push_history(message))
    await started.wait()
    scene.reset()
    release.set()
    with pytest.raises(GenerationCancelled, match="removed or reset"):
        await asyncio.wait_for(task, 3)
    assert scene.history == []
    assert message.knowledge.views[0].status == "pending"
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_websocket_edit_schedules_rebuild_and_save(setup, monkeypatch):
    scene, summarizer, request = setup
    message = NarratorMessage(message="The bell rings.")
    await scene.push_history(message)
    saved = AsyncMock()
    monkeypatch.setattr(scene, "attempt_auto_save", saved)
    handler = SimpleNamespace(scene=scene, queue_put=lambda data: None)
    plugin = SceneMessagePlugin(handler)
    await plugin.handle_edit({"id": message.id, "text": "The bell stops."})
    await asyncio.sleep(0)
    await summarizer.ensure_perceptions(scene)
    assert request.await_count == 2
    assert message.knowledge.revision == 2
    assert all(view.status == "ready" for view in message.knowledge.views)
    assert saved.await_count >= 1


@pytest.mark.parametrize(
    "wrap",
    [
        lambda value: value,
        lambda value: "Here is the analysis:\n```json\n" + value + "\n```",
        lambda value: "```JSON\n" + value + "\n```\nDone.",
        lambda value: "```json\n" + value,
        lambda value: "```\n" + value + "\n```",
    ],
)
def test_project_code_block_extraction(wrap):
    assert len(parse_perceptions(wrap(answer()), ("Alice", "Bob"))) == 2


@pytest.mark.asyncio
async def test_long_history_edit_reanalyzes_only_its_own_passage(setup):
    scene, summarizer, request = setup
    messages = [
        CharacterMessage(message=f"Alice: Independent weather report {i}.")
        for i in range(200)
    ]
    await scene.push_history(messages)
    assert request.await_count == 200
    assert all(
        not view.sources for message in messages for view in message.knowledge.views
    )
    untouched = messages[-1].knowledge
    scene.edit_message(messages[2].id, "Alice: Corrected weather report.")
    assert (
        sum(summarizer._perception_needed(scene, message) for message in messages) == 1
    )
    await summarizer.ensure_perceptions(scene)
    assert request.await_count == 201
    assert messages[-1].knowledge == untouched


def test_dense_saved_dependency_graph_has_linear_freshness_walk(setup, monkeypatch):
    import talemate.knowledge.perspectives as perspectives
    from talemate.knowledge.perspective_models import (
        Acquisition,
        PerspectiveView,
        SourcePerspectives,
        SceneKnowledge,
        content_digest,
    )

    scene, _, _ = setup
    references = []
    for index in range(perspectives.MAX_DEPENDENCY_DEPTH + 1):
        message = CharacterMessage(message=f"Alice: {index}.")
        message.knowledge = SourcePerspectives(
            content_digest=content_digest(message.message),
            acquired=Acquisition(order=index + 1, ts=0),
            views=(
                PerspectiveView(
                    id=f"view-{index}",
                    audience=("Alice",),
                    status="ready",
                    text=str(index),
                    sources=tuple(references[-12:]),
                ),
            ),
        )
        scene.history.append(message)
        scene.knowledge = SceneKnowledge(last_order=index + 1)
        reference = source_reference(scene, "message", message.id)
        references.append(select_character_view(scene, reference, "Alice").source)
    original = perspectives._find
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(perspectives, "_find", counted)
    assert select_character_view(scene, references[-1], "Alice").status == "ready"
    assert calls <= perspectives.MAX_DEPENDENCY_DEPTH + 2


@pytest.mark.asyncio
async def test_omission_tracks_unperceived_physical_passage(setup):
    scene, summarizer, request = setup
    prior = NarratorMessage(message="Bob lies unconscious on the floor.")
    scene.history.append(prior)
    message = CharacterMessage(message="Alice: The password is swordfish.")
    output = json.loads(answer(bob=None))
    output["views"][1]["passage_ids"] = [prior.id]
    request.return_value = result(json.dumps(output))
    await scene.push_history(message)
    alice = message.knowledge.views[0]
    assert [
        item.message_id for item in message.knowledge.views[1].passage_provenance
    ] == [message.id, prior.id]
    scene.edit_message(prior.id, "Bob sits awake, watching the room.")
    assert message.knowledge.views[0] == alice
    assert message.knowledge.views[1].status == "pending"
    request.return_value = result(answer(bob="Bob hears the password swordfish."))
    await summarizer.ensure_perceptions(scene)
    assert (
        select_character_view(
            scene, source_reference(scene, "message", message.id), "Bob"
        ).text
        == "Bob hears the password swordfish."
    )
    assert prior.knowledge is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["retry", "cancel", "ignore"])
async def test_dispatcher_remains_free_to_answer_edit_retry(setup, monkeypatch, action):
    scene, summarizer, request = setup
    message = NarratorMessage(message="The bell rings.")
    await scene.push_history(message)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    request.side_effect = [result("malformed"), result()]
    plugin = SceneMessagePlugin(
        SimpleNamespace(scene=scene, queue_put=lambda data: None)
    )
    received = asyncio.Queue()

    async def receive_loop():
        while True:
            frame = await received.get()
            if frame["type"] == "scene_message":
                await plugin.handle(frame)
            else:
                resolve_generation_error(frame["request_id"], frame["action"])
                return

    loop = asyncio.create_task(receive_loop())
    await received.put(
        {
            "type": "scene_message",
            "action": "edit",
            "id": message.id,
            "text": "The bell stops.",
        }
    )
    try:
        rid = await wait_for_dialog()
        assert message.knowledge.views[0].status == "failed"
        await received.put(
            {"type": "generation_error_response", "request_id": rid, "action": action}
        )
        await asyncio.wait_for(loop, 3)
        async with asyncio.timeout(3):
            while rid in _generation_error_futures:
                await asyncio.sleep(0.01)
        if action == "retry":
            await summarizer.ensure_perceptions(scene)
            assert message.knowledge.views[0].status == "ready"
        else:
            assert message.knowledge.views[0].status == "failed"
    finally:
        loop.cancel()


@pytest.mark.asyncio
async def test_cancelled_regeneration_restores_reinforcement_tail(setup, monkeypatch):
    from talemate.scene_message import ReinforcementMessage

    scene, _, request = setup
    scene.actors.append(Actor(scene.character_data["Alice"], get_agent("conversation")))
    message = CharacterMessage(message="Alice: Original.")
    await scene.push_history(message)
    tail = [
        ReinforcementMessage(message="First state.", source="a"),
        ReinforcementMessage(message="Second state.", source="b"),
    ]
    scene.history.extend(tail)
    monkeypatch.setattr(
        "talemate.regenerate._regenerate_inplace",
        AsyncMock(return_value=[("Alice: Revised.", "regenerate")]),
    )
    request.side_effect = GenerationCancelled("Cancelled analysis")
    with pytest.raises(GenerationCancelled):
        await regenerate(scene)
    assert scene.history == [message, *tail]
    assert message.message == "Alice: Revised."


@pytest.mark.asyncio
async def test_relevant_cast_and_scaled_answer_budget(setup):
    from talemate.client.presets import max_tokens_for_kind

    scene, _, request = setup
    scene.character_data.update(
        {f"Person{i}": Character(name=f"Person{i}") for i in range(40)}
    )
    scene.active_characters = ["Alice", *(f"Person{i}" for i in range(10))]
    message = NarratorMessage(message="A long passage. " * 200, present=["Bob"])
    names = ["Alice", "Bob", *(f"Person{i}" for i in range(10))]
    request.return_value = result(
        json.dumps(
            {
                "views": [
                    {
                        "audience": [name],
                        "status": "ready",
                        "text": "The passage.",
                        "knowledge_ids": [],
                        "passage_ids": [],
                    }
                    for name in names
                ]
            }
        )
    )
    await scene.push_history(message)
    context = request.await_args.kwargs["vars"]["context"]
    assert {character["name"] for character in context["cast"]} == set(names)
    assert max_tokens_for_kind(request.await_args.args[2], 32768) > 2048
    assert len(message.knowledge.views) == 12


@pytest.mark.asyncio
async def test_empty_cast_defers_without_permanent_empty_record(setup):
    scene, summarizer, request = setup
    scene.active_characters = []
    message = NarratorMessage(message="The room is quiet.")
    await scene.push_history(message)
    assert message.knowledge is None
    request.assert_not_awaited()
    scene.active_characters = ["Alice", "Bob"]
    await summarizer.ensure_perceptions(scene)
    assert message.knowledge.views
    request.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_stops_existing_dependent_waiters(setup):
    scene, summarizer, request = setup
    request.return_value = result("malformed")
    producer = asyncio.create_task(
        scene.push_history(CharacterMessage(message="Alice: Hello."))
    )
    rid = await wait_for_dialog()
    dependent = asyncio.create_task(summarizer.ensure_perceptions(scene))
    await asyncio.sleep(0)
    resolve_generation_error(rid, "cancel")
    outcomes = await asyncio.wait_for(
        asyncio.gather(producer, dependent, return_exceptions=True), 3
    )
    assert all(isinstance(outcome, GenerationCancelled) for outcome in outcomes)
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_provenance_survives_save_and_detects_unbound_physical_edit(setup):
    from talemate.knowledge.perspectives import bind_perspective_sources

    scene, summarizer, request = setup
    prior = NarratorMessage(message="Bob is asleep.")
    scene.history.append(prior)
    message = CharacterMessage(message="Alice: Hello.")
    payload = json.loads(answer(bob=None))
    payload["views"][1]["passage_ids"] = [prior.id]
    request.return_value = result(json.dumps(payload))
    await scene.push_history(message)
    saved = [entry.model_dump() for entry in scene.history]
    scene.history = [
        NarratorMessage.model_validate(saved[0]),
        CharacterMessage.model_validate(saved[1]),
    ]
    assert scene.history[1].model_dump() == saved[1]
    object.__setattr__(scene.history[0], "message", "Bob is awake.")
    view = select_character_view(
        scene, source_reference(scene, "message", message.id), "Bob"
    )
    assert view.status == "pending"
    assert view.text is None
    bind_perspective_sources(scene)


@pytest.mark.asyncio
async def test_reject_unoffered_analytical_input_ids(setup):
    from talemate.agents.summarize.perceptions import resolve_perception_inputs

    scene, _, _ = setup
    message = CharacterMessage(message="Alice: Hello.")
    scene.history.append(message)
    payload = json.loads(answer())
    payload["views"][0]["knowledge_ids"] = ["K1-999"]
    with pytest.raises(ValueError, match="not offered"):
        resolve_perception_inputs(
            parse_perceptions(json.dumps(payload), ("Alice", "Bob")),
            perception_context(scene, message),
        )


@pytest.mark.parametrize("text", ["A ```print(1)``` sign.", "A stray ``` marker."])
@pytest.mark.parametrize(
    "wrapper", ["{}", "```json\n{}\n```", "Analysis:\n```JSON\n{}\n```\nDone."]
)
def test_literal_fences_inside_perception_prose(text, wrapper):
    parsed = parse_perceptions(wrapper.format(answer(alice=text)), ("Alice", "Bob"))
    assert parsed[0].text == text


@pytest.mark.asyncio
async def test_cited_history_has_bounded_rebuild_and_one_index_per_scan(
    setup, monkeypatch
):
    import talemate.knowledge.perspectives as perspectives
    from talemate.agents.summarize.perceptions import CONTEXT_PASSAGES

    scene, summarizer, request = setup

    async def cite_previous(*args, **kwargs):
        views = []
        for character in kwargs["vars"]["context"]["cast"]:
            known = character["established_knowledge"]
            views.append(
                {
                    "audience": [character["name"]],
                    "status": "ready",
                    "text": "An observation.",
                    "knowledge_ids": [known[-1]["id"]] if known else [],
                    "passage_ids": [],
                }
            )
        return result(json.dumps({"views": views}))

    request.side_effect = cite_previous
    messages = [CharacterMessage(message=f"Alice: Report {i}.") for i in range(200)]
    await scene.push_history(messages)
    assert request.await_count == 200
    assert sum(bool(message.knowledge.views[0].sources) for message in messages) > 150
    original_sources = perspectives._sources
    scans = 0

    def counted(scene):
        nonlocal scans
        scans += 1
        yield from original_sources(scene)

    monkeypatch.setattr(perspectives, "_sources", counted)
    await summarizer.ensure_perceptions(scene)
    assert scans == 1
    assert request.await_count == 200
    untouched = messages[-1].knowledge
    scene.edit_message(messages[2].id, "Alice: Corrected report.")
    read = perspectives.PerspectiveReadContext(scene)
    pending = sum(
        summarizer._perception_needed(scene, message, read=read) for message in messages
    )
    assert 1 < pending <= perspectives.MAX_DEPENDENCY_DEPTH + CONTEXT_PASSAGES + 1
    await summarizer.ensure_perceptions(scene)
    assert request.await_count == 200 + pending
    assert messages[-1].knowledge == untouched


def test_saved_deep_chain_stops_at_bound_with_indexed_lookups(setup, monkeypatch):
    import talemate.knowledge.perspectives as perspectives
    from talemate.knowledge.perspective_models import (
        Acquisition,
        PerspectiveView,
        SourcePerspectives,
        SceneKnowledge,
        content_digest,
    )

    scene, _, _ = setup
    reference = None
    for index in range(1000):
        message = CharacterMessage(message=f"Alice: {index}.")
        message.knowledge = SourcePerspectives(
            content_digest=content_digest(message.message),
            acquired=Acquisition(order=index + 1, ts=0),
            views=(
                PerspectiveView(
                    id=f"deep-{index}",
                    audience=("Alice",),
                    status="ready",
                    text=str(index),
                    sources=(reference,) if reference else (),
                ),
            ),
        )
        scene.history.append(message)
        reference = perspectives.SourceReference(
            kind="message",
            id=message.id,
            revision=1,
            view_id=f"deep-{index}",
            view_revision=1,
        )
    scene.knowledge = SceneKnowledge(last_order=1000)
    original_sources, original_find = perspectives._sources, perspectives._find
    scans = lookups = 0

    def count_sources(scene):
        nonlocal scans
        scans += 1
        yield from original_sources(scene)

    def count_find(*args, **kwargs):
        nonlocal lookups
        lookups += 1
        return original_find(*args, **kwargs)

    monkeypatch.setattr(perspectives, "_sources", count_sources)
    monkeypatch.setattr(perspectives, "_find", count_find)
    assert select_character_view(scene, reference, "Alice").status == "pending"
    assert scans == 1
    assert lookups <= perspectives.MAX_DEPENDENCY_DEPTH + 1


def test_depth_limit_is_preserved_by_shared_freshness_cache(setup):
    import talemate.knowledge.perspectives as perspectives
    from talemate.knowledge.perspective_models import (
        Acquisition,
        PerspectiveView,
        SourcePerspectives,
        SceneKnowledge,
        content_digest,
    )

    scene, _, _ = setup
    reference = None
    for index in range(perspectives.MAX_DEPENDENCY_DEPTH + 1):
        message = CharacterMessage(message=f"Alice: {index}.")
        message.knowledge = SourcePerspectives(
            content_digest=content_digest(message.message),
            acquired=Acquisition(order=index + 1, ts=0),
            views=(
                PerspectiveView(
                    id=f"limit-{index}",
                    audience=("Alice",),
                    status="ready",
                    text=str(index),
                    sources=(reference,) if reference else (),
                ),
            ),
        )
        scene.history.append(message)
        reference = perspectives.SourceReference(
            kind="message",
            id=message.id,
            revision=1,
            view_id=f"limit-{index}",
            view_revision=1,
        )
    scene.knowledge = SceneKnowledge(last_order=len(scene.history))
    read = perspectives.PerspectiveReadContext(scene)
    assert select_character_view(scene, reference, "Alice", read=read).status == "ready"
    assert not perspectives.can_cite_view(scene, reference, "Alice", read=read)
    context = perception_context(scene, CharacterMessage(message="Alice: Next."))
    assert all(
        item["source"]["id"] != reference.id
        for character in context["cast"]
        for item in character["established_knowledge"]
    )
    new = CharacterMessage(message="Alice: New dependent.")
    scene.history.append(new)
    with pytest.raises(ValueError, match="dependency"):
        set_source_perspectives(
            scene,
            "message",
            new.id,
            [
                {
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": "Too deep.",
                    "sources": [reference],
                }
            ],
        )
    assert new.knowledge is None
