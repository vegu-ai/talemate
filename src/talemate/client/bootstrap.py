from enum import Enum

import pydantic

__all__ = [
    "ClientType",
    "ClientBootstrap",
    "register_list",
    "list_all",
]

LISTS = {}


class ClientType(str, Enum):
    """Client type enum."""

    textgen = "textgenwebui"
    automatic1111 = "automatic1111"


class ClientBootstrap(pydantic.BaseModel):
    """Client bootstrap model."""

    # client type, currently supports "textgen" and "automatic1111"

    client_type: ClientType

    # unique client identifier

    uid: str

    # connection name

    name: str

    # connection information for the client
    # REST api url

    api_url: str

    # service name (for example runpod)

    service_name: str


class register_list:
    def __init__(self, service_name: str):
        self.service_name = service_name

    def __call__(self, func):
        LISTS[self.service_name] = func
        return func


async def list_all(exclude_urls: list[str] = list()):
    """
    Return a list of client bootstrap objects.
    """

    for service_name, func in LISTS.items():
        async for item in func():
            if item.api_url not in exclude_urls:
                yield item.dict()
