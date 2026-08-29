"""Unit tests for talemate.instance: AGENTS / CLIENTS registries and helpers.

We avoid exercising async code paths that depend on a real Config or LLM
clients (instantiate_clients / instantiate_agents / configure_agents /
ensure_agent_llm_client). Those flows are tested elsewhere via the
bootstrap fixtures and require a fully-wired environment.
"""

import asyncio

import pytest

import talemate.agents as agents_module
import talemate.client as clients_module
import talemate.config.state as config_state
import talemate.instance as instance
from talemate.client.registry import CLIENT_CLASSES
from talemate.config.schema import Client as ClientConfig

from conftest import MockClient, bootstrap_engine


# ---------------------------------------------------------------------------
# Sandbox: fully isolate AGENTS/CLIENTS for each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registries():
    """Snapshot and restore AGENTS / CLIENTS / CLIENT_STATUS_TASKS so tests
    can't bleed state.

    The instance module owns module-level dicts that other tests and
    fixtures populate. Each test in this file gets a clean slate. The status
    task registry matters especially: a task left behind by one test belongs
    to that test's (closed) event loop, and a later test coalescing onto it
    would await a cross-loop task.
    """
    saved_agents = dict(instance.AGENTS)
    saved_clients = dict(instance.CLIENTS)
    saved_status_tasks = dict(instance.CLIENT_STATUS_TASKS)
    instance.AGENTS.clear()
    instance.CLIENTS.clear()
    instance.CLIENT_STATUS_TASKS.clear()
    yield
    instance.AGENTS.clear()
    instance.AGENTS.update(saved_agents)
    instance.CLIENTS.clear()
    instance.CLIENTS.update(saved_clients)
    instance.CLIENT_STATUS_TASKS.clear()
    instance.CLIENT_STATUS_TASKS.update(saved_status_tasks)


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


class TestGetAgent:
    def test_returns_registered_agent(self):
        bootstrap_engine()
        # Bootstrap registers all real agents under their agent_type keys.
        director = instance.get_agent("director")
        assert director is not None
        assert director.agent_type == "director"

    def test_raises_keyerror_for_missing_agent(self):
        # Empty registry -> any lookup must raise.
        with pytest.raises(KeyError, match="director"):
            instance.get_agent("director")

    def test_raises_when_value_is_none(self):
        # The implementation treats falsy registry entries as missing.
        instance.AGENTS["director"] = None
        with pytest.raises(KeyError):
            instance.get_agent("director")


# ---------------------------------------------------------------------------
# get_client / destroy_client
# ---------------------------------------------------------------------------


class TestClientRegistry:
    def test_get_client_returns_registered(self):
        client = MockClient("alpha")
        instance.CLIENTS["alpha"] = client
        assert instance.get_client("alpha") is client

    def test_get_client_raises_for_missing(self):
        with pytest.raises(KeyError, match="alpha"):
            instance.get_client("alpha")

    def test_get_client_raises_when_value_is_none(self):
        instance.CLIENTS["alpha"] = None
        with pytest.raises(KeyError):
            instance.get_client("alpha")

    @pytest.mark.asyncio
    async def test_destroy_client_removes_from_registry(self):
        client = MockClient("alpha")
        instance.CLIENTS["alpha"] = client

        await instance.destroy_client("alpha")

        assert "alpha" not in instance.CLIENTS

    @pytest.mark.asyncio
    async def test_destroy_client_calls_destroy_on_instance(self):
        destroyed = []

        class _ObservableClient(MockClient):
            async def destroy(self):
                destroyed.append(self.name)

        instance.CLIENTS["alpha"] = _ObservableClient("alpha")

        await instance.destroy_client("alpha")

        assert destroyed == ["alpha"]
        assert "alpha" not in instance.CLIENTS

    @pytest.mark.asyncio
    async def test_destroy_client_is_noop_when_missing(self):
        # Removing a non-existent client should not raise.
        await instance.destroy_client("nonexistent")
        assert "nonexistent" not in instance.CLIENTS


# ---------------------------------------------------------------------------
# Type listings
# ---------------------------------------------------------------------------


