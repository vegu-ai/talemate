"""Unit tests for the `openrouter` embeddings driver of the Memory agent.

The driver reuses ChromaDB's `OpenAIEmbeddingFunction` with the OpenRouter
base URL, so the tests pin the two things that separate it from the `openai`
driver: which key it reads, and which host the embedding function talks to.
The request shape is exercised against the real ChromaDB embedding function
with a stubbed transport, so a ChromaDB upgrade that changes the call cannot
pass silently.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import talemate.agents.memory as memory
from talemate.agents.memory import (
    OPENROUTER_EMBEDDINGS_BASE_URL,
    ChromaDBMemoryAgent,
)
from talemate.config.schema import (
    EmbeddingFunctionPreset,
    generate_chromadb_presets,
)


class _FakeCollection:
    def __init__(self, name):
        self.name = name

    def count(self):
        return 0


class _FakeDBClient:
    def __init__(self):
        self.calls = []

    def get_or_create_collection(self, name, embedding_function=None, metadata=None):
        self.calls.append(
            {
                "name": name,
                "embedding_function": embedding_function,
                "metadata": metadata,
            }
        )
        return _FakeCollection(name)


class _RecordingEmbeddingFunction:
    def __init__(self, api_key=None, model_name=None, api_base=None):
        self.api_key = api_key
        self.model_name = model_name
        self.api_base = api_base


class _FakeEmbeddingFunctions:
    OpenAIEmbeddingFunction = _RecordingEmbeddingFunction


class _FakeScene:
    def __init__(self, memory_id="scene-1"):
        self.memory_id = memory_id


def _config(openai_key=None, openrouter_key=None):
    return SimpleNamespace(
        presets=SimpleNamespace(embeddings=generate_chromadb_presets()),
        openai=SimpleNamespace(api_key=openai_key),
        openrouter=SimpleNamespace(api_key=openrouter_key),
    )


@pytest.fixture
def agent(monkeypatch):
    """A ChromaDBMemoryAgent without the signal connections `__init__` makes."""
    agent = object.__new__(ChromaDBMemoryAgent)
    agent.db = None
    agent.memory_tracker = {}
    agent._ready_to_add = False
    agent._db_generation = 0
    agent._db_lock = threading.Lock()
    agent.actions = ChromaDBMemoryAgent.init_actions()
    agent.db_client = _FakeDBClient()

    config = _config()
    monkeypatch.setattr(ChromaDBMemoryAgent, "config", property(lambda self: config))
    agent._test_config = config
    return agent


def _select(agent, preset: str, **keys):
    agent.actions["_config"].config["embeddings"].value = preset
    for provider, key in keys.items():
        setattr(getattr(agent._test_config, provider), "api_key", key)


def test_shipped_openrouter_preset_mirrors_the_openai_one():
    presets = generate_chromadb_presets()

    openrouter = presets["openrouter"]
    openai = presets["openai"]

    assert openrouter.embeddings == "openrouter"
    assert openrouter.model == "openai/text-embedding-3-small"
    assert openrouter.local is False
    assert openrouter.gpu_recommendation is False
    assert openrouter.distance == openai.distance
    assert openrouter.distance_mod == openai.distance_mod
    assert openrouter.distance_function == openai.distance_function


def test_openrouter_preset_selects_the_openrouter_driver(agent):
    _select(agent, "openrouter")

    assert agent.using_openrouter_embeddings is True
    assert agent.using_openai_embeddings is False
    assert agent.using_local_embeddings is False
    assert agent.model == "openai/text-embedding-3-small"


@pytest.mark.parametrize(
    "preset,label",
    [
        ("openrouter", "OpenRouter"),
        ("openai", "OpenAI"),
    ],
)
def test_a_missing_key_is_reported_as_an_agent_error(agent, preset, label):
    _select(agent, preset)

    assert agent.missing_hosted_embeddings_provider == label
    assert agent.ready is False
    assert agent.status == "error"
    assert agent.agent_details["error"]["value"] == f"No {label} API key set"


@pytest.mark.parametrize(
    "preset,provider",
    [("openrouter", "openrouter"), ("openai", "openai")],
)
def test_a_present_key_clears_the_error(agent, preset, provider):
    _select(agent, preset, **{provider: "sk-key"})

    assert agent.missing_hosted_embeddings_provider is None
    assert "error" not in agent.agent_details


@pytest.mark.parametrize(
    "preset",
    [
        "default",
        "Alibaba-NLP/gte-base-en-v1.5",
        "client-api-preset",
        "legacy-driver",
        "gone-from-config",
    ],
)
def test_a_driver_that_needs_no_key_never_trips_the_gate(agent, preset):
    """`ready`, `status` and `agent_details` route EVERY driver through the
    gate now, so the drivers that carry no key of their own have to pass it
    with both keys unset - a legacy driver value and a missing preset key
    included."""
    presets = agent._test_config.presets.embeddings
    presets["client-api-preset"] = EmbeddingFunctionPreset(
        embeddings="client-api", client="kobold", local=False
    )
    presets["legacy-driver"] = EmbeddingFunctionPreset(embeddings="instructor")
    _select(agent, preset)

    assert agent.missing_hosted_embeddings_provider is None


@pytest.mark.parametrize("preset", ["default", "Alibaba-NLP/gte-base-en-v1.5"])
def test_a_local_driver_reaches_the_db_check_rather_than_the_gate(agent, preset):
    """The gate returns False before the db handle is even consulted, so a
    local driver with no keys set must fall through to the handle."""
    _select(agent, preset)
    agent.db_client = None

    assert agent.ready is False
    assert agent.status == "waiting"
    assert "error" not in agent.agent_details

    agent.db_client = _FakeDBClient()

    assert agent.ready is True
    assert agent.status == "active"


def test_the_other_providers_key_does_not_satisfy_the_driver(agent):
    _select(agent, "openrouter", openai="sk-openai")

    assert agent.missing_hosted_embeddings_provider == "OpenRouter"


def test_the_openrouter_driver_gets_its_own_collection(agent):
    """The driver alone must separate the collections, at an equal model."""
    presets = agent._test_config.presets.embeddings
    presets["openai"].model = presets["openrouter"].model
    scene = _FakeScene()

    _select(agent, "openrouter", openrouter="sk-openrouter")
    openrouter_name = agent.make_collection_name(scene)

    _select(agent, "openai", openai="sk-openai")

    assert openrouter_name != agent.make_collection_name(scene)


def test_build_collection_points_the_embedding_function_at_openrouter(
    agent, monkeypatch
):
    monkeypatch.setattr(memory, "embedding_functions", _FakeEmbeddingFunctions)
    _select(agent, "openrouter", openrouter="sk-openrouter")

    agent._build_collection("collection")

    ef = agent.db_client.calls[0]["embedding_function"]
    assert ef.api_base == OPENROUTER_EMBEDDINGS_BASE_URL
    assert ef.api_key == "sk-openrouter"
    assert ef.model_name == "openai/text-embedding-3-small"


def test_build_collection_leaves_the_openai_driver_on_its_own_host(agent, monkeypatch):
    monkeypatch.setattr(memory, "embedding_functions", _FakeEmbeddingFunctions)
    _select(agent, "openai", openai="sk-openai")

    agent._build_collection("collection")

    ef = agent.db_client.calls[0]["embedding_function"]
    assert ef.api_base is None
    assert ef.api_key == "sk-openai"


def test_build_collection_without_a_key_refuses(agent, monkeypatch):
    monkeypatch.setattr(memory, "embedding_functions", _FakeEmbeddingFunctions)
    _select(agent, "openrouter")

    with pytest.raises(ValueError, match="OpenRouter API key"):
        agent._build_collection("collection")


def test_the_embedding_request_goes_to_openrouter(agent):
    """The real ChromaDB embedding function, with the transport stubbed out."""
    _select(agent, "openrouter", openrouter="sk-openrouter")

    ef = agent._openai_compatible_embedding_function(
        "OpenRouter",
        agent.openrouter_api_key,
        agent.model,
        OPENROUTER_EMBEDDINGS_BASE_URL,
    )

    assert str(ef.client.base_url).rstrip("/") == OPENROUTER_EMBEDDINGS_BASE_URL

    requests = []

    class _FakeEmbeddings:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])],
            )

    ef.client = SimpleNamespace(embeddings=_FakeEmbeddings())

    embeddings = ef(["hello world"])

    assert requests == [
        {"model": "openai/text-embedding-3-small", "input": ["hello world"]}
    ]
    assert len(embeddings) == 1
    assert list(embeddings[0]) == pytest.approx([0.1, 0.2, 0.3])
