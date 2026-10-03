import asyncio
import threading
from contextlib import ExitStack, nullcontext
from unittest.mock import AsyncMock, Mock

import chromadb
from chromadb.api.types import EmbeddingFunction
import pytest

from talemate.agents.memory import ChromaDBMemoryAgent
from talemate.agents.memory.exceptions import MemoryShutdownRefused
from talemate.character import Character
from talemate.context import ActiveScene, SceneIsLoading
import talemate.instance as instance
from talemate.knowledge.disclosures import grant_disclosure
from talemate.knowledge.perspectives import (
    set_source_perspectives,
    source_content_changed,
    reset_perspectives,
)
from talemate.knowledge.schema import EntryVisibility
from talemate.scene_message import NarratorMessage
from talemate.tale_mate import Actor
from talemate.world_state import ManualContext

pytestmark = pytest.mark.asyncio


class FixedEmbedding(EmbeddingFunction):
    def __init__(self):
        pass

    @staticmethod
    def build_from_config(config):
        return FixedEmbedding()

    def __call__(self, input):
        return [[1.0, 0.0] for _ in input]

    @staticmethod
    def name():
        return "audience-test"

    def get_config(self):
        return {}


@pytest.fixture
def chroma_clients():
    # PersistentClient keeps a global System reference until explicitly closed.
    # Release its native threads after every test, including replacement stores.
    with ExitStack() as clients:

        def create(**kwargs):
            return clients.enter_context(chromadb.PersistentClient(**kwargs))

        yield create


@pytest.fixture
async def indexed_scene(scene, monkeypatch, tmp_path, chroma_clients):
    scene.knowledge_eligibility = "perception"
    scene.history = []
    scene.archived_history = []
    scene.layered_history = []
    scene.character_data = {}
    scene.actors = []
    for name in ("Elmer", "Marie"):
        character = Character(name=name, is_player=name == "Elmer")
        actor = Actor(character, instance.get_agent("conversation"))
        actor.scene = scene
        scene.actors.append(actor)
        scene.character_data[name] = character
    scene.active_characters = ["Elmer", "Marie"]
    memory = ChromaDBMemoryAgent()
    memory.client = scene.mock_client
    memory.connect(scene)
    memory.db = chroma_clients(path=str(tmp_path)).create_collection(
        "audience-memory", embedding_function=FixedEmbedding()
    )
    memory._ready_to_add = True
    monkeypatch.setitem(instance.AGENTS, "memory", memory)
    summarizer = instance.get_agent("summarizer")
    summarizer.connect(scene)
    scene.world_state.manual_context["lore"] = ManualContext(
        id="lore",
        text="Common rain lore.",
        meta={"typ": "world_state", "source": "manual", "region": "harbor"},
    )
    message = NarratorMessage(
        message="Reader secret. Marie carries a lantern and hides a coded diary."
    )
    scene.history.append(message)
    with ActiveScene(scene):
        set_source_perspectives(
            scene,
            "message",
            message.id,
            [
                {
                    "audience": ["Elmer"],
                    "text": "Marie carries a lantern.",
                    "status": "ready",
                },
                {
                    "audience": ["Marie"],
                    "text": "Marie hides a coded diary.",
                    "status": "ready",
                },
            ],
        )
        await memory.add(message.message, uid="reader", typ="history")
        yield scene, memory, message


async def contents(memory, viewer="Elmer", **where):
    return {
        doc.raw
        for doc in await memory.get("lantern", viewer=viewer, limit=100, **where)
    }


async def test_real_chroma_union_selects_supported_text_and_composes_scopes(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    calls = []
    query = type(memory.db).query

    def observed(db, **kwargs):
        calls.append(kwargs)
        return query(db, **kwargs)

    monkeypatch.setattr(type(memory.db), "query", observed)
    selected = await contents(memory)
    assert "Common rain lore." in selected
    assert any("Marie carries a lantern." in text for text in selected)
    assert not any(
        "Reader secret" in text or "coded diary" in text for text in selected
    )
    assert len(calls) == 1
    assert "$or" in str(calls[0]["where"])
    assert await contents(memory, region="harbor") == {"Common rain lore."}
    assert await contents(memory, typ="fact") == set()
    assert await contents(memory, character="Marie", typ="fact") == set()
    author = await contents(memory, viewer=None)
    assert any("Reader secret" in text for text in author)
    assert not any(
        doc.meta.get("knowledge_index")
        for doc in await memory.get("lantern", limit=100)
    )


async def test_visibility_updates_resync_common_and_named_audiences(indexed_scene):
    scene, memory, _ = indexed_scene
    manager = scene.world_state_manager
    assert "Common rain lore." in await contents(memory)
    await manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="list", characters=["Marie"])
    )
    assert "Common rain lore." not in await contents(memory)
    assert "Common rain lore." in await contents(memory, "Marie")
    await manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="list", characters=["Elmer"])
    )
    assert "Common rain lore." in await contents(memory)
    assert "Common rain lore." not in await contents(memory, "Marie")
    await manager.set_world_entry_visibility("lore", EntryVisibility(mode="owner"))
    assert "Common rain lore." not in await contents(memory)
    await manager.set_world_entry_visibility("lore", EntryVisibility())
    assert "Common rain lore." in await contents(memory, "Marie")


async def test_authored_sheet_visibility_uses_audience_not_subject(indexed_scene):
    scene, memory, _ = indexed_scene
    marie = scene.character_data["Marie"]
    await marie.set_base_attribute("secret", "Private family name")
    await scene.world_state_manager.set_character_entry_visibility(
        "Marie", "secret", EntryVisibility(mode="owner")
    )
    assert not await contents(memory, character="Marie", typ="base_attribute")
    await scene.world_state_manager.set_character_entry_visibility(
        "Marie", "secret", EntryVisibility(mode="list", characters=["Elmer"])
    )
    assert await contents(memory, character="Marie", typ="base_attribute") == {
        "Marie's secret: Private family name"
    }


async def test_supported_rename_resyncs_views_and_visibility(indexed_scene):
    scene, memory, _ = indexed_scene
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="list", characters=["Elmer"])
    )
    before = await contents(memory)
    scene.character_data["Elmer"].rename("Elias")
    assert await contents(memory, "Elias") == before
    with pytest.raises(ValueError, match="Unknown memory viewer"):
        await contents(memory, "Elmer")
    stored = memory.db.get(where={"knowledge_index": True}, include=["metadatas"])
    assert not any(
        "Elmer" in meta.get("knowledge_audience", ()) for meta in stored["metadatas"]
    )


async def test_source_edit_removes_stale_views_but_keeps_disclosure(
    indexed_scene,
):
    scene, memory, message = indexed_scene
    scene.archived_history.append(
        {
            "id": "origin",
            "text": "Only the selected sentence. Private remainder.",
            "start": 0,
            "end": 0,
            "ts": 0,
        }
    )
    grant_disclosure(scene, "Elmer", "origin", text="Only the selected sentence.")
    assert "Only the selected sentence." in await contents(memory)
    message.message = "Changed reader secret."
    source_content_changed(scene, "message", message.id)
    selected = await contents(memory)
    assert "Only the selected sentence." in selected
    assert not any(
        "lantern" in text
        or "reader secret" in text.lower()
        or "Private remainder" in text
        for text in selected
    )
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {"audience": ["Elmer"], "text": "Marie left.", "status": "ready"},
            {"audience": ["Marie"], "status": "omitted"},
        ],
    )
    assert any("Marie left." in text for text in await contents(memory))
    assert not any("Marie left." in text for text in await contents(memory, "Marie"))


async def test_hidden_sources_are_not_searchable(indexed_scene):
    _, memory, message = indexed_scene
    assert any("Marie carries a lantern." in text for text in await contents(memory))
    message.hide()
    assert await contents(memory, typ="fact") == set()
    assert not any("lantern" in text for text in await contents(memory))
    message.unhide()
    assert any("Marie carries a lantern." in text for text in await contents(memory))


