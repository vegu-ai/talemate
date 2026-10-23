"""MistralAI client: shared reasoning-effort config and streaming chunk handling.

The Mistral SDK streams `delta.content` as `str | list[ContentChunk] | None`;
a list holds TextChunks and, with reasoning on, ThinkChunks. These tests pin
the parameter passing and the chunk handling (issue #950).
"""

import inspect
from types import SimpleNamespace

import pytest
from mistralai.client.chat import Chat as MistralChat
from mistralai.client.models import (
    CompletionChunk,
    CompletionEvent,
    CompletionResponseStreamChoice,
    DeltaMessage,
    TextChunk,
    ThinkChunk,
    UsageInfo,
)

import talemate.config.state as config_state
from talemate.client import mistral
from talemate.client.context import ClientContext
from talemate.config.schema import Config
from talemate.server.config import client_model_defaults


def text_event(content):
    return CompletionEvent(
        data=CompletionChunk(
            id="test",
            model="mistral-large-latest",
            choices=[
                CompletionResponseStreamChoice(
                    index=0,
                    delta=DeltaMessage(content=content),
                    finish_reason=None,
                )
            ],
        )
    )


def usage_event(prompt_tokens=10, completion_tokens=5):
    return CompletionEvent(
        data=CompletionChunk(
            id="test",
            model="mistral-large-latest",
            choices=[],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
            ),
        )
    )


def absent_content_event():
    """The real final chunk shape: a choice whose delta omits content."""
    return CompletionEvent(
        data=CompletionChunk(
            id="test",
            model="mistral-large-latest",
            choices=[
                CompletionResponseStreamChoice(
                    index=0,
                    delta=DeltaMessage(),
                    finish_reason=None,
                )
            ],
        )
    )


# Pins the fake's request side against the real SDK: a misspelt or
# unsupported keyword fails here instead of passing silently.
STREAM_ASYNC_SIGNATURE = inspect.signature(MistralChat.stream_async)


async def event_stream(events):
    for event in events:
        yield event


@pytest.fixture
def wire(monkeypatch):
    """Replace the Mistral SDK client with a fake recording stream_async calls.

    Each call drains the events appended since the previous call, so a
    request gets its own stream the way the real API serves one.
    """
    calls = []
    events = []
    cursor = 0

    class FakeChat:
        async def stream_async(self, **kwargs):
            nonlocal cursor
            STREAM_ASYNC_SIGNATURE.bind(object(), **kwargs)
            calls.append(kwargs)
            batch = events[cursor:]
            cursor = len(events)
            return event_stream(batch)

    class FakeMistral:
        def __init__(self, api_key=None, server_url=None):
            self.chat = FakeChat()

    monkeypatch.setattr(mistral, "Mistral", FakeMistral)
    return SimpleNamespace(calls=calls, events=events)


@pytest.fixture
def client(cfg_isolation, monkeypatch):
    monkeypatch.setattr(config_state.CONFIG.mistralai, "api_key", "test-key")

    def create(**kwargs):
        # the default model accepts reasoning_effort
        config = {"name": "mistral", "type": "mistral", "model": "mistral-large-4"}
        config.update(kwargs)
        config_state.CONFIG.clients["mistral"] = mistral.ClientConfig(**config)
        return mistral.MistralAIClient(name="mistral")

    return create


@pytest.mark.parametrize("effort", ["none", "high"])
async def test_reasoning_on_sends_none_and_high_unchanged(client, wire, effort):
    wire.events.append(text_event("answer"))
    await client(reason_enabled=True, effort_level=effort).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert wire.calls[-1]["reasoning_effort"] == effort


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "xhigh", "max"])
async def test_unsupported_effort_levels_are_sent_as_high(client, wire, effort):
    # The listed models accept only "none"/"high" (probed live); any other
    # requested level is sent as "high" rather than rejected with a 400.
    wire.events.append(text_event("answer"))
    await client(reason_enabled=True, effort_level=effort).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert wire.calls[-1]["reasoning_effort"] == "high"


@pytest.mark.parametrize("effort", ["default", "high"])
async def test_reasoning_off_sends_no_effort(client, wire, effort):
    wire.events.append(text_event("answer"))
    await client(reason_enabled=False, effort_level=effort).generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert "reasoning_effort" not in wire.calls[-1]
    assert wire.calls[-1]["max_tokens"] == 96


