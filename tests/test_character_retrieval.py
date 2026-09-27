import asyncio
import json
import threading
from unittest.mock import AsyncMock, Mock

import pytest
import test_memory_audiences

from talemate.agents.context import ActiveAgent
from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.config import get_config
from talemate.history import ArchiveEntry
from talemate.instance import get_agent
from talemate.knowledge.disclosures import grant_disclosure
from talemate.knowledge.perspectives import set_source_perspectives
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge
from talemate.prompts import Prompt
from talemate.regenerate import regenerate
from talemate.scene_message import DirectorMessage
from talemate.tale_mate import Scene
from talemate.world_state import Reinforcement

pytestmark = pytest.mark.asyncio
indexed_scene = test_memory_audiences.indexed_scene
chroma_clients = test_memory_audiences.chroma_clients


@pytest.fixture
def rag(indexed_scene, monkeypatch):
    scene, memory, message = indexed_scene
    conversation = get_agent("conversation")
    conversation.connect(scene)
    get_agent("world_state").connect(scene)
    monkeypatch.setattr(
        memory.actions["retrieval"].config["mmr_threshold"], "value", 1.0
    )
    monkeypatch.setattr(
        conversation.actions["use_long_term_memory"].config["cache"], "value", False
    )
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["memory_pass"],
        "value",
        False,
    )
    return scene, memory, message, conversation


def views(
    scene,
    message,
    public="Marie carries a lantern.",
    private="Zed hides a coded diary.",
):
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": ["Elmer"], "text": public, "status": "ready"},
            {"audience": ["Marie"], "text": private, "status": "ready"},
        ],
    )


async def test_direct_queries_and_entities_ignore_private_changes_and_follow_disclosure(
    rag, monkeypatch
):
    scene, memory, message, conversation = rag
    scene.character_data["Zed"] = Character(
        name="Zed", description="Zed reads the tides."
    )
    # Direct fixture mutation bypasses the roster's authored-source notification.
    memory.invalidate_audience_index(scene, groups={("authored",)})
    views(scene, message)
    queries, entities = [], []
    get = memory._get
    by_meta = memory.get_documents_by_meta

    def observed(text, *args, **kwargs):
        queries.append((text, kwargs.get("viewer")))
        return get(text, *args, **kwargs)

    async def observed_meta(meta, **kwargs):
        entities.append((meta, kwargs.get("viewer")))
        return await by_meta(meta, **kwargs)

    monkeypatch.setattr(memory, "_get", observed)
    monkeypatch.setattr(memory, "get_documents_by_meta", observed_meta)
    await conversation.rag_build(scene.character_data["Elmer"])
    before = list(queries)
    assert before and all(viewer == "Elmer" for _, viewer in before)
    assert all("Zed" not in text and "diary" not in text for text, _ in before)
    assert entities == []
    queries.clear()
    message.message = "Reader-only change: Zed is at the secret cliff."
    views(scene, message, private="Zed moved the diary to the secret cliff.")
    await conversation.rag_build(scene.character_data["Elmer"])
    assert queries == before
    assert entities == []
    grant_disclosure(scene, "Elmer", "lore", text="Zed knows the harbor tides.")
    queries.clear()
    result = await conversation.rag_build(scene.character_data["Elmer"])
    assert queries != before and any("Zed" in text for text, _ in queries)
    assert (
        {"character": "Zed", "typ": "base_attribute", "attr": "description"},
        "Elmer",
    ) in entities
    assert any("Zed reads the tides" in text for text in result)


async def test_filtered_candidate_cutoff_and_no_similarity_rescue(rag, monkeypatch):
    scene, memory, _, _ = rag
    await memory.ensure_audience_index(scene)
    lore = await memory.get_documents_by_meta({"region": "harbor"}, viewer="Elmer")
    memory.db.update(ids=list(lore), embeddings=[[0.9, 0.1]])
    crowded = [f"private-{i}" for i in range(30)]
    memory.db.add(
        ids=crowded,
        documents=["Private reader fact."] * 30,
        embeddings=[[1.0, 0.0]] * 30,
        metadatas=[{"knowledge_index": False, "region": "harbor"}] * 30,
    )
    global_nearest = memory.db.query(
        query_embeddings=[[1.0, 0.0]], n_results=10, where={"region": "harbor"}
    )
    assert set(global_nearest["ids"][0]) <= set(crowded)
    result = await memory.multi_query(
        ["harbor"], limit=1, viewer="Elmer", region="harbor", filter=lambda doc: True
    )
    assert [doc.raw for doc in result] == ["Common rain lore."]

    def rejected(doc):
        return False

    assert await memory.multi_query(["harbor"], viewer="Elmer", filter=rejected) == []


async def test_metadata_and_id_paths_return_only_supported_variants(rag):
    scene, memory, _, conversation = rag
    scene.character_data["Zed"] = Character(
        name="Zed",
        description="A hidden occupation.",
        visibility={"description": EntryVisibility(mode="owner")},
    )
    memory.invalidate_audience_index()
    assert await conversation.entity_lookup(["Zed was named."], viewer="Elmer") == []
    assert await memory.get_document("Zed.description.0", viewer="Elmer") == {}
    docs = await memory.get_documents_by_meta({"region": "harbor"}, viewer="Elmer")
    assert {doc.raw for doc in docs.values()} == {"Common rain lore."}
    assert all(identity.startswith("knowledge:") for identity in docs)
    assert any("Reader secret" in doc.raw for doc in await memory.get("lantern"))