class TestTypeListings:
    def test_agent_types_matches_agent_classes(self):
        types_listed = list(instance.agent_types())
        assert types_listed == list(agents_module.AGENT_CLASSES.keys())
        # The known core agents must all be registered upstream.
        assert "director" in types_listed
        assert "narrator" in types_listed
        assert "memory" in types_listed

    def test_client_types_matches_client_classes(self):
        types_listed = list(instance.client_types())
        assert types_listed == list(clients_module.CLIENT_CLASSES.keys())
        # Each type should map to a real class
        for typ in types_listed:
            assert clients_module.CLIENT_CLASSES[typ] is not None


# ---------------------------------------------------------------------------
# Instance iterators
# ---------------------------------------------------------------------------


class TestInstanceIterators:
    def test_client_instances_yields_pairs(self):
        a = MockClient("alpha")
        b = MockClient("beta")
        instance.CLIENTS["alpha"] = a
        instance.CLIENTS["beta"] = b

        listed = dict(instance.client_instances())

        assert listed == {"alpha": a, "beta": b}

    def test_agent_instances_yields_pairs(self):
        bootstrap_engine()
        listed = dict(instance.agent_instances())
        assert "director" in listed
        assert "narrator" in listed
        # Returned objects must be the same instances stored in the registry.
        assert listed["director"] is instance.AGENTS["director"]


# ---------------------------------------------------------------------------
# agent_instances_with_client
# ---------------------------------------------------------------------------


class TestAgentInstancesWithClient:
    def test_yields_only_agents_using_this_client(self):
        bootstrap_engine()
        c1 = MockClient("client-one")
        c2 = MockClient("client-two")
        # Wire two specific agents to c1, leave others to c2 / None
        instance.AGENTS["director"].client = c1
        instance.AGENTS["narrator"].client = c1
        instance.AGENTS["editor"].client = c2

        agents_for_c1 = list(instance.agent_instances_with_client(c1))
        agent_types_c1 = {a.agent_type for a in agents_for_c1}
        assert "director" in agent_types_c1
        assert "narrator" in agent_types_c1
        assert "editor" not in agent_types_c1

    def test_yields_nothing_when_no_match(self):
        bootstrap_engine()
        unused = MockClient("unused")
        # No agent has been wired to this client
        for agent in instance.AGENTS.values():
            if hasattr(agent, "client"):
                agent.client = None

        results = list(instance.agent_instances_with_client(unused))
        assert results == []

    def test_handles_agents_without_client_attribute(self):
        # The helper uses getattr(agent, "client", None) to be safe; this
        # ensures it does not raise on agents that never assigned client.
        class _StubAgent:
            agent_type = "stub"

        instance.AGENTS["stub"] = _StubAgent()
        c = MockClient("anything")
        # Must not raise - just yields nothing for this agent.
        results = list(instance.agent_instances_with_client(c))
        assert results == []


# ---------------------------------------------------------------------------
# get_active_client
# ---------------------------------------------------------------------------


class TestGetActiveClient:
    def test_returns_first_enabled_client(self):
        a = MockClient("alpha")
        b = MockClient("beta")
        instance.CLIENTS["alpha"] = a
        instance.CLIENTS["beta"] = b
        # Both MockClients report enabled=True, so we get the first one.
        result = instance.get_active_client()
        assert result is a

    def test_skips_disabled_clients(self):
        class _DisabledClient(MockClient):
            @property
            def enabled(self):
                return False

        disabled = _DisabledClient("alpha")
        active = MockClient("beta")
        instance.CLIENTS["alpha"] = disabled
        instance.CLIENTS["beta"] = active
        assert instance.get_active_client() is active

    def test_returns_none_when_no_clients(self):
        assert instance.get_active_client() is None

    def test_returns_none_when_all_clients_disabled(self):
        class _DisabledClient(MockClient):
            @property
            def enabled(self):
                return False

        instance.CLIENTS["alpha"] = _DisabledClient("alpha")
        assert instance.get_active_client() is None


# ---------------------------------------------------------------------------
# emit_agent_status (sync, dispatches when agent provided)
# ---------------------------------------------------------------------------


