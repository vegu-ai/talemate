"""
Tests for the apply pipeline of the ``config/save`` websocket action.

``handle_save`` persists the full config, but a saved ``clients`` or
``agents`` section also has to be applied to the running instance (clients
instantiated/purged, agents reconfigured). The pipeline is diff-gated so a
plain settings save (e.g. gameplay options) stays free of client/agent
churn, and it runs before the ``app_config`` broadcast so the frontend only
ever adopts a config that is already live.

That broadcast is what ``config.changed`` receivers do (the real one is
``WebsocketHandler.on_config_changed``), so these tests keep a stand-in for it
connected: with the signal disconnected, an ordering assertion could not see a
pre-apply broadcast even if one went out.
"""

import pytest

import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.instance as instance
import talemate.server.config as server_config
from talemate.config import Config
from talemate.config.schema import Agent, Client
from talemate.server.config import ConfigPlugin

APPLY_FUNCTIONS = (
    "instantiate_clients",
    "purge_clients",
    "emit_clients_status",
    "configure_agents",
    "ensure_agent_llm_client",
)


@pytest.fixture(autouse=True)
def isolated_config_signals():
    """
    set_dirty() broadcasts config.changed to whatever receivers other test
    modules left connected (e.g. mock agents) - isolate the signal here. The
    plugin fixture connects the one receiver these tests care about.
    """
    saved = {}
    for name in ("config.changed", "config.changed.follow"):
        signal = async_signals.get(name)
        saved[signal] = signal.receivers
        signal.receivers = []
    yield
    for signal, receivers in saved.items():
        signal.receivers = receivers


class _MockWebsocketHandler:
    def __init__(self, events):
        self.events = events
        self.messages: list[dict] = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)
        self.events.append(("emit", {"type": data.get("type")}))

    async def on_config_changed(self, config: Config):
        """Stand-in for WebsocketHandler.on_config_changed."""
        self.queue_put({"type": "app_config", "data": config.model_dump()})


@pytest.fixture
def events():
    return []


@pytest.fixture
def app_config(monkeypatch):
    config = Config(
        clients={
            "TestClient": Client(type="openai", name="TestClient", model="gpt-4o-mini"),
        },
        agents={
            "conversation": Agent(name="conversation", client="TestClient"),
        },
    )
    monkeypatch.setattr(config_state, "CONFIG", config)
    return config


@pytest.fixture
def apply_calls(monkeypatch, events):
    def recorder(name):
        async def record(*args, **kwargs):
            events.append((name, kwargs))

        return record

    for name in APPLY_FUNCTIONS:
        monkeypatch.setattr(server_config, name, recorder(name))
    return events


@pytest.fixture
def plugin(events):
    handler = _MockWebsocketHandler(events)
    async_signals.get("config.changed").connect(handler.on_config_changed)
    return ConfigPlugin(handler)


def _payload(config: Config, **sections) -> dict:
    data = config.model_dump()
    data.update(sections)
    return {"config": data}


def _called(events) -> list[str]:
    return [name for name, _ in events]


@pytest.mark.asyncio
async def test_clients_changed_applies_client_pipeline(app_config, plugin, apply_calls):
    clients = app_config.model_dump()["clients"]
    clients["TestClient"]["model"] = "gpt-4o"

    await plugin.handle_save(_payload(app_config, clients=clients))

    assert _called(apply_calls) == [
        "instantiate_clients",
        "purge_clients",
        "emit_clients_status",
        "ensure_agent_llm_client",
        "emit",
        "emit",
    ]

    # status has to be settled before the frontend adopts the config
    assert dict(apply_calls)["emit_clients_status"] == {"wait_for_status": True}

    assert app_config.clients["TestClient"].model == "gpt-4o"