async def test_default_effort_sends_nothing(client, wire):
    """A saved config without an effort choice keeps its request shape."""
    wire.events.append(text_event("answer"))
    await client(reason_enabled=True, effort_level="default").generate(
        "hello", {"max_tokens": 96}, "conversation"
    )
    assert "reasoning_effort" not in wire.calls[-1]


async def test_action_override_disables_the_effort(client, wire):
    wire.events.append(text_event("answer"))
    reasoning_client = client(reason_enabled=True, effort_level="high")
    with ClientContext(disable_reasoning=True, requires_active_scene=False):
        await reasoning_client.generate("hello", {"max_tokens": 96}, "conversation")
    assert "reasoning_effort" not in wire.calls[-1]


async def test_action_effort_override_wins_over_config(client, wire):
    wire.events.append(text_event("answer"))
    reasoning_client = client(reason_enabled=True, effort_level="low")
    with ClientContext(reasoning_effort="high", requires_active_scene=False):
        await reasoning_client.generate("hello", {"max_tokens": 96}, "conversation")
    assert wire.calls[-1]["reasoning_effort"] == "high"


@pytest.mark.parametrize("override", ["low", "xhigh"])
async def test_action_effort_override_is_sent_as_high(client, wire, override):
    # A per-action override can still carry a level the control no longer
    # offers; like any unsupported level it is sent as "high".
    wire.events.append(text_event("answer"))
    c = client(reason_enabled=True, effort_level="high")
    with ClientContext(reasoning_effort=override, requires_active_scene=False):
        await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert wire.calls[-1]["reasoning_effort"] == "high"


def test_listed_model_offers_only_the_accepted_effort_levels(client):
    c = client(model="mistral-large-4", reason_enabled=True)
    assert c.reasoning_display.control == "effort"
    assert mistral.EFFORT_CHOICES == ["default", "none", "high"]
    assert c.reasoning_display.effort_choices == mistral.EFFORT_CHOICES
    # the client editor's Reasoning Effort field offers the same levels
    choices = mistral.MistralAIClient.Meta().extra_fields["effort_level"].choices
    assert [choice["value"] for choice in choices] == mistral.EFFORT_CHOICES


async def test_listed_model_sends_the_effort_and_shows_the_control(client, wire):
    wire.events.append(text_event("answer"))
    c = client(model="mistral-large-4", reason_enabled=True, effort_level="high")
    await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert wire.calls[-1]["reasoning_effort"] == "high"
    assert c.reasoning_display.control == "effort"
    assert c.reasoning_display.effort_choices == mistral.EFFORT_CHOICES


async def test_unlisted_model_never_sends_the_effort_and_falls_back(client, wire):
    # mistral-large-latest rejects reasoning_effort (HTTP 400, code 3051)
    wire.events.append(text_event("answer"))
    c = client(model="mistral-large-latest", reason_enabled=True, effort_level="high")
    await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert "reasoning_effort" not in wire.calls[-1]
    # the base client's token-budget display, the anthropic.py fallback
    assert c.reasoning_display.control == "tokens"
    assert c.reasoning_display.effort_choices is None

    # a per-action effort override does not reach an unlisted model either
    with ClientContext(reasoning_effort="high", requires_active_scene=False):
        wire.events.append(text_event("answer"))
        await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert "reasoning_effort" not in wire.calls[-1]


async def test_str_content_streams_and_counts_tokens(client, wire):
    wire.events.append(text_event("an"))
    wire.events.append(text_event("swer"))
    wire.events.append(usage_event(prompt_tokens=7, completion_tokens=3))
    c = client()
    response = await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert response == "answer"
    assert c._returned_prompt_tokens == 7
    assert c._returned_response_tokens == 3


async def test_list_content_with_thinking_chunks(client, wire):
    """The confirmed crash: a list content delta with TextChunks and a ThinkChunk."""
    wire.events.append(
        text_event([ThinkChunk(thinking=[TextChunk(text="let me think")])])
    )
    wire.events.append(text_event([TextChunk(text="the "), TextChunk(text="answer")]))
    wire.events.append(usage_event())
    c = client(reason_enabled=True, effort_level="high")
    response = await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert response == "the answer"
    assert c.reasoning_response == "let me think"