class TestEmitAgentStatus:
    def test_uninitialized_emit_uses_class_metadata(self, monkeypatch):
        captured = []

        def fake_emit(typ, **kwargs):
            captured.append((typ, kwargs))

        monkeypatch.setattr(instance, "emit", fake_emit)

        # Pull a real agent class from the registry so config_options() works.
        director_cls = agents_module.AGENT_CLASSES["director"]
        instance.emit_agent_status(director_cls, agent=None)

        assert len(captured) == 1
        typ, kwargs = captured[0]
        assert typ == "agent_status"
        assert kwargs["status"] == "uninitialized"
        assert kwargs["id"] == "director"
        # The data field should be populated from the class' config_options().
        assert "data" in kwargs

    @pytest.mark.asyncio
    async def test_initialized_emit_schedules_emit_status(self):
        # When an agent instance is provided, emit_agent_status schedules
        # the agent's own emit_status() coroutine via create_task.
        called = []

        class _StubAgent:
            agent_type = "stub"

            async def emit_status(self):
                called.append(True)

        agent = _StubAgent()
        instance.emit_agent_status(_StubAgent, agent=agent)
        # Yield to the loop so the scheduled task can run.
        import asyncio as _asyncio

        await _asyncio.sleep(0)
        assert called == [True]


# ---------------------------------------------------------------------------
# emit_agents_status / emit_agent_status_by_client
# ---------------------------------------------------------------------------


class TestEmitAgentsStatus:
    def test_emit_agents_status_iterates_known_classes(self, monkeypatch):
        recorded = []

        def fake_emit_agent_status(cls, agent=None):
            recorded.append((cls.agent_type, agent))

        monkeypatch.setattr(instance, "emit_agent_status", fake_emit_agent_status)

        instance.emit_agents_status()

        # All registered agent types should be enumerated, sorted by
        # verbose_name, with `agent=None` (since registry is empty).
        types_seen = {entry[0] for entry in recorded}
        assert types_seen == set(agents_module.AGENT_CLASSES.keys())
        for _, agent in recorded:
            assert agent is None

    def test_emit_agent_status_by_client_filters_to_matching(self, monkeypatch):
        bootstrap_engine()
        c1 = MockClient("c1")
        instance.AGENTS["director"].client = c1
        # Other agents have no client (or different) - they must NOT be emitted.

        recorded = []

        def fake_emit_agent_status(cls, agent=None):
            recorded.append(cls.agent_type)

        monkeypatch.setattr(instance, "emit_agent_status", fake_emit_agent_status)

        instance.emit_agent_status_by_client(c1)

        # Only the director agent (the one wired to c1) is emitted.
        assert recorded == ["director"]


# ---------------------------------------------------------------------------
# emit_clients_status
# ---------------------------------------------------------------------------


class TestEmitClientsStatus:
    @pytest.mark.asyncio
    async def test_emit_clients_status_invokes_status_on_each(self):
        called = []

        class _RecordingClient(MockClient):
            async def status(self):
                called.append(self.name)

        instance.CLIENTS["alpha"] = _RecordingClient("alpha")
        instance.CLIENTS["beta"] = _RecordingClient("beta")

        await instance.emit_clients_status(wait_for_status=True)

        assert sorted(called) == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_emit_clients_status_skips_none_entries(self):
        called = []

        class _RecordingClient(MockClient):
            async def status(self):
                called.append(self.name)

        instance.CLIENTS["alpha"] = _RecordingClient("alpha")
        instance.CLIENTS["beta"] = None  # falsy entries are skipped

        await instance.emit_clients_status(wait_for_status=True)

        assert called == ["alpha"]


# ---------------------------------------------------------------------------
# client status sweep coalescing (issue #89 - overlapping sweeps must share
# one in-flight status() round-trip per client)
# ---------------------------------------------------------------------------


class _GatedStatusClient(MockClient):
    """Counts status() calls; each call blocks until the gate is set."""

    def __init__(self, name: str, gate: asyncio.Event):
        super().__init__(name)
        self.status_calls = 0
        self._gate = gate

    async def status(self):
        self.status_calls += 1
        await self._gate.wait()


