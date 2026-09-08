"""
Agent action overrides: the learned-action registry, its websocket plumbing
and the config handlers that set and clear an override.
"""

from __future__ import annotations

import pytest

import talemate.instance as instance
from talemate.agents import observed_actions
from talemate.agents.context import ActiveAgent
from talemate.client.base import ClientBase
from talemate.client.context import ClientContext, set_client_context_attribute
from talemate.config import state as config_state
from talemate.config.schema import AgentActionOverride, Client as ClientConfig, Config
from talemate.emit import Receiver
from talemate.server.config import ConfigPlugin
from talemate.server.websocket_server import WebsocketHandler


class _FakeAgent:
    async def summarize(self):
        """Summarize the text handed in.

        Second paragraph that must not leak into the hint.
        """

    async def build_archive(self):
        pass

    async def determine_character_description(self):
        """The generated description, or an empty string when the model
        declined, wrapped over two physical lines.

        Second paragraph."""

    not_callable = "a plain attribute"


class _MockWebsocketHandler:
    def __init__(self):
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)


@pytest.fixture(autouse=True)
def clean_registry():
    observed_actions.reset()
    yield
    observed_actions.reset()


@pytest.fixture
def fake_agent(monkeypatch):
    monkeypatch.setitem(instance.AGENTS, "summarizer", _FakeAgent())


@pytest.fixture
def emitted():
    received: list = []

    def collect(emission):
        received.append(emission)

    receiver = Receiver()
    receiver.handle_agent_actions_observed = collect
    receiver.connect()
    yield received
    receiver.disconnect()


def _agent(agent_type):
    class _Agent:
        verbose_name = agent_type.title()

        def allow_repetition_break(self, kind, action, auto=False):
            return False

        def inject_prompt_paramters(self, parameters, kind, action):
            pass

    _Agent.agent_type = agent_type
    return _Agent()


def _named(name):
    def fn():
        pass

    fn.__name__ = name
    return fn


class TestRecordContext:
    def test_first_sight_creates_the_entry_and_broadcasts(self, fake_agent, emitted):
        with ActiveAgent(_agent("summarizer"), _named("summarize")) as ctx:
            new_keys = observed_actions.record_context(ctx, "openrouter")

        assert new_keys == ["summarizer.summarize"]
        (entry,) = observed_actions.snapshot()
        assert entry == {
            "key": "summarizer.summarize",
            "agent_type": "summarizer",
            "action": "summarize",
            "client_name": "openrouter",
            "served_by": "summarizer",
            "description": "Summarize the text handed in.",
        }
        (emission,) = emitted
        assert emission.typ == "agent_actions_observed"
        assert emission.data["actions"] == [entry]

    def test_snapshot_is_sorted_by_key(self, emitted):
        for agent_type, action in [
            ("world_state", "request_world_state"),
            ("summarizer", "summarize"),
            ("narrator", "narrate_environment"),
        ]:
            with ActiveAgent(_agent(agent_type), _named(action)) as ctx:
                observed_actions.record_context(ctx, "c")

        assert [a["key"] for a in observed_actions.snapshot()] == [
            "narrator.narrate_environment",
            "summarizer.summarize",
            "world_state.request_world_state",
        ]

    def test_learns_every_action_in_the_chain_with_one_broadcast(self, emitted):
        with ActiveAgent(_agent("summarizer"), _named("build_archive")):
            with ActiveAgent(_agent("summarizer"), _named("summarize")) as ctx:
                new_keys = observed_actions.record_context(ctx, "openrouter")

        assert new_keys == ["summarizer.summarize", "summarizer.build_archive"]
        assert [a["key"] for a in observed_actions.snapshot()] == [
            "summarizer.build_archive",
            "summarizer.summarize",
        ]
        assert len(emitted) == 1

    def test_chain_crossing_agents_learns_both_served_by_the_innermost(self, emitted):
        with ActiveAgent(_agent("director"), _named("persist_character")):
            with ActiveAgent(
                _agent("creator"), _named("determine_character_name")
            ) as ctx:
                observed_actions.record_context(ctx, "openrouter")

        assert [(a["key"], a["served_by"]) for a in observed_actions.snapshot()] == [
            ("creator.determine_character_name", "creator"),
            ("director.persist_character", "creator"),
        ]

    def test_delegate_uses_the_delegated_function_name(self, emitted):
        with ActiveAgent(
            _agent("narrator"), _named("delegate"), (_named("generate_response"),)
        ) as ctx:
            observed_actions.record_context(ctx, "openrouter")

        assert [a["key"] for a in observed_actions.snapshot()] == [
            "narrator.generate_response"
        ]

    def test_no_context_learns_nothing(self, emitted):
        assert observed_actions.record_context(None, "openrouter") == []
        assert observed_actions.snapshot() == []
        assert emitted == []

    def test_known_chain_on_the_same_client_does_not_broadcast_again(self, emitted):
        with ActiveAgent(_agent("summarizer"), _named("summarize")) as ctx:
            observed_actions.record_context(ctx, "openrouter")
            assert observed_actions.record_context(ctx, "openrouter") == []

        assert len(emitted) == 1

    def test_server_change_on_the_same_client_broadcasts(self, emitted):
        # two chains under one outer action on a single client, then the
        # outer action is served by the other agent
        with ActiveAgent(_agent("director"), _named("persist_character")):
            with ActiveAgent(
                _agent("creator"), _named("determine_character_name")
            ) as ctx:
                observed_actions.record_context(ctx, "openrouter")
            with ActiveAgent(
                _agent("world_state"), _named("extract_character_sheet")
            ) as ctx:
                observed_actions.record_context(ctx, "openrouter")
        assert len(emitted) == 2
        assert observed_actions.snapshot()[1]["served_by"] == "world_state"

        with ActiveAgent(_agent("director"), _named("persist_character")):
            with ActiveAgent(
                _agent("creator"), _named("determine_character_name")
            ) as ctx:
                changed = observed_actions.record_context(ctx, "openrouter")

        assert changed == ["director.persist_character"]
        assert len(emitted) == 3
        assert observed_actions.snapshot()[1]["served_by"] == "creator"

    def test_client_change_on_a_known_action_broadcasts(self, emitted):
        with ActiveAgent(_agent("summarizer"), _named("summarize")) as ctx:
            observed_actions.record_context(ctx, "openrouter")
            changed = observed_actions.record_context(ctx, "koboldcpp")

        assert changed == ["summarizer.summarize"]
        assert len(emitted) == 2
        assert emitted[-1].data["actions"][0]["client_name"] == "koboldcpp"