@pytest.mark.asyncio
async def test_new_client_applies_client_pipeline(app_config, plugin, apply_calls):
    clients = app_config.model_dump()["clients"]
    clients["SecondClient"] = Client(
        type="openai", name="SecondClient", model="gpt-4o"
    ).model_dump()

    await plugin.handle_save(_payload(app_config, clients=clients))

    assert "instantiate_clients" in _called(apply_calls)
    assert set(app_config.clients) == {"TestClient", "SecondClient"}


@pytest.mark.asyncio
async def test_agents_changed_applies_agent_pipeline(app_config, plugin, apply_calls):
    agents = app_config.model_dump()["agents"]
    agents["conversation"]["enabled"] = False

    await plugin.handle_save(_payload(app_config, agents=agents))

    # configure_agents runs ensure_agent_llm_client itself, so no explicit call
    assert _called(apply_calls) == [
        "configure_agents",
        "emit",
        "emit",
    ]

    assert app_config.agents["conversation"].enabled is False


@pytest.mark.asyncio
async def test_unchanged_sections_do_not_apply(app_config, plugin, apply_calls):
    payload = _payload(app_config)
    payload["config"]["game"]["general"]["auto_save"] = False

    await plugin.handle_save(payload)

    assert _called(apply_calls) == ["emit", "emit"]
    assert app_config.game.general.auto_save is False


@pytest.mark.asyncio
async def test_both_sections_changed_apply_both_pipelines(
    app_config, plugin, apply_calls
):
    clients = app_config.model_dump()["clients"]
    clients["TestClient"]["model"] = "gpt-4o"
    agents = app_config.model_dump()["agents"]
    agents["conversation"]["client"] = "OtherClient"

    await plugin.handle_save(_payload(app_config, clients=clients, agents=agents))

    assert _called(apply_calls) == [
        "instantiate_clients",
        "purge_clients",
        "emit_clients_status",
        "configure_agents",
        "emit",
        "emit",
    ]


@pytest.mark.asyncio
async def test_save_still_emits_app_config_and_completion(
    app_config, plugin, apply_calls
):
    await plugin.handle_save(_payload(app_config))

    messages = plugin.websocket_handler.messages
    assert messages[0]["type"] == "app_config"
    assert messages[0]["data"]["clients"]["TestClient"]["model"] == "gpt-4o-mini"
    assert messages[1] == {
        "type": "config",
        "action": "save_complete",
        "request_id": None,
    }


@pytest.mark.asyncio
async def test_no_app_config_broadcast_before_the_apply_pipeline(
    app_config, plugin, apply_calls
):
    """
    update_config() marks the config dirty, and a dirty config broadcasts - so
    without holding that signal back the frontend would adopt the new config
    while the running clients/agents were still the old ones.
    """
    clients = app_config.model_dump()["clients"]
    clients["TestClient"]["model"] = "gpt-4o"

    await plugin.handle_save(_payload(app_config, clients=clients))

    called = _called(apply_calls)
    broadcasts = [i for i, name in enumerate(called) if name == "emit"]
    applies = [i for i, name in enumerate(called) if name in APPLY_FUNCTIONS]
    assert applies, "expected the client pipeline to run"
    assert min(broadcasts) > max(applies)
    # exactly one broadcast: app_config, followed by the completion
    types = [message.get("type") for message in plugin.websocket_handler.messages]
    assert types == ["app_config", "config"]