async def test_none_content_is_skipped(client, wire):
    wire.events.append(text_event(None))
    wire.events.append(text_event("answer"))
    wire.events.append(usage_event())
    response = await client().generate("hello", {"max_tokens": 96}, "conversation")
    assert response == "answer"


async def test_empty_choices_and_absent_content_are_skipped(client, wire):
    wire.events.append(usage_event(prompt_tokens=4, completion_tokens=1))
    wire.events.append(absent_content_event())
    wire.events.append(text_event("answer"))
    response = await client().generate("hello", {"max_tokens": 96}, "conversation")
    assert response == "answer"


async def test_retry_with_the_same_dict_does_not_keep_the_old_effort(client, wire):
    """A retry reuses the caller's parameters dict; the effort must not stick."""
    wire.events.append(text_event("answer"))
    c = client(reason_enabled=True, effort_level="high")
    parameters = {"max_tokens": 96}
    await c.generate("hello", parameters, "conversation")
    assert wire.calls[-1]["reasoning_effort"] == "high"
    assert "reasoning_effort" not in parameters

    # the effort is switched to default (or Reasoning off) before the retry
    c.client_config.effort_level = "default"
    wire.events.append(text_event("answer"))
    await c.generate("hello", parameters, "conversation")
    assert "reasoning_effort" not in wire.calls[-1]
    assert "reasoning_effort" not in parameters


async def test_reasoning_does_not_leak_into_the_next_test_run(client, wire):
    """The prompt editor's Test button calls generate() without a prompt
    request, where nothing resets the reasoning between calls."""
    wire.events.append(
        text_event([ThinkChunk(thinking=[TextChunk(text="first call thinking")])])
    )
    wire.events.append(text_event("answer"))
    c = client(reason_enabled=True, effort_level="high")
    await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert c.reasoning_response == "first call thinking"

    wire.events.append(text_event("answer"))
    response = await c.generate("hello", {"max_tokens": 96}, "conversation")
    assert response == "answer"
    assert c.reasoning_response is None


def test_new_client_defaults(client):
    # Meta().defaults is what the frontend applies to a new client.
    defaults = mistral.MistralAIClient.Meta().defaults.model_dump()
    assert defaults["model"] == "mistral-large-4"
    assert defaults["effort_level"] == "default"
    # the saved config model resolves a missing effort to "default" as well
    assert client_model_defaults("mistral")["effort_level"] == "default"


def test_supported_models_are_still_served():
    assert mistral.SUPPORTED_MODELS == [
        "mistral-small-latest",
        "mistral-medium-latest",
        "mistral-large-latest",
        "mistral-large-4",
    ]


def test_saved_client_without_an_effort_gets_default_and_keeps_its_tokens():
    saved = {"type": "mistral", "name": "saved", "reason_tokens": 4096}
    config = Config.model_validate({"clients": {"saved": saved}})
    loaded = config.clients["saved"]
    assert loaded.effort_level == "default"
    assert loaded.reason_tokens == 4096
    loaded.effort_level = "medium"
    restored = Config.model_validate_json(config.model_dump_json()).clients["saved"]
    assert restored.effort_level == "medium"
    assert restored.reason_tokens == 4096


def test_status_offers_the_effort_selector(client):
    reasoning_client = client(reason_enabled=True, effort_level="high")
    status = reasoning_client._common_status_data()
    assert status["reasoning_display"]["control"] == "effort"
    assert status["reasoning_display"]["effort_choices"] == mistral.EFFORT_CHOICES
    assert status["min_reason_tokens"] == 0
    meta = mistral.MistralAIClient.Meta()
    assert meta.reason_tokens_as_allowance
    choices = meta.extra_fields["effort_level"].choices
    assert [choice["value"] for choice in choices] == mistral.EFFORT_CHOICES


def test_no_reasoning_pattern_required(client):
    """Thinking streams in as ThinkChunks; the text never carries think tags."""
    assert client(reason_enabled=True).requires_reasoning_pattern is False
    assert client(reason_enabled=True).reasoning_display.control == "effort"
    assert client().reasoning_display is None
