"""Anthropic client: known-model lists and prefill handling."""

import inspect
import re
from types import SimpleNamespace

import anthropic
import pytest

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client import anthropic as anthropic_client
from talemate.client.context import ClientContext
from talemate.context import ActiveScene

from conftest import MockScene, bootstrap_scene

CLAUDE_5_MODELS = [
    "claude-haiku-5-5",
    "claude-sonnet-5",
    "claude-sonnet-5-5",
    "claude-opus-5",
    "claude-opus-5-5",
    "claude-fable-5",
    "claude-fable-5-1",
]

# Opus 4.8 answers like the Claude 5 models on every probe.
ADAPTIVE_ONLY_MODELS = CLAUDE_5_MODELS + ["claude-opus-4-7", "claude-opus-4-8"]

REFUSES_PREFILL = ADAPTIVE_ONLY_MODELS + ["claude-opus-4-6", "claude-sonnet-4-6"]

ACCEPTS_PREFILL = ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5"]

ALWAYS_THINKING = ["claude-opus-5-5", "claude-fable-5"]
THINKING_OFF = {"claude-sonnet-5-5": "between_tools", "claude-opus-5": "disabled"}
THINKS_ON_REQUEST_ONLY = [
    m for m in CLAUDE_5_MODELS if m not in ALWAYS_THINKING and m not in THINKING_OFF
]
SAMPLING = {"temperature": 0.7, "top_p": 0.9, "top_k": 40, "max_tokens": 64}
SAMPLING_OLD_MODELS = ["claude-opus-4-5", "claude-opus-4-6", "claude-sonnet-4-6"]
NO_XHIGH_EFFORT = ["claude-opus-4-6", "claude-sonnet-4-6"]

CREATE_SIGNATURE = inspect.signature(anthropic.resources.messages.AsyncMessages.create)


@pytest.fixture
def make_client(cfg_isolation, monkeypatch):
    monkeypatch.setattr(config_state.CONFIG.anthropic, "api_key", "test-key")

    def make(model: str, **config):
        config_state.CONFIG.clients["anthropic_models"] = anthropic_client.ClientConfig(
            type="anthropic", name="anthropic_models", model=model, **config
        )
        return anthropic_client.AnthropicClient(name="anthropic_models")

    return make


@pytest.fixture
def wire(monkeypatch):
    """Replace the SDK client with a fake that records create() calls.

    The request side is bound against the real signature, so a keyword the
    installed SDK does not accept fails here instead of passing silently.
    """
    calls = []
    reply = SimpleNamespace(text="The room is dark.")

    async def stream():
        yield SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(usage=SimpleNamespace(input_tokens=5)),
        )
        yield SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text=reply.text),
        )
        yield SimpleNamespace(
            type="message_delta", usage=SimpleNamespace(output_tokens=4)
        )

    class FakeMessages:
        async def create(self, **kwargs):
            CREATE_SIGNATURE.bind(object(), **kwargs)
            calls.append(kwargs)
            return stream()

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic_client, "AsyncAnthropic", FakeAnthropic)
    return SimpleNamespace(calls=calls, reply=reply)


@pytest.fixture
def scene_env():
    scene = MockScene()
    agents = bootstrap_scene(scene)
    scene.active = True
    with ActiveScene(scene), ActiveAgent(agents["summarizer"], lambda: None):
        yield


@pytest.mark.parametrize("model", CLAUDE_5_MODELS + ["claude-opus-4-8"])
def test_model_can_be_picked(model):
    assert model in anthropic_client.SUPPORTED_MODELS
    assert model in anthropic_client.AnthropicClient.Meta().manual_model_choices


@pytest.mark.parametrize("model", ADAPTIVE_ONLY_MODELS)
def test_adaptive_only_models_force_adaptive_thinking(make_client, model):
    client = make_client(model, reason_enabled=True, thinking_mode="budget")
    assert client.supports_adaptive_thinking
    assert client.requires_adaptive_thinking
    assert client.reasoning_display.control == "effort"