@pytest.mark.asyncio
async def test_apply_failure_reports_a_saved_but_unapplied_config(
    app_config, plugin, apply_calls, monkeypatch
):
    """
    The config is stored before it is applied, so a failing apply must not be
    reported as a failed save - and the frontend still gets the stored config.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("client blew up")

    monkeypatch.setattr(server_config, "instantiate_clients", boom)

    clients = app_config.model_dump()["clients"]
    clients["TestClient"]["model"] = "gpt-4o"
    payload = _payload(app_config, clients=clients)
    payload["request_id"] = "save-44"

    await plugin.handle_save(payload)

    messages = plugin.websocket_handler.messages
    assert [message.get("type") for message in messages] == ["app_config", "config"]
    assert messages[-1]["action"] == "operation_done"
    assert messages[-1]["request_id"] == "save-44"
    assert messages[-1]["failed_action"] == "save"
    # what failed is the apply, not the save - the sender has to be able to
    # tell the two apart without reading the message
    assert messages[-1]["stage"] == "apply"
    assert "client blew up" in messages[-1]["error"]["message"]
    # the save itself landed
    assert app_config.clients["TestClient"].model == "gpt-4o"
    assert app_config.dirty is True


@pytest.mark.asyncio
async def test_a_failing_config_changed_receiver_reports_the_same_way(
    app_config, plugin, apply_calls
):
    """
    A receiver of the broadcast is the last leg of applying a saved config -
    one that errors out leaves whoever it feeds on the old config, so the save
    cannot be answered as a clean one either.
    """

    async def boom(config):
        raise RuntimeError("receiver blew up")

    signal = async_signals.get("config.changed")
    signal.connect(boom)
    try:
        payload = _payload(app_config)
        payload["request_id"] = "save-45"

        await plugin.handle_save(payload)
    finally:
        signal.disconnect(boom)

    messages = plugin.websocket_handler.messages
    assert messages[-1]["action"] == "operation_done"
    assert messages[-1]["request_id"] == "save-45"
    assert messages[-1]["failed_action"] == "save"
    assert messages[-1]["stage"] == "apply"
    assert "receiver blew up" in messages[-1]["error"]["message"]
    assert [message.get("action") for message in messages].count("save_complete") == 0


async def _failing_client_save(app_config, plugin, monkeypatch) -> None:
    """A clients save whose apply pipeline raises - what a retry starts from."""

    async def boom(*args, **kwargs):
        raise RuntimeError("client blew up")

    recorder = server_config.instantiate_clients
    monkeypatch.setattr(server_config, "instantiate_clients", boom)

    clients = app_config.model_dump()["clients"]
    clients["TestClient"]["model"] = "gpt-4o"

    await plugin.handle_save(_payload(app_config, clients=clients))

    monkeypatch.setattr(server_config, "instantiate_clients", recorder)
    plugin.websocket_handler.messages.clear()


@pytest.mark.asyncio
async def test_retry_of_a_failed_apply_runs_the_pipeline_again(
    app_config, plugin, apply_calls, monkeypatch
):
    """
    The stored config is already the payload, so the retry diffs as unchanged -
    without remembering the failed section it would skip the pipeline and
    report a success the running clients never saw.
    """
    await _failing_client_save(app_config, plugin, monkeypatch)
    apply_calls.clear()

    # the identical save the user (or the wizard's "Apply & finish") retries -
    # the stored config already holds it, so nothing diffs
    await plugin.handle_save(_payload(app_config))

    assert _called(apply_calls) == [
        "instantiate_clients",
        "purge_clients",
        "emit_clients_status",
        "ensure_agent_llm_client",
        "emit",
        "emit",
    ]
    assert plugin.websocket_handler.messages[-1]["action"] == "save_complete"


@pytest.mark.asyncio
async def test_save_of_another_section_still_applies_the_failed_one(
    app_config, plugin, apply_calls, monkeypatch
):
    """A gameplay toggle saved afterwards must not leave the clients stale either."""
    await _failing_client_save(app_config, plugin, monkeypatch)
    apply_calls.clear()

    payload = _payload(app_config)
    payload["config"]["game"]["general"]["auto_save"] = False
    await plugin.handle_save(payload)

    assert "instantiate_clients" in _called(apply_calls)
    assert app_config.game.general.auto_save is False


@pytest.mark.asyncio
async def test_applied_sections_are_not_reapplied_on_the_next_save(
    app_config, plugin, apply_calls, monkeypatch
):
    """Once the retry applied, an unrelated save is diff-gated again."""
    await _failing_client_save(app_config, plugin, monkeypatch)

    await plugin.handle_save(_payload(app_config))
    apply_calls.clear()

    payload = _payload(app_config)
    payload["config"]["game"]["general"]["auto_save"] = False
    await plugin.handle_save(payload)

    assert _called(apply_calls) == ["emit", "emit"]


@pytest.mark.asyncio
async def test_failure_during_a_forced_reapply_keeps_the_section_pending(
    app_config, plugin, apply_calls, monkeypatch
):
    """
    The forced re-apply is only forced by the record it clears on success - if
    it fails again the record has to survive it, or the save after that would
    diff as unchanged and skip a pipeline the running clients never saw.
    """
    await _failing_client_save(app_config, plugin, monkeypatch)
    apply_calls.clear()

    async def boom(*args, **kwargs):
        raise RuntimeError("status never settled")

    monkeypatch.setattr(server_config, "emit_clients_status", boom)

    # diffs as unchanged - the pending record is the only thing applying it
    await plugin.handle_save(_payload(app_config))

    assert _called(apply_calls) == [
        "instantiate_clients",
        "purge_clients",
        "emit",
        "emit",
    ]
    assert server_config.APPLY_PIPELINE.pending == {"clients"}
    assert plugin.websocket_handler.messages[-1]["stage"] == "apply"


@pytest.mark.asyncio
async def test_failure_in_the_client_finalize_keeps_the_section_pending(
    app_config, plugin, apply_calls, monkeypatch
):
    """
    Repointing the agents is the tail of a clients-only apply, so the section
    counts as applied only once it is through - marking it after the apply
    steps instead would report clients the agents never got pointed at as live.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("no client to point at")

    monkeypatch.setattr(server_config, "ensure_agent_llm_client", boom)

    clients = app_config.model_dump()["clients"]
    clients["TestClient"]["model"] = "gpt-4o"

    await plugin.handle_save(_payload(app_config, clients=clients))

    assert _called(apply_calls) == [
        "instantiate_clients",
        "purge_clients",
        "emit_clients_status",
        "emit",
        "emit",
    ]
    assert server_config.APPLY_PIPELINE.pending == {"clients"}
    assert plugin.websocket_handler.messages[-1]["stage"] == "apply"