class _OfflineClient(ClientBase):
    client_type = "stub"

    def __init__(self, name, response="answer"):
        super().__init__(name=name)
        self._response = response
        self.connected = True

    @property
    def supported_parameters(self):
        return ["temperature", "max_tokens"]

    async def generate(self, prompt, parameters, kind):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def status(self):
        self.connected = True

    async def get_model_name(self):
        return "stub-model"


@pytest.fixture
def stub_client_config():
    saved = dict(config_state.CONFIG.clients)
    config_state.CONFIG.clients["stub_overrides"] = ClientConfig(
        type="stub", name="stub_overrides", model="stub-model", enabled=True
    )
    yield
    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved)


class TestSendPromptLearnsTheAction:
    async def _send(self, client):
        with ActiveAgent(_agent("summarizer"), _named("build_archive")):
            with ActiveAgent(_agent("summarizer"), _named("summarize")):
                with ClientContext(requires_active_scene=False):
                    set_client_context_attribute("requires_active_scene", False)
                    return await client.send_prompt("summarize this", kind="summarize")

    async def test_a_sent_request_learns_the_chain_on_the_client(
        self, stub_client_config, emitted
    ):
        client = _OfflineClient(name="stub_overrides")

        assert await self._send(client) == "answer"
        assert [(a["key"], a["client_name"]) for a in observed_actions.snapshot()] == [
            ("summarizer.build_archive", "stub_overrides"),
            ("summarizer.summarize", "stub_overrides"),
        ]
        assert len(emitted) == 1

    async def test_a_failed_request_is_still_learned(
        self, stub_client_config, emitted, monkeypatch
    ):
        client = _OfflineClient(
            name="stub_overrides", response=RuntimeError("provider 400")
        )

        async def ignore(*args, **kwargs):
            return "ignore"

        monkeypatch.setattr(client, "_auto_retry_or_prompt", ignore)

        assert await self._send(client) == ""
        assert [a["key"] for a in observed_actions.snapshot()] == [
            "summarizer.build_archive",
            "summarizer.summarize",
        ]

    async def test_a_registry_failure_does_not_break_the_request(
        self, stub_client_config, monkeypatch
    ):
        def boom(*args, **kwargs):
            raise RuntimeError("registry exploded")

        monkeypatch.setattr(observed_actions, "record_context", boom)
        client = _OfflineClient(name="stub_overrides")

        assert await self._send(client) == "answer"


