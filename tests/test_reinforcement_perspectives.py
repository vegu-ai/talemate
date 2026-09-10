from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import test_perception_lifecycle
import test_character_retrieval
import test_memory_audiences
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.context import project_character_history
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.perspectives import (
    bind_perspective_sources,
    select_character_view,
    source_reference,
    validate_saved_knowledge,
)
from talemate.knowledge.schema import EntryVisibility
from talemate.prompts import Prompt
from talemate.scene_message import ContextInvestigationMessage, ReinforcementMessage
from talemate.world_state import Reinforcement, WorldState
from talemate.tale_mate import Actor

pytestmark = pytest.mark.asyncio
setup = test_perception_lifecycle.setup
answer = test_perception_lifecycle.answer
result = test_perception_lifecycle.result
rag = test_character_retrieval.rag
indexed_scene = test_memory_audiences.indexed_scene
chroma_clients = test_memory_audiences.chroma_clients

QUESTION = "Where is the secret poison stash?"
READER = "A lantern is lit. The poison stash is under Bob's bed."
VISIBLE = "Alice sees the lantern's light."


async def apply(scene, request, *, insert="all-context", character=None):
    if not scene.actors:
        for item in scene.character_data.values():
            actor = Actor(item, get_agent("conversation"))
            actor.scene = scene
            scene.actors.append(actor)
    reinforcement = Reinforcement(question=QUESTION, character=character, insert=insert)
    scene.world_state.reinforce.append(reinforcement)
    request.return_value = result(answer(VISIBLE, None))
    world = get_agent("world_state")
    message = world._prepare_reinforcement(reinforcement, False)
    await world._apply_reinforcement(reinforcement, message, READER, False)
    return reinforcement


def render_inserts(scene, viewer, *, technical=False):
    return Prompt.get(
        "common.extra-context-static",
        vars={
            "scene": scene,
            "knowledge_viewer": viewer,
            "reinforcement_character": "Bob",
            "reinforcement_inserts": ["all-context", "conversation-context"],
            "reinforcement_character_inserts": ["all-context", "conversation-context"],
            "technical": technical,
        },
    ).render()


@pytest.mark.parametrize(
    "insert", ["sequential", "all-context", "conversation-context", "never"]
)
@pytest.mark.parametrize("character", [None, "Bob"])
async def test_all_modes_analyze_heading_once_and_scope_history_inserts_and_side_entries(
    setup, insert, character
):
    scene, summarizer, request = setup
    reinforcement = await apply(scene, request, insert=insert, character=character)
    source = reinforcement.source_for(scene)
    assert source.message == READER
    context = request.call_args.kwargs["vars"]["context"]
    assert QUESTION in context["passage"]["text"]
    assert READER in context["passage"]["text"]
    await summarizer.ensure_perceptions(scene)
    assert request.await_count == 1
    assert bool(scene.history) == (insert == "sequential")
    history = "\n".join(project_character_history(scene, "Alice"))
    assert (VISIBLE in history) == (insert == "sequential")
    assert "poison" not in history
    assert project_character_history(scene, "Bob") == []
    for technical in (False, True):
        inserted = render_inserts(scene, "Alice", technical=technical)
        assert (VISIBLE in inserted) == (
            insert in ("all-context", "conversation-context")
        )
        assert "poison" not in inserted
        assert VISIBLE not in render_inserts(scene, "Bob", technical=technical)
    rows = audience_documents(scene)
    assert rows and all("poison" not in row["text"] for row in rows.values())
    side = [row for row in rows.values() if row["group"] == ("authored",)]
    assert side and all(row["text"] == VISIBLE for row in side)
    assert all(row["meta"]["knowledge_audience"] == ["Alice"] for row in side)
    assert all(not row["meta"]["knowledge_common"] for row in side)
    if character:
        assert scene.character_data[character].details[QUESTION] == READER
    else:
        assert READER in scene.world_state.manual_context[QUESTION].text
    assert READER in reinforcement.context_for(scene)


