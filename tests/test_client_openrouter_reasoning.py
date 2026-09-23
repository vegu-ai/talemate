import json

import httpx
import pytest

import talemate.config.state as config_state
from talemate.client import openrouter
from talemate.client.context import ClientContext


@pytest.fixture
def wire(monkeypatch):
    requests = []
    async_client = httpx.AsyncClient

    def respond(request):
        requests.append(json.loads(request.content))
        chunk = {"choices": [{"index": 0, "delta": {"content": "answer"}}]}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(
        openrouter.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(respond)),
    )
    return requests


@pytest.fixture
def client(cfg_isolation, monkeypatch):
    monkeypatch.setattr(config_state.CONFIG.openrouter, "api_key", "test-key")

    def create(**kwargs):
        config_state.CONFIG.clients["openrouter"] = openrouter.ClientConfig(
            name="openrouter",
            type="openrouter",
            model="anthropic/claude-haiku-4.5",
            **kwargs,
        )
        return openrouter.OpenRouterClient(name="openrouter")

    return create


async def test_reasoning_on_sends_the_reasoning_budget(client, wire):
    await client(reason_enabled=True, reason_tokens=2048).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert wire[-1]["reasoning"] == {"max_tokens": 2048}


async def test_reasoning_budget_respects_the_minimum(client, wire):
    await client(reason_enabled=True, reason_tokens=64).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert wire[-1]["reasoning"] == {"max_tokens": openrouter.MIN_THINKING_TOKENS}


async def test_reasoning_off_sends_no_reasoning_object(client, wire):
    await client(reason_enabled=False, reason_tokens=2048).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert "reasoning" not in wire[-1]
    assert wire[-1]["max_tokens"] == 96


async def test_action_override_sends_no_reasoning_object(client, wire):
    reasoning_client = client(reason_enabled=True, reason_tokens=2048)
    with ClientContext(disable_reasoning=True, requires_active_scene=False):
        await reasoning_client.generate("hello", {"max_tokens": 96}, "conversation")
    assert "reasoning" not in wire[-1]