@pytest.mark.parametrize("model", CLAUDE_5_MODELS + ["claude-opus-4-8"])
def test_max_output_tokens(make_client, model):
    assert make_client(model).api_max_output_tokens == 64000


@pytest.mark.parametrize("model", REFUSES_PREFILL)
def test_models_that_refuse_prefill_are_not_coerced(make_client, model):
    assert not make_client(model).can_be_coerced


@pytest.mark.parametrize("model", ACCEPTS_PREFILL)
def test_models_that_accept_prefill_are_coerced(make_client, model):
    assert make_client(model).can_be_coerced


@pytest.mark.parametrize("model", ACCEPTS_PREFILL)
async def test_prefill_stays_a_trailing_assistant_message(
    make_client, wire, scene_env, model
):
    client = make_client(model)
    response = await client.send_prompt(
        "Describe the room.<|BOT|>The room is", kind="analyze_freeform"
    )

    messages = wire.calls[-1]["messages"]
    assert messages[-1] == {"role": "assistant", "content": "The room is"}
    assert "Start your response with" not in messages[0]["content"]
    assert response == "The room is dark."


@pytest.mark.parametrize("model", ADAPTIVE_ONLY_MODELS)
async def test_coercion_is_folded_into_the_user_turn(
    make_client, wire, scene_env, model
):
    client = make_client(model)
    wire.reply.text = "The room is dark."
    response = await client.send_prompt(
        "Describe the room.<|BOT|>The room is", kind="analyze_freeform"
    )

    messages = wire.calls[-1]["messages"]
    assert [m["role"] for m in messages] == ["user"]
    assert re.search(
        r"[Ss]tart your (response|answer) with: The room is$", messages[0]["content"]
    )
    assert response == "dark."


@pytest.mark.parametrize("model", CLAUDE_5_MODELS)
async def test_claude_5_request_matches_the_probed_wire_contract(
    make_client, wire, scene_env, model
):
    client = make_client(model, reason_enabled=True, thinking_mode="budget")
    await client.send_prompt(
        "Describe the room.<|BOT|>The room is",
        kind="analyze_freeform",
    )

    request = wire.calls[-1]
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"] == {"effort": client.effort_level}
    for sampling in ("temperature", "top_p", "top_k"):
        assert sampling not in request
    assert request["messages"][-1]["role"] == "user"


async def generate(client, parameters=None):
    with ClientContext():
        await client.generate("hello", dict(parameters or SAMPLING), "conversation")


@pytest.mark.parametrize("model", CLAUDE_5_MODELS)
async def test_claude_5_request_without_reasoning_carries_no_sampling(
    make_client, wire, scene_env, model
):
    await generate(make_client(model, reason_enabled=False))

    request = wire.calls[-1]
    for sampling in ("temperature", "top_p", "top_k", "extra_body"):
        assert sampling not in request


@pytest.mark.parametrize("model", ALWAYS_THINKING)
def test_models_without_an_off_switch_report_reasoning_locked(make_client, model):
    client = make_client(model, reason_enabled=False)
    assert client.reason_locked
    assert client.reason_enabled_configured
    assert client.reasoning_display.control == "effort"


@pytest.mark.parametrize("model", ALWAYS_THINKING)
async def test_locked_model_thinks_and_leaves_the_length_to_instructions(
    make_client, wire, scene_env, model
):
    client = make_client(model, reason_enabled=False)
    await client.send_prompt("Describe the room.", kind="analyze_freeform")

    request = wire.calls[-1]
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"] == {"effort": client.effort_level}
    assert request["max_tokens"] == 64000


@pytest.mark.parametrize("model", THINKS_ON_REQUEST_ONLY)
def test_models_with_an_off_switch_are_not_locked(make_client, model):
    client = make_client(model, reason_enabled=False)
    assert not client.reason_locked
    assert not client.reason_enabled_configured