class TestClientStatusCoalescing:
    @pytest.mark.asyncio
    async def test_overlapping_status_sweeps_coalesce(self):
        gate = asyncio.Event()
        client_a = _GatedStatusClient("alpha", gate)
        client_b = _GatedStatusClient("beta", gate)
        instance.CLIENTS.update({"alpha": client_a, "beta": client_b})

        await instance.emit_clients_status()
        await asyncio.sleep(0)  # let the status tasks start
        assert client_a.status_calls == 1
        assert client_b.status_calls == 1

        # second and third sweeps while the first is still in flight join it
        await instance.emit_clients_status()
        await asyncio.sleep(0)
        gate.set()
        await instance.emit_clients_status(wait_for_status=True)

        assert client_a.status_calls == 1
        assert client_b.status_calls == 1

    @pytest.mark.asyncio
    async def test_new_sweep_after_completion_issues_fresh_status_calls(self):
        gate = asyncio.Event()
        gate.set()
        client_a = _GatedStatusClient("alpha", gate)
        instance.CLIENTS["alpha"] = client_a

        await instance.emit_clients_status(wait_for_status=True)
        assert client_a.status_calls == 1

        await instance.emit_clients_status(wait_for_status=True)
        assert client_a.status_calls == 2

    @pytest.mark.asyncio
    async def test_failed_status_task_is_replaced_on_next_sweep(self):
        class _ExplodingClient(_GatedStatusClient):
            async def status(self):
                self.status_calls += 1
                if self.status_calls == 1:
                    raise RuntimeError("probe failed")

        gate = asyncio.Event()
        gate.set()
        client_a = _ExplodingClient("alpha", gate)
        instance.CLIENTS["alpha"] = client_a

        await instance.emit_clients_status()
        with pytest.raises(RuntimeError):
            await instance.CLIENT_STATUS_TASKS["alpha"]

        await instance.emit_clients_status(wait_for_status=True)
        assert client_a.status_calls == 2

    @pytest.mark.asyncio
    async def test_instantiate_clients_only_emits_for_new_clients(
        self, patched_config, monkeypatch
    ):
        emits = []

        async def fake_emit(wait_for_status=False):
            emits.append(wait_for_status)

        monkeypatch.setattr(instance, "emit_clients_status", fake_emit)

        # config's client already instantiated - a value-only change must
        # not trigger a status sweep
        instance.CLIENTS["my-stub"] = MockClient("my-stub")
        await instance.instantiate_clients()
        assert emits == []

        # a genuinely new client still triggers the sweep
        del instance.CLIENTS["my-stub"]
        await instance.instantiate_clients()
        assert emits == [False]
        assert "my-stub" in instance.CLIENTS

    @pytest.mark.asyncio
    async def test_destroy_client_clears_status_task(self):
        gate = asyncio.Event()
        gate.set()
        client_a = _GatedStatusClient("alpha", gate)
        instance.CLIENTS["alpha"] = client_a

        await instance.emit_clients_status(wait_for_status=True)
        assert "alpha" in instance.CLIENT_STATUS_TASKS

        await instance.destroy_client("alpha")
        assert "alpha" not in instance.CLIENT_STATUS_TASKS
        assert "alpha" not in instance.CLIENTS


# ---------------------------------------------------------------------------
# purge_clients (uses live config but only iterates the registry)
# ---------------------------------------------------------------------------


class TestPurgeClients:
    @pytest.mark.asyncio
    async def test_purge_removes_clients_not_in_config(self):
        # Add a client whose name is guaranteed not to be in config.example.yaml
        destroyed = []

        class _Trackable(MockClient):
            async def destroy(self):
                destroyed.append(self.name)

        instance.CLIENTS["unknown-client"] = _Trackable("unknown-client")

        await instance.purge_clients()

        assert destroyed == ["unknown-client"]
        assert "unknown-client" not in instance.CLIENTS


# ---------------------------------------------------------------------------
# agent_ready_checks
# ---------------------------------------------------------------------------


class TestAgentReadyChecks:
    @pytest.mark.asyncio
    async def test_ready_check_gated_on_enabled_but_setup_check_always_runs(self):
        # ready_check is gated on `enabled` (it asks "is this agent ready to
        # work?"). setup_check runs for every live agent slot so auto-setup
        # paths (like TTS auto-enabling itself when kcpp loads a TTS model)
        # can fire before the user manually turns the agent on.
        ready_called = []
        setup_called = []

        class _Agent:
            def __init__(self, agent_type, enabled):
                self.agent_type = agent_type
                self.enabled = enabled

            async def ready_check(self):
                ready_called.append(self.agent_type)
                return True

            async def setup_check(self):
                setup_called.append(self.agent_type)
                return False

        instance.AGENTS["enabled-one"] = _Agent("enabled-one", True)
        instance.AGENTS["disabled-one"] = _Agent("disabled-one", False)
        instance.AGENTS["none-slot"] = None

        await instance.agent_ready_checks()

        assert ready_called == ["enabled-one"]
        assert sorted(setup_called) == ["disabled-one", "enabled-one"]