@pytest.mark.parametrize("character", [None, "Bob"])
async def test_authored_visibility_narrows_generated_side_entry_and_pin(
    setup, character
):
    scene, _, request = setup
    reinforcement = await apply(scene, request, character=character)
    identity = f"Bob.detail.{QUESTION}" if character else QUESTION
    scene.active_pins = [
        SimpleNamespace(
            pin=SimpleNamespace(entry_id=identity),
            title=QUESTION,
            time_aware_text=READER,
            context_id=QUESTION,
        )
    ]
    for technical in (False, True):
        rendered = render_inserts(scene, "Alice", technical=technical)
        assert VISIBLE in rendered and "poison" not in rendered
    visibility = EntryVisibility(mode="list", characters=["Bob"])
    if character:
        await scene.world_state_manager.set_character_entry_visibility(
            character, f"detail.{QUESTION}", visibility
        )
    else:
        await scene.world_state_manager.set_world_entry_visibility(QUESTION, visibility)
    request.return_value = result(answer(VISIBLE, None))
    world = get_agent("world_state")
    await world._apply_reinforcement(
        reinforcement, world._prepare_reinforcement(reinforcement, False), READER, False
    )
    assert (
        scene.character_data[character].visibility[f"detail.{QUESTION}"]
        if character
        else scene.world_state.manual_context[QUESTION].visibility
    ) == visibility
    assert not reinforcement.context_for(scene, "Alice")
    assert not any(
        row["group"] == ("authored",) for row in audience_documents(scene).values()
    )
    assert VISIBLE not in render_inserts(scene, "Alice")
    assert QUESTION in render_inserts(scene, None)


async def test_direct_source_edits_fail_closed_rebuild_and_survive_save(setup):
    scene, summarizer, request = setup
    reinforcement = await apply(scene, request)
    old = source_reference(scene, "message", reinforcement.perspective_source.id)
    reinforcement.answer = "The lantern went dark; the poison remains hidden."
    with pytest.raises(GenerationCancelled, match="stale"):
        reinforcement.context_for(scene, "Alice")
    assert not any(
        row["group"] == ("authored",) for row in audience_documents(scene).values()
    )
    request.return_value = result(answer("Alice sees the lantern go dark.", None))
    await summarizer.ensure_perceptions(scene)
    assert reinforcement.perspective_source.id > old.id
    assert "go dark" in reinforcement.context_for(scene, "Alice")
    assert select_character_view(scene, old, "Alice").status == "unavailable"
    payload = {
        "knowledge_eligibility": "perception",
        "knowledge": scene.knowledge.model_dump(),
        "history": [],
        "archived_history": [],
        "layered_history": [],
        "character_data": {
            name: char.model_dump() for name, char in scene.character_data.items()
        },
        "world_state": scene.world_state.model_dump(),
    }
    assert validate_saved_knowledge(payload) == scene.knowledge
    scene.world_state = WorldState.model_validate(payload["world_state"])
    bind_perspective_sources(scene)
    restored = scene.world_state.reinforce[0]
    assert "go dark" in restored.context_for(scene, "Alice")
    assert ReinforcementMessage(message="next").id > restored.perspective_source.id
    assert request.await_count == 2


async def test_direct_failure_and_retry_use_shared_lifecycle(setup, monkeypatch):
    scene, summarizer, request = setup
    reinforcement = Reinforcement(
        question=QUESTION, answer=READER, insert="all-context"
    )
    scene.world_state.reinforce.append(reinforcement)
    request.return_value = result("not structured")
    recovery = AsyncMock(return_value="ignore")
    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", recovery)
    with pytest.raises(GenerationCancelled, match="successful retry"):
        await summarizer.finalize_perceptions(scene, [])
    assert reinforcement.perspective_source.knowledge.views[0].status == "failed"
    with pytest.raises(GenerationCancelled, match="failed"):
        reinforcement.context_for(scene, "Alice")
    assert reinforcement.answer == READER
    request.return_value = result(answer(VISIBLE, None))
    await summarizer.ensure_perceptions(scene)
    assert reinforcement.context_for(scene, "Alice") == VISIBLE
    assert request.await_count == 2
    recovery.assert_awaited_once()


@pytest.mark.parametrize("discovery", [False, True])
async def test_investigations_review_titles_and_distinguish_actual_learning(
    setup, discovery
):
    scene, summarizer, request = setup
    message = ContextInvestigationMessage(
        message="Alice searches the bed and finds a vial."
        if discovery
        else "The reader learns a vial is under the bed.",
        sub_type="query",
    )
    message.set_source("narrator", "narrate_query", query=QUESTION)
    request.return_value = result(
        answer("Alice finds a vial under the bed." if discovery else None, None)
    )
    await scene.push_history(message)
    assert QUESTION in request.call_args.kwargs["vars"]["context"]["passage"]["text"]
    history = "\n".join(project_character_history(scene, "Alice"))
    assert ("finds a vial" in history) == discovery
    assert "poison" not in history
    assert project_character_history(scene, "Bob") == []
    revision = message.knowledge.revision
    message.set_source(
        "narrator", "narrate_query", query="What is the secret antidote?"
    )
    assert message.knowledge.revision > revision
    with pytest.raises(GenerationCancelled, match="pending"):
        project_character_history(scene, "Alice")
    await summarizer.ensure_perceptions(scene)
    assert "antidote" in request.call_args.kwargs["vars"]["context"]["passage"]["text"]
    assert request.await_count == 2


