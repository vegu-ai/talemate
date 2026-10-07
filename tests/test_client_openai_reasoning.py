import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client import openai, openai_compat
from talemate.client.base import EMPTY_RESPONSE_MESSAGE
from talemate.client.context import ClientContext
from talemate.client.model_prompts import model_prompt
from talemate.client.toggleable_parameters import PARAMETERS_FIELD_GROUP
from talemate.config.schema import Config
from talemate.exceptions import ReasoningResponseError


@pytest.fixture
def clients(cfg_isolation):
    def create(client_type="openai_compat", **kwargs):
        cls = (
            openai.OpenAIClient
            if client_type == "openai"
            else openai_compat.OpenAICompatibleClient
        )
        defaults = {
            "model": "gpt-4o" if client_type == "openai" else "test-model",
            "api_url": "https://provider.test/v1",
            "reason_enabled": True,
            "reason_tokens": 2048,
            "effort_level": "high",
            "enforce_response_length": "cap_tokens_and_instructions",
            "override_base_url": "https://provider.test/v1",
        }
        defaults.update(kwargs)
        config_state.CONFIG.clients[client_type] = cls.config_cls(
            name=client_type, type=client_type, **defaults
        )
        client = cls(name=client_type)
        client.connected = True
        return client

    agent = SimpleNamespace(
        agent_type="narrator",
        verbose_name="Narrator",
        allow_repetition_break=lambda *args, **kwargs: False,
        inject_prompt_paramters=lambda *args: None,
    )
    with ActiveAgent(agent, lambda: None):
        yield create


@pytest.fixture
def wire_choice_overrides():
    return []


def compatible_choices(chat: bool, content: str | None) -> list[dict]:
    if chat:
        return [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ]
    return [{"index": 0, "finish_reason": "stop", "text": content}]


@pytest.fixture
def wire_stream_deltas():
    return [{"content": "answer"}]


@pytest.fixture
async def wire(monkeypatch, wire_choice_overrides, wire_stream_deltas):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if body.get("stream"):
            if request.url.path.endswith("/chat/completions"):
                object_type = "chat.completion.chunk"
                choices = [{"index": 0, "delta": delta} for delta in wire_stream_deltas]
            else:
                object_type = "text_completion"
                choices = [{"index": 0, "text": "<think>thought</think>answer"}]
            chunks = [
                {
                    "id": "test",
                    "object": object_type,
                    "created": 0,
                    "model": body["model"],
                    "choices": [choice],
                }
                for choice in choices
            ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
                + "data: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": wire_choice_overrides.pop(0)
                if wire_choice_overrides
                else [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "answer"},
                        "text": "<think>thought</think>answer",
                    }
                ],
            },
        )

    async with AsyncOpenAI(
        api_key="test-key",
        base_url="https://provider.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: sdk)
        monkeypatch.setattr(
            openai_compat.OpenAICompatibleClient, "make_client", lambda self: sdk
        )
        yield requests


@pytest.mark.parametrize(
    "choices",
    [
        [],
        [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "refusal": "Declined",
                },
            }
        ],
    ],
    ids=["empty-choices", "refusal"],
)
async def test_openai_non_streaming_empty_response_ignore(
    clients, wire, wire_choice_overrides, choices, monkeypatch
):
    client = clients("openai", stream=False)
    wire_choice_overrides.append(choices)
    ignore = AsyncMock(return_value="ignore")
    monkeypatch.setattr(client, "_prompt_generation_error", ignore)
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == ""
    ignore.assert_awaited_once()
    assert ignore.call_args.args[0] == EMPTY_RESPONSE_MESSAGE
    assert len(wire) == 1
    assert client.request_information.tokens == 0


async def test_openai_non_streaming_empty_choices_use_empty_response_retry(
    clients, wire, wire_choice_overrides, monkeypatch
):
    client = clients("openai", stream=False, retry_empty_response=1)
    wire_choice_overrides.append([])
    prompt_error = AsyncMock(return_value="ignore")
    monkeypatch.setattr(client, "_prompt_generation_error", prompt_error)
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    assert len(wire) == 2
    assert all(body["stream"] is False for _, body in wire)
    prompt_error.assert_not_awaited()


async def test_openai_non_streaming_response_records_whole_response_tokens(
    clients, wire
):
    client = clients("openai", stream=False)
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    info = client._common_status_data()["request_information"]
    assert info["tokens"] == client.count_tokens("answer") > 0
    assert info["first_token_time"] is None


