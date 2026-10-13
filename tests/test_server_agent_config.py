"""
Tests for the ``agent_config`` websocket router.

Registry ops (dynamic child actions) write straight into ``config.agents``, so
they have to broadcast the config the same way a save does - a frontend holding
a snapshot that predates the op would revert it with its next full-config save.

The router is also shared: the settings view, the agent drawer and the world
editor all send on it, so every answer carries back the ``request_id`` of the
request it answers.

Ordering matters to the settings page, which repairs its working copy from the
broadcast when the completion arrives: the fake agent below mirrors the real
(debounced) status emission, so the sequence under test is the production one.
"""

import asyncio

import pytest

import talemate.agents.base as agents_base
import talemate.agents.visual.backends.comfyui as comfyui_backend
import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.server.agent_config as server_agent_config
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.schema import GEN_TYPE, PROMPT_TYPE
from talemate.config import Config
from talemate.config.schema import Agent
from talemate.server.agent_config import AgentConfigPlugin

REGISTRY_KEY = "backends"


@pytest.fixture(autouse=True)
def isolated_config_signals():
    """set_dirty() reaches whatever receivers other test modules left connected."""
    saved = {}
    for name in ("config.changed", "config.changed.follow"):
        signal = async_signals.get(name)
        saved[signal] = signal.receivers
        signal.receivers = []
    yield
    for signal, receivers in saved.items():
        signal.receivers = receivers


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)

    async def on_config_changed(self, config: Config):
        """Stand-in for WebsocketHandler.on_config_changed."""
        self.queue_put({"type": "app_config", "data": config.model_dump()})


class _FakeAgent:
    agent_type = "tts"

    def __init__(self, handler):
        self.handler = handler
        self.children: dict[str, str] = {}
        self.status_task: asyncio.Task | None = None
        self.choice_refreshes = 0
        self.choices_status_emits = 0
        self.status_emits = 0

    def refresh_choices(self):
        self.choice_refreshes += 1

    def is_dynamic_registry(self, action_key):
        return action_key == REGISTRY_KEY

    def dynamic_child_slugs(self, action_key):
        return list(self.children)

    def register_dynamic_child(self, action_key, slug, label):
        self.children[slug] = label

    async def persist_dynamic_external_state(self, action_key):
        pass

    async def save_config(self):
        config = config_state.get_config()
        config.agents[self.agent_type] = Agent(name=self.agent_type)
        config.dirty = True

    async def emit_choices_status(self):
        self.choices_status_emits += 1
        self.handler.queue_put({"type": "agent_status", "name": self.agent_type})

    async def emit_status(self, *args, **kwargs):
        """Debounced, like the real one: the status lands on a later loop pass,
        after the completion its caller queues on return."""
        self.status_emits += 1
        self.status_task = asyncio.create_task(self._emit_status_debounced())

    async def _emit_status_debounced(self):
        self.handler.queue_put({"type": "agent_status", "name": self.agent_type})


@pytest.fixture
def app_config(monkeypatch):
    config = Config()
    monkeypatch.setattr(config_state, "CONFIG", config)
    return config


@pytest.fixture
def plugin(monkeypatch, app_config):
    handler = _MockWebsocketHandler()
    async_signals.get("config.changed").connect(handler.on_config_changed)

    async def noop_commit():
        config_state.get_config().dirty = False

    monkeypatch.setattr(server_agent_config, "commit_config", noop_commit)
    plugin = AgentConfigPlugin(handler)
    agent = _FakeAgent(handler)
    monkeypatch.setattr(server_agent_config, "AGENTS", {"tts": agent})
    plugin.agent = agent
    yield plugin
    if agent.status_task:
        # a test that never yielded to the loop leaves the debounce pending
        agent.status_task.cancel()


def _types(plugin) -> list[str]:
    return [message.get("type") for message in plugin.websocket_handler.messages]


def _completion(plugin) -> dict:
    """The router's answer - the debounced status may land on either side of it."""
    answers = [
        message
        for message in plugin.websocket_handler.messages
        if message.get("type") == "agent_config"
    ]
    return answers[-1]


@pytest.mark.asyncio
async def test_registry_op_broadcasts_the_config_first(plugin, app_config):
    await plugin.handle(
        {
            "action": "register_child",
            "agent_type": "tts",
            "action_key": REGISTRY_KEY,
            "label": "My Backend",
            "request_id": "reg-1",
        }
    )

    # let the debounced status land
    await asyncio.sleep(0)

    assert plugin.agent.children == {"my-backend": "My Backend"}
    # without the app_config broadcast, every frontend keeps a config snapshot
    # that predates the op - and reverts it with its next full-config save.
    # The settings page repairs its working copy from that broadcast on the
    # completion, precisely because the status is not there yet.
    assert _types(plugin) == ["app_config", "agent_config", "agent_status"]
    assert "tts" in plugin.websocket_handler.messages[0]["data"]["agents"]


