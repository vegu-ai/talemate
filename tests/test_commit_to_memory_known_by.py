"""#913: a Known by change during the bulk archive write stays in memory."""

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import chromadb
from chromadb.api.types import EmbeddingFunction
from chromadb.config import Settings
import pytest

from conftest import MockScene
import talemate.instance as instance
from talemate.agents.memory import ChromaDBMemoryAgent
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.knowledge.schema import EntryVisibility
from talemate.world_state.manager import WorldStateManager

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
        return "known-by-test"

    def get_config(self):
        return {}


def known_by(*names):
    return EntryVisibility(mode="list", characters=list(names))


@pytest.fixture
def chroma_client(tmp_path):
    with chromadb.PersistentClient(
        path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False)
    ) as client:
        yield client


@pytest.fixture
def scene(persistence_scene_factory, chroma_client, monkeypatch):
    scene = persistence_scene_factory()
    scene.name, scene.project_name, scene.filename = "Rebuild", "rebuild", "scene.json"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.archived_history = [
        {"id": "S1", "text": "The war ended.", "ts": 0},
        {"id": "S2", "text": "The town was rebuilt.", "ts": 0},
    ]
    memory = ChromaDBMemoryAgent()
    memory.client = scene.mock_client
    memory.db_client = chroma_client
    monkeypatch.setattr(
        memory,
        "_build_collection",
        lambda name: chroma_client.get_or_create_collection(
            name, embedding_function=FixedEmbedding()
        ),
    )
    monkeypatch.setitem(instance.AGENTS, "memory", memory)
    memory.connect(scene)
    return scene


@pytest.fixture
def held_bulk_write(scene, monkeypatch):
    """Holds the first bulk write in its executor thread until released."""
    memory = instance.get_agent("memory")
    started, release = threading.Event(), threading.Event()
    write = memory._add_many
    calls = []

    def held(objects):
        calls.append(objects)
        if len(calls) == 1:
            started.set()
            if not release.wait(10):
                raise TimeoutError("bulk write was never released")
        write(objects)

    monkeypatch.setattr(memory, "_add_many", held)
    return started, release


@pytest.fixture
def metadata_updates(scene, monkeypatch):
    memory = instance.get_agent("memory")
    update = Mock(wraps=memory._update_metadata)
    monkeypatch.setattr(memory, "_update_metadata", update)
    return update


async def bulk_write_started(started):
    assert await asyncio.to_thread(started.wait, 10)


def stored_audience(identity):
    meta = instance.get_agent("memory").db.get(ids=[identity])["metadatas"][0]
    return json.loads(meta["present"]) if meta["presence_known"] else None


@pytest.mark.parametrize(
    "present,visibility,audience",
    [
        (None, known_by("Alice"), ["Alice"]),
        (["Alice"], EntryVisibility(mode="everyone"), None),
    ],
)
async def test_known_by_set_during_the_bulk_write_stays_in_memory(
    scene, held_bulk_write, metadata_updates, present, visibility, audience
):
    if present is not None:
        scene.archived_history[0]["present"] = present
    started, release = held_bulk_write
    with ActiveScene(scene):
        commit = asyncio.create_task(scene.commit_to_memory())
        await bulk_write_started(started)
        await WorldStateManager(scene).set_static_history_known_by("S1", visibility)
        assert stored_audience("S1") == audience
        release.set()
        await asyncio.wait_for(commit, 10)

    assert stored_audience("S1") == audience
    assert stored_audience("S2") is None
    metadata_updates.assert_called_once()
    (objects,) = metadata_updates.call_args.args
    assert [obj["id"] for obj in objects] == ["S1"]


async def test_a_commit_without_a_change_makes_no_metadata_update(
    scene, metadata_updates
):
    scene.archived_history[0]["present"] = ["Bob"]
    with ActiveScene(scene):
        await scene.commit_to_memory()

    assert stored_audience("S1") == ["Bob"]
    assert stored_audience("S2") is None
    metadata_updates.assert_not_called()


async def test_save_as_during_the_bulk_write_completes_with_the_new_audience(
    scene, held_bulk_write
):
    started, release = held_bulk_write
    with ActiveScene(scene):
        commit = asyncio.create_task(scene.commit_to_memory())
        await bulk_write_started(started)
        await WorldStateManager(scene).set_static_history_known_by(
            "S1", known_by("Alice")
        )
        await asyncio.wait_for(scene.save(save_as=True, copy_name="copy.json"), 10)
        release.set()
        await asyncio.wait_for(commit, 10)

    assert scene.filename == "copy.json"
    assert Path(scene.save_dir, "copy.json").exists()
    assert stored_audience("S1") == ["Alice"]
    assert stored_audience("S2") is None


async def test_restore_during_the_bulk_write_completes_with_the_restored_audience(
    scene, held_bulk_write
):
    scene.archived_history[0]["present"] = ["Bob"]
    scene.restore_from = "baseline.json"
    await scene.save_restore("baseline.json")
    scene.archived_history[0].pop("present")
    started, release = held_bulk_write
    with ActiveScene(scene):
        commit = asyncio.create_task(scene.commit_to_memory())
        await bulk_write_started(started)
        await asyncio.wait_for(scene.restore(), 10)
        release.set()
        await asyncio.wait_for(commit, 10)

    assert scene.archived_history[0]["present"] == ["Bob"]
    assert stored_audience("S1") == ["Bob"]
    assert stored_audience("S2") is None


async def test_a_correction_for_a_released_scene_is_not_written(
    scene, held_bulk_write, metadata_updates
):
    memory = instance.get_agent("memory")
    started, release = held_bulk_write
    with ActiveScene(scene):
        commit = asyncio.create_task(scene.commit_to_memory())
        await bulk_write_started(started)

    loaded = MockScene()
    loaded.archived_history = [
        {"id": "S1", "text": "The war ended.", "ts": 0, "present": ["Bob"]}
    ]
    memory.connect(loaded)
    with ActiveScene(loaded):
        await loaded.commit_to_memory()
    scene.archived_history[0]["present"] = ["Alice"]
    release.set()
    await asyncio.wait_for(commit, 10)

    assert memory.scene is loaded
    metadata_updates.assert_not_called()
    assert stored_audience("S1") != ["Alice"]