@pytest.mark.parametrize("method", ["queries", "questions"])
async def test_ai_retrieval_inputs_and_templates_are_scoped(rag, monkeypatch, method):
    scene, memory, _, conversation = rag
    marie = scene.character_data["Marie"]
    marie.description = "PRIVATE SHEET."
    marie.visibility["description"] = EntryVisibility(mode="owner")
    scene.world_state.reinforce = [
        Reinforcement(
            question="PRIVATE QUESTION",
            answer="PRIVATE REINFORCEMENT",
            insert="all-context",
        )
    ]
    memory.invalidate_audience_index()
    request = AsyncMock(return_value=("", {"response": "1. lantern"}))
    monkeypatch.setattr(Prompt, "request", request)
    await conversation.rag_build(
        scene.character_data["Elmer"],
        retrieval_method=method,
        sub_instruction="Find a way home.",
    )
    variables = request.call_args.kwargs["vars"]
    assert variables["memory_viewer"] == "Elmer"
    assert variables["goal"] == "Find a way home."
    assert "Marie carries a lantern" in variables["text"]
    assert "Reader secret" not in variables["text"]
    assert "PRIVATE SHEET" not in variables["memory_character_context"]
    monkeypatch.setattr(Prompt, "query_memory", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        Prompt, "instruct_text", lambda *args, **kwargs: ["Where is the lantern?"]
    )
    rendered = Prompt.get(request.call_args.args[0], vars=variables).render()
    assert "PRIVATE" not in rendered and "coded diary" not in rendered


async def test_questions_template_pins_backend_viewer(rag, monkeypatch):
    scene, memory, _, _ = rag
    query = AsyncMock(wraps=memory.multi_query)
    monkeypatch.setattr(memory, "multi_query", query)
    prompt = Prompt.get(
        "world_state.analyze-text-and-extract-context",
        vars={"scene": scene, "memory_viewer": "Elmer"},
    )
    result = prompt.query_memory(
        "lantern", as_question_answer=False, iterate=5, viewer=None
    )
    assert query.call_args.kwargs["viewer"] == "Elmer"
    assert not any("coded diary" in item or "Reader secret" in item for item in result)


async def test_cache_separates_viewers_and_tracks_disclosures_and_views(
    rag, monkeypatch
):
    scene, _, message, conversation = rag
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "queries")
    request = AsyncMock(return_value=("", {"response": "1. lantern"}))
    monkeypatch.setattr(Prompt, "request", request)
    elmer = scene.character_data["Elmer"]
    await conversation.rag_build(elmer)
    await conversation.rag_build(elmer)
    assert request.call_count == 1
    await conversation.rag_build(scene.character_data["Marie"])
    assert request.call_count == 2
    grant_disclosure(scene, "Elmer", "lore", text="A newly learned tide.")
    await conversation.rag_build(elmer)
    assert request.call_count == 3
    views(scene, message, public="Marie lowered the lantern.")
    result = await conversation.rag_build(elmer)
    assert request.call_count == 4
    assert any("Marie lowered" in text for text in result)
    assert not any("Marie carries" in text for text in result)


async def test_view_change_during_ai_request_does_not_publish_stale_cache(
    rag, monkeypatch
):
    scene, _, message, conversation = rag
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "queries")
    calls = 0

    async def request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            views(scene, message, public="Marie lowered the lantern.")
        return "", {"response": "1. lantern"}

    monkeypatch.setattr(Prompt, "request", request)
    result = await conversation.rag_build(scene.character_data["Elmer"])
    assert calls == 2
    assert not any("Marie carries" in text for text in result)
    assert await conversation.rag_build(scene.character_data["Elmer"]) == result
    assert calls == 2


async def test_character_api_has_no_raw_override_and_author_api_retains_it(
    rag, monkeypatch
):
    scene, _, _, conversation = rag
    with pytest.raises(TypeError, match="prompt"):
        await conversation.rag_build(
            scene.character_data["Elmer"], prompt="Reader secret."
        )
    with pytest.raises(ValueError, match="Perception characters must use rag_build"):
        await conversation.rag_build_for_author(
            character=scene.character_data["Elmer"], prompt="Reader secret."
        )
    request = AsyncMock(return_value=("", {"response": "1. lantern"}))
    monkeypatch.setattr(Prompt, "request", request)
    await conversation.rag_build_for_author(
        prompt="Author-only scenario.", retrieval_method="queries"
    )
    assert request.call_args.kwargs["vars"]["text"] == "Author-only scenario."
    assert request.call_args.kwargs["vars"]["knowledge_viewer"] is None


async def test_character_template_does_not_forward_shared_override(rag, monkeypatch):
    scene, _, _, conversation = rag
    calls = []

    def action(self, agent, name, **kwargs):
        calls.append((name, kwargs))
        return []

    monkeypatch.setattr(Prompt, "agent_action", action)
    with ActiveAgent(conversation, conversation.rag_build):
        Prompt.get(
            "common.memory-context",
            vars={
                "scene": scene,
                "talking_character": scene.character_data["Elmer"],
                "memory_prompt": "Shared private override.",
            },
        ).render()
    assert calls and calls[0][0] == "rag_build"
    assert "prompt" not in calls[0][1]


async def test_perception_viewer_does_not_depend_on_legacy_toggle(rag, monkeypatch):
    scene, _, _, conversation = rag
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["perspective_filter"],
        "value",
        False,
    )
    assert conversation.rag_knowledge_viewer(scene.character_data["Elmer"]) == "Elmer"
    monkeypatch.setattr(conversation.actions["use_long_term_memory"], "enabled", False)
    assert await conversation.rag_build(scene.character_data["Elmer"]) == []


async def test_optional_memory_pass_uses_projected_history(rag, monkeypatch):
    scene, _, _, conversation = rag
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["memory_pass"], "value", True
    )
    request = AsyncMock(return_value=("", {"answer": "none", "items": []}))
    monkeypatch.setattr(Prompt, "request", request)
    await conversation.rag_build(scene.character_data["Elmer"])
    variables = request.call_args.kwargs["vars"]
    assert request.call_args.args[0] == "conversation.memory-pass"
    assert variables["character_retrieval"] is True
    assert "Marie carries a lantern" in "\n".join(variables["scene_history"])
    rendered = Prompt.get("conversation.memory-pass", vars=variables).render()
    assert "Reader secret" not in rendered and "coded diary" not in rendered


async def test_scene_switch_during_ai_request_rejects_the_result(rag, monkeypatch):
    scene, memory, _, conversation = rag

    async def request(*args, **kwargs):
        memory.scene = object()
        return "", {"response": "A stale answer."}

    monkeypatch.setattr(Prompt, "request", request)
    try:
        with pytest.raises(RuntimeError, match="scene or collection"):
            await conversation.rag_build(
                scene.character_data["Elmer"], retrieval_method="questions"
            )
    finally:
        memory.scene = scene


async def test_rag_retry_budget_covers_queries_and_memory_pass(rag, monkeypatch):
    scene, _, message, conversation = rag
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "queries")
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["memory_pass"], "value", True
    )
    calls = []

    async def request(name, *args, **kwargs):
        calls.append(name)
        assert len(calls) <= 4, "RAG exceeded two attempts / four paid requests"
        views(scene, message, public=f"Marie moved her lantern {len(calls)} times.")
        if name == "conversation.memory-pass":
            return "", {"answer": "none", "items": []}
        return "", {"response": "1. lantern"}

    monkeypatch.setattr(Prompt, "request", request)
    with pytest.raises(RuntimeError, match="kept changing"):
        await conversation.rag_build(scene.character_data["Elmer"])
    assert (
        calls
        == [
            "world_state.analyze-text-and-generate-rag-queries",
            "conversation.memory-pass",
        ]
        * 2
    )
    assert await conversation.rag_get_cache(scene.character_data["Elmer"]) is None


async def test_scoped_cache_hit_stays_behind_audience_index_guard(rag, monkeypatch):
    scene, memory, _, conversation = rag
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "direct")
    character = scene.character_data["Elmer"]
    await conversation.rag_set_cache(["Guarded context."], character)
    monkeypatch.setattr(
        memory,
        "ensure_audience_index",
        AsyncMock(side_effect=RuntimeError("audience index unavailable")),
    )

    with pytest.raises(RuntimeError, match="audience index unavailable"):
        await conversation.rag_build(character)


async def test_cache_hit_is_refused_while_memory_write_is_in_flight(rag, monkeypatch):
    scene, memory, _, conversation = rag
    character = await configure_cached_rag(
        rag, monkeypatch, "legacy", "character", "queries"
    )
    await conversation.rag_set_cache(["Earlier context."], character)
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = memory._add

    def blocked(*args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(memory, "_add", blocked)
    pending = asyncio.create_task(memory.add("A concurrent edit.", uid="concurrent"))
    await asyncio.wait_for(started.wait(), timeout=5)
    try:
        assert await conversation.rag_get_cache(character) is None
    finally:
        release.set()
        await asyncio.wait_for(pending, timeout=5)
    assert await conversation.rag_get_cache(character) is None


@pytest.mark.parametrize("mode", ["direction", "internal_monologue"])
@pytest.mark.parametrize("guidance", [None, "Live guidance replaces stored direction."])
async def test_retrieval_keeps_only_own_direction_with_configured_format(
    rag, monkeypatch, mode, guidance
):
    scene, memory, _, conversation = rag
    own = DirectorMessage("Inspect your lantern.", meta={"character": "Elmer"})
    other = DirectorMessage("PRIVATE DIRECTOR MESSAGE.", meta={"character": "Marie"})
    scene.history.extend([own, other])
    monkeypatch.setattr(
        get_agent("director").actions["direct"].config["actor_direction_mode"],
        "value",
        mode,
    )
    expected = own.as_format(scene.conversation_format, mode=mode)
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(memory, "multi_query", query)
    await conversation.semantic_context(viewer="Elmer")
    query_text = "\n".join(query.call_args.args[0])
    assert expected in query_text
    assert "PRIVATE DIRECTOR" not in query_text
    request = AsyncMock(return_value=("", {"answer": "none", "items": []}))
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveAgent(conversation, conversation.memory_pass) as context:
        context.state["director__actor_guidance"] = guidance
        await conversation.memory_pass(
            scene.character_data["Elmer"], ["A lantern memory."]
        )
    history = "\n".join(request.call_args.kwargs["vars"]["scene_history"])
    assert (expected in history) == (guidance is None)
    assert "PRIVATE DIRECTOR" not in history


async def test_legacy_template_preserves_raw_author_override_with_character(
    rag, monkeypatch
):
    scene, _, _, conversation = rag
    rag[0].knowledge_eligibility = "legacy"
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["memory_pass"], "value", True
    )
    semantic = AsyncMock(wraps=conversation.semantic_context)
    memory_pass = AsyncMock(return_value=["Processed legacy memory."])
    monkeypatch.setattr(conversation, "semantic_context", semantic)
    monkeypatch.setattr(conversation, "memory_pass", memory_pass)
    monkeypatch.setattr(
        conversation.actions["use_long_term_memory"].config["retrieval_method"],
        "value",
        "queries",
    )
    request = AsyncMock(return_value=("", {"response": "1. lantern"}))
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveAgent(conversation, conversation.rag_build):
        rendered = Prompt.get(
            "common.memory-context",
            vars={
                "scene": scene,
                "talking_character": scene.character_data["Elmer"],
                "memory_prompt": "Explicit author history.",
                "sub_instruction": "Find a way home.",
            },
        ).render()
    variables = request.call_args.kwargs["vars"]
    assert variables["text"] == "Explicit author history."
    assert variables["goal"] == "Find a way home."
    assert variables["knowledge_viewer"] == "Elmer"
    assert semantic.call_args.kwargs["filter"] is not None
    memory_pass.assert_awaited_once()
    assert memory_pass.call_args.args[0] is scene.character_data["Elmer"]
    assert memory_pass.call_args.args[1]
    assert "Processed legacy memory." in rendered


