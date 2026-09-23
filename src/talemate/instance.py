"""
Keep track of clients and agents
"""

import asyncio
import traceback
from typing import TYPE_CHECKING

import structlog

import talemate.agents as agents
import talemate.client as clients
from talemate.client.base import ClientStatus
from talemate.emit import emit
from talemate.emit.signals import handlers
import talemate.emit.async_signals as async_signals
from talemate.config import get_config, Config, mark_apply_pending

if TYPE_CHECKING:
    from talemate.agents.base import Agent

log = structlog.get_logger("talemate")

AGENTS = {}
CLIENTS = {}

# in-flight client.status() tasks keyed by client name - lets overlapping
# status sweeps share one remote round-trip per client instead of stacking them
CLIENT_STATUS_TASKS = {}

# last reported ready-check failure per agent type, so an agent that fails on
# every sweep is reported once rather than every 3 seconds
AGENT_READY_CHECK_ERRORS = {}


def get_agent(typ: str):
    agent = AGENTS.get(typ)

    if not agent:
        raise KeyError(f"Agent {typ} has not been instantiated")

    return agent


async def destroy_client(name: str):
    client = CLIENTS.get(name)
    if client:
        await client.destroy()
        del CLIENTS[name]
    CLIENT_STATUS_TASKS.pop(name, None)


def get_client(name: str):
    client = CLIENTS.get(name)

    if not client:
        raise KeyError(f"Client {name} has not been instantiated")

    return client


def agent_types():
    return agents.AGENT_CLASSES.keys()


def client_types():
    return clients.CLIENT_CLASSES.keys()


def client_instances():
    return CLIENTS.items()


def agent_instances():
    return AGENTS.items()


def agent_instances_with_client(client):
    """
    return a list of agents that have the specified client
    """

    for typ, agent in agent_instances():
        if getattr(agent, "client", None) == client:
            yield agent


def emit_agent_status_by_client(client):
    """
    Will emit status of all agents that have the specified client
    """

    for agent in agent_instances_with_client(client):
        emit_agent_status(agent.__class__, agent)


async def bounded_client_status(client):
    """Run one status probe, bounded by the client's probe timeout.

    The bound lives here rather than in `ClientBase.status()` because a client
    type that overrides `status()` (ollama, pi_bridge) does its own I/O before
    the base method runs. A probe that never returns would keep this client's
    CLIENT_STATUS_TASKS slot occupied for the life of the process, and no
    later sweep would ever probe it again.
    """
    # asyncio.timeout, not wait_for: it tells its own deadline apart from a
    # cancellation arriving from outside (the wait_for_status gather path), and
    # on 3.11 it also avoids the extra task hop that would delay the probe by
    # an event-loop turn
    try:
        async with asyncio.timeout(client.status_probe_timeout):
            await client.status()
    except asyncio.TimeoutError:
        log.warning(
            "client status probe timed out",
            client=client.name,
            timeout=client.status_probe_timeout,
        )
        # remote_model_name goes too: a locked-model client would keep
        # reporting the last known model in its error frame otherwise
        client.remote_model_name = None
        client.connected = False
        client.emit_status()


async def emit_clients_status(wait_for_status: bool = False):
    """
    Will emit status of all clients
    """
    # log.debug("emit", type="client status")
    tasks = []
    for name, client in list(CLIENTS.items()):
        if not client:
            continue
        # the frontend builds its client list from these emissions alone, so
        # every sweep reports the last known state at once - a client behind a
        # slow or dead endpoint must not wait for its probe to appear in the UI
        try:
            client.emit_status()
        except Exception:
            log.error(
                "client status emit failed",
                name=name,
                error=traceback.format_exc(),
            )
        task = CLIENT_STATUS_TASKS.get(name)
        if not task or task.done():
            task = asyncio.create_task(bounded_client_status(client))
            CLIENT_STATUS_TASKS[name] = task
        tasks.append(task)

    if wait_for_status:
        await asyncio.gather(*tasks)


