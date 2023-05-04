"""
Retrieve pod information from the server which can then be used to bootstrap talemate client
connection for the pod.  This is a simple wrapper around the runpod module.
"""

import dotenv
import runpod
import os
import json

from .bootstrap import ClientBootstrap, ClientType, register_list

from talemate.config import load_config

import structlog

log = structlog.get_logger("talemate.client.runpod")

dotenv.load_dotenv()

runpod.api_key = load_config().get("runpod", {}).get("api_key", "")

def is_textgen_pod(pod):
    
    name = pod["name"].lower()
    
    if "textgen" in name or "thebloke llms" in name:
        return True
    
    return False

def get_textgen_pods():
    """
    Return a list of text generation pods.
    """
    
    if not runpod.api_key:
        return
    
    for pod in runpod.get_pods():
        if not pod["desiredStatus"] == "RUNNING":
            continue
        if is_textgen_pod(pod):
            yield pod
            

def get_automatic1111_pods():
    """
    Return a list of automatic1111 pods.
    """
    
    if not runpod.api_key:
        return
    
    for pod in runpod.get_pods():
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
        api_url = f"https://{id}-5000.proxy.runpod.net/api"
    elif client_type == ClientType.automatic1111:
        api_url = f"https://{id}-5000.proxy.runpod.net/api"
    
    return ClientBootstrap(
        client_type=client_type,
        uid=pod["id"],
        name=pod["name"],
        api_url=api_url,
        service_name="runpod"
    )
            

@register_list("runpod")
def client_bootstrap_list():
    """
    Return a list of client bootstrap options.
    """
    textgen_pods = list(get_textgen_pods()) 
    automatic1111_pods = list(get_automatic1111_pods())
    
    for pod in textgen_pods:
        yield _client_bootstrap(ClientType.textgen, pod)
    
    for pod in automatic1111_pods:
        yield _client_bootstrap(ClientType.automatic1111, pod)