async def test_retrieve_memories_global_uses_viewer_projection_and_scope(
    rag, monkeypatch
):
    scene, _, _, _ = rag
    request = AsyncMock(return_value=("", {"response": "A supported answer."}))
    monkeypatch.setattr(Prompt, "request", request)
    prompt = Prompt.get(
        "world_state.analyze-text-and-extract-context",
        vars={"scene": scene, "memory_viewer": "Elmer"},
    )
    assert (
        prompt.retrieve_memories(["PRIVATE CALLER HISTORY"], goal="Find a way home.")
        == "A supported answer."
    )
    variables = request.call_args.kwargs["vars"]
    assert variables["memory_viewer"] == "Elmer"
    assert "Marie carries a lantern" in variables["text"]
    assert "PRIVATE" not in variables["text"]
    prompt.vars.pop("memory_viewer")
    prompt.retrieve_memories(["Author override"], goal="Find a way home.")
    assert request.call_args.kwargs["vars"]["text"] == "Author override"
    assert request.call_args.kwargs["vars"]["knowledge_viewer"] is None


@pytest.mark.parametrize(
    "template,section",
    [
        ("conversation.memory-pass", "ELMER"),
        ("world_state.analyze-text-and-generate-rag-queries", "CHARACTERS"),
        ("world_state.analyze-text-and-extract-context", "CHARACTERS"),
    ],
)
@pytest.mark.parametrize("records", ["VISIBLE CHARACTER RECORD", ""])
async def test_scoped_character_context_has_nonempty_section(
    rag, monkeypatch, template, section, records
):
    scene, _, _, _ = rag
    monkeypatch.setattr(
        Prompt, "instruct_text", lambda *args, **kwargs: ["Where is the lantern?"]
    )
    monkeypatch.setattr(Prompt, "query_memory", lambda *args, **kwargs: [])
    rendered = Prompt.get(
        template,
        vars={
            "scene": scene,
            "character": scene.character_data["Elmer"],
            "character_retrieval": True,
            "memory_character_context": records,
            "viewer": "Elmer",
            "goal": "Continue the scene",
            "num_queries": 1,
            "text": "Marie carries a lantern.",
            "scene_history": [],
            "candidates": [],
        },
    ).render(apply_sectioning=False)
    marker = f"<|SECTION:{section}|>"
    assert (marker in rendered) == bool(records)
    if records:
        block = rendered.split(marker, 1)[1].split("<|CLOSE_SECTION|>", 1)[0]
        assert records in block


async def test_direct_retrieval_cache_tracks_disclosures(rag, monkeypatch):
    scene, memory, _, conversation = rag
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "direct")
    query = Mock(wraps=memory._get)
    request = AsyncMock(side_effect=AssertionError("Direct retrieval called the model"))
    monkeypatch.setattr(memory, "_get", query)
    monkeypatch.setattr(Prompt, "request", request)
    elmer = scene.character_data["Elmer"]
    initial = await conversation.rag_build(elmer)
    count = query.call_count
    assert count and scene.rag_cache
    assert await conversation.rag_build(elmer) == initial
    assert query.call_count == count
    grant_disclosure(scene, "Elmer", "lore", text="The harbor closes at midnight.")
    result = await conversation.rag_build(elmer)
    assert query.call_count > count
    assert any("midnight" in item for item in result)
    assert await conversation.rag_build(elmer, retrieval_method="direct") == result
    request.assert_not_awaited()


async def test_legacy_direct_retrieval_sees_world_entry_edit_at_same_history(
    rag, monkeypatch
):
    scene, memory, _, conversation = rag
    # Complete fixture reconciliation before selecting legacy behavior.
    await memory.ensure_audience_index(scene)
    rag[0].knowledge_eligibility = "legacy"
    # A legacy store has no perception variants competing at the result cutoff.
    memory.db.delete(ids=memory.db.get()["ids"])
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "direct")
    elmer = scene.character_data["Elmer"]
    await scene.world_state_manager.save_world_entry(
        "lore", "The harbor opens at dawn.", {}
    )
    history = scene.history[-1].fingerprint
    before = await conversation.rag_build(elmer)
    assert any("opens at dawn" in doc for doc in before)
    await scene.world_state_manager.save_world_entry(
        "lore", "The harbor closes at dusk.", {}
    )
    after = await conversation.rag_build(elmer)
    assert scene.history[-1].fingerprint == history
    assert any("closes at dusk" in doc for doc in after)
    assert not any("opens at dawn" in doc for doc in after)
    assert not scene.rag_cache


async def configure_cached_rag(rag, monkeypatch, mode, viewer, method):
    scene, memory, _, conversation = rag
    await memory.ensure_audience_index(scene)
    if mode == "legacy":
        scene.knowledge_eligibility = "legacy"
        memory.db.delete(ids=memory.db.get()["ids"])
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", method)
    if viewer == "shared":
        monkeypatch.setattr(conversation, "rag_knowledge_viewer", lambda _: None)
    return None if viewer == "author" else scene.character_data["Elmer"]


