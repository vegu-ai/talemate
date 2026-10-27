"""The decision model settings ask the backend for OpenRouter's decision models."""

from __future__ import annotations

import asyncio

import pytest

from talemate.client import openrouter
from talemate.emit import Receiver
from talemate.server.config import ConfigPlugin
from talemate.server.websocket_server import WebsocketHandler


class _MockWebsocketHandler:
    def __init__(self):
        self.messages = []
        self.scene = None

    def queue_put(self, data):
        self.messages.append(data)


@pytest.mark.asyncio
async def test_the_list_is_sent_without_holding_up_the_handler(monkeypatch):
    release = asyncio.Event()

    async def fetch():
        await release.wait()
        return [openrouter.DecisionModel(id="typesafe/jev-1.13", name="Jev 1.13")]

    monkeypatch.setattr(openrouter, "fetch_available_decision_models", fetch)
    handler = _MockWebsocketHandler()
    plugin = ConfigPlugin(handler)

    await plugin.handle({"type": "config", "action": "request_decision_models"})
    assert handler.messages == []

    release.set()
    await asyncio.gather(*plugin._decision_model_requests)

    assert handler.messages == [
        {
            "type": "config",
            "action": "decision_models",
            "data": {"models": [{"id": "typesafe/jev-1.13", "name": "Jev 1.13"}]},
        }
    ]
    assert plugin._decision_model_requests == set()


@pytest.mark.asyncio
async def test_an_unavailable_list_is_sent_empty(monkeypatch):
    async def fetch():
        return []

    monkeypatch.setattr(openrouter, "fetch_available_decision_models", fetch)
    handler = _MockWebsocketHandler()
    plugin = ConfigPlugin(handler)

    await plugin.handle_request_decision_models({})
    await asyncio.gather(*plugin._decision_model_requests)

    assert handler.messages[0]["data"] == {"models": []}


@pytest.mark.asyncio
async def test_a_list_that_arrives_later_is_pushed_to_the_page(monkeypatch):
    """A fetch after the page's own request (the config-save retry, or one
    after the cooldown) reaches the page without another request."""

    async def fetch_list(state, list_name, url, parse, headers=None, refresh=False):
        return parse([{"id": "liquid/d1", "name": "LiquidAI: d1"}])

    monkeypatch.setattr(openrouter, "_fetch_list", fetch_list)
    monkeypatch.setattr(openrouter, "DECISION_MODELS", [])
    pushed: list[dict] = []
    handler = WebsocketHandler.__new__(WebsocketHandler)
    handler.queue_put = pushed.append
    receiver = Receiver()
    receiver.handle_decision_models_changed = handler.handle_decision_models_changed
    receiver.connect()
    try:
        await openrouter.fetch_available_decision_models()
    finally:
        receiver.disconnect()

    assert pushed == [
        {
            "type": "config",
            "action": "decision_models",
            "data": {"models": [{"id": "liquid/d1", "name": "LiquidAI: d1"}]},
        }
    ]