def sync_emit_clients_status(*args, **kwargs):
    """
    Will emit status of all clients
    in synchronous mode
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(emit_clients_status())


handlers["request_client_status"].connect(sync_emit_clients_status)


def emit_agent_status(cls, agent=None):
    if not agent:
        emit(
            "agent_status",
            message="",
            id=cls.agent_type,
            status="uninitialized",
            data=cls.config_options(),
        )
    else:
        asyncio.create_task(agent.emit_status())
        # loop = asyncio.get_event_loop()
        # loop.run_until_complete(agent.emit_status())


def emit_agents_status(*args, **kwargs):
    """
    Will emit status of all agents
    """
    # log.debug("emit", type="agent status")
    for typ, cls in sorted(
        agents.AGENT_CLASSES.items(), key=lambda x: x[1].verbose_name
    ):
        agent = AGENTS.get(typ)
        emit_agent_status(cls, agent)


handlers["request_agent_status"].connect(emit_agents_status)


async def agent_ready_checks():
    for agent in AGENTS.values():
        if not agent:
            continue
        # one agent's failure must not stop the agents after it, nor the
        # steps that run after this sweep in the status loop. It is swallowed
        # here, so the status loop's own dedup never sees it - an agent that
        # fails every sweep would report a traceback every 3 seconds without
        # the dedup below.
        try:
            if agent.enabled:
                await agent.ready_check()
            # setup_check runs unconditionally so agents with auto-setup enabled
            # can flip themselves on (or sync their state) without first needing
            # the user to manually enable them.
            await agent.setup_check()
        except Exception:
            error = traceback.format_exc()
            if AGENT_READY_CHECK_ERRORS.get(agent.agent_type) == error:
                log.debug("agent ready check failed", agent=agent.agent_type)
            else:
                AGENT_READY_CHECK_ERRORS[agent.agent_type] = error
                log.error(
                    "agent ready check failed",
                    agent=agent.agent_type,
                    error=error,
                )
        else:
            AGENT_READY_CHECK_ERRORS.pop(agent.agent_type, None)


def get_active_client():
    for client in CLIENTS.values():
        if client.enabled:
            return client
    return None


async def instantiate_agents():
    config: Config = get_config()

    for typ, cls in agents.AGENT_CLASSES.items():
        if typ in AGENTS:
            continue

        agent_config = config.agents.get(typ)
        if agent_config:
            _agent_config = agent_config.model_dump()

            client_name = _agent_config.pop("client", None)
            if client_name:
                _agent_config["client"] = CLIENTS.get(client_name)

            _agent_config.pop("name", None)
            actions = _agent_config.pop("actions", None)
            enabled = _agent_config.pop("enabled", True)

            agent = cls(**_agent_config)

            if actions:
                await agent.apply_config(actions=actions, enabled=enabled)

            if not enabled and agent.has_toggle:
                agent.is_enabled = False
            elif enabled is True and agent.has_toggle:
                agent.is_enabled = True

            AGENTS[typ] = agent
            await agent.emit_status()
        else:
            agent = cls()
            AGENTS[typ] = agent
            await agent.emit_status()

    await ensure_agent_llm_client()


async def instantiate_clients():
    config: Config = get_config()
    created = False
    for name, client_config in config.clients.items():
        if name in CLIENTS:
            continue

        client = clients.get_client_class(client_config.type)(
            **client_config.model_dump()
        )
        CLIENTS[name] = client
        created = True

    if created:
        await emit_clients_status()


async def apply_agent_config(agent: "Agent", **config) -> None:
    try:
        await agent.apply_config(**config, force=agent.config_apply_failed)
    except (Exception, asyncio.CancelledError):
        agent.config_apply_failed = True
        mark_apply_pending("agents")
        raise
    else:
        agent.config_apply_failed = False


async def configure_agents():
    config: Config = get_config()
    for name, agent_config in config.agents.items():
        agent = AGENTS.get(name)
        if not agent:
            log.warn("agent not found", name=name)
            continue

        await apply_agent_config(agent, **agent_config.model_dump())
        await agent.emit_status()

    await ensure_agent_llm_client()


async def ensure_agent_llm_client():
    config: Config = get_config()
    for name, agent in AGENTS.items():
        agent_config = config.agents.get(name)

        if not agent:
            log.warn("agent not found", name=name)
            continue

        if not agent.requires_llm_client:
            continue

        client_name = agent_config.client if agent_config else None

        if not client_name:
            client = get_active_client()

        elif not CLIENTS.get(client_name):
            client = get_active_client()

        else:
            client = CLIENTS.get(client_name)
            if client and not client.enabled:
                client = get_active_client()

        log.debug(
            "ensure_agent_llm_client",
            agent=agent.agent_type,
            client=client.client_type if client else None,
        )

        if agent.client != client:
            agent.client = client
            await agent.emit_status()


async def purge_clients():
    """Checks for clients in CLIENTS that are not longer in the config
    and removes them
    """
    config: Config = get_config()
    for name, _ in list(CLIENTS.items()):
        if name in config.clients:
            continue
        await destroy_client(name)


async def on_config_changed(config: Config):
    await emit_clients_status()
    emit_agents_status()


async def on_client_disabled(client_status: ClientStatus):
    await ensure_agent_llm_client()


async def on_client_enabled(client_status: ClientStatus):
    await ensure_agent_llm_client()


async_signals.get("config.changed").connect(on_config_changed)
async_signals.get("client.disabled").connect(on_client_disabled)
async_signals.get("client.enabled").connect(on_client_enabled)