def test_a_cover_declaration_that_does_not_reach_backward_is_refused(monkeypatch):
    """
    A section's apply can only deliver the finalize of a section that already
    ran - a forward, self-referencing or misspelled entry would just no-op, so
    the pipeline refuses it where it is built.
    """
    monkeypatch.setattr(
        server_config.ClientsApplySection, "covers_finalize_of", ("agents",)
    )

    with pytest.raises(ValueError, match="agents"):
        server_config.ConfigApplyPipeline()


def test_a_section_key_outside_the_literal_is_refused(monkeypatch):
    """
    The keys carry the outcome of a run - one outside ApplySectionKey would
    only surface as a validation error raised out of the pipeline, where it
    would mask whatever the apply actually failed on.
    """
    monkeypatch.setattr(server_config.ClientsApplySection, "key", "clientz")

    with pytest.raises(ValueError, match="not an ApplySectionKey"):
        server_config.ConfigApplyPipeline()


def test_two_sections_claiming_the_same_key_are_refused(monkeypatch):
    """A key is what a pending record names - two sections cannot share one."""
    monkeypatch.setattr(server_config.ClientsApplySection, "key", "agents")

    with pytest.raises(ValueError, match="another section already claims"):
        server_config.ConfigApplyPipeline()


async def _failing_agent_save(app_config, plugin, monkeypatch) -> None:
    """The agents-side mirror of _failing_client_save."""

    async def boom(*args, **kwargs):
        raise RuntimeError("agent blew up")

    recorder = server_config.configure_agents
    monkeypatch.setattr(server_config, "configure_agents", boom)

    agents = app_config.model_dump()["agents"]
    agents["conversation"]["enabled"] = False

    await plugin.handle_save(_payload(app_config, agents=agents))

    monkeypatch.setattr(server_config, "configure_agents", recorder)
    plugin.websocket_handler.messages.clear()