@pytest.mark.asyncio
async def test_registry_op_completion_echoes_the_request_id(plugin):
    await plugin.handle(
        {
            "action": "register_child",
            "agent_type": "tts",
            "action_key": REGISTRY_KEY,
            "label": "My Backend",
            "request_id": "reg-2",
        }
    )

    completion = _completion(plugin)
    assert completion["action"] == "operation_done"
    assert completion["request_id"] == "reg-2"
    assert "error" not in completion


@pytest.mark.asyncio
async def test_refused_registry_op_is_attributable(plugin):
    await plugin.handle(
        {
            "action": "register_child",
            "agent_type": "tts",
            "action_key": REGISTRY_KEY,
            "label": "   ",
            "request_id": "reg-3",
        }
    )

    messages = plugin.websocket_handler.messages
    assert _types(plugin) == ["agent_config"]
    assert messages[0]["request_id"] == "reg-3"
    assert messages[0]["failed_action"] == "register_child"
    assert messages[0]["error"]["message"] == "Label is required"


@pytest.mark.asyncio
async def test_unknown_agent_is_refused_with_the_request_id(plugin):
    await plugin.handle(
        {
            "action": "unregister_child",
            "agent_type": "nonexistent",
            "action_key": REGISTRY_KEY,
            "slug": "whatever",
            "request_id": "reg-4",
        }
    )

    refusal = _completion(plugin)
    assert refusal["request_id"] == "reg-4"
    assert refusal["failed_action"] == "unregister_child"


@pytest.mark.asyncio
async def test_request_id_is_optional(plugin):
    """The drawer and the world editor send on this router without ids."""
    await plugin.handle(
        {
            "action": "register_child",
            "agent_type": "tts",
            "action_key": REGISTRY_KEY,
            "label": "My Backend",
        }
    )

    completion = _completion(plugin)
    assert completion["action"] == "operation_done"
    assert "request_id" not in completion


@pytest.mark.asyncio
async def test_refresh_choices_rescans_then_emits_the_choices_status(plugin):
    await plugin.handle({"action": "refresh_choices", "agent_type": "tts"})

    assert plugin.agent.choice_refreshes == 1
    assert plugin.agent.choices_status_emits == 1
    # the full status emit runs per-backend hooks that can reach servers
    assert plugin.agent.status_emits == 0
    assert _types(plugin) == ["agent_status"]


@pytest.mark.asyncio
async def test_refresh_choices_reaches_no_comfyui_server(plugin, monkeypatch):
    agent = VisualAgent()
    backend = comfyui_backend.Backend(
        api_url="http://127.0.0.1:1",
        workflow=comfyui_backend.Workflow(nodes={}, mtime=0, path="unused.json"),
        gen_type=GEN_TYPE.TEXT_TO_IMAGE,
        prompt_type=PROMPT_TYPE.DESCRIPTIVE,
    )
    agent.actions["_config"].config["backend"].value = "comfyui"
    agent.backend = backend
    assert agent.comfyui_handler("backend") is not None
    monkeypatch.setattr(server_agent_config, "AGENTS", {"visual": agent})

    reached = []

    def reached_the_server(*args, **kwargs):
        reached.append(args)
        raise RuntimeError("the ComfyUI server was contacted")

    for name in ("ready", "test_connection", "ensure_test_connection_task"):
        monkeypatch.setattr(
            comfyui_backend.Backend, name, reached_the_server, raising=False
        )
    monkeypatch.setattr(
        comfyui_backend.Backend, "models", property(reached_the_server), raising=False
    )
    emitted = []
    monkeypatch.setattr(
        agents_base, "emit", lambda typ, **kwargs: emitted.append((typ, kwargs))
    )

    await plugin.handle({"action": "refresh_choices", "agent_type": "visual"})
    await asyncio.sleep(0.2)

    assert reached == []
    assert [typ for typ, _ in emitted] == ["agent_status"]
    assert emitted[0][1]["id"] == "visual"
    assert agent.actions["comfyui_image_create"].config["workflow"].choices


@pytest.mark.asyncio
async def test_refresh_choices_for_an_unknown_agent_is_refused(plugin):
    await plugin.handle({"action": "refresh_choices", "agent_type": "nonexistent"})

    assert plugin.agent.choice_refreshes == 0
    assert plugin.websocket_handler.messages[0]["error"]["message"] == (
        "Agent 'nonexistent' not found"
    )
