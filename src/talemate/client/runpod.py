"""
Retrieve pod information from the server which can then be used to bootstrap talemate client
connection for the pod.  This is a simple wrapper around the runpod module.
"""

import asyncio
import json
import os

import dotenv
import runpod
import structlog

from talemate.config import load_config

from .bootstrap import ClientBootstrap, ClientType, register_list

log = structlog.get_logger("talemate.client.runpod")

dotenv.load_dotenv()

runpod.api_key = load_config().get("runpod", {}).get("api_key", "")


def is_textgen_pod(pod):
    name = pod["name"].lower()

    if "textgen" in name or "thebloke llms" in name:
        return True

    return False


async def _async_get_pods():
    """
    asyncio wrapper around get_pods.
    """

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, runpod.get_pods)


async def get_textgen_pods():
    """
    Return a list of text generation pods.
    """

    if not runpod.api_key:
        return

    for pod in await _async_get_pods():
        if not pod["desiredStatus"] == "RUNNING":
            continue
        if is_textgen_pod(pod):
            yield pod


async def get_automatic1111_pods():
    """
    Return a list of automatic1111 pods.
    """

    if not runpod.api_key:
        return

    for pod in await _async_get_pods():
        if not pod["desiredStatus"] == "RUNNING":
            continue
        if "automatic1111" in pod["name"].lower():
            yield pod


def _client_bootstrap(client_type: ClientType, pod):
    """
    Return a client bootstrap object for the given client type and pod.
    """

    id = pod["id"]

    if client_type == ClientType.textgen:
        api_url = f"https://{id}-5000.proxy.runpod.net"
    elif client_type == ClientType.automatic1111:
        api_url = f"https://{id}-5000.proxy.runpod.net"

    return ClientBootstrap(
        client_type=client_type,
        uid=pod["id"],
        name=pod["name"],
        api_url=api_url,
        service_name="runpod",
    )


@register_list("runpod")
async def client_bootstrap_list():
    """
    Return a list of client bootstrap options.
    """
    textgen_pods = []
    async for pod in get_textgen_pods():
        textgen_pods.append(pod)

    automatic1111_pods = []
    async for pod in get_automatic1111_pods():
        automatic1111_pods.append(pod)

    for pod in textgen_pods:
        yield _client_bootstrap(ClientType.textgen, pod)

    for pod in automatic1111_pods:
        yield _client_bootstrap(ClientType.automatic1111, pod)
