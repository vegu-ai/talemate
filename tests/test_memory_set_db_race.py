"""Unit tests for the `_set_db` / `close_db` race.

`set_db` runs `_set_db` in an executor thread, so cancelling the awaiting task
(a websocket disconnect mid-load) does not stop the thread. Without the
generation guard the thread installs a db handle for a scene that has already
been released, leaking an orphan collection on disk.

Cleanup belongs to `close_db`, which works from the released scene's name and
therefore no longer needs an installed handle; a stale `_set_db` only drops
what it built. The race is simulated deterministically: the fake db client
performs the mid-flight mutation from inside `get_or_create_collection`, which
is exactly where the real thread is parked when the disconnect lands.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

import chromadb.errors

import talemate.agents.memory as memory
from talemate.agents.memory import ChromaDBMemoryAgent


class _FakeCollection:
    def __init__(self, name: str, count: int = 0, count_error=None):
        self.name = name
        self._count = count
        self.count_error = count_error
        self.deletes = []
        self.upserts = []

    def count(self):
        if self.count_error:
            raise self.count_error
        return self._count

    def delete(self, **kwargs):
        self.deletes.append(kwargs)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)


class _FakeDBClient:
    """Records collection handling and can mutate the agent mid-flight."""

    def __init__(self, count: int = 0):
        self.count = count
        self.count_error = None
        self.delete_error = None
        self.collections = {}
        self.deleted = []
        self.before_get_or_create = None
        self.on_get_or_create = None

    def get_or_create_collection(self, name, embedding_function=None, metadata=None):
        if self.before_get_or_create:
            self.before_get_or_create(name)
        collection = self.collections.setdefault(
            name, _FakeCollection(name, self.count, self.count_error)
        )
        if self.on_get_or_create:
            self.on_get_or_create(name)
        return collection

    def get_collection(self, name):
        try:
            return self.collections[name]
        except KeyError:
            raise chromadb.errors.NotFoundError()

    def delete_collection(self, name):
        if self.delete_error:
            raise self.delete_error
        if name not in self.collections:
            raise chromadb.errors.NotFoundError()
        self.deleted.append(name)
        self.collections.pop(name)


class _FakeScene:
    """Only the attributes the db lifecycle reads."""

    def __init__(
        self,
        memory_id="scene-1",
        saved=False,
        memory_session_id="session-new",
        saved_memory_session_id=None,
    ):
        self.memory_id = memory_id
        self.memory_revision = 0
        self.saved = saved
        self.memory_session_id = memory_session_id
        self.saved_memory_session_id = saved_memory_session_id


@pytest.fixture(autouse=True)
def no_embedding_model(monkeypatch):
    """Keep the sentence-transformer branch from constructing a real model."""

    class _FakeSentenceTransformerEmbeddingFunction:
        models = {}

        def __init__(self, model_name=None, trust_remote_code=False, device=None):
            self.model_name = model_name

    class _FakeEmbeddingFunctions:
        SentenceTransformerEmbeddingFunction = _FakeSentenceTransformerEmbeddingFunction

    monkeypatch.setattr(memory, "embedding_functions", _FakeEmbeddingFunctions)


@pytest.fixture
def agent():
    """A ChromaDBMemoryAgent without the signal connections `__init__` makes."""
    agent = object.__new__(ChromaDBMemoryAgent)
    agent.db = None
    agent.memory_tracker = {}
    agent._ready_to_add = False
    agent._db_generation = 0
    agent._db_lock = threading.Lock()
    agent.actions = ChromaDBMemoryAgent.init_actions()
    agent.db_client = _FakeDBClient()
    agent.scene = _FakeScene()
    return agent


def test_set_db_installs_the_handle(agent):
    scene = agent.scene

    agent._set_db()

    collection_name = agent.make_collection_name(scene)
    assert agent.db is agent.db_client.collections[collection_name]
    assert agent.collection_name == collection_name
    assert agent._ready_to_add is True
    assert scene._memory_never_persisted is True


def test_set_db_records_a_populated_collection_as_persisted(agent):
    agent.db_client.count = 3
    scene = agent.scene

    agent._set_db()

    assert scene._memory_never_persisted is False


def test_disconnect_mid_set_only_drops_the_handle(agent):
    scene = agent.scene
    released = _FakeScene(memory_id="scene-2")

    def disconnect(name):
        agent.close_db(scene)
        agent.scene = released

    agent.db_client.on_get_or_create = disconnect
    collection_name = agent.make_collection_name(scene)

    agent._set_db()

    assert agent.db is None
    assert agent._ready_to_add is False
    # exactly one delete, from `close_db` - the stale thread cleans up nothing
    assert agent.db_client.deleted == [collection_name]


def test_scene_rebind_alone_drops_the_handle(agent):
    scene = agent.scene
    collection_name = agent.make_collection_name(scene)

    def rebind(name):
        agent.scene = _FakeScene(memory_id="scene-2")

    agent.db_client.on_get_or_create = rebind

    agent._set_db()

    assert agent.db is None
    assert agent._ready_to_add is False
    assert agent.db_client.deleted == []
    assert agent.db_client.collections[collection_name].deletes == []


def test_a_rename_while_naming_the_collection_refuses_the_install(agent):
    scene = agent.scene
    real_make_collection_name = agent.make_collection_name
    renamed = []

    def rename_after_naming(scene_arg):
        # what `save_as` does: close_db, then a new memory_id, then commit
        name = real_make_collection_name(scene_arg)
        if not renamed:
            renamed.append(name)
            agent.close_db(scene)
            scene.memory_id = "scene-renamed"
        return name

    agent.make_collection_name = rename_after_naming

    agent._set_db()

    assert agent.db is None
    assert agent._ready_to_add is False


def test_stale_build_leaves_an_empty_shell(agent):
    scene = agent.scene
    collection_name = agent.make_collection_name(scene)

    def disconnect(name):
        agent.close_db(scene)
        agent.scene = _FakeScene(memory_id="scene-2")

    # the release lands before the collection exists, so the stale build
    # re-creates it - the documented residual
    agent.db_client.before_get_or_create = disconnect

    agent._set_db()

    shell = agent.db_client.collections[collection_name]
    assert shell.upserts == []
    assert shell.count() == 0
    assert agent.db is None
    assert agent.db_client.deleted == []


def test_close_db_survives_a_missing_collection(agent):
    # what `release_scene` passes: a placeholder scene with no collection on disk
    placeholder = _FakeScene(memory_id="placeholder")

    agent.close_db(placeholder)

    assert agent.db_client.deleted == []


def test_close_db_discards_a_never_saved_scene_without_a_handle(agent):
    scene = agent.scene
    collection_name = agent.make_collection_name(scene)
    agent.db_client.collections[collection_name] = _FakeCollection(collection_name)

    agent.close_db(scene)

    assert agent.db_client.deleted == [collection_name]


def test_close_db_removes_unsaved_memory_without_a_handle(agent):
    scene = agent.scene
    scene.saved_memory_session_id = "session-old"
    collection_name = agent.make_collection_name(scene)
    collection = _FakeCollection(collection_name)
    agent.db_client.collections[collection_name] = collection

    agent.close_db(scene)

    assert agent.db_client.deleted == []
    assert collection.deletes == [
        {
            "where": {
                "$and": [
                    {"session": "session-new"},
                    {"source": "talemate"},
                ]
            }
        }
    ]


def test_close_db_honors_remove_unsaved_memory_false(agent):
    scene = agent.scene
    scene.saved_memory_session_id = "session-old"
    collection_name = agent.make_collection_name(scene)
    collection = _FakeCollection(collection_name)
    agent.db_client.collections[collection_name] = collection

    agent.close_db(scene, remove_unsaved_memory=False)

    assert collection.deletes == []
    assert agent.db_client.deleted == []


def test_close_db_drops_the_handle_even_when_cleanup_raises(agent):
    scene = agent.scene
    agent._set_db()
    generation = agent._db_generation
    agent.db_client.delete_error = RuntimeError("delete failed")

    with pytest.raises(RuntimeError, match="delete failed"):
        agent.close_db(scene)

    assert agent.db is None
    assert agent._ready_to_add is False
    assert agent._db_generation == generation + 1


def test_close_db_bumps_the_generation_without_a_handle(agent):
    scene = _FakeScene(saved=True, saved_memory_session_id="session-new")
    generation = agent._db_generation

    agent.close_db(scene)

    assert agent._db_generation == generation + 1
    assert agent.db is None
    assert agent.db_client.deleted == []


def test_drop_db_bumps_the_generation_without_a_handle(agent):
    generation = agent._db_generation

    agent.drop_db()

    assert agent._db_generation == generation + 1
    assert agent.db_client.deleted == []


def test_drop_db_deletes_the_installed_collection(agent):
    agent._set_db()
    collection_name = agent.collection_name
    generation = agent._db_generation

    agent.drop_db()

    assert agent.db is None
    assert agent._ready_to_add is False
    assert agent._db_generation == generation + 1
    assert agent.db_client.deleted == [collection_name]


def test_drop_db_survives_a_missing_collection(agent):
    agent._set_db()
    agent.db_client.collections.pop(agent.collection_name)

    agent.drop_db()

    assert agent.db is None
    assert agent.db_client.deleted == []


def test_count_failure_leaves_cleanup_to_close_db(agent):
    scene = agent.scene
    agent.db_client.count_error = RuntimeError("count failed")
    collection_name = agent.make_collection_name(scene)

    with pytest.raises(RuntimeError, match="count failed"):
        agent._set_db()

    assert agent.db is None
    assert agent._ready_to_add is False
    assert agent.db_client.deleted == []

    agent.close_db(scene)

    assert agent.db_client.deleted == [collection_name]


async def _release(agent, ready: bool = False):
    """Rebind the agent mid-wait, optionally as the next scene's `set_db` would."""
    await asyncio.sleep(0.15)
    agent.scene = _FakeScene(memory_id="scene-2")
    agent._ready_to_add = ready