class TestActionDescription:
    def test_first_paragraph_is_joined_into_one_line(self, fake_agent):
        assert observed_actions.action_description(
            "summarizer", "determine_character_description"
        ) == (
            "The generated description, or an empty string when the model"
            " declined, wrapped over two physical lines."
        )

    def test_undocumented_method_has_no_hint(self, fake_agent):
        assert (
            observed_actions.action_description("summarizer", "build_archive") is None
        )

    def test_node_graph_action_has_no_hint(self, fake_agent):
        assert (
            observed_actions.action_description(
                "summarizer", "analyze_scene_progression"
            )
            is None
        )

    def test_non_callable_attribute_has_no_hint(self, fake_agent):
        assert observed_actions.action_description("summarizer", "not_callable") is None

    def test_unknown_agent_has_no_hint(self):
        assert observed_actions.action_description("nobody", "summarize") is None


class TestWebsocketPlumbing:
    async def test_request_agent_actions_replies_with_the_snapshot(self, fake_agent):
        with ActiveAgent(_agent("summarizer"), _named("summarize")) as ctx:
            observed_actions.record_context(ctx, "openrouter")
        handler = _MockWebsocketHandler()

        await ConfigPlugin(handler).handle_request_agent_actions({})

        (message,) = handler.messages
        assert message["type"] == "config"
        assert message["action"] == "agent_actions"
        assert [a["key"] for a in message["data"]["actions"]] == [
            "summarizer.summarize"
        ]

    def test_first_sight_reaches_the_frontend_as_the_same_message(self, fake_agent):
        pushed: list[dict] = []
        handler = WebsocketHandler.__new__(WebsocketHandler)
        handler.queue_put = pushed.append

        with_receiver = Receiver()
        with_receiver.handle_agent_actions_observed = (
            handler.handle_agent_actions_observed
        )
        with_receiver.connect()
        try:
            with ActiveAgent(_agent("summarizer"), _named("summarize")) as ctx:
                observed_actions.record_context(ctx, "openrouter")
        finally:
            with_receiver.disconnect()

        (message,) = pushed
        assert message["type"] == "config"
        assert message["action"] == "agent_actions"
        assert message["data"]["actions"][0]["description"] == (
            "Summarize the text handed in."
        )


@pytest.fixture
def app_config(monkeypatch):
    config = Config()
    monkeypatch.setattr(config_state, "CONFIG", config)

    async def no_broadcast(self):
        return []

    monkeypatch.setattr(Config, "set_dirty", no_broadcast)
    return config


class TestOverrideHandlers:
    async def test_set_creates_the_override(self, app_config):
        plugin = ConfigPlugin(_MockWebsocketHandler())

        await plugin.handle_set_agent_action_override(
            {"data": {"key": "summarizer.build_archive", "disable_reasoning": True}}
        )

        assert app_config.agent_actions.overrides == {
            "summarizer.build_archive": AgentActionOverride(disable_reasoning=True)
        }

    async def test_set_replaces_an_existing_override(self, app_config):
        app_config.agent_actions.overrides["summarizer.build_archive"] = (
            AgentActionOverride(disable_reasoning=True)
        )
        plugin = ConfigPlugin(_MockWebsocketHandler())

        await plugin.handle_set_agent_action_override(
            {"data": {"key": "summarizer.build_archive", "disable_reasoning": False}}
        )

        assert (
            app_config.agent_actions.overrides[
                "summarizer.build_archive"
            ].disable_reasoning
            is False
        )

    async def test_clear_removes_the_override(self, app_config):
        app_config.agent_actions.overrides["summarizer.build_archive"] = (
            AgentActionOverride(disable_reasoning=True)
        )
        plugin = ConfigPlugin(_MockWebsocketHandler())

        await plugin.handle_clear_agent_action_override(
            {"data": {"key": "summarizer.build_archive"}}
        )

        assert app_config.agent_actions.overrides == {}

    async def test_clear_of_an_unknown_key_is_a_no_op(self, app_config, monkeypatch):
        calls = []

        async def spy(self):
            calls.append(True)
            return []

        monkeypatch.setattr(Config, "set_dirty", spy)
        plugin = ConfigPlugin(_MockWebsocketHandler())

        await plugin.handle_clear_agent_action_override(
            {"data": {"key": "nobody.nothing"}}
        )

        assert calls == []
