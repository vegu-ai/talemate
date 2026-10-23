"""Tests for the TabbyAPI client request payload and stream handling."""

import json
from types import SimpleNamespace

import httpx
import pytest

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client import tabbyapi as tabbyapi_module
from talemate.client.base import STOPPING_STRINGS
from talemate.client.tabbyapi import TabbyAPIClient
from talemate.exceptions import GenerationProcessingError


def _sse(*events) -> str:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


@pytest.fixture
def tabby(cfg_isolation, monkeypatch):
    state = {
        "status": 200,
        "body": _sse({"choices": [{"text": "answer"}]}),
        "requests": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(json.loads(request.content))
        return httpx.Response(state["status"], text=state["body"])

    native_client = httpx.AsyncClient

    class _MockClient(native_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tabbyapi_module.httpx, "AsyncClient", _MockClient)

    def make(**kwargs):
        config_state.CONFIG.clients["tabby"] = tabbyapi_module.ClientConfig(
            type="tabbyapi",
            name="tabby",
            api_url="http://fake:5000/v1",
            api_key="key",
            **kwargs,
        )
        client = TabbyAPIClient(name="tabby")
        client.remote_model_name = "model"
        client.new_request()
        return client

    state["make"] = make
    return state


def _agent_context():
    agent = SimpleNamespace(
        agent_type="narrator",
        verbose_name="Narrator",
        inject_prompt_paramters=lambda *args: None,
    )
    return ActiveAgent(agent, lambda: None)


@pytest.mark.asyncio
async def test_stop_and_samplers_reach_the_request(tabby):
    client = tabby["make"]()
    parameters = {
        "max_tokens": 100,
        "top_k": 40,
        "repetition_penalty": 1.1,
        "extra_stopping_strings": ["Bob:"],
    }
    with _agent_context():
        client.tune_prompt_parameters(parameters, "conversation")
    client.clean_prompt_parameters(parameters)

    await client.generate("prompt", parameters, "conversation")

    body = tabby["requests"][-1]
    assert body["stop"] == STOPPING_STRINGS + ["Bob:"]
    assert body["top_k"] == 40
    assert body["repetition_penalty"] == 1.1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason_enabled", [False, True])
async def test_chat_sends_enable_thinking_and_captures_reasoning(tabby, reason_enabled):
    tabby["body"] = _sse(
        {"choices": [{"delta": {"reasoning_content": "Thinking."}}]},
        {"choices": [{"delta": {"content": "Answer."}}]},
    )
    client = tabby["make"](
        api_handles_prompt_template=True, reason_enabled=reason_enabled
    )

    response = await client.generate("prompt", {"max_tokens": 50}, "narrate")

    assert tabby["requests"][-1]["enable_thinking"] is reason_enabled
    assert response == "Answer."
    assert client._reasoning_response == "Thinking."
    assert client.strip_reasoning(response) == ("Answer.", None)


@pytest.mark.asyncio
async def test_stream_error_event_raises(tabby):
    tabby["body"] = _sse({"error": {"message": "Completion aborted."}})
    client = tabby["make"]()

    with pytest.raises(GenerationProcessingError) as excinfo:
        await client.generate("prompt", {"max_tokens": 50}, "narrate")
    assert str(excinfo.value) == "TabbyAPI error - Completion aborted."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, body, expected",
    [
        (401, {"detail": "Invalid API key"}, "TabbyAPI error (401) - Invalid API key"),
        (
            422,
            {
                "detail": {
                    "error": {"message": "Chat completions are disabled", "trace": None}
                }
            },
            "TabbyAPI error (422) - Chat completions are disabled",
        ),
        (
            422,
            {
                "detail": [
                    {
                        "type": "greater_than_equal",
                        "loc": ["body", "max_tokens"],
                        "msg": "Input should be greater than or equal to 0",
                        "input": -135,
                    }
                ]
            },
            "TabbyAPI error (422) - body.max_tokens: Input should be greater than or equal to 0",
        ),
        (
            400,
            {"error": {"message": "Prompt exceeds max_seq_len"}},
            "TabbyAPI error (400) - Prompt exceeds max_seq_len",
        ),
    ],
    ids=["auth", "request-error", "validation", "context-length"],
)
async def test_http_error_raises_with_message(tabby, status, body, expected):
    tabby["status"] = status
    tabby["body"] = json.dumps(body)
    client = tabby["make"]()

    with pytest.raises(GenerationProcessingError) as excinfo:
        await client.generate("prompt", {"max_tokens": 50}, "narrate")
    assert str(excinfo.value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("fill_words", [200, 3500])
async def test_uncapped_completion_lets_tabbyapi_fill_the_context(tabby, fill_words):
    client = tabby["make"](max_token_length=4096)

    await client.generate("word " * fill_words, {}, "narrate")

    assert tabby["requests"][-1]["max_tokens"] == 0


@pytest.mark.asyncio
async def test_chat_inline_reasoning_is_stripped_without_reasoning_content(tabby):
    tabby["body"] = _sse(
        {"choices": [{"delta": {"content": "<think>Thinking.</think>Answer."}}]}
    )
    client = tabby["make"](api_handles_prompt_template=True, reason_enabled=True)

    response = await client.generate("prompt", {"max_tokens": 50}, "narrate")
    stripped, reasoning = client.strip_reasoning(response)

    assert stripped == "Answer."
    assert reasoning == "<think>Thinking.</think>"


@pytest.mark.asyncio
async def test_chat_prefill_continues_the_final_message(tabby):
    tabby["body"] = _sse({"choices": [{"delta": {"content": " dark."}}]})
    client = tabby["make"](api_handles_prompt_template=True)

    response = await client.generate(
        "Describe the room.<|BOT|>The room is", {"max_tokens": 50}, "narrate"
    )

    body = tabby["requests"][-1]
    assert response == " dark."
    assert body["messages"][-1] == {"role": "assistant", "content": "The room is"}
    assert body["continue_final_message"] is True
    assert body["add_generation_prompt"] is False


def test_prompt_template_is_auto_determined():
    assert TabbyAPIClient.auto_determine_prompt_template is True