@pytest.mark.parametrize("chat", [False, True], ids=["text", "chat"])
async def test_openai_compatible_empty_choices_use_empty_response_retry(
    clients, wire, wire_choice_overrides, chat, monkeypatch
):
    client = clients(
        api_handles_prompt_template=chat,
        reason_enabled=False,
        retry_empty_response=1,
        stream=False,
    )
    wire_choice_overrides.extend([[], compatible_choices(chat, "answer")])
    prompt_error = AsyncMock(return_value="ignore")
    monkeypatch.setattr(client, "_prompt_generation_error", prompt_error)
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    expected_path = "/v1/chat/completions" if chat else "/v1/completions"
    assert [path for path, _ in wire] == [expected_path, expected_path]
    prompt_error.assert_not_awaited()


@pytest.mark.parametrize("chat", [False, True], ids=["text", "chat"])
async def test_openai_compatible_null_response_ignore(
    clients, wire, wire_choice_overrides, chat, monkeypatch
):
    client = clients(
        api_handles_prompt_template=chat, reason_enabled=False, stream=False
    )
    wire_choice_overrides.append(compatible_choices(chat, None))
    ignore = AsyncMock(return_value="ignore")
    monkeypatch.setattr(client, "_prompt_generation_error", ignore)
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == ""
    ignore.assert_awaited_once()
    assert ignore.call_args.args[0] == EMPTY_RESPONSE_MESSAGE
    assert len(wire) == 1
    assert client.request_information.tokens == 0


@pytest.mark.parametrize("chat", [False, True], ids=["text", "chat"])
async def test_openai_compatible_response_records_whole_response_tokens(
    clients, wire, wire_choice_overrides, chat
):
    client = clients(
        api_handles_prompt_template=chat, reason_enabled=False, stream=False
    )
    wire_choice_overrides.append(compatible_choices(chat, "answer"))
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    info = client._common_status_data()["request_information"]
    assert info["tokens"] == client.count_tokens("answer") > 0
    assert info["first_token_time"] is None


@pytest.mark.parametrize(
    "client_type,chat",
    [("openai", True), ("openai_compat", True), ("openai_compat", False)],
    ids=["openai", "compatible-chat", "compatible-text"],
)
async def test_whole_response_rate_uses_full_request_duration(
    clients, wire, wire_choice_overrides, client_type, chat, monkeypatch
):
    kwargs = {"reason_enabled": False, "stream": False}
    if client_type != "openai":
        kwargs["api_handles_prompt_template"] = chat
    client = clients(client_type, **kwargs)
    monkeypatch.setattr(client, "count_tokens", lambda content: 200)
    wire_choice_overrides.append(compatible_choices(chat, "answer"))
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    client.request_information.start_time = 100.0
    client.request_information.end_time = 102.0
    assert client.request_information.tokens == 200
    assert client.request_information.first_token_time is None
    assert client.request_information.rate == 100.0


def test_openai_parameters_share_group_metadata():
    groups = [
        field.group
        for field in openai.OpenAIClient.Meta().extra_fields.values()
        if field.group and field.group.name == "parameters"
    ]
    assert len(groups) == 5
    assert all(group == PARAMETERS_FIELD_GROUP for group in groups)


@pytest.mark.parametrize("model", ["o1", "o3-mini", "gpt-5-mini", "gpt-6-luna"])
@pytest.mark.parametrize(
    "effort", ["default", "none", "minimal", "low", "medium", "high", "xhigh", "max"]
)
async def test_openai_sends_effort_and_preserves_completion_cap(
    clients, wire, model, effort
):
    client = clients(
        "openai",
        model=model,
        effort_level=effort,
        reason_enabled=True,
        send_temperature=True,
        send_top_p=True,
        send_presence_penalty=True,
    )
    client.emit_status()
    assert client.reason_enabled
    parameters = {
        "max_tokens": 256,
        "temperature": 0.8,
        "top_p": 0.9,
        "presence_penalty": 0.1,
    }
    client.tune_prompt_parameters(parameters, "test")
    client.clean_prompt_parameters(parameters)

    assert await client.generate("hello", parameters, "conversation") == "answer"

    path, body = wire[-1]
    assert path == "/v1/chat/completions"
    assert body["max_completion_tokens"] == 2304
    assert "max_tokens" not in body
    assert body["top_p"] == 0.9
    assert body["presence_penalty"] == 0.1
    assert body["temperature"] == 0.8
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["stream"] is True
    if effort == "default":
        assert "reasoning_effort" not in body
    else:
        assert body["reasoning_effort"] == effort
    assert "reasoning" not in body