async def cached_reply_turn(rag, monkeypatch, mode, *, archive_during_push=False):
    scene, memory, _, conversation = rag
    character = await configure_cached_rag(
        rag, monkeypatch, mode, "character", "queries"
    )
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["memory_pass"],
        "value",
        True,
    )
    monkeypatch.setattr(
        conversation,
        "semantic_context",
        AsyncMock(
            return_value=[
                MemoryDocument(
                    "The harbor closes at dusk.",
                    {"typ": "world_state"},
                    "harbor",
                    "The harbor closes at dusk.",
                )
            ]
        ),
    )
    query = AsyncMock(return_value=["The tide is rising."])
    monkeypatch.setattr(
        get_agent("world_state"),
        "analyze_text_and_extract_context_via_queries",
        query,
    )
    calls = {}
    dialogue_prompts = []
    reply = 0

    async def send_prompt(prompt, *args, **kwargs):
        nonlocal reply
        calls[prompt.uid] = calls.get(prompt.uid, 0) + 1
        if prompt.uid == "conversation.memory-pass":
            return '<ITEMS><ITEM n="1">The harbor will close at dusk.</ITEM></ITEMS>'
        if prompt.uid == "summarizer.perceptions":
            views = [
                {
                    "audience": [item["name"]],
                    "status": "ready",
                    "text": f"{item['name']} hears Elmer reply.",
                    "exclusions": [
                        {
                            "span": prompt.vars["context"]["passage"]["text"],
                            "reason": "test",
                            "forbidden": [],
                        }
                    ],
                    "knowledge_ids": [],
                    "passage_ids": [],
                }
                for item in prompt.vars["context"]["cast"]
            ]
            return json.dumps({"views": views})
        if prompt.uid.startswith("conversation.dialogue-"):
            dialogue_prompts.append(prompt.prompt)
            reply += 1
            return f"Elmer: Reply {reply}."
        raise AssertionError(f"Unexpected LLM request: {prompt.uid}")

    monkeypatch.setattr(scene.mock_client, "send_prompt", send_prompt)
    if mode == "perception":

        async def sync_reply_index(event):
            if event.scene is scene:
                await memory.ensure_audience_index(scene)

        scene.signals["push_history.after"].connect(sync_reply_index)
    if archive_during_push:
        wrote_archive = False

        async def archive_after_reply(event):
            nonlocal wrote_archive
            if event.scene is scene and not wrote_archive:
                wrote_archive = True
                await scene.push_archive(ArchiveEntry(text="A new harbor archive."))

        scene.signals["push_history.after"].connect(archive_after_reply)

    original = (await conversation.converse(character.actor))[0]
    await scene.push_history(original)
    return original, query, calls, dialogue_prompts


@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_regenerate_reuses_query_and_memory_pass(rag, monkeypatch, mode):
    scene, _, _, _ = rag
    original, query, calls, dialogue_prompts = await cached_reply_turn(
        rag, monkeypatch, mode
    )

    assert await regenerate(scene) == [original]
    assert query.await_count == 1
    assert calls["conversation.memory-pass"] == 1
    assert len(dialogue_prompts) == 2
    assert all(
        "The harbor will close at dusk." in prompt for prompt in dialogue_prompts
    )


async def test_viewerless_regenerate_refreshes_after_intro_edit(rag, monkeypatch):
    scene, _, message, conversation = rag
    assert scene.pop_message(message)
    scene.set_intro("The harbor opens under a clear sky.")
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["perspective_filter"],
        "value",
        False,
    )
    original, query, calls, _ = await cached_reply_turn(rag, monkeypatch, "legacy")

    scene.set_intro("The harbor opens under a violent storm.")
    assert await regenerate(scene) == [original]
    assert query.await_count == 2
    assert calls["conversation.memory-pass"] == 2


async def test_viewerless_dependencies_accept_none_intro(rag, monkeypatch):
    scene, _, _, conversation = rag
    monkeypatch.setattr(conversation, "rag_knowledge_viewer", lambda _: None)
    boundary = conversation.rag_history_boundary()
    scene.intro = None
    without_intro = conversation.rag_cache_dependencies(None, boundary)
    scene.intro = ""

    assert conversation.rag_cache_dependencies(None, boundary) == without_intro


async def test_removing_retained_edge_from_deleted_message_refreshes_regenerate(
    rag, monkeypatch
):
    scene, _, message, _ = rag
    edge = KnowledgeEdge(
        character="Elmer",
        target="lore",
        source="inferred",
        message_id=message.id,
    )
    scene.world_state.knowledge.append(edge)
    assert scene.pop_message(message)
    assert edge.message_id is None
    original, query, calls, _ = await cached_reply_turn(rag, monkeypatch, "legacy")

    await scene.world_state_manager.remove_knowledge_edge(edge.id)
    assert await regenerate(scene) == [original]
    assert query.await_count == 2
    assert calls["conversation.memory-pass"] == 2


async def test_disabling_memory_pass_does_not_serve_cached_refinement(rag, monkeypatch):
    scene, _, _, conversation = rag
    _, query, calls, dialogue_prompts = await cached_reply_turn(
        rag, monkeypatch, "legacy"
    )
    scene.history.pop()
    monkeypatch.setattr(
        conversation.actions["character_knowledge"].config["memory_pass"],
        "value",
        False,
    )

    await conversation.converse(scene.get_character("Elmer").actor)
    assert query.await_count == 1
    assert calls["conversation.memory-pass"] == 1
    assert "The harbor will close at dusk." in dialogue_prompts[0]
    assert "The harbor will close at dusk." not in dialogue_prompts[-1]
    assert "The harbor closes at dusk." in dialogue_prompts[-1]


async def test_disabling_rag_cache_disables_refinement_lookup_and_store(
    rag, monkeypatch
):
    scene, _, _, conversation = rag
    _, query, calls, _ = await cached_reply_turn(rag, monkeypatch, "legacy")
    entry = next(iter(scene.rag_cache.values()))
    processed_before = dict(entry["processed"])

    class ObservedProcessed(dict):
        writes = 0

        def __setitem__(self, key, value):
            self.writes += 1
            return super().__setitem__(key, value)

    entry["processed"] = observed = ObservedProcessed(entry["processed"])
    scene.history.pop()
    monkeypatch.setattr(
        conversation.actions["use_long_term_memory"].config["cache"],
        "value",
        False,
    )

    actor = scene.get_character("Elmer").actor
    await conversation.converse(actor)
    assert query.await_count == 2
    assert calls["conversation.memory-pass"] == 2
    assert dict(observed) == processed_before
    assert observed.writes == 0
    assert entry in scene.rag_cache.values()