async def test_rebuild_and_metadata_replacement_remove_obsolete_audiences(
    indexed_scene,
):
    scene, memory, message = indexed_scene
    before = await contents(memory)
    memory.db.delete(where={"knowledge_index": True})
    await memory.rebuild_audience_index()
    assert await contents(memory) == before
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {
                "audience": ["Marie"],
                "text": "Marie carries a lantern.",
                "status": "ready",
            },
            {"audience": ["Elmer"], "status": "omitted"},
        ],
    )
    assert not any("lantern" in text for text in await contents(memory))
    assert any("lantern" in text for text in await contents(memory, "Marie"))
    await memory.rebuild_audience_index()
    assert not any("lantern" in text for text in await contents(memory))


async def test_failed_index_write_blocks_query_and_retries(indexed_scene, monkeypatch):
    scene, memory, _ = indexed_scene
    await contents(memory)
    original = memory._sync_audience_documents
    attempts = 0

    def fail(db, documents, fingerprints):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Index write failed")

    monkeypatch.setattr(memory, "_sync_audience_documents", fail)
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="owner")
    )
    with pytest.raises(RuntimeError, match="Index write failed"):
        await contents(memory)
    assert attempts
    monkeypatch.setattr(memory, "_sync_audience_documents", original)
    assert "Common rain lore." not in await contents(memory)


async def test_legacy_viewer_is_rejected_without_backfill(indexed_scene):
    scene, memory, _ = indexed_scene
    await memory.ensure_audience_index(scene)
    await memory.purge_audience_index(scene)
    scene.knowledge_eligibility = "legacy"
    before = memory.db.count()
    with pytest.raises(ValueError, match="requires perception mode"):
        await contents(memory)
    await memory.rebuild_audience_index()
    assert memory.db.count() == before
    assert memory.db.get(where={"knowledge_index": True})["ids"] == []


async def test_unchanged_and_unrelated_documents_are_not_reembedded(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    calls = []
    upsert = type(memory.db).upsert

    def observed(db, **kwargs):
        calls.extend(kwargs["metadatas"])
        return upsert(db, **kwargs)

    monkeypatch.setattr(type(memory.db), "upsert", observed)
    await contents(memory)
    assert calls == []
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="list", characters=["Marie"])
    )
    await contents(memory)
    assert calls and all(meta["knowledge_source"] == "lore" for meta in calls)


async def test_shared_current_cast_does_not_authorize_a_future_character(indexed_scene):
    scene, memory, message = indexed_scene
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {
                "audience": ["Elmer", "Marie"],
                "text": "They both see the lantern.",
                "status": "ready",
            }
        ],
    )
    await contents(memory)
    scene.character_data["Newcomer"] = Character(name="Newcomer")
    assert await contents(memory, "Newcomer") == {"Common rain lore."}


async def test_scene_switch_never_installs_into_the_next_collection(
    indexed_scene, monkeypatch, tmp_path, chroma_clients
):
    from talemate.tale_mate import Scene

    scene, memory, _ = indexed_scene
    await contents(memory)
    original = memory._sync_audience_documents
    next_scene = Scene()
    next_scene.knowledge_eligibility = "perception"
    next_db = chroma_clients(path=str(tmp_path / "next")).create_collection(
        "next-audience-memory", embedding_function=FixedEmbedding()
    )

    def switch(db, documents, fingerprints):
        memory.scene = next_scene
        memory.db = next_db
        return original(db, documents, fingerprints)

    monkeypatch.setattr(memory, "_sync_audience_documents", switch)
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="owner")
    )
    with pytest.raises(RuntimeError, match="scene or collection"):
        await memory.ensure_audience_index(scene)
    assert next_db.count() == 0


