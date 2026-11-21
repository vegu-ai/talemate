from types import SimpleNamespace

import pytest

import talemate.agents.memory as memory
from talemate.agents.memory import ChromaDBMemoryAgent
from talemate.agents.memory.embedding_compat import (
    GTE_MODEL,
    GTE_REVISION,
    model_revision_kwargs,
)
from talemate.config.schema import EmbeddingFunctionPreset, generate_chromadb_presets


class _FakeDBClient:
    def get_or_create_collection(self, name, embedding_function=None, metadata=None):
        return object()


@pytest.fixture
def load_calls(monkeypatch):
    calls = []

    class _FakeSentenceTransformerEmbeddingFunction:
        models = {}

        def __init__(self, **kwargs):
            calls.append(kwargs)
            self._model = [type("M", (), {"auto_model": None})()]

    class _FakeEmbeddingFunctions:
        SentenceTransformerEmbeddingFunction = _FakeSentenceTransformerEmbeddingFunction

    monkeypatch.setattr(memory, "embedding_functions", _FakeEmbeddingFunctions)
    monkeypatch.setattr(memory, "restore_gte_buffers", lambda ef, model_name: None)
    return calls


@pytest.fixture
def presets(monkeypatch):
    presets = generate_chromadb_presets()
    config = SimpleNamespace(presets=SimpleNamespace(embeddings=presets))
    monkeypatch.setattr(ChromaDBMemoryAgent, "config", property(lambda self: config))
    return presets


def _build(preset: str):
    agent = object.__new__(ChromaDBMemoryAgent)
    agent.actions = ChromaDBMemoryAgent.init_actions()
    agent.actions["_config"].config["embeddings"].value = preset
    agent.db_client = _FakeDBClient()
    agent._build_collection("collection")


def test_gte_preset_loads_the_pinned_revision(load_calls, presets):
    assert generate_chromadb_presets()[GTE_MODEL].model == GTE_MODEL

    _build(GTE_MODEL)

    assert [call["revision"] for call in load_calls] == [GTE_REVISION]
    assert load_calls[0]["model_name"] == GTE_MODEL


def test_default_preset_loads_without_a_revision(load_calls, presets):
    _build("default")

    assert len(load_calls) == 1
    assert "revision" not in load_calls[0]


def test_custom_preset_naming_the_gte_model_loads_the_pinned_revision(
    load_calls, presets
):
    presets["my-gte"] = EmbeddingFunctionPreset(
        embeddings="sentence-transformer", model=GTE_MODEL, custom=True
    )

    _build("my-gte")

    assert [call["revision"] for call in load_calls] == [GTE_REVISION]
    assert load_calls[0]["model_name"] == GTE_MODEL


def test_preset_keyed_like_gte_but_naming_another_model_gets_no_revision(
    load_calls, presets
):
    presets[GTE_MODEL] = EmbeddingFunctionPreset(
        embeddings="sentence-transformer", model="all-MiniLM-L6-v2", custom=True
    )

    _build(GTE_MODEL)

    assert load_calls[0]["model_name"] == "all-MiniLM-L6-v2"
    assert "revision" not in load_calls[0]


@pytest.mark.parametrize("model_name", ["all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"])
def test_other_models_get_no_revision(model_name):
    assert model_revision_kwargs(model_name) == {}


def test_gte_revision_is_a_full_commit_hash():
    assert len(GTE_REVISION) == 40
    int(GTE_REVISION, 16)
    assert model_revision_kwargs(GTE_MODEL) == {"revision": GTE_REVISION}