async def test_rag_boundary_ignores_message_storage_stamps(rag):
    scene, _, message, conversation = rag
    before = conversation.rag_history_boundary()
    message.rev += 1
    message.asset_id = "portrait"
    message.asset_type = "avatar"
    assert conversation.rag_history_boundary() == before
    message.hide()
    assert conversation.rag_history_boundary() != before
    message.unhide()
    assert conversation.rag_history_boundary() == before
    message.message = f"{message.message} Changed."
    assert conversation.rag_history_boundary() != before


async def test_rag_dependency_digest_is_memoized_per_memory_revision(rag, monkeypatch):
    scene, memory, _, conversation = rag
    scene.knowledge_eligibility = "legacy"
    get = type(memory.db).get
    digest_reads = 0

    def observed(db, *args, **kwargs):
        nonlocal digest_reads
        if kwargs.get("include") == ["documents", "metadatas"]:
            digest_reads += 1
        return get(db, *args, **kwargs)

    monkeypatch.setattr(type(memory.db), "get", observed)
    boundary = conversation.rag_history_boundary()
    character = scene.character_data["Elmer"]
    for _ in range(5):
        conversation.rag_cache_dependencies(character, boundary)
    assert digest_reads == 1
    scene.memory_revision += 1
    conversation.rag_cache_dependencies(character, boundary)
    assert digest_reads == 2


@pytest.mark.parametrize("viewer", ["author", "shared", "character"])
async def test_non_scoped_rag_cache_tracks_settings_and_collection_generation(
    rag, monkeypatch, viewer
):
    scene, memory, _, conversation = rag
    character = await configure_cached_rag(
        rag, monkeypatch, "legacy", viewer, "queries"
    )
    before_key = conversation.long_term_memory_cache_key_for(character)
    before_dependencies = conversation.rag_cache_dependencies(
        character, conversation.rag_history_boundary()
    )
    recency = memory.actions["retrieval"].config["recency_weight"]
    monkeypatch.setattr(recency, "value", recency.value + 0.1)
    assert conversation.long_term_memory_cache_key_for(character) != before_key
    memory._db_generation += 1
    assert (
        conversation.rag_cache_dependencies(
            character, conversation.rag_history_boundary()
        )
        != before_dependencies
    )


async def test_memory_pass_cache_tracks_resolved_preset_values(rag, monkeypatch):
    scene, _, _, conversation = rag
    _, query, calls, _ = await cached_reply_turn(rag, monkeypatch, "legacy")
    scene.history.pop()
    analytical = get_config().presets.inference.analytical
    monkeypatch.setattr(analytical, "temperature", analytical.temperature + 0.1)

    await conversation.converse(scene.get_character("Elmer").actor)
    assert query.await_count == 1
    assert calls["conversation.memory-pass"] == 2


@pytest.mark.parametrize("mode", ["legacy", "perception"])
@pytest.mark.parametrize("change", ["world_entry", "archive"])
async def test_unrelated_write_invalidates_query_and_memory_pass(
    rag, monkeypatch, mode, change
):
    scene, _, _, _ = rag
    _, query, calls, _ = await cached_reply_turn(rag, monkeypatch, mode)
    if change == "world_entry":
        await scene.world_state_manager.save_world_entry(
            "lore", "The lantern was extinguished.", {}
        )
    else:
        await scene.push_archive(ArchiveEntry(text="A new harbor archive."))

    assert await regenerate(scene)
    assert query.await_count == 2
    assert calls["conversation.memory-pass"] == 2


@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_archive_written_inside_push_history_invalidates_reply_cache(
    rag, monkeypatch, mode
):
    scene, _, _, _ = rag
    _, query, calls, _ = await cached_reply_turn(
        rag, monkeypatch, mode, archive_during_push=True
    )

    assert await regenerate(scene)
    assert query.await_count == 2
    assert calls["conversation.memory-pass"] == 2


@pytest.mark.parametrize("mode", ["legacy", "perception"])
@pytest.mark.parametrize("viewer", ["author", "shared", "character"])
@pytest.mark.parametrize("method", ["queries", "questions"])
@pytest.mark.parametrize("edit", ["world", "detail", "manual", "delete"])
async def test_cached_retrieval_follows_memory_edits(
    rag, monkeypatch, mode, viewer, method, edit
):
    scene, _, _, conversation = rag
    character = await configure_cached_rag(rag, monkeypatch, mode, viewer, method)
    ai = AsyncMock(return_value=[] if method == "queries" else "")
    monkeypatch.setattr(
        get_agent("world_state"),
        "analyze_text_and_extract_context_via_queries"
        if method == "queries"
        else "analyze_text_and_extract_context",
        ai,
    )

    async def save(text):
        if edit == "detail":
            await scene.character_data["Elmer"].set_detail("harbor", text)
        elif edit == "manual":
            await scene.world_state_manager.update_context_db_entry(
                "lore", text, {"source": "manual", "typ": "world_state"}
            )
        else:
            await scene.world_state_manager.save_world_entry("lore", text, {})

    await save("The harbor opens at dawn.")
    history = scene.history[-1].fingerprint
    before = await conversation.rag_build(character)
    assert any("opens at dawn" in doc for doc in before)
    assert await conversation.rag_build(character) == before
    assert ai.await_count == 1

    if edit == "delete":
        await scene.world_state_manager.delete_context_db_entry("lore")
    else:
        await save("The harbor closes at dusk.")
    after = await conversation.rag_build(character)

    assert scene.history[-1].fingerprint == history
    assert ai.await_count == 2
    assert not any("opens at dawn" in doc for doc in after)
    if edit != "delete":
        assert any("closes at dusk" in doc for doc in after)
        assert await conversation.rag_build(character) == after
        assert ai.await_count == 2