async def test_cancelled_write_finishes_before_a_retry_can_publish(
    indexed_scene, monkeypatch
):
    import threading

    scene, memory, _ = indexed_scene
    await contents(memory)
    state = memory._audience_state(scene)
    await memory.ensure_audience_index(scene)
    started, release = threading.Event(), threading.Event()
    original = memory._sync_audience_documents
    first = True

    def blocked(db, documents, fingerprints):
        nonlocal first
        if first:
            first = False
            started.set()
            assert release.wait(5)
        return original(db, documents, fingerprints)

    monkeypatch.setattr(memory, "_sync_audience_documents", blocked)
    state.revision += 1
    writer = asyncio.create_task(memory.ensure_audience_index(scene))
    await asyncio.to_thread(started.wait, 5)
    writer.cancel()
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="owner")
    )
    retry = asyncio.create_task(contents(memory))
    await asyncio.sleep(0)
    assert not writer.done()
    assert not retry.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await writer
    assert "Common rain lore." not in await retry


@pytest.mark.parametrize("method", ["purge_audience_index", "ensure_audience_index"])
async def test_audience_cancel_then_refusal_preserves_cancellation(
    indexed_scene, monkeypatch, method
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    state = memory._audience_state(scene)
    await memory.ensure_audience_index(scene)
    state.revision += 1
    started, release = asyncio.Event(), asyncio.Event()

    async def refuse(*args, **kwargs):
        started.set()
        await release.wait()
        raise MemoryShutdownRefused()

    monkeypatch.setattr(memory, "_to_thread", refuse)
    task = asyncio.create_task(getattr(memory, method)(scene))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert state.lock.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert task.cancelling() == 1
    assert not state.lock.locked()
    assert state.fingerprints is None
    assert state.dirty is None


@pytest.mark.parametrize("queued", [False, True])
async def test_audience_read_refusal_cancels_without_result(
    indexed_scene, monkeypatch, queued
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    await memory.ensure_audience_index(scene)
    started, release = asyncio.Event(), asyncio.Event()
    applied = Mock()

    async def refuse(*args, **kwargs):
        started.set()
        await release.wait()
        raise MemoryShutdownRefused()

    monkeypatch.setattr(memory, "_to_thread", refuse)

    async def read():
        applied(
            await memory.audience_read(memory._get_document, "lore", viewer="Elmer")
        )

    if not queued:
        memory.refuse_new_memory_work()
    task = asyncio.create_task(read())
    if queued:
        await asyncio.wait_for(started.wait(), 2)
        memory.refuse_new_memory_work()
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert task.cancelling() == 1
    applied.assert_not_called()


async def test_shutdown_while_waiting_for_audience_lock_cancels_read(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    state = memory._audience_state(scene)
    await memory.ensure_audience_index(scene)
    warning = Mock()
    monkeypatch.setattr("talemate.agents.memory.audiences.log.warning", warning)
    async with state.lock:
        task = asyncio.create_task(contents(memory, viewer=None))
        await asyncio.sleep(0)
        assert not task.done()
        memory.refuse_new_memory_work()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert task.cancelling() == 1
    warning.assert_not_called()


async def test_saved_sources_rebuild_an_empty_real_collection(
    indexed_scene, monkeypatch, tmp_path, chroma_clients
):
    import json
    from talemate.load import load_scene_from_data
    from talemate.tale_mate import Scene

    scene, memory, _ = indexed_scene
    grant_disclosure(scene, "Elmer", "lore", text="An explicitly learned rain fact.")
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="list", characters=["Elmer"])
    )
    expected = {name: await contents(memory, name) for name in ("Elmer", "Marie")}
    saved = json.loads(scene.json)
    restored = Scene()
    memory.connect(restored)
    memory.db = chroma_clients(path=str(tmp_path / "restored")).create_collection(
        "restored-audience-memory", embedding_function=FixedEmbedding()
    )
    monkeypatch.setattr(memory, "set_db", AsyncMock())
    with ActiveScene(restored):
        await load_scene_from_data(restored, saved, name="audience-reload.json")
        await memory.rebuild_audience_index()
        assert {name: await contents(memory, name) for name in expected} == expected


async def test_author_queries_survive_audience_write_failure(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    canonical = {"character": "Marie", "typ": "details", "detail": "occupation"}
    await memory.add_many(
        [{"id": "occupation", "text": "Marie is a sailor.", "meta": canonical}]
    )
    await memory.ensure_audience_index(scene)

    def fail(*args):
        raise RuntimeError("Index write failed")

    monkeypatch.setattr(memory, "_sync_audience_documents", fail)
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="owner")
    )
    assert "Marie is a sailor." in await contents(memory, viewer=None)
    assert set(await memory.get_documents_by_meta(canonical)) == {"occupation"}
    with pytest.raises(RuntimeError, match="Index write failed"):
        await contents(memory)