@pytest.mark.asyncio
async def test_retry_of_a_failed_agent_apply_runs_the_agent_pipeline_only(
    app_config, plugin, apply_calls, monkeypatch
):
    """The clients were never in question, so the forced re-apply leaves them alone."""
    await _failing_agent_save(app_config, plugin, monkeypatch)
    apply_calls.clear()

    await plugin.handle_save(_payload(app_config))

    assert _called(apply_calls) == ["configure_agents", "emit", "emit"]
    assert not server_config.APPLY_PIPELINE.pending
    assert plugin.websocket_handler.messages[-1]["action"] == "save_complete"


@pytest.mark.asyncio
async def test_a_section_marked_pending_elsewhere_is_applied_by_the_next_save(
    app_config, plugin, apply_calls
):
    """
    The help chat stores an agent setting whose apply failed and marks the
    agents through the config layer - the next save applies them although the
    agents section diffs as unchanged.
    """
    config_state.mark_apply_pending("agents")

    await plugin.handle_save(_payload(app_config))

    assert _called(apply_calls) == ["configure_agents", "emit", "emit"]
    assert not server_config.APPLY_PIPELINE.pending


@pytest.mark.asyncio
async def test_a_clean_client_apply_is_not_recorded_when_the_agents_fail(
    app_config, plugin, apply_calls, monkeypatch
):
    """
    Only what did not get through is stale: the clients are live once their
    status settled, so a failure in the agent half must not force the (blocking)
    client pipeline onto the next save.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("agent blew up")

    recorder = server_config.configure_agents
    monkeypatch.setattr(server_config, "configure_agents", boom)

    clients = app_config.model_dump()["clients"]
    clients["TestClient"]["model"] = "gpt-4o"
    agents = app_config.model_dump()["agents"]
    agents["conversation"]["enabled"] = False

    await plugin.handle_save(_payload(app_config, clients=clients, agents=agents))

    monkeypatch.setattr(server_config, "configure_agents", recorder)
    assert server_config.APPLY_PIPELINE.pending == {"agents"}
    apply_calls.clear()

    await plugin.handle_save(_payload(app_config))

    assert _called(apply_calls) == ["configure_agents", "emit", "emit"]


@pytest.mark.asyncio
async def test_two_failed_applies_accumulate_both_sections(
    app_config, plugin, apply_calls, monkeypatch
):
    """A second failure adds to the record, it does not replace it."""
    await _failing_agent_save(app_config, plugin, monkeypatch)
    # the clients apply fails before anything lands, so the pending agents
    # section it was dragging along stays pending too
    await _failing_client_save(app_config, plugin, monkeypatch)

    assert server_config.APPLY_PIPELINE.pending == {"clients", "agents"}
    apply_calls.clear()

    payload = _payload(app_config)
    payload["config"]["game"]["general"]["auto_save"] = False
    await plugin.handle_save(payload)

    assert _called(apply_calls) == [
        "instantiate_clients",
        "purge_clients",
        "emit_clients_status",
        "configure_agents",
        "emit",
        "emit",
    ]
    assert not server_config.APPLY_PIPELINE.pending


@pytest.mark.asyncio
async def test_save_completion_echoes_request_id(app_config, plugin, apply_calls):
    """
    The settings view and the clients/agents drawer both save through this
    action - the completion has to say whose save it answers.
    """
    payload = _payload(app_config)
    payload["request_id"] = "save-42"

    await plugin.handle_save(payload)

    completion = plugin.websocket_handler.messages[-1]
    assert completion["action"] == "save_complete"
    assert completion["request_id"] == "save-42"


@pytest.mark.asyncio
async def test_refused_save_is_attributable(app_config, plugin, apply_calls):
    """A rejected payload answers with an id-carrying error, not silence."""
    data = _payload(app_config)
    data["action"] = "save"
    data["request_id"] = "save-43"
    # clients is a mapping of client models - a scalar fails validation
    data["config"]["clients"] = "not-a-client-map"

    await plugin.handle(data)

    messages = plugin.websocket_handler.messages
    assert len(messages) == 1
    assert messages[0]["action"] == "operation_done"
    assert messages[0]["request_id"] == "save-43"
    assert messages[0]["failed_action"] == "save"
    assert messages[0]["error"]["message"]
    # a refusal is not an apply failure - nothing was stored, so everything
    # stacked on this payload carries the rejected content
    assert "stage" not in messages[0]
    # nothing was applied and the config is untouched
    assert [name for name in _called(apply_calls) if name in APPLY_FUNCTIONS] == []
    assert "TestClient" in config_state.CONFIG.clients


# ----------------------------------------------------------------------------
# deletion-by-omission: the two shapes where a client leaves the config
#
# These run the REAL apply functions against a fake client/agent registry -
# a save that drops a client only removes it from the config, so what actually
# purges the instance and repoints the agents is the pipeline below.
# ----------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, **kwargs):
        self.name = kwargs.get("name")
        self.client_type = kwargs.get("type")
        self.enabled = kwargs.get("enabled", True)
        self.destroyed = False

    async def destroy(self):
        self.destroyed = True


class _FakeAgent:
    requires_llm_client = True

    def __init__(self, agent_type: str, client=None):
        self.agent_type = agent_type
        self.client = client
        self.applied = None

    async def apply_config(self, **kwargs):
        self.applied = kwargs

    async def emit_status(self, *args, **kwargs):
        pass


@pytest.fixture
def live_instance(monkeypatch, app_config):
    """A running instance holding the config's client, used by one agent."""
    client = _FakeClient(name="TestClient", type="openai")
    agent = _FakeAgent("conversation", client=client)
    monkeypatch.setattr(instance, "CLIENTS", {"TestClient": client})
    monkeypatch.setattr(instance, "AGENTS", {"conversation": agent})
    monkeypatch.setattr(instance, "CLIENT_STATUS_TASKS", {})
    monkeypatch.setattr(instance.clients, "get_client_class", lambda _type: _FakeClient)

    # real status sweeps talk to the client's backend
    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(instance, "emit_clients_status", noop)
    monkeypatch.setattr(server_config, "emit_clients_status", noop)
    return {"client": client, "agent": agent}