@pytest.mark.parametrize("viewer", ["author", "shared", "character"])
@pytest.mark.parametrize("method", ["queries", "questions"])
async def test_memory_edit_during_retrieval_does_not_publish_or_retry(
    rag, monkeypatch, viewer, method
):
    scene, _, _, conversation = rag
    character = await configure_cached_rag(rag, monkeypatch, "legacy", viewer, method)
    await scene.world_state_manager.save_world_entry(
        "lore", "The harbor opens at dawn.", {}
    )
    started, resume = asyncio.Event(), asyncio.Event()

    async def request(*args, **kwargs):
        started.set()
        await asyncio.wait_for(resume.wait(), timeout=5)
        return [] if method == "queries" else ""

    ai = AsyncMock(side_effect=request)
    monkeypatch.setattr(
        get_agent("world_state"),
        "analyze_text_and_extract_context_via_queries"
        if method == "queries"
        else "analyze_text_and_extract_context",
        ai,
    )
    pending = asyncio.create_task(conversation.rag_build(character))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await scene.world_state_manager.save_world_entry(
            "lore", "The harbor closes at dusk.", {}
        )
    finally:
        resume.set()
        current = await asyncio.wait_for(pending, timeout=5)

    assert any("opens at dawn" in doc for doc in current)
    assert ai.await_count == 1
    assert not scene.rag_cache
    assert await conversation.rag_get_cache(character) is None
    fresh = await conversation.rag_build(character)
    assert any("closes at dusk" in doc for doc in fresh)
    assert not any("opens at dawn" in doc for doc in fresh)
    assert ai.await_count == 2
    assert await conversation.rag_build(character) == fresh
    assert ai.await_count == 2


@pytest.mark.parametrize("method", ["queries", "questions"])
async def test_perception_memory_edit_during_retrieval_retries_once(
    rag, monkeypatch, method
):
    scene, _, _, conversation = rag
    character = await configure_cached_rag(
        rag, monkeypatch, "perception", "character", method
    )
    await scene.world_state_manager.save_world_entry(
        "lore", "The harbor opens at dawn.", {}
    )
    started, resume = asyncio.Event(), asyncio.Event()

    async def request(*args, **kwargs):
        started.set()
        await asyncio.wait_for(resume.wait(), timeout=5)
        return [] if method == "queries" else ""

    ai = AsyncMock(side_effect=request)
    monkeypatch.setattr(
        get_agent("world_state"),
        "analyze_text_and_extract_context_via_queries"
        if method == "queries"
        else "analyze_text_and_extract_context",
        ai,
    )
    pending = asyncio.create_task(conversation.rag_build(character))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await scene.world_state_manager.save_world_entry(
            "lore", "The harbor closes at dusk.", {}
        )
    finally:
        resume.set()
        current = await asyncio.wait_for(pending, timeout=5)
    assert ai.await_count == 2
    assert any("closes at dusk" in doc for doc in current)
    assert not any("opens at dawn" in doc for doc in current)
    assert await conversation.rag_build(character) == current
    assert ai.await_count == 2


async def test_audience_cache_digest_follows_built_document_revision(rag, monkeypatch):
    scene, memory, _, conversation = rag
    character = await configure_cached_rag(
        rag, monkeypatch, "perception", "character", "questions"
    )
    monkeypatch.setattr(conversation, "semantic_context", AsyncMock(return_value=[]))
    question_started = asyncio.Event()
    question_release = asyncio.Event()
    answers = 0

    async def answer(*args, **kwargs):
        nonlocal answers
        answers += 1
        if answers == 1:
            question_started.set()
            await asyncio.wait_for(question_release.wait(), timeout=5)
            return "Stale rain lore."
        return "Fresh restricted lore."

    monkeypatch.setattr(
        get_agent("world_state"), "analyze_text_and_extract_context", answer
    )
    sync_started = asyncio.Event()
    sync_release = threading.Event()
    loop = asyncio.get_running_loop()
    sync = memory._sync_audience_documents
    block_once = True

    def blocked_sync(db, documents, fingerprints):
        nonlocal block_once
        if block_once:
            block_once = False
            loop.call_soon_threadsafe(sync_started.set)
            assert sync_release.wait(timeout=5)
        return sync(db, documents, fingerprints)

    monkeypatch.setattr(memory, "_sync_audience_documents", blocked_sync)
    pending = asyncio.create_task(conversation.rag_build(character))
    await asyncio.wait_for(question_started.wait(), timeout=5)
    memory.invalidate_audience_index(scene, groups={("authored",)})
    await asyncio.wait_for(sync_started.wait(), timeout=5)
    scene.world_state.manual_context.pop("lore")
    memory.invalidate_audience_index(scene)
    question_release.set()
    try:
        for _ in range(100):
            if scene.rag_cache:
                break
            await asyncio.sleep(0)
        assert scene.rag_cache
    finally:
        sync_release.set()
    result = await asyncio.wait_for(pending, timeout=5)

    assert answers == 2
    assert "Fresh restricted lore." in result
    assert "Stale rain lore." not in result


@pytest.mark.parametrize("method", ["queries", "questions"])
async def test_scene_rebind_during_retrieval_does_not_publish(rag, monkeypatch, method):
    scene, _, _, conversation = rag
    await configure_cached_rag(rag, monkeypatch, "legacy", "author", method)
    await scene.world_state_manager.save_world_entry(
        "lore", "The harbor opens at dawn.", {}
    )
    replacement = Scene()
    replacement.rag_cache = {}
    replacement.memory_revision = scene.memory_revision
    replacement.history = list(scene.history)
    started, resume = asyncio.Event(), asyncio.Event()

    async def request(*args, **kwargs):
        started.set()
        await asyncio.wait_for(resume.wait(), timeout=5)
        return [] if method == "queries" else ""

    monkeypatch.setattr(
        get_agent("world_state"),
        "analyze_text_and_extract_context_via_queries"
        if method == "queries"
        else "analyze_text_and_extract_context",
        request,
    )
    pending = asyncio.create_task(conversation.rag_build())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        monkeypatch.setattr(conversation, "scene", replacement)
    finally:
        resume.set()
        current = await asyncio.wait_for(pending, timeout=5)
    assert any("opens at dawn" in doc for doc in current)
    assert not scene.rag_cache
    assert not replacement.rag_cache