@pytest.mark.parametrize(
    "insert", ["sequential", "all-context", "conversation-context", "never"]
)
@pytest.mark.parametrize("character", [None, "Bob"])
async def test_legacy_reinforcement_has_no_perception_request_or_serialized_source(
    setup, monkeypatch, insert, character
):
    scene, summarizer, request = setup
    scene.knowledge_eligibility = "legacy"
    finalize = AsyncMock()
    monkeypatch.setattr(summarizer, "finalize_perceptions", finalize)
    reinforcement = await apply(scene, request, insert=insert, character=character)
    if insert != "sequential":
        finalize.assert_not_awaited()
    request.assert_not_awaited()
    assert "perspective_source" not in reinforcement.model_dump()
    assert READER in reinforcement.context_for(scene, "Alice")


async def test_finalization_rejects_scene_switch_before_preparing_direct_sources(
    setup, monkeypatch
):
    from talemate.tale_mate import Scene

    scene, summarizer, request = setup
    reinforcement = Reinforcement(
        question=QUESTION, answer=READER, insert="all-context"
    )
    scene.world_state.reinforce.append(reinforcement)
    monkeypatch.setattr(summarizer, "scene", Scene())
    with pytest.raises(GenerationCancelled, match="scene changed"):
        await summarizer.finalize_perceptions(scene, [])
    assert reinforcement.perspective_source is None
    request.assert_not_awaited()


async def test_real_index_updates_generated_entries_and_cache_then_removes_sources(
    rag, monkeypatch
):
    import json

    scene, memory, _, conversation = rag
    request = AsyncMock()
    monkeypatch.setattr(Prompt, "request", request)

    def response(text):
        return result(
            json.dumps(
                {
                    "views": [
                        {"audience": ["Elmer"], "status": "ready", "text": text},
                        {"audience": ["Marie"], "status": "omitted", "text": None},
                    ]
                }
            )
        )

    reinforcement = Reinforcement(question=QUESTION, insert="all-context")
    scene.world_state.reinforce.append(reinforcement)
    world = get_agent("world_state")
    request.return_value = response("Elmer notices a lantern.")
    await world._apply_reinforcement(
        reinforcement, world._prepare_reinforcement(reinforcement, False), READER, False
    )
    elmer = scene.character_data["Elmer"]
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "direct")
    await conversation.rag_build(elmer)
    key = conversation.long_term_memory_cache_key_for(elmer)
    documents = await memory.get_document(QUESTION, viewer="Elmer")
    assert documents and all("Elmer notices" in doc for doc in documents.values())
    assert not await memory.get_document(QUESTION, viewer="Marie")
    assert READER in (await memory.get_document(QUESTION))[QUESTION]
    source = source_reference(scene, "message", reinforcement.perspective_source.id)
    request.return_value = response("Elmer sees the lantern go dark.")
    await scene.world_state.add_reinforcement(
        QUESTION,
        answer="The lantern went dark. The poison is still hidden.",
        insert="all-context",
    )
    documents = await memory.get_document(QUESTION, viewer="Elmer")
    assert documents and all("go dark" in doc for doc in documents.values())
    assert all("poison" not in doc for doc in documents.values())
    assert conversation.long_term_memory_cache_key_for(elmer) == key
    assert await conversation.rag_get_cache(elmer) is None
    assert "go dark" in render_inserts(scene, "Elmer")
    await scene.world_state.remove_reinforcement(0)
    assert source_reference(scene, "message", source.id) is None
    assert not await memory.get_document(QUESTION, viewer="Elmer")
    assert not await memory.get_document(QUESTION)
    assert not await memory.get_document(str(source.id), viewer="Elmer")
    assert request.await_count == 2