async def test_author_query_without_collection_degrades(indexed_scene):
    scene, memory, _ = indexed_scene
    await contents(memory)
    await memory.ensure_audience_index(scene)
    memory.db = None
    memory._ready_to_add = False
    assert await contents(memory, viewer=None) == set()
    assert await memory.get_documents_by_meta({"typ": "history"}) == {}
    with pytest.raises(RuntimeError, match="not writable"):
        await contents(memory)


async def test_cast_membership_updates_without_character_memory_writes(indexed_scene):
    scene, memory, _ = indexed_scene
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="list", characters=["Future"])
    )
    await contents(memory)
    future = Character(name="Future")
    assert future.memory_documents() == []
    await scene.add_actor(
        Actor(future, instance.get_agent("conversation")), commit_to_memory=False
    )
    assert "Common rain lore." in await contents(memory, "Future")
    await scene.remove_character(future, purge_from_memory=False)
    await contents(memory)
    stored = memory.db.get(where={"knowledge_index": True}, include=["metadatas"])
    assert not any(
        "Future" in meta.get("knowledge_audience", ()) for meta in stored["metadatas"]
    )


async def test_reset_removes_indexed_history_and_disclosures(
    indexed_scene,
):
    scene, memory, _ = indexed_scene
    grant_disclosure(scene, "Elmer", "lore", text="An independent remembered detail.")
    assert any("lantern" in text for text in await contents(memory))
    assert "An independent remembered detail." in await contents(memory)
    scene.history = []
    assert reset_perspectives(scene) is None
    assert await contents(memory) == {"Common rain lore."}


