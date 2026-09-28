import pytest

import talemate.config.state as config_state
from talemate.client import anthropic


@pytest.fixture
def make_client():
    names = []

    def make(model: str, **config):
        name = f"anthropic_reasoning_{len(names)}"
        names.append(name)
        config_state.CONFIG.clients[name] = anthropic.ClientConfig(
            type="anthropic", name=name, model=model, **config
        )
        return anthropic.AnthropicClient(name=name)

    yield make
    for name in names:
        config_state.CONFIG.clients.pop(name, None)


def test_no_display_while_reasoning_is_off(make_client):
    client = make_client("claude-opus-4-7", reason_enabled=False)
    assert client.reasoning_display is None


@pytest.mark.parametrize(
    "model,thinking_mode",
    [
        ("claude-opus-4-7", "budget"),
        ("claude-opus-4-7", "adaptive"),
        ("claude-opus-4-6", "adaptive"),
    ],
)
def test_adaptive_thinking_offers_the_effort_selector(
    make_client, model, thinking_mode
):
    client = make_client(model, reason_enabled=True, thinking_mode=thinking_mode)
    display = client.reasoning_display
    assert display.control == "effort"
    assert display.effort_choices == ["low", "medium", "high", "xhigh", "max"]


@pytest.mark.parametrize(
    "model,thinking_mode",
    [
        ("claude-opus-4-6", "budget"),
        ("claude-sonnet-4-5", "adaptive"),
    ],
)
def test_budget_thinking_offers_the_token_input(make_client, model, thinking_mode):
    client = make_client(model, reason_enabled=True, thinking_mode=thinking_mode)
    display = client.reasoning_display
    assert display.control == "tokens"
    assert display.effort_choices is None