async def test_add_aborts_instead_of_writing_into_the_next_scene(agent):
    agent._set_db()
    collection = agent.db
    agent._ready_to_add = False

    await asyncio.wait_for(
        asyncio.gather(
            memory.MemoryAgent.add.__wrapped__(agent, "hello"),
            _release(agent, ready=True),
        ),
        timeout=5,
    )

    assert collection.upserts == []


async def test_add_does_not_park_forever_after_a_release(agent):
    agent._set_db()
    collection = agent.db
    agent._ready_to_add = False

    await asyncio.wait_for(
        asyncio.gather(
            memory.MemoryAgent.add.__wrapped__(agent, "hello"),
            _release(agent),
        ),
        timeout=5,
    )

    assert collection.upserts == []


async def test_add_many_aborts_when_the_scene_is_released(agent):
    agent._set_db()
    collection = agent.db
    agent._ready_to_add = False

    await asyncio.wait_for(
        asyncio.gather(
            memory.MemoryAgent.add_many.__wrapped__(
                agent, [{"id": "e1", "text": "hello"}]
            ),
            _release(agent, ready=True),
        ),
        timeout=5,
    )

    assert collection.upserts == []


async def test_delete_aborts_when_the_scene_is_released(agent):
    agent._set_db()
    collection = agent.db
    agent._ready_to_add = False

    await asyncio.wait_for(
        asyncio.gather(
            memory.MemoryAgent.delete.__wrapped__(agent, {"source": "talemate"}),
            _release(agent, ready=True),
        ),
        timeout=5,
    )

    assert collection.deletes == []