@pytest.mark.parametrize("model,thinking_type", list(THINKING_OFF.items()))
async def test_model_that_thinks_by_default_is_sent_its_off_switch(
    make_client, wire, scene_env, model, thinking_type
):
    client = make_client(model, reason_enabled=False)
    await client.send_prompt("Describe the room.", kind="analyze_freeform")

    request = wire.calls[-1]
    assert request["thinking"] == {"type": thinking_type}
    assert request["max_tokens"] < 64000


@pytest.mark.parametrize("model", THINKING_OFF)
async def test_off_switch_gives_way_to_reasoning(make_client, wire, scene_env, model):
    await generate(make_client(model, reason_enabled=True))

    assert wire.calls[-1]["thinking"] == {"type": "adaptive"}


@pytest.mark.parametrize("model", THINKS_ON_REQUEST_ONLY)
async def test_other_models_send_no_thinking_field_with_reasoning_off(
    make_client, wire, scene_env, model
):
    await generate(make_client(model, reason_enabled=False))

    assert "thinking" not in wire.calls[-1]


@pytest.mark.parametrize("model", SAMPLING_OLD_MODELS)
async def test_sampling_goes_through_extra_body_without_top_p_next_to_temperature(
    make_client, wire, scene_env, model
):
    await generate(make_client(model, reason_enabled=False))

    request = wire.calls[-1]
    assert request["extra_body"] == {"temperature": 0.7, "top_k": 40}
    for sampling in ("temperature", "top_p", "top_k"):
        assert sampling not in request


@pytest.mark.parametrize("model", SAMPLING_OLD_MODELS)
async def test_top_p_is_kept_without_temperature(make_client, wire, scene_env, model):
    await generate(
        make_client(model, reason_enabled=False), {"top_p": 0.9, "max_tokens": 64}
    )

    assert wire.calls[-1]["extra_body"] == {"top_p": 0.9}


@pytest.mark.parametrize("model", SAMPLING_OLD_MODELS)
async def test_reasoning_drops_sampling(make_client, wire, scene_env, model):
    await generate(make_client(model, reason_enabled=True))

    assert "extra_body" not in wire.calls[-1]


def test_sonnet_4_6_takes_adaptive_thinking_but_not_only(make_client):
    client = make_client(
        "claude-sonnet-4-6", reason_enabled=True, thinking_mode="adaptive"
    )
    assert client.supports_adaptive_thinking
    assert not client.requires_adaptive_thinking
    assert client.api_max_output_tokens == 64000


@pytest.mark.parametrize("model,thinking_type", list(THINKING_OFF.items()))
async def test_action_override_sends_the_off_switch(
    make_client, wire, scene_env, model, thinking_type
):
    client = make_client(model, reason_enabled=True)
    with ClientContext(disable_reasoning=True):
        await client.generate("hello", {"max_tokens": 64}, "conversation")

    assert wire.calls[-1]["thinking"] == {"type": thinking_type}


@pytest.mark.parametrize("model", ALWAYS_THINKING)
async def test_action_override_does_not_unlock_reasoning(
    make_client, wire, scene_env, model
):
    client = make_client(model, reason_enabled=True)
    with ClientContext(disable_reasoning=True):
        await client.generate("hello", {"max_tokens": 64}, "conversation")

    assert wire.calls[-1]["thinking"] == {"type": "adaptive"}


@pytest.mark.parametrize("model", NO_XHIGH_EFFORT)
async def test_xhigh_effort_is_not_offered_or_sent_where_it_is_refused(
    make_client, wire, scene_env, model
):
    client = make_client(
        model, reason_enabled=True, thinking_mode="adaptive", effort_level="xhigh"
    )
    assert "xhigh" not in client.reasoning_display.effort_choices

    await generate(client)

    assert wire.calls[-1]["output_config"] == {"effort": "high"}


async def test_xhigh_effort_is_kept_where_it_is_accepted(make_client, wire, scene_env):
    client = make_client("claude-opus-4-7", reason_enabled=True, effort_level="xhigh")
    assert "xhigh" in client.reasoning_display.effort_choices

    await generate(client)

    assert wire.calls[-1]["output_config"] == {"effort": "xhigh"}