# ---------------------------------------------------------------------------
# instantiate_clients
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_client_class():
    """Register a non-network 'test-stub' client type for the duration of
    the test. Restores the registry afterwards so other tests don't see it."""

    class _StubClient(MockClient):
        client_type = "test-stub"

        def __init__(self, **kwargs):
            super().__init__(name=kwargs.get("name", "stub"))
            self._kwargs = kwargs

        async def status(self):
            return None

    saved = CLIENT_CLASSES.get("test-stub")
    CLIENT_CLASSES["test-stub"] = _StubClient
    yield _StubClient
    if saved is None:
        CLIENT_CLASSES.pop("test-stub", None)
    else:
        CLIENT_CLASSES["test-stub"] = saved


@pytest.fixture
def patched_config(stub_client_class):
    """Patch the live config to declare a single test-stub client.

    The session-wide _use_example_config fixture installs the example
    Config; here we further mutate it for the test and restore on teardown.
    """
    saved = dict(config_state.CONFIG.clients)
    config_state.CONFIG.clients["my-stub"] = ClientConfig(
        type="test-stub", name="my-stub"
    )
    yield config_state.CONFIG
    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved)


class TestInstantiateClients:
    @pytest.mark.asyncio
    async def test_creates_clients_from_config(self, patched_config):
        # Sanity: registry starts empty
        assert "my-stub" not in instance.CLIENTS

        await instance.instantiate_clients()

        assert "my-stub" in instance.CLIENTS
        client = instance.CLIENTS["my-stub"]
        assert client.client_type == "test-stub"

    @pytest.mark.asyncio
    async def test_skips_already_registered_clients(self, patched_config):
        # Pre-register a client under the same name; instantiate_clients
        # should not overwrite it.
        existing = MockClient("my-stub")
        instance.CLIENTS["my-stub"] = existing

        await instance.instantiate_clients()

        assert instance.CLIENTS["my-stub"] is existing


# ---------------------------------------------------------------------------
# instantiate_agents (no-config branch only)
# ---------------------------------------------------------------------------


class TestInstantiateAgents:
    @pytest.mark.asyncio
    async def test_creates_default_agent_for_every_class_in_registry(self):
        # The example config (loaded by the autouse fixture in conftest) has
        # no per-agent overrides, so every agent goes through the bare
        # `cls()` branch.
        await instance.instantiate_agents()

        # All AGENT_CLASSES keys should now have a corresponding instance.
        for typ in agents_module.AGENT_CLASSES:
            assert typ in instance.AGENTS
            assert instance.AGENTS[typ].agent_type == typ

    @pytest.mark.asyncio
    async def test_skips_existing_agents(self):
        # Pre-populate one agent so we can verify it is not replaced.
        # The placeholder must satisfy ensure_agent_llm_client's downstream
        # requires_llm_client check.
        class _Stub:
            agent_type = "director"
            requires_llm_client = False
            client = None

            async def emit_status(self):
                return None

        existing = _Stub()
        instance.AGENTS["director"] = existing

        await instance.instantiate_agents()

        assert instance.AGENTS["director"] is existing


# ---------------------------------------------------------------------------
# ensure_agent_llm_client
# ---------------------------------------------------------------------------


class TestEnsureAgentLLMClient:
    @pytest.mark.asyncio
    async def test_assigns_active_client_to_agents_requiring_llm(self):
        # Bootstrap real agents; then register a single MockClient as the
        # only available enabled client. Each agent that requires an LLM
        # should be wired to it.
        bootstrap_engine()
        active = MockClient("active")
        instance.CLIENTS["active"] = active
        # Clear any pre-existing client wires so we observe the assignment.
        for agent in instance.AGENTS.values():
            agent.client = None

        await instance.ensure_agent_llm_client()

        for typ, agent in instance.AGENTS.items():
            if agent.requires_llm_client:
                assert agent.client is active, f"{typ} not wired to active client"
