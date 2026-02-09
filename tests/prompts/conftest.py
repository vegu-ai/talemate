"""
Shared pytest fixtures for prompt template tests.

These fixtures enable unit testing of Jinja2 templates with mocked agent calls
and scene data, without requiring an LLM connection.

For helper functions, see helpers.py.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Import helpers for use in fixtures
from .helpers import create_mock_scene, create_mock_agent


# Path to test data directory
DATA_DIR = Path(__file__).parent.parent / "data" / "prompts"


def load_json(path: Path) -> dict:
    """Load JSON data from file."""
    with open(path) as f:
        return json.load(f)


def dict_to_mock(data: dict) -> Mock:
    """
    Recursively convert a dict to a Mock with attributes.

    This allows test data loaded from JSON to be used as mock objects
    with attribute access (e.g., mock.name instead of mock["name"]).
    """
    mock = Mock()
    for key, value in data.items():
        if isinstance(value, dict):
            setattr(mock, key, dict_to_mock(value))
        elif isinstance(value, list):
            setattr(
                mock,
                key,
                [dict_to_mock(v) if isinstance(v, dict) else v for v in value],
            )
        else:
            setattr(mock, key, value)
    return mock


@pytest.fixture
def load_scene():
    """Factory fixture to load scene data from JSON files."""

    def _load(name: str) -> Mock:
        data = load_json(DATA_DIR / "scenes" / f"{name}.json")
        mock = dict_to_mock(data)
        # Add common scene methods as mocks
        mock.context_history = Mock(return_value=[])
        mock.get_characters = Mock(return_value=[])
        mock.num_history_entries = 0
        return mock

    return _load


@pytest.fixture
def load_character():
    """Factory fixture to load character data from JSON files."""

    def _load(name: str) -> Mock:
        data = load_json(DATA_DIR / "characters" / f"{name}.json")
        return dict_to_mock(data)

    return _load


@pytest.fixture
def load_context():
    """Factory fixture to load template context from JSON files."""

    def _load(agent: str, template: str) -> dict:
        context_file = DATA_DIR / "contexts" / agent / f"{template}.json"
        if context_file.exists():
            return load_json(context_file)
        # Return minimal default context if file doesn't exist
        return {}

    return _load


@pytest.fixture
def mock_scene():
    """Default mock Scene using helper function."""
    return create_mock_scene()


@pytest.fixture
def mock_character():
    """Default mock Character - loads npc_character.json."""
    from .helpers import create_mock_character

    return create_mock_character()


@pytest.fixture
def mock_client():
    """Minimal mock LLM Client."""
    client = Mock()
    client.max_token_length = 4096
    client.decensor_enabled = False
    client.can_be_coerced = True
    client.data_format = "json"
    client.model_name = "test-model"
    client.optimize_prompt_caching = False
    return client


@pytest.fixture
def mock_agent():
    """Minimal mock Agent using helper function."""
    return create_mock_agent()


@pytest.fixture
def set_active_context(mock_scene, mock_agent):
    """Context manager to set active_scene and active_agent."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    scene_token = active_scene.set(mock_scene)
    agent_token = active_agent.set(mock_agent)
    yield
    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


@pytest.fixture
def patch_agent_queries():
    """
    Patch agent query functions that templates may call.

    This patches `talemate.instance.get_agent` to return a mock agent
    that can be configured with return values for specific methods.
    """
    with patch("talemate.instance.get_agent") as mock_get_agent:
        mock_narrator = Mock()
        mock_narrator.narrate_query = AsyncMock(return_value="Mocked query response")

        mock_world_state = Mock()
        mock_world_state.analyze_text_and_answer_question = AsyncMock(
            return_value="Mocked analysis"
        )
        mock_world_state.analyze_and_follow_instruction = AsyncMock(
            return_value="Mocked instruction result"
        )
        mock_world_state.analyze_text_and_extract_context = AsyncMock(
            return_value="Mocked context"
        )

        mock_memory = Mock()
        mock_memory.query = AsyncMock(return_value="Mocked memory")
        mock_memory.multi_query = AsyncMock(return_value={})

        def get_agent_side_effect(agent_type):
            agents = {
                "narrator": mock_narrator,
                "world_state": mock_world_state,
                "memory": mock_memory,
            }
            return agents.get(agent_type, Mock())

        mock_get_agent.side_effect = get_agent_side_effect
        yield mock_get_agent


@pytest.fixture
def patch_rag_build():
    """
    Patch the RAG build action used by memory-context.jinja2.

    This is needed because memory-context.jinja2 calls:
    agent_action(agent.agent_type, "rag_build", prompt=memory_prompt)
    """
    with patch("talemate.instance.get_agent") as mock_get_agent:
        mock_agent = Mock()
        mock_agent.rag_build = AsyncMock(return_value=[])
        mock_get_agent.return_value = mock_agent
        yield mock_get_agent