@pytest.mark.asyncio
async def test_renamed_client_is_instantiated_purged_and_repointed(
    app_config, plugin, live_instance
):
    clients = {
        "RenamedClient": Client(
            type="openai", name="RenamedClient", model="gpt-4o-mini"
        ).model_dump()
    }
    agents = app_config.model_dump()["agents"]
    agents["conversation"]["client"] = "RenamedClient"

    await plugin.handle_save(_payload(app_config, clients=clients, agents=agents))

    assert set(instance.CLIENTS) == {"RenamedClient"}
    assert live_instance["client"].destroyed is True
    assert live_instance["agent"].client is instance.CLIENTS["RenamedClient"]


@pytest.mark.asyncio
async def test_deleted_client_still_referenced_falls_back_to_an_active_client(
    app_config, plugin, live_instance
):
    """
    The agents section is untouched, so its entry still names the deleted
    client - ensure_agent_llm_client is what stops the agent from holding a
    purged client.
    """
    fallback = _FakeClient(name="OtherClient", type="openai")
    instance.CLIENTS["OtherClient"] = fallback

    clients = {
        "OtherClient": Client(
            type="openai", name="OtherClient", model="gpt-4o-mini"
        ).model_dump()
    }

    await plugin.handle_save(_payload(app_config, clients=clients))

    assert set(instance.CLIENTS) == {"OtherClient"}
    assert live_instance["client"].destroyed is True
    assert app_config.agents["conversation"].client == "TestClient"
    assert live_instance["agent"].client is fallback