@pytest.mark.parametrize(
    "model", ["gpt-4o", "o4-mini", "custom-gpt-6-astra", "custom-model"]
)
@pytest.mark.parametrize("effort", ["default", "none", "low"])
async def test_openai_omits_effort_with_reasoning_off(clients, wire, model, effort):
    client = clients(
        "openai",
        model=model,
        effort_level=effort,
        reason_enabled=False,
        send_temperature=True,
    )
    client.emit_status()
    assert not client.reason_enabled
    assert client.count_tokens("hello") > 0
    parameters = {"max_tokens": 256, "temperature": 0.8}
    client.tune_prompt_parameters(parameters, "test")
    client.clean_prompt_parameters(parameters)
    await client.generate("hello", parameters, "conversation")
    body = wire[-1][1]
    assert body["max_completion_tokens"] == 256
    assert body["temperature"] == 0.8
    assert "max_tokens" not in body
    assert "reasoning_effort" not in body
    assert client.reasoning_display is None
    assert [message["role"] for message in body["messages"]] == ["system", "user"]

    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    assert "reasoning_effort" not in wire[-1][1]
    assert client._common_status_data()["reasoning_override_applies"] is False
    assert client.effort_level == effort


def test_openai_token_counter_falls_back_for_unknown_model():
    assert (
        openai.num_tokens_from_messages([{"content": "Hello world"}], "my-finetune")
        == 8
    )


@pytest.mark.parametrize(
    "model,locked",
    [
        ("gpt-5", True),
        ("gpt-5.4", True),
        ("gpt-6", True),
        ("gpt-6-astra", True),
        ("gpt-4o", False),
        ("gpt-4.1", False),
        ("o1", False),
        ("o3", False),
        ("o4-mini", False),
        ("custom-gpt-5", False),
        (None, False),
    ],
)
def test_openai_reasoning_lock_controls_effective_status(clients, model, locked):
    client = clients("openai", model=model, reason_enabled=False)
    client.emit_status()
    status = client._common_status_data()
    assert status["reason_locked"] == locked
    assert status["reason_enabled"] == locked
    assert bool(status["reasoning_display"]) == locked
    assert status["reasoning_override_applies"] is False
    assert client.client_config.reason_enabled is False


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-6-astra"])
def test_compatible_reasoning_is_not_locked_by_openai_prefixes(clients, model):
    client = clients(
        model=model, reason_enabled=False, reasoning_effort_format="reasoning_effort"
    )
    assert not client.reason_locked
    assert not client.reason_enabled_configured
    assert client.reasoning_effort is None
    assert client.reasoning_display is None


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-6-astra"])
@pytest.mark.parametrize("effort", ["default", "none", "low"])
async def test_openai_locked_reasoning_survives_override_and_config_round_trip(
    clients, wire, model, effort
):
    client = clients(
        "openai",
        model=model,
        reason_enabled=False,
        reason_tokens=8192,
        effort_level=effort,
    )
    saved = client.client_config.model_dump_json()
    with ClientContext(disable_reasoning=True, requires_active_scene=False):
        assert client.reason_enabled
        assert not client.reasoning_disabled_for_action
        assert not client.reasoning_override_applies
        assert await client.send_prompt("hello") == "answer"
    body = wire[-1][1]
    assert body["max_completion_tokens"] == 96 + 8192
    assert body.get("reasoning_effort") == (None if effort == "default" else effort)
    assert client.client_config.model_dump_json() == saved

    restored = openai.ClientConfig.model_validate_json(saved)
    config_state.CONFIG.clients["openai"] = restored
    restarted = openai.OpenAIClient(name="openai")
    assert restarted.reason_locked
    assert restarted.reason_enabled_configured
    assert restored.reason_enabled is False
    assert restarted.reason_tokens == 8192
    assert restarted.effort_level == effort

    restored.model = "gpt-4.1"
    assert not restarted.reason_locked
    assert not restarted.reason_enabled_configured
    assert restarted.reasoning_display is None
    assert restarted.reason_tokens == 8192
    assert restarted.effort_level == effort


def test_openai_model_choices_offer_current_chat_aliases():
    choices = openai.OpenAIClient.Meta().manual_model_choices
    assert {
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-5.1",
        "gpt-5.2",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.5",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-6-astra",
        "gpt-6-luna",
        "gpt-6-sol",
        "o3",
        "o4-mini",
        "chat-latest",
    } <= set(choices)
    assert not {
        "gpt-3.5-turbo-0613",
        "gpt-4-0125-preview",
        "gpt-4-1106-preview",
        "gpt-4-turbo-preview",
        "gpt-4o-mini-realtime-preview",
        "gpt-4o-realtime-preview",
        "o1-mini",
        "o1-preview",
    } & set(choices)
    assert len(choices) == len(set(choices))
    assert openai.OpenAIClient.Meta().manual_model


@pytest.mark.parametrize("model", ["o1-mini", "gpt-4o-2024-11-20", "my-private-model"])
def test_openai_model_choices_do_not_restrict_saved_or_manual_names(clients, model):
    client = clients("openai", model=model)
    assert model not in client.Meta().manual_model_choices
    saved = openai.ClientConfig.model_validate_json(
        client.client_config.model_dump_json()
    )
    assert saved.model == model
    assert client.model_name == model