@pytest.mark.parametrize("guard", ["readonly", "not_ready"])
async def test_direct_index_call_does_not_write_unavailable_collection(
    indexed_scene, guard
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    await memory.ensure_audience_index(scene)
    scene._memory_never_persisted = False
    scene.immutable_save = False
    before = memory.db.get(include=["metadatas", "documents"])
    scene.history = []
    if guard == "not_ready":
        memory._ready_to_add = False
    with SceneIsLoading(scene) if guard == "readonly" else nullcontext():
        with pytest.raises(RuntimeError, match="not writable"):
            await memory.rebuild_audience_index()
        assert memory.db.get(include=["metadatas", "documents"]) == before
    memory._ready_to_add = True
    await memory.ensure_audience_index(scene)
    assert not any("lantern" in text for text in await contents(memory))


async def test_reconcile_marks_preexisting_rows_without_losing_metadata(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    await memory.ensure_audience_index(scene)
    scene.knowledge_eligibility = "legacy"
    metadata = {
        "character": "Marie",
        "typ": "base_attribute",
        "attr": "occupation",
        "ts": 12,
        "pin_only": False,
    }
    await memory.add_many(
        [{"id": "old-sheet", "text": "Marie is a sailor.", "meta": metadata}]
    )
    original = memory.db.get(ids=["old-sheet"], include=["metadatas"])["metadatas"][0]
    assert "knowledge_index" not in original
    scene.knowledge_eligibility = "perception"
    await memory.rebuild_audience_index()
    marked = memory.db.get(ids=["old-sheet"], include=["metadatas"])["metadatas"][0]
    assert marked == {**original, "knowledge_index": False}
    assert set(await memory.get_documents_by_meta(metadata)) == {"old-sheet"}
    assert "Marie is a sailor." in await contents(memory, viewer=None)
    assert "Marie is a sailor." not in await contents(memory)


async def test_sheet_visibility_uses_metadata_when_document_ids_change(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    marie = scene.character_data["Marie"]
    await marie.set_base_attribute("secret", "Private family name")
    await scene.world_state_manager.set_character_entry_visibility(
        "Marie", "secret", EntryVisibility(mode="owner")
    )
    original = Character.memory_documents

    def prefixed(character):
        return [{**doc, "id": f"sheet:{doc['id']}"} for doc in original(character)]

    monkeypatch.setattr(Character, "memory_documents", prefixed)
    await memory.rebuild_audience_index()
    assert not await contents(memory, character="Marie", typ="base_attribute")
    assert await contents(memory, "Marie", character="Marie", typ="base_attribute") == {
        "Marie's secret: Private family name"
    }


async def test_source_updates_and_memory_writes_do_not_rederive_unrelated_views(
    indexed_scene, monkeypatch
):
    import talemate.knowledge.memory as materializer

    scene, memory, changed = indexed_scene
    other = NarratorMessage(message="An unrelated bell rings.")
    scene.history.append(other)
    set_source_perspectives(
        scene,
        "message",
        other.id,
        [{"audience": ["Elmer"], "text": "Elmer hears a bell.", "status": "ready"}],
    )
    await contents(memory)
    selected = []
    select = materializer.select_character_view

    def observed(scene, reference, name, **kwargs):
        selected.append(reference.key)
        return select(scene, reference, name, **kwargs)

    monkeypatch.setattr(materializer, "select_character_view", observed)
    set_source_perspectives(
        scene,
        "message",
        changed.id,
        [
            {
                "audience": ["Elmer"],
                "text": "Marie lowered the lantern.",
                "status": "ready",
            }
        ],
    )
    result = await contents(memory)
    assert selected and set(selected) == {("message", changed.id, 0)}
    assert "Elmer hears a bell." in result
    assert "Marie lowered the lantern." in result
    assert await contents(memory, typ="fact") == set()
    selected.clear()
    await memory.add_many(
        [{"id": "lore", "text": "Common rain lore.", "meta": {"typ": "world_state"}}]
    )
    assert "Elmer hears a bell." in await contents(memory)
    assert selected == []


async def test_failed_partial_sync_rebuilds_latest_sources(indexed_scene, monkeypatch):
    scene, memory, message = indexed_scene
    await contents(memory)
    sync = memory._sync_audience_documents
    attempts = 0

    def fail_once(db, documents, fingerprints):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Partial update failed")
        return sync(db, documents, fingerprints)

    monkeypatch.setattr(memory, "_sync_audience_documents", fail_once)
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [
            {
                "audience": ["Elmer"],
                "text": "Marie put the lantern down.",
                "status": "ready",
            }
        ],
    )
    with pytest.raises(RuntimeError, match="Partial update failed"):
        await memory.ensure_audience_index(scene)
    result = await contents(memory)
    assert "Marie put the lantern down." in result
    assert not any("Marie carries" in text for text in result)
    assert "Common rain lore." in result


@pytest.mark.parametrize("canonical_write", [False, True])
@pytest.mark.parametrize("kind", ["message", "summary"])
async def test_removed_source_without_notification_drops_cached_rows(
    indexed_scene, kind, canonical_write
):
    scene, memory, message = indexed_scene
    if kind == "summary":
        scene.layered_history = [[{"id": "L7", "text": "Reader summary.", "ts": 0}]]
        set_source_perspectives(
            scene,
            "summary",
            "L7",
            [{"audience": ["Elmer"], "text": "A layered memory.", "status": "ready"}],
            layer=1,
        )
        removed_text = "A layered memory."
    else:
        removed_text = "Marie carries a lantern."
    assert removed_text in await contents(memory, typ="history")
    state = memory._audience_state(scene)
    await memory.ensure_audience_index(scene)
    assert state.dirty == set()
    if kind == "summary":
        scene.layered_history = []
    else:
        scene.history.remove(message)
    if canonical_write:
        await memory.add("An unrelated canonical update.", uid="unrelated")
    result = await contents(memory)
    assert removed_text not in result
    assert "Common rain lore." in result
    stored = memory.db.get(where={"knowledge_index": True}, include=["documents"])
    assert removed_text not in stored["documents"]


async def test_rename_you_refreshes_owner_and_list_authored_audiences(indexed_scene):
    scene, memory, _ = indexed_scene
    player = scene.character_data["Elmer"]
    player.rename("You")
    await player.set_base_attribute("secret", "You keep a private name.")
    await scene.world_state_manager.set_character_entry_visibility(
        "You", "secret", EntryVisibility(mode="owner")
    )
    await scene.world_state_manager.set_world_entry_visibility(
        "lore", EntryVisibility(mode="list", characters=["You"])
    )
    assert "You's secret: You keep a private name." in await contents(memory, "You")
    assert "Common rain lore." in await contents(memory, "You")
    player.rename("Alice")
    assert player.base_attributes["secret"] == "You keep a private name."
    assert "Alice's secret: You keep a private name." in await contents(memory, "Alice")
    assert "Common rain lore." in await contents(memory, "Alice")
    assert not await contents(memory, "Marie", typ="base_attribute")
    assert "Common rain lore." not in await contents(memory, "Marie")
    stored = memory.db.get(where={"knowledge_index": True}, include=["metadatas"])
    assert not any(
        "You" in meta.get("knowledge_audience", ()) for meta in stored["metadatas"]
    )


async def test_author_reads_unmarked_rows_when_first_reconcile_fails(
    indexed_scene, monkeypatch, tmp_path, chroma_clients
):
    scene, memory, _ = indexed_scene
    await contents(memory)
    await memory.ensure_audience_index(scene)
    memory.db = chroma_clients(path=str(tmp_path / "pre-gate")).create_collection(
        "pre-gate-memory", embedding_function=FixedEmbedding()
    )
    scene.knowledge_eligibility = "legacy"
    metadata = {"character": "Marie", "typ": "base_attribute", "attr": "occupation"}
    await memory.add_many(
        [{"id": "old-sheet", "text": "Marie is a sailor.", "meta": metadata}]
    )
    original = memory.db.get(ids=["old-sheet"], include=["metadatas"])["metadatas"][0]
    assert "knowledge_index" not in original
    # Persisted managed variants must still be excluded from both author paths.
    memory.db.add(
        ids=["knowledge:old-variant"],
        documents=["A character-only variant."],
        metadatas=[{**metadata, "knowledge_index": True}],
    )

    def fail(*args, **kwargs):
        raise RuntimeError("Initial marking failed")

    monkeypatch.setattr(type(memory.db), "update", fail)
    scene.knowledge_eligibility = "perception"
    assert await contents(memory, viewer=None) == {"Marie is a sailor."}
    assert set(await memory.get_documents_by_meta(metadata)) == {"old-sheet"}
    assert (
        memory.db.get(ids=["old-sheet"], include=["metadatas"])["metadatas"][0]
        == original
    )
    with pytest.raises(RuntimeError, match="Initial marking failed"):
        await contents(memory)


@pytest.mark.parametrize("queued_rebuild", [False, True])
async def test_switch_off_purges_audience_rows_and_cached_state(
    indexed_scene, queued_rebuild
):
    from talemate.world_state.manager import WorldStateManager

    scene, memory, _ = indexed_scene
    scene.history = []
    scene.character_data["Marie"].description = "Marie tends the lighthouse."
    await scene.character_data["Marie"].commit_to_memory(memory)
    await memory.ensure_audience_index(scene)
    stored = memory.db.get(where={"knowledge_index": True})
    assert stored["ids"]
    canonical = memory.db.get(where={"knowledge_index": False})["ids"]
    assert canonical
    state = memory._audience_state(scene)
    assert state.documents

    if queued_rebuild:
        await state.lock.acquire()
        switch = asyncio.create_task(
            WorldStateManager(scene).update_scene_settings(
                knowledge_eligibility="legacy"
            )
        )
        await asyncio.sleep(0)
        rebuild = asyncio.create_task(memory.ensure_audience_index(scene))
        await asyncio.sleep(0)
        state.lock.release()
        await switch
        await rebuild
    else:
        await WorldStateManager(scene).update_scene_settings(
            knowledge_eligibility="legacy"
        )

    assert memory.db.get(where={"knowledge_index": True})["ids"] == []
    assert memory.db.get(where={"knowledge_index": False})["ids"] == canonical
    assert scene not in memory._audience_states
    await memory.ensure_audience_index(scene)
    assert memory.db.get(where={"knowledge_index": True})["ids"] == []
    results = await memory.get("lighthouse", limit=100)
    assert all(not doc.meta.get("knowledge_index") for doc in results)


async def test_empty_world_state_commit_refreshes_authored_audiences(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    assert "Common rain lore." in await contents(memory)
    state = memory._audience_state(scene)
    await memory.ensure_audience_index(scene)
    audience_revision = state.revision
    memory_revision = scene.memory_revision
    scene.world_state.manual_context.clear()
    upsert = Mock(side_effect=AssertionError("Empty input must not write the store"))
    monkeypatch.setattr(memory, "_add_many", upsert)

    await scene.world_state.commit_to_memory(memory)

    assert state.revision > audience_revision
    assert scene.memory_revision == memory_revision
    upsert.assert_not_called()
    assert "Common rain lore." not in await contents(memory)


async def test_cancelled_direct_delete_removes_stale_audience_projection(
    indexed_scene, monkeypatch
):
    scene, memory, _ = indexed_scene
    await scene.world_state.commit_to_memory(memory)
    assert "Common rain lore." in await contents(memory)
    await memory.ensure_audience_index(scene)
    assert memory.db.get(ids=["lore"])["ids"] == ["lore"]
    scene.world_state.manual_context.pop("lore")
    loop = asyncio.get_running_loop()
    started, invalidated = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    delete = memory._delete
    invalidate = memory.invalidate_audience_index

    def blocked(meta):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        delete(meta)

    def observe(*args, **kwargs):
        invalidate(*args, **kwargs)
        invalidated.set()

    monkeypatch.setattr(memory, "_delete", blocked)
    monkeypatch.setattr(memory, "invalidate_audience_index", observe)
    pending = asyncio.create_task(memory.delete({"ids": ["lore"]}))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not invalidated.is_set()
    finally:
        release.set()
        await asyncio.wait_for(invalidated.wait(), timeout=5)

    assert memory.db.get(ids=["lore"])["ids"] == []
    assert "Common rain lore." not in await contents(memory)
    stored = memory.db.get(where={"knowledge_index": True}, include=["documents"])
    assert "Common rain lore." not in stored["documents"]


async def test_stale_views_stay_in_the_audience_index(indexed_scene):
    from talemate.knowledge.perspective_models import content_digest

    scene, memory, message = indexed_scene
    object.__setattr__(message, "present", ["Elmer", "Marie"])
    kept = "Marie carries a lantern."
    await memory.rebuild_audience_index()
    assert any(kept in text for text in await contents(memory))
    object.__setattr__(
        message,
        "knowledge",
        message.knowledge.model_copy(
            update={"content_digest": content_digest("An older text.")}
        ),
    )
    await memory.rebuild_audience_index()
    # out of sync, but still what the character last knew
    assert any(kept in text for text in await contents(memory))