@pytest.mark.parametrize("edit", ["world", "delete"])
async def test_cancelled_perception_write_refreshes_audience_cache(
    rag, monkeypatch, edit
):
    scene, memory, _, conversation = rag
    character = await configure_cached_rag(
        rag, monkeypatch, "perception", "character", "queries"
    )
    monkeypatch.setattr(
        get_agent("world_state"),
        "analyze_text_and_extract_context_via_queries",
        AsyncMock(return_value=[]),
    )
    manager = scene.world_state_manager
    await manager.save_world_entry("lore", "The harbor opens at dawn.", {})
    before = await conversation.rag_build(character)
    assert any("opens at dawn" in doc for doc in before)
    started, invalidated = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    operation_name = "_add_many" if edit == "world" else "_delete"
    original = getattr(memory, operation_name)
    invalidate = memory.invalidate_audience_index

    def blocked(*args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    def observe_invalidation(*args, **kwargs):
        invalidate(*args, **kwargs)
        invalidated.set()

    monkeypatch.setattr(memory, operation_name, blocked)
    monkeypatch.setattr(memory, "invalidate_audience_index", observe_invalidation)
    pending = asyncio.create_task(
        manager.save_world_entry("lore", "The harbor closes at dusk.", {})
        if edit == "world"
        else manager.delete_context_db_entry("lore")
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        pending.cancel()
        # Deliver cancellation while the actual ChromaDB write is still paused.
        await asyncio.sleep(0)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=5)
        await asyncio.wait_for(invalidated.wait(), timeout=5)
    after = await conversation.rag_build(character)
    assert not any("opens at dawn" in doc for doc in after)
    if edit == "world":
        assert any("closes at dusk" in doc for doc in after)
    else:
        assert "lore" not in scene.world_state.manual_context
        assert not await memory.get_document("lore", viewer=character.name)


async def test_cache_tracks_distance_and_collection_generation(
    rag, monkeypatch, chroma_clients, tmp_path
):
    scene, memory, _, conversation = rag
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    monkeypatch.setattr(config["retrieval_method"], "value", "direct")
    elmer = scene.character_data["Elmer"]
    assert await conversation.rag_build(elmer)
    key = conversation.long_term_memory_cache_key_for(elmer)
    assert len(key) == 64
    with monkeypatch.context() as patch:
        patch.setattr(type(memory), "max_distance", property(lambda self: -1.0))
        assert conversation.long_term_memory_cache_key_for(elmer) != key
        assert not await conversation.rag_build(elmer)
    generation = memory._audience_state(scene).collection_revision
    memory.db = chroma_clients(path=str(tmp_path / "replacement")).create_collection(
        "audience-memory", embedding_function=test_memory_audiences.FixedEmbedding()
    )
    assert await conversation.rag_build(elmer)
    assert memory._audience_state(scene).collection_revision == generation + 1
    assert conversation.long_term_memory_cache_key_for(elmer) == key
    cache = scene.rag_cache[key]
    assert cache["dependencies"]["audience_collection_revision"] == generation + 1


async def test_scoped_metadata_rejects_legacy_and_id_lists_filter_sources(
    rag, monkeypatch
):
    _, memory, _, _ = rag
    documents = await memory.get_document(["F1", "lore", "missing"], viewer="Elmer")
    assert {doc.meta["knowledge_id"] for doc in documents.values()} == {"lore"}
    assert all(identity.startswith("knowledge:") for identity in documents)
    assert await memory.get_document([], viewer="Elmer") == {}
    rag[0].knowledge_eligibility = "legacy"
    with pytest.raises(ValueError, match="requires perception mode"):
        await memory.get_documents_by_meta({"typ": "fact"}, viewer="Elmer")
    with pytest.raises(ValueError, match="requires perception mode"):
        memory._get_documents_by_meta({"typ": "fact"}, viewer="Elmer")


async def test_memory_writes_leave_bounded_invalid_perception_entries(rag, monkeypatch):
    scene, memory, message, conversation = rag
    config = conversation.actions["use_long_term_memory"].config
    monkeypatch.setattr(config["cache"], "value", True)
    viewers = [scene.character_data[name] for name in ("Elmer", "Marie")]
    fingerprint = message.fingerprint
    previous_keys = None
    for number in range(10):
        await scene.world_state_manager.save_world_entry(
            "rolling-update", f"Stored update {number}.", {}
        )
        await memory.ensure_audience_index(scene)
        if previous_keys is not None:
            for viewer in viewers:
                assert await conversation.rag_get_cache(viewer) is None
        keys = set()
        for viewer in viewers:
            await conversation.rag_set_cache([f"Context {number}"], viewer)
            keys.add(conversation.long_term_memory_cache_key_for(viewer))
            assert await conversation.rag_get_cache(viewer) == [f"Context {number}"]
        assert set(scene.rag_cache) == keys
        if previous_keys is not None:
            assert keys == previous_keys
        previous_keys = keys
    assert message.fingerprint == fingerprint


async def test_empty_memory_write_preserves_valid_perception_cache(rag, monkeypatch):
    scene, memory, _, conversation = rag
    monkeypatch.setattr(
        conversation.actions["use_long_term_memory"].config["cache"], "value", True
    )
    await memory.ensure_audience_index(scene)
    viewer = scene.character_data["Elmer"]
    await conversation.rag_set_cache(["Still valid"], viewer)
    cache = dict(scene.rag_cache)
    revision = scene.memory_revision
    await memory.add("")
    assert scene.memory_revision == revision
    assert scene.rag_cache == cache
    assert await conversation.rag_get_cache(viewer) == ["Still valid"]
