"""
Keep track of clients and agents
"""

import asyncio

import structlog

import talemate.agents as agents
import talemate.client as clients
import talemate.client.bootstrap as bootstrap
from talemate.emit import emit
from talemate.emit.signals import handlers

log = structlog.get_logger("talemate")

AGENTS = {}
CLIENTS = {}


def get_agent(typ: str, *create_args, **create_kwargs):
    agent = AGENTS.get(typ)

    if agent:
        return agent

    if create_args or create_kwargs:
        cls = agents.get_agent_class(typ)
        agent = cls(*create_args, **create_kwargs)
        set_agent(typ, agent)
        return agent


def set_agent(typ, agent):
    AGENTS[typ] = agent


def destroy_client(name: str):
    client = CLIENTS.get(name)
    if client:
        del CLIENTS[name]


def get_client(name: str, *create_args, **create_kwargs):
    client = CLIENTS.get(name)

    if client:
        if create_kwargs:
            client.reconfigure(**create_kwargs)
        return client

    if "type" in create_kwargs:
        typ = create_kwargs.get("type")
        cls = clients.get_client_class(typ)
        client = cls(name=name, *create_args, **create_kwargs)
        set_client(name, client)
        return client


def set_client(name, client):
    CLIENTS[name] = client


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


async def emit_clients_status():
    """
    Will emit status of all clients
    """
    # log.debug("emit", type="client status")
    for client in CLIENTS.values():
        if client:
            await client.status()


def _sync_emit_clients_status(*args, **kwargs):
    """
    Will emit status of all clients
    in synchronous mode
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(emit_clients_status())


handlers["request_client_status"].connect(_sync_emit_clients_status)


async def emit_client_bootstraps():
    emit("client_bootstraps", data=list(await bootstrap.list_all()))


def sync_emit_clients_status():
    """
    Will emit status of all clients
    in synchronous mode
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(emit_clients_status())


async def sync_client_bootstraps():
    """
    Will loop through all registered client bootstrap lists and spawn / update
    client instances from them.
    """

    for service_name, func in bootstrap.LISTS.items():
        async for client_bootstrap in func():
            log.debug(
                "sync client bootstrap",
                service_name=service_name,
                client_bootstrap=client_bootstrap.dict(),
            )
            client = get_client(
                client_bootstrap.name,
                type=client_bootstrap.client_type.value,
                api_url=client_bootstrap.api_url,
                enabled=True,
            )
            await client.status()


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
        #loop = asyncio.get_event_loop()
        #loop.run_until_complete(agent.emit_status())


def emit_agents_status(*args, **kwargs):
    """
    Will emit status of all agents
    """
    # log.debug("emit", type="agent status")
    for typ, cls in sorted(agents.AGENT_CLASSES.items(), key=lambda x: x[1].verbose_name):
        agent = AGENTS.get(typ)
        emit_agent_status(cls, agent)


handlers["request_agent_status"].connect(emit_agents_status)

async def agent_ready_checks():
    for agent in AGENTS.values():
        if agent and agent.enabled:
            await agent.ready_check()