async def test_direct_answer_changed_during_analysis_discards_stale_response(setup):
    scene, summarizer, request = setup
    reinforcement = Reinforcement(
        question=QUESTION, answer=READER, insert="all-context"
    )
    scene.world_state.reinforce.append(reinforcement)
    calls = 0

    async def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert calls <= 2, "Repeated stale-source retries"
        if calls == 1:
            reinforcement.answer = "The lantern is dark."
            return result(answer(VISIBLE, None))
        assert "lantern is dark" in kwargs["vars"]["context"]["passage"]["text"]
        return result(answer("Alice sees the lantern go dark.", None))

    request.side_effect = changing
    await summarizer.finalize_perceptions(scene, [])
    assert (
        reinforcement.context_for(scene, "Alice") == "Alice sees the lantern go dark."
    )
    assert calls == 2


async def test_insert_mode_changes_retire_only_the_selected_source(setup):
    scene, _, request = setup
    first = await apply(scene, request, insert="sequential")
    first_id = first.source_for(scene).id
    second = Reinforcement(question="Weather?", insert="sequential")
    scene.world_state.reinforce.append(second)
    world = get_agent("world_state")
    await world._apply_reinforcement(
        second, world._prepare_reinforcement(second, False), "It rains.", False
    )
    second_source = second.source_for(scene)
    await scene.world_state.add_reinforcement(
        QUESTION, answer=READER, insert="all-context"
    )
    assert second.source_for(scene) is second_source
    assert source_reference(scene, "message", first_id) is None
    direct_id = first.source_for(scene).id
    assert first.context_for(scene, "Alice") == VISIBLE
    await scene.world_state.add_reinforcement(
        QUESTION, answer=READER, insert="sequential"
    )
    assert source_reference(scene, "message", direct_id) is None
    assert first.perspective_source is None
    assert second.source_for(scene) is second_source
    await world._apply_reinforcement(
        first, world._prepare_reinforcement(first, False), READER, False
    )
    assert first.source_for(scene).id not in (first_id, direct_id)
    assert first.context_for(scene, "Alice") == VISIBLE


async def test_direct_passage_does_not_acquire_a_later_disclosure_on_retry(setup):
    from talemate.agents.summarize.perceptions import perception_context
    from talemate.knowledge.perspectives import add_disclosure

    scene, summarizer, request = setup
    reinforcement = await apply(scene, request)
    source = reinforcement.perspective_source
    disclosure = add_disclosure(
        scene, audience=["Alice"], text="The late secret is a sapphire."
    )
    assert disclosure.message_id_boundary >= source.id
    source.message = "A different reader interpretation."
    reinforcement.answer = source.message
    await summarizer.ensure_perceptions(scene)
    context = perception_context(scene, source)
    assert all(
        "sapphire" not in item["text"]
        for character in context["cast"]
        for item in character["established_knowledge"]
    )
    later = ContextInvestigationMessage(message="Alice learns the future secret.")
    request.return_value = result(answer("Alice learns the future secret.", None))
    await scene.push_history(later)
    context = perception_context(scene, source)
    assert all(item["id"] != later.id for item in context["prior_physical_context"])
    assert all(
        "future secret" not in item["text"]
        for actor in context["cast"]
        for item in actor["established_knowledge"]
    )


@pytest.mark.parametrize("character", [None, "Bob"])
async def test_orphaned_generated_entry_stays_restricted_after_save(setup, character):
    import json

    scene, _, request = setup
    await apply(scene, request, character=character)
    identity = f"Bob.detail.{QUESTION}" if character else QUESTION
    scene.world_state.reinforce.clear()
    payload = json.loads(json.dumps(scene.world_state.model_dump()))
    scene.world_state = WorldState.model_validate(payload)
    assert scene.world_state.is_reinforcement_entry(identity)
    assert not any(
        row["group"] == ("authored",) for row in audience_documents(scene).values()
    )
    scene.active_pins = [
        SimpleNamespace(
            pin=SimpleNamespace(entry_id=identity),
            title=QUESTION,
            time_aware_text=READER,
            context_id=identity,
        )
    ]
    assert "poison" not in render_inserts(scene, "Alice")
    assert "poison" in render_inserts(scene, None)
    if character:
        from talemate.context import ActiveScene

        with ActiveScene(scene):
            scene.character_data["Bob"].rename("Robert")
        assert scene.world_state.is_reinforcement_entry(f"Robert.detail.{QUESTION}")
        assert not any(
            row["group"] == ("authored",) for row in audience_documents(scene).values()
        )
