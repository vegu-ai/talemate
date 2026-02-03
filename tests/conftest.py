"""
Shared pytest fixtures and test infrastructure.

Provides MockClient, MockScene, and bootstrap functions used across
multiple test modules (test_graphs, test_layered_history, etc.).
"""

import contextvars
from collections import deque

import talemate.agents as agents
import talemate.agents.memory
import talemate.agents.tts.voice_library as voice_library
import talemate.instance as instance
from talemate.client import ClientBase
from talemate.tale_mate import Scene


# ---------------------------------------------------------------------------
# Contextvar-based response queue for MockClient
# ---------------------------------------------------------------------------

client_responses = contextvars.ContextVar("client_responses", default=deque())


class MockClientContext:
    """Async context manager that provides a fresh response queue."""

    async def __aenter__(self):
        try:
            self.client_responses = client_responses.get()
        except LookupError:
            _client_responses = deque()
            self.token = client_responses.set(_client_responses)
            self.client_responses = _client_responses

        return self.client_responses

    async def __aexit__(self, exc_type, exc_value, traceback):
        if hasattr(self, "token"):
            client_responses.reset(self.token)


# ---------------------------------------------------------------------------
# Mock classes
# ---------------------------------------------------------------------------


class MockClient(ClientBase):
    """LLM client stub that pops pre-defined responses from a queue."""

    def __init__(self, name: str):
        self.name = name
        self.remote_model_name = "test-model"
        self.current_status = "idle"
        self.prompt_history = []

    @property
    def enabled(self):
        return True

    async def send_prompt(
        self, prompt, kind="conversation", finalize=lambda x: x, retries=2, **kwargs
    ):
        response_stack = client_responses.get()
        self.prompt_history.append({"prompt": prompt, "kind": kind})
        if not response_stack:
            return ""
        return response_stack.popleft()


class MockMemoryAgent(talemate.agents.memory.MemoryAgent):
    """MemoryAgent with no-op persistence methods."""

    async def add_many(self, items: list[dict]):
        pass

    async def delete(self, filters: dict):
        pass


class MockScene(Scene):
    """Real Scene subclass with auto_progress forced on."""

    @property
    def auto_progress(self):
        return True


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------


def bootstrap_engine():
    """Instantiate all real agents (using MockMemoryAgent for memory)."""
    voice_library.VOICE_LIBRARY = voice_library.VoiceLibrary(voices={})
    for agent_type in agents.AGENT_CLASSES:
        if agent_type == "memory":
            agent = MockMemoryAgent()
        else:
            agent = agents.AGENT_CLASSES[agent_type]()
        instance.AGENTS[agent_type] = agent


def bootstrap_scene(mock_scene):
    """Wire a MockClient and the mock_scene into every agent."""
    bootstrap_engine()
    client = MockClient("test_client")
    for agent in instance.AGENTS.values():
        agent.client = client
        agent.scene = mock_scene

    director = instance.get_agent("director")
    conversation = instance.get_agent("conversation")
    summarizer = instance.get_agent("summarizer")
    editor = instance.get_agent("editor")
    world_state = instance.get_agent("world_state")

    mock_scene.mock_client = client

    return {
        "director": director,
        "conversation": conversation,
        "summarizer": summarizer,
        "editor": editor,
        "world_state": world_state,
    }