@pytest.mark.parametrize(
    "model,locked",
    [
        ("gpt-4o", False),
        ("o1-mini", False),
        ("gpt-5-chat-latest", True),
        ("gpt-6-luna", True),
    ],
)
@pytest.mark.parametrize("reason_enabled", [False, True])
async def test_openai_status_preserves_reasoning_setting_and_padding(
    clients, wire, model, locked, reason_enabled
):
    client = clients("openai", model=model, reason_enabled=reason_enabled)
    client.emit_status()
    effective_reasoning = reason_enabled or locked
    assert client.reason_enabled == effective_reasoning
    assert client.reason_locked == locked
    assert client.client_config.reason_enabled == reason_enabled
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    body = wire[-1][1]
    assert body["max_completion_tokens"] == 96 + (2048 if effective_reasoning else 0)
    assert "max_tokens" not in body
    assert body.get("reasoning_effort") == ("high" if effective_reasoning else None)
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["stream"] is True


@pytest.mark.parametrize(
    "matched,unmatched,locked",
    [
        ("o1-mini", "gpt-4o", False),
        ("o1-preview", "custom-model", False),
        ("o3-mini", "o4-mini", False),
        ("gpt-5-mini", "gpt-6-luna", True),
    ],
)
@pytest.mark.parametrize("reason_enabled", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("send_system_message", [False, True])
async def test_openai_names_share_request_shape_and_reasoning_state(
    clients,
    wire,
    matched,
    unmatched,
    locked,
    reason_enabled,
    stream,
    send_system_message,
):
    bodies = []
    effective_reasoning = reason_enabled or locked
    for model in (matched, unmatched):
        client = clients(
            "openai",
            model=model,
            reason_enabled=reason_enabled,
            stream=stream,
            send_system_message=send_system_message,
        )
        client.emit_status()
        assert client.reason_enabled == effective_reasoning
        assert client._common_status_data()["stream"] == stream
        assert (
            client._common_status_data()["send_system_message"] == send_system_message
        )
        with ClientContext(requires_active_scene=False):
            assert await client.send_prompt("hello") == "answer"
        body = wire[-1][1].copy()
        assert body.pop("model") == model
        bodies.append(body)
    assert bodies[0] == bodies[1]
    assert bodies[0]["stream"] == stream
    assert bodies[0]["max_completion_tokens"] == 96 + (
        2048 if effective_reasoning else 0
    )
    assert [message["role"] for message in bodies[0]["messages"]] == (
        ["system", "user"] if send_system_message else ["user"]
    )
    assert not ({"temperature", "top_p", "presence_penalty"} & bodies[0].keys())


@pytest.mark.parametrize("token_parameter", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("model", ["gpt-5-mini", "custom-model"])
async def test_openai_override_completion_parameter_survives_prompt_cleaning(
    clients, wire, token_parameter, model
):
    client = clients("openai", model=model, completion_token_parameter=token_parameter)
    assert client._common_status_data()["completion_token_parameter"] == token_parameter
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    body = wire[-1][1]
    assert body[token_parameter] == 2144
    assert ({"max_tokens", "max_completion_tokens"} & body.keys()) == {token_parameter}
    assert body["reasoning_effort"] == "high"


@pytest.mark.parametrize("model", ["gpt-5-mini", "gpt-4o", "custom-model"])
async def test_new_openai_client_defaults_leave_room_for_reasoning(
    clients, wire, model
):
    # Both client creation UIs seed their working copy from Meta.defaults.
    defaults = openai.OpenAIClient.Meta().defaults.model_dump()
    defaults["model"] = model
    defaults["override_base_url"] = "https://provider.test/v1"
    client = clients("openai", **defaults, enforce_response_length="adaptive")
    assert client.reason_enabled
    assert client.reason_tokens == 1024
    assert all(not getattr(client, f"send_{p}") for p in openai.TOGGLEABLE_PARAMETERS)
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    assert not ({"max_tokens", "max_completion_tokens"} & wire[-1][1].keys())


@pytest.mark.parametrize("reason_enabled", [None, False, True])
def test_saved_openai_reasoning_setting_is_not_replaced_by_new_client_defaults(
    reason_enabled,
):
    saved = {"type": "openai", "name": "saved", "reason_tokens": 8192}
    if reason_enabled is not None:
        saved["reason_enabled"] = reason_enabled
    config = Config.model_validate({"clients": {"saved": saved}})
    loaded = config.clients["saved"]
    assert loaded.reason_enabled == bool(reason_enabled)
    assert loaded.reason_tokens == 8192
    assert all(not getattr(loaded, f"send_{p}") for p in openai.TOGGLEABLE_PARAMETERS)
    assert loaded.stream
    assert loaded.send_system_message
    assert loaded.completion_token_parameter == "max_completion_tokens"
    loaded.stream = False
    loaded.send_system_message = False
    loaded.send_temperature = True
    loaded.completion_token_parameter = "max_tokens"
    restored = Config.model_validate_json(config.model_dump_json()).clients["saved"]
    assert not restored.stream
    assert not restored.send_system_message
    assert restored.send_temperature
    assert not restored.send_top_p
    assert not restored.send_presence_penalty
    assert restored.completion_token_parameter == "max_tokens"
    assert restored.reason_enabled == bool(reason_enabled)
    assert restored.reason_tokens == 8192


@pytest.mark.parametrize("client_type", ["openai", "openai_compat"])
@pytest.mark.parametrize("parameter", ["temperature", "top_p", "presence_penalty"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_sampler_settings_reach_wire(
    clients, wire, client_type, parameter, enabled
):
    client = clients(
        client_type,
        api_handles_prompt_template=True,
        reason_failure_behavior="ignore",
        **{f"send_{parameter}": enabled},
    )
    assert client._common_status_data()[f"send_{parameter}"] == enabled
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    body = wire[-1][1]
    assert (parameter in body) == enabled
    for other in {"temperature", "top_p", "presence_penalty"} - {parameter}:
        assert (other in body) == (client_type == "openai_compat")


@pytest.mark.parametrize("token_parameter", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("mode", ["reasoning_effort", "reasoning"])
async def test_compatible_completion_parameter_survives_prompt_cleaning(
    clients, wire, token_parameter, mode
):
    client = clients(
        api_handles_prompt_template=True,
        completion_token_parameter=token_parameter,
        reasoning_effort_format=mode,
        reason_failure_behavior="ignore",
    )
    assert client._common_status_data()["completion_token_parameter"] == token_parameter
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    body = wire[-1][1]
    assert body[token_parameter] == 2144
    assert ({"max_tokens", "max_completion_tokens"} & body.keys()) == {token_parameter}
    assert body[mode] == ("high" if mode == "reasoning_effort" else {"effort": "high"})


@pytest.mark.parametrize("client_type", ["openai", "openai_compat"])
@pytest.mark.parametrize("token_parameter", ["max_tokens", "max_completion_tokens"])
async def test_disabled_response_cap_stays_omitted(
    clients, wire, client_type, token_parameter
):
    client = clients(
        client_type,
        api_handles_prompt_template=True,
        completion_token_parameter=token_parameter,
        enforce_response_length="instructions",
        reason_failure_behavior="ignore",
    )
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    assert not ({"max_tokens", "max_completion_tokens"} & wire[-1][1].keys())


@pytest.mark.parametrize("chat", [False, True])
@pytest.mark.parametrize("mode", ["none", "reasoning_effort", "reasoning"])
@pytest.mark.parametrize("effort", ["default", "low", "high"])
@pytest.mark.parametrize("token_parameter", ["max_tokens", "max_completion_tokens"])
async def test_compatible_serializes_selected_format(
    clients, wire, chat, mode, effort, token_parameter
):
    client = clients(
        api_handles_prompt_template=chat,
        reasoning_effort_format=mode,
        effort_level=effort,
        completion_token_parameter=token_parameter,
    )
    parameters = {"max_tokens": 256}
    client.tune_prompt_parameters(parameters, "test")
    client.clean_prompt_parameters(parameters)
    await client.generate("hello", parameters, "conversation")
    path, body = wire[-1]
    assert path == ("/v1/chat/completions" if chat else "/v1/completions")
    assert body[token_parameter] == 2304
    assert ({"max_tokens", "max_completion_tokens"} & body.keys()) == {token_parameter}
    assert "extra_body" not in body
    if mode == "none" or effort == "default":
        assert "reasoning_effort" not in body
        assert "reasoning" not in body
    elif mode == "reasoning":
        assert body["reasoning"] == {"effort": effort}
        assert "reasoning_effort" not in body
    else:
        assert body["reasoning_effort"] == effort
        assert "reasoning" not in body


@pytest.mark.parametrize(
    "client_type,chat,mode",
    [
        ("openai", True, "reasoning_effort"),
        ("openai_compat", True, "reasoning_effort"),
        ("openai_compat", False, "reasoning_effort"),
        ("openai_compat", True, "reasoning"),
        ("openai_compat", False, "reasoning"),
    ],
)
async def test_action_override_omits_effort_and_padding(
    clients, wire, client_type, chat, mode
):
    client = clients(
        client_type, api_handles_prompt_template=chat, reasoning_effort_format=mode
    )
    with ClientContext(disable_reasoning=True):
        display = client.reasoning_display
        assert display.control == "effort"
        parameters = {"max_tokens": 256}
        client.tune_prompt_parameters(parameters, "test")
        client.clean_prompt_parameters(parameters)
        await client.generate("hello", parameters, "conversation")
    body = wire[-1][1]
    assert "reasoning_effort" not in body
    assert "reasoning" not in body
    assert body.get("max_completion_tokens", body.get("max_tokens")) == 256


@pytest.mark.parametrize("mode", ["none", "reasoning_effort", "reasoning"])
def test_disabled_compatible_reasoning_omits_effort_and_display(clients, mode):
    client = clients(reason_enabled=False, reasoning_effort_format=mode)
    assert client.reasoning_effort is None
    assert client.reasoning_display is None
    assert not client.reasoning_override_applies


@pytest.mark.parametrize(
    "client_type,mode",
    [
        ("openai", "reasoning_effort"),
        ("openai_compat", "reasoning_effort"),
        ("openai_compat", "reasoning"),
    ],
)
@pytest.mark.parametrize("effort", ["default", "none", "high"])
def test_effort_card_follows_configured_reasoning_toggle(
    clients, client_type, mode, effort
):
    client = clients(
        client_type,
        reason_enabled=False,
        effort_level=effort,
        reasoning_effort_format=mode,
    )
    assert client._common_status_data()["reasoning_display"] is None

    client.client_config.reason_enabled = True
    enabled = client._common_status_data()["reasoning_display"]
    assert enabled["control"] == "effort"
    assert client._common_status_data()["effort_level"] == effort

    with ClientContext(disable_reasoning=True):
        assert not client.reason_enabled
        assert client._common_status_data()["reasoning_display"] == enabled

    client.client_config.reason_enabled = False
    disabled = client._common_status_data()
    assert disabled["reasoning_display"] is None
    assert disabled["effort_level"] == effort
    assert disabled["reason_tokens"] == 2048


@pytest.mark.parametrize("client_type", ["openai", "openai_compat"])
def test_saved_reason_tokens_and_new_fields_round_trip(client_type):
    data = {
        "clients": {
            "saved": {
                "name": "saved",
                "type": client_type,
                "reason_tokens": 8192,
                "reason_enabled": True,
            }
        }
    }
    config = Config.model_validate(data)
    saved = config.clients["saved"]
    assert saved.reason_tokens == 8192
    assert saved.effort_level == "default"
    saved.effort_level = "low"
    if client_type == "openai_compat":
        assert saved.reasoning_effort_format == "none"
        assert saved.completion_token_parameter == "max_tokens"
        saved.reasoning_effort_format = "reasoning"
        saved.completion_token_parameter = "max_completion_tokens"
    restored = Config.model_validate_json(config.model_dump_json()).clients["saved"]
    assert restored.reason_tokens == 8192
    assert restored.effort_level == "low"
    if client_type == "openai_compat":
        assert restored.reasoning_effort_format == "reasoning"
        assert restored.completion_token_parameter == "max_completion_tokens"
    assert restored.reason_enabled
    assert all(
        getattr(restored, f"send_{name}") == (client_type == "openai_compat")
        for name in ("temperature", "top_p", "presence_penalty")
    )


@pytest.mark.parametrize(
    "client_type,mode",
    [
        ("openai", "reasoning_effort"),
        ("openai_compat", "reasoning"),
        ("openai_compat", "none"),
    ],
)
def test_status_describes_effort_and_completion_allowance(clients, client_type, mode):
    client = clients(client_type, reasoning_effort_format=mode)
    data = client._common_status_data()
    assert data["effort_level"] == "high"
    assert data["reason_tokens"] == 2048
    assert client.Meta().reason_tokens_as_allowance
    field = client.Meta().extra_fields["effort_level"]
    assert field.group.name == "reasoning"
    assert "default" in [choice["value"] for choice in field.choices]
    assert client.Meta().defaults.effort_level == "default"
    assert data["reasoning_override_applies"]
    display = data["reasoning_display"]
    assert display["control"] == ("tokens" if mode == "none" else "effort")
    assert set(display) == {"control", "effort_choices"}
    if client_type == "openai_compat":
        assert data["reasoning_effort_format"] == mode


def test_completion_prompt_keeps_reasoning_token_rendering(clients, monkeypatch):
    client = clients(reasoning_effort_format="reasoning_effort")
    template = model_prompt.env.from_string(
        "{{ reasoning_tokens }}|{{ enable_thinking }}|{{ prompt }}"
    )
    monkeypatch.setattr(
        model_prompt, "get_template", lambda name: (template, "test.jinja2")
    )
    assert client.prompt_template("system", "hello") == "2048|True|hello"
    with ClientContext(disable_reasoning=True):
        assert client.prompt_template("system", "hello") == "0|False|hello"


@pytest.mark.parametrize(
    "client_type,chat",
    [("openai", True), ("openai_compat", True), ("openai_compat", False)],
)
async def test_send_prompt_reaches_wire_and_preserves_extraction(
    clients, wire, client_type, chat
):
    client = clients(
        client_type,
        api_handles_prompt_template=chat,
        reasoning_effort_format="reasoning",
        reason_failure_behavior="ignore",
    )
    agent = SimpleNamespace(
        agent_type="narrator",
        verbose_name="Narrator",
        allow_repetition_break=lambda *args, **kwargs: False,
        inject_prompt_paramters=lambda *args: None,
    )
    with ActiveAgent(agent, lambda: None), ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    body = wire[-1][1]
    if client_type == "openai":
        assert body["reasoning_effort"] == "high"
    else:
        assert body["reasoning"] == {"effort": "high"}
        if not chat:
            assert client.reasoning_response == "<think>thought</think>"


def chat_reasoning_choices(content: str | None, reasoning_field: str) -> list[dict]:
    return [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": content,
                reasoning_field: "worked it out",
            },
        }
    ]


@pytest.mark.parametrize("chat", [True, False], ids=["chat", "text"])
def test_compatible_reasoning_pattern_stays_configurable_in_both_modes(clients, chat):
    client = clients(api_handles_prompt_template=chat)
    assert client.requires_reasoning_pattern is True


def inline_choices(content: str) -> list[dict]:
    return compatible_choices(True, content)


@pytest.mark.parametrize("stream", [False, True], ids=["whole", "stream"])
async def test_compatible_chat_strips_reasoning_left_in_the_content(
    clients, wire, wire_choice_overrides, wire_stream_deltas, stream
):
    client = clients(api_handles_prompt_template=True, stream=stream)
    text = "<think>secret plan</think>The story continues."
    wire_choice_overrides.append(inline_choices(text))
    wire_stream_deltas[:] = [{"content": text}]
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "The story continues."
    assert client.reasoning_response == "<think>secret plan</think>"


@pytest.mark.parametrize("behavior", ["fail", "ignore"])
async def test_compatible_chat_without_any_reasoning_never_fails_on_the_pattern(
    clients, wire, wire_choice_overrides, behavior
):
    client = clients(
        api_handles_prompt_template=True, stream=False, reason_failure_behavior=behavior
    )
    wire_choice_overrides.append(inline_choices("The story continues."))
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "The story continues."
    assert client.reasoning_response is None


@pytest.mark.parametrize(
    "extra",
    [{"reason_validation_pattern": "<think>"}, {"reason_prefill": "<think>"}],
    ids=["validation-pattern", "prefill"],
)
def test_compatible_chat_unclosed_reasoning_is_not_the_answer(clients, extra):
    client = clients(api_handles_prompt_template=True, **extra)
    text = (
        "<think>long reasoning cut off"
        if "reason_validation_pattern" in extra
        else "reasoning cut off"
    )
    with pytest.raises(ReasoningResponseError):
        client.strip_reasoning(text)


def test_compatible_chat_separate_reasoning_skips_the_pattern(clients):
    client = clients(api_handles_prompt_template=True)
    client._reasoning_response = "r"
    assert client.strip_reasoning("<think>x</think>Ans") == (
        "<think>x</think>Ans",
        None,
    )
    client._reasoning_response = None
    assert client.strip_reasoning("<think>x</think>Ans") == ("Ans", "<think>x</think>")


async def test_compatible_text_mode_still_requires_the_pattern(
    clients, wire, wire_choice_overrides, monkeypatch
):
    client = clients(
        api_handles_prompt_template=False,
        stream=False,
        reason_failure_behavior="fail",
    )
    wire_choice_overrides.append(compatible_choices(False, "no reasoning here"))
    dialog = AsyncMock(return_value="ignore")
    monkeypatch.setattr(client, "_prompt_generation_error", dialog)
    with ClientContext(requires_active_scene=False):
        await client.send_prompt("hello")
    assert "pattern not found" in dialog.call_args.args[0]


async def test_whole_chat_response_with_reasoning_reports_the_request_rate(
    clients, wire, wire_choice_overrides, monkeypatch
):
    client = clients(api_handles_prompt_template=True, stream=False)
    monkeypatch.setattr(client, "count_tokens", lambda content: 100)
    wire_choice_overrides.append(chat_reasoning_choices("answer", "reasoning_content"))
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    info = client.request_information
    assert info.tokens == 200
    assert info.first_token_time is None
    info.start_time = 100.0
    info.end_time = 102.0
    assert info.rate == 100.0


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning"])
@pytest.mark.parametrize("stream", [False, True], ids=["whole", "stream"])
async def test_compatible_chat_reasoning_comes_from_the_response_field(
    clients, wire, wire_choice_overrides, wire_stream_deltas, field, stream
):
    client = clients(api_handles_prompt_template=True, stream=stream)
    wire_choice_overrides.append(chat_reasoning_choices("answer", field))
    wire_stream_deltas[:] = [
        {field: "worked "},
        {field: "it out"},
        {"content": "answer"},
    ]
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    assert client.reasoning_response == "worked it out"
    assert len(wire) == 1


async def test_compatible_chat_reasoning_ignores_the_strip_pattern(
    clients, wire, wire_choice_overrides
):
    client = clients(
        api_handles_prompt_template=True,
        stream=False,
        reason_failure_behavior="fail",
        reason_response_pattern=".*?</never>",
    )
    wire_choice_overrides.append(chat_reasoning_choices("answer", "reasoning_content"))
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == "answer"
    assert client.reasoning_response == "worked it out"


async def test_compatible_chat_with_only_reasoning_is_an_empty_response(
    clients, wire, wire_choice_overrides, monkeypatch
):
    client = clients(api_handles_prompt_template=True, stream=False)
    wire_choice_overrides.append(chat_reasoning_choices(None, "reasoning_content"))
    dialog = AsyncMock(return_value="ignore")
    monkeypatch.setattr(client, "_prompt_generation_error", dialog)
    with ClientContext(requires_active_scene=False):
        assert await client.send_prompt("hello") == ""
    assert dialog.call_args.args[0] == EMPTY_RESPONSE_MESSAGE


@pytest.mark.parametrize("chat", [True, False], ids=["chat", "text"])
async def test_compatible_streams_by_default_and_counts_tokens_as_they_arrive(
    clients, wire, chat
):
    client = clients(api_handles_prompt_template=chat, reason_enabled=False)
    with ClientContext(requires_active_scene=False):
        assert (await client.send_prompt("hello")).endswith("answer")
    assert wire[0][1]["stream"] is True
    info = client.request_information
    assert info.tokens > 0
    assert info.first_token_time is not None


async def test_compatible_stream_counts_reasoning_tokens(
    clients, wire, wire_stream_deltas
):
    client = clients(api_handles_prompt_template=True)
    wire_stream_deltas[:] = [
        {"reasoning_content": "one two three"},
        {"content": ""},
        {"content": "ok"},
    ]
    with ClientContext(requires_active_scene=False):
        await client.send_prompt("hello")
    assert client.request_information.tokens == client.count_tokens(
        "one two three"
    ) + client.count_tokens("ok")


async def test_compatible_stream_can_be_disabled(clients, wire):
    client = clients(api_handles_prompt_template=True, stream=False)
    with ClientContext(requires_active_scene=False):
        await client.send_prompt("hello")
    assert wire[0][1]["stream"] is False


def test_compatible_stream_is_a_setting_with_a_default(clients):
    meta = openai_compat.OpenAICompatibleClient.Meta()
    assert meta.defaults.stream is True
    assert meta.extra_fields["stream"].type == "bool"
    assert clients(stream=False).stream is False


@pytest.mark.parametrize(
    "api_key,expected",
    [("", openai_compat.KEYLESS_PLACEHOLDER), ("secret-key", "secret-key")],
)
def test_compatible_client_builds_without_an_api_key(clients, api_key, expected):
    client = clients(api_key=api_key)
    sdk = openai_compat.OpenAICompatibleClient.make_client(client)
    assert sdk.api_key == expected


@pytest.mark.parametrize(
    "client_cls,name",
    [
        (openai_compat.OpenAICompatibleClient, "reasoning_effort_format"),
        (openai_compat.OpenAICompatibleClient, "completion_token_parameter"),
        (openai.OpenAIClient, "completion_token_parameter"),
    ],
)
def test_identifier_choices_explain_themselves(client_cls, name):
    choices = client_cls.Meta().extra_fields[name].choices
    assert choices
    assert all(choice["description"] for choice in choices)


def test_effort_level_choices_explain_default_and_none():
    field = openai_compat.OpenAICompatibleClient.Meta().extra_fields["effort_level"]
    described = {c["value"] for c in field.choices if c.get("description")}
    assert described == {"default", "none"}
    assert [c["value"] for c in field.choices] == [
        "default",
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]


@pytest.mark.parametrize(
    "client_type", ["openai_compat", "groq", "openai", "textgenwebui"]
)
def test_new_clients_start_with_a_reasoning_budget(client_type):
    from talemate.server.config import client_model_defaults

    assert client_model_defaults(client_type)["reason_tokens"] >= 1024
