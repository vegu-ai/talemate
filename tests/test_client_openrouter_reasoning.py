import json
from types import SimpleNamespace

import httpx
import pytest

import talemate.config.state as config_state
from talemate.client import openrouter
from talemate.agents.context import ActiveAgent
from talemate.client.context import ClientContext
from talemate.client.reasoning_effort import EFFORT_LEVELS
from talemate.config.schema import Config


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


@pytest.mark.parametrize("effort", EFFORT_LEVELS)
async def test_reasoning_on_sends_the_effort_without_a_budget(client, wire, effort):
    await client(reason_enabled=True, effort_level=effort).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    expected = {"enabled": True} if effort == "default" else {"effort": effort}
    assert wire[-1]["reasoning"] == expected


@pytest.mark.parametrize("effort", ["default", "high"])
async def test_reasoning_off_sends_no_reasoning_object(client, wire, effort):
    await client(reason_enabled=False, effort_level=effort).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert "reasoning" not in wire[-1]
    assert wire[-1]["max_tokens"] == 96


async def test_action_override_sends_no_reasoning_object(client, wire):
    reasoning_client = client(reason_enabled=True, effort_level="high")
    with ClientContext(disable_reasoning=True, requires_active_scene=False):
        await reasoning_client.generate("hello", {"max_tokens": 96}, "conversation")
    assert "reasoning" not in wire[-1]


@pytest.fixture
def active_agent():
    agent = SimpleNamespace(
        agent_type="narrator",
        verbose_name="Narrator",
        allow_repetition_break=lambda *args, **kwargs: False,
        inject_prompt_paramters=lambda *args: None,
    )
    with ActiveAgent(agent, lambda: None):
        yield


async def test_reason_tokens_add_room_to_a_capped_response(client, wire, active_agent):
    capped = client(
        reason_enabled=True,
        reason_tokens=64,
        effort_level="medium",
        enforce_response_length="cap_tokens",
    )
    with ClientContext(requires_active_scene=False):
        await capped.send_prompt("hello", kind="conversation")
    assert wire[-1]["max_tokens"] == 96 + 64
    assert wire[-1]["reasoning"] == {"effort": "medium"}


async def test_new_client_defaults_reason_at_the_model_default_effort(
    client, wire, active_agent
):
    defaults = openrouter.OpenRouterClient.Meta().defaults.model_dump()
    defaults.pop("model")
    new_client = client(**defaults)
    assert new_client.effort_level == "default"
    assert new_client.reason_tokens == 2048
    with ClientContext(requires_active_scene=False):
        await new_client.send_prompt("hello", kind="conversation")
    assert wire[-1]["reasoning"] == {"enabled": True}
    assert "max_tokens" not in wire[-1]


def test_status_offers_the_effort_selector_and_the_allowance(client):
    reasoning_client = client(reason_enabled=True, effort_level="low")
    status = reasoning_client._common_status_data()
    assert status["reasoning_display"]["show_effort_selector"]
    assert not status["reasoning_display"]["show_token_slider"]
    assert status["reasoning_display"]["effort_choices"] == EFFORT_LEVELS
    assert status["min_reason_tokens"] == 0
    meta = openrouter.OpenRouterClient.Meta()
    assert meta.reason_tokens_as_allowance
    choices = meta.extra_fields["effort_level"].choices
    assert [choice["value"] for choice in choices] == EFFORT_LEVELS


def test_saved_client_without_an_effort_gets_default_and_keeps_its_tokens():
    saved = {"type": "openrouter", "name": "saved", "reason_tokens": 4096}
    config = Config.model_validate({"clients": {"saved": saved}})
    loaded = config.clients["saved"]
    assert loaded.effort_level == "default"
    assert loaded.reason_tokens == 4096
    loaded.effort_level = "medium"
    restored = Config.model_validate_json(config.model_dump_json()).clients["saved"]
    assert restored.effort_level == "medium"
    assert restored.reason_tokens == 4096
