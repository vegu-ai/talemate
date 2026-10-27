from collections.abc import Callable

import httpx

from ..provider import ProviderCapabilities
from .typesafe import TypeSafeDecisionProvider


class SystemOneDecisionProvider(TypeSafeDecisionProvider):
    name = "systemone"

    def __init__(
        self,
        model: str,
        base_url: str,
        credential: Callable[[], str | None],
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        capabilities: ProviderCapabilities | None = None,
    ):
        super().__init__(model, credential, transport, capabilities=capabilities)
        self.url = f"{base_url.rstrip('/')}/v1/systemone" if base_url else ""
