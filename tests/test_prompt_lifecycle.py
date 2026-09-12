import asyncio
import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client import anthropic, base, koboldcpp, textgenwebui
from talemate.client.base import ClientBase
from talemate.client.context import ClientContext
from talemate.config.schema import Client as ClientConfig
from talemate.exceptions import GenerationCancelled, GenerationProcessingError
from talemate.prompts.base import active_template_uid


class LifecycleClient(ClientBase):
    client_type = "lifecycle"

    @property
    def supported_parameters(self):
        return ["temperature", "max_tokens"]

    async def generate(self, prompt, parameters, kind):
        raise AssertionError("A test must supply its provider outcome")

    async def status(self):
        self.connected = True

    async def get_model_name(self):
        return "test-model"


@pytest.fixture
def lifecycle_client(cfg_isolation, monkeypatch):
    config_state.CONFIG.clients["lifecycle"] = ClientConfig(
        name="lifecycle", type="lifecycle", model="test-model", enabled=True
    )
    client = LifecycleClient(name="lifecycle")
    client.remote_model_name = "test-model"
    client.connected = True
    events = []

    def emit(typ, **kwargs):
        if typ == "prompt_sent":
            events.append(kwargs["data"])

    monkeypatch.setattr(base, "emit", emit)
    return client, events


async def send(client, text="hello"):
    agent = SimpleNamespace(
        agent_type="narrator",
        verbose_name="Narrator",
        allow_repetition_break=lambda *args, **kwargs: False,
        inject_prompt_paramters=lambda *args: None,
    )

    def narrate():
        pass

    token = active_template_uid.set("narrator.test")
    try:
        with ActiveAgent(agent, narrate), ClientContext(requires_active_scene=False):
            return await client.send_prompt(text)
    finally:
        active_template_uid.reset(token)


@pytest.mark.asyncio
async def test_start_is_visible_before_status_probe_and_preparation(
    lifecycle_client, monkeypatch
):
    client, events = lifecycle_client
    started, release = asyncio.Event(), asyncio.Event()

    async def status():
        started.set()
        await release.wait()

    async def generate(*args):
        client._returned_prompt_tokens = 0
        client._returned_response_tokens = 0
        return "answer"

    monkeypatch.setattr(client, "status", status)
    monkeypatch.setattr(client, "generate", generate)
    task = asyncio.create_task(send(client))
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert len(events) == 1
        assert events[0]["status"] == "active"
        assert events[0]["prompt"] == "hello"
        assert events[0]["response"] is None
        assert events[0]["response_tokens"] is None
        assert events[0]["time"] is None
        assert events[0]["agent_type"] == "narrator"
        assert events[0]["agent_action"] == "narrate"
        assert events[0]["template_uid"] == "narrator.test"
        release.set()
        assert await asyncio.wait_for(task, 2) == "answer"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert len({event["request_id"] for event in events}) == 1
    assert [event["status"] for event in events].count("completed") == 1
    assert events[-1]["prompt_tokens"] == 0
    assert events[-1]["response_tokens"] == 0
    assert events[-1]["attempts"] == 1
    assert events[-1]["response"] == "answer"
    assert events[-1]["time"] >= 0
    assert events[-2]["generation_parameters"]


@pytest.mark.asyncio
async def test_same_client_overlap_keeps_usage_reasoning_and_identity(
    lifecycle_client, monkeypatch
):
    client, events = lifecycle_client
    started = {name: asyncio.Event() for name in ("first", "second")}
    release = {name: asyncio.Event() for name in started}

    async def generate(prompt, *args):
        name = "first" if "first" in prompt else "second"
        client._returned_prompt_tokens = 11 if name == "first" else 22
        client._returned_response_tokens = 33 if name == "first" else 44
        client._reasoning_response = name + " reasoning"
        started[name].set()
        await release[name].wait()
        return name + " answer"

    monkeypatch.setattr(client, "generate", generate)
    tasks = {}
    try:
        for name in started:
            tasks[name] = asyncio.create_task(send(client, name))
            await asyncio.wait_for(started[name].wait(), 2)
        release["second"].set()
        assert await asyncio.wait_for(tasks["second"], 2) == "second answer"
        assert all(
            event["status"] == "active"
            for event in events
            if "first" in event["prompt"]
        )
        release["first"].set()
        assert await asyncio.wait_for(tasks["first"], 2) == "first answer"
    finally:
        for event in release.values():
            event.set()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
    completed = [event for event in events if event["status"] == "completed"]
    assert [event["response"] for event in completed] == [
        "second answer",
        "first answer",
    ]
    assert [event["prompt_tokens"] for event in completed] == [22, 11]
    assert [event["response_tokens"] for event in completed] == [44, 33]
    assert [event["reasoning"] for event in completed] == [
        "second reasoning",
        "first reasoning",
    ]
    assert len({event["request_id"] for event in completed}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["provider", "empty", "processing", "cancel", "unexpected"]
)
async def test_terminal_outcomes(lifecycle_client, monkeypatch, outcome):
    client, events = lifecycle_client

    async def generate(*args):
        if outcome == "empty":
            return ""
        if outcome == "cancel":
            raise GenerationCancelled("cancel")
        raise RuntimeError("provider failure")

    async def ignore(*args, **kwargs):
        assert events[-1]["status"] == "active"
        return "ignore"

    async def fail(*args):
        if outcome == "processing":
            raise GenerationProcessingError("Cannot process response")
        raise ValueError("Unexpected failure")

    monkeypatch.setattr(client, "generate", generate)
    monkeypatch.setattr(client, "_prompt_generation_error", ignore)
    if outcome in ("processing", "unexpected"):
        monkeypatch.setattr(client, "_generate_with_reasoning_handling", fail)
    if outcome == "cancel":
        with pytest.raises(GenerationCancelled):
            await asyncio.wait_for(send(client), 2)
    elif outcome == "unexpected":
        with pytest.raises(ValueError):
            await asyncio.wait_for(send(client), 2)
    else:
        assert await asyncio.wait_for(send(client), 2) == ""
    terminal = [event for event in events if event["status"] != "active"]
    assert len(terminal) == 1
    assert terminal[0]["status"] == ("cancelled" if outcome == "cancel" else "failed")
    assert terminal[0]["error"]
    assert terminal[0]["time"] >= 0


@pytest.mark.asyncio
async def test_task_cancellation_cleans_up_provider_and_emits_terminal(
    lifecycle_client, monkeypatch
):
    client, events = lifecycle_client
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def generate(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(client, "generate", generate)
    task = asyncio.create_task(send(client))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert cancelled.is_set()
    assert events[-1]["status"] == "cancelled"
    assert len([event for event in events if event["status"] != "active"]) == 1


@pytest.mark.asyncio
async def test_retry_success_updates_one_logical_record(lifecycle_client, monkeypatch):
    client, events = lifecycle_client
    calls = 0

    async def generate(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return "recovered"

    async def retry(*args, **kwargs):
        return "retry"

    monkeypatch.setattr(client, "generate", generate)
    monkeypatch.setattr(client, "_prompt_generation_error", retry)
    assert await asyncio.wait_for(send(client), 2) == "recovered"
    assert len({event["request_id"] for event in events}) == 1
    assert events[-1]["status"] == "completed"
    assert events[-1]["attempts"] == 2
    assert events[-1]["error"] is None
    assert any(event["error"] for event in events[:-1])


@pytest.mark.asyncio
async def test_jsonl_has_one_terminal_record(lifecycle_client, monkeypatch, tmp_path):
    client, events = lifecycle_client

    async def generate(*args):
        return "logged"

    monkeypatch.setattr(client, "generate", generate)
    monkeypatch.setenv("TALEMATE_LOG_PROMPTS", "1")
    monkeypatch.setattr(base, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(ClientBase, "_prompt_log_file", None)
    try:
        await asyncio.wait_for(send(client), 2)
        records = [
            json.loads(line)
            for line in (tmp_path / "prompt_log.jsonl").read_text().splitlines()
        ]
        assert records == [events[-1]]
        assert records[0]["status"] == "completed"
    finally:
        if ClientBase._prompt_log_file:
            ClientBase._prompt_log_file.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["textgen-chat", "textgen-completion", "kobold"])
async def test_executor_streams_keep_request_metadata_under_overlap(
    cfg_isolation, monkeypatch, provider
):
    module = koboldcpp if provider == "kobold" else textgenwebui
    cls = (
        module.KoboldCppClient
        if provider == "kobold"
        else module.TextGeneratorWebuiClient
    )
    config_state.CONFIG.clients[provider] = module.ClientConfig(
        name=provider,
        type=cls.client_type,
        model="test-model",
        api_url="http://fixture.invalid/api/v1",
        api_handles_prompt_template=provider == "textgen-chat",
    )
    client = cls(name=provider)
    client.connected = True
    client.remote_model_name = "test-model"
    client.auto_determine_prompt_template = False
    events, information = [], {}
    started = {name: asyncio.Event() for name in ("first", "second")}
    release = {name: threading.Event() for name in started}
    finished = {name: threading.Event() for name in started}
    loop = asyncio.get_running_loop()

    async def status():
        pass

    monkeypatch.setattr(client, "status", status)
    monkeypatch.setattr(client, "prompt_template", lambda system, prompt: prompt)
    monkeypatch.setattr(
        client,
        "chat_messages_for_coercion",
        lambda prompt, kind: ([{"role": "user", "content": prompt}], None),
        raising=False,
    )
    monkeypatch.setattr(
        base,
        "emit",
        lambda typ, **kw: events.append(kw["data"]) if typ == "prompt_sent" else None,
    )

    def post(url, **kwargs):
        parameters = kwargs["json"]
        prompt = parameters.get("prompt") or parameters["messages"][0]["content"]
        name = "first" if "first" in prompt else "second"
        information[name] = client.request_information
        loop.call_soon_threadsafe(started[name].set)
        return SimpleNamespace(name=name, raise_for_status=lambda: None)

    class Stream:
        def __init__(self, response):
            self.name = response.name

        def events(self):
            name = self.name
            try:
                assert release[name].wait(5), "provider was not released"
                answer = name + " answer"
                if provider == "textgen-chat":
                    payload = {
                        "choices": [
                            {
                                "delta": {
                                    "content": answer,
                                    "reasoning_content": name + " reasoning",
                                }
                            }
                        ]
                    }
                elif provider == "textgen-completion":
                    payload = {"choices": [{"text": answer}]}
                else:
                    payload = {"token": answer}
                yield SimpleNamespace(data=json.dumps(payload))
                yield SimpleNamespace(data="[DONE]")
            finally:
                finished[name].set()

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.sseclient, "SSEClient", Stream)
    tasks = {}
    try:
        for name in started:
            tasks[name] = asyncio.create_task(send(client, name))
            await asyncio.wait_for(started[name].wait(), 3)
        assert information["first"] is not information["second"]
        for name in ("second", "first"):
            release[name].set()
            assert await asyncio.wait_for(tasks[name], 3) == name + " answer"
    finally:
        for event in release.values():
            event.set()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
    completed = [event for event in events if event["status"] == "completed"]
    assert [event["response"] for event in completed] == [
        "second answer",
        "first answer",
    ]
    for event, name in zip(completed, ("second", "first")):
        expected_tokens = client.count_tokens(name + " answer")
        if provider == "textgen-chat":
            assert event["reasoning"] == name + " reasoning"
            expected_tokens += client.count_tokens(name + " reasoning")
        assert information[name].tokens == expected_tokens
        assert information[name].end_time is not None
        assert finished[name].is_set()
    assert len({event["request_id"] for event in completed}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "retry", "failed", "cancelled"])
async def test_effective_provider_parameters_refresh_terminal_and_jsonl(
    lifecycle_client, monkeypatch, tmp_path, outcome
):
    client, events = lifecycle_client
    started, release = asyncio.Event(), asyncio.Event()
    calls, sent = 0, []

    async def generate(prompt, parameters, kind):
        nonlocal calls
        calls += 1
        parameters.pop("temperature", None)
        parameters["thinking"] = {"type": "adaptive"}
        parameters["output_config"] = {"effort": "high"}
        parameters["provider"] = {"order": ["fixture-" + str(calls)]}
        parameters["cache_control"] = {"type": "ephemeral"}
        sent.append(deepcopy(parameters))
        started.set()
        await release.wait()
        if outcome == "failed" or (outcome == "retry" and calls == 1):
            raise RuntimeError("controlled provider failure")
        return "answer"

    async def error_action(*args, **kwargs):
        return "retry" if outcome == "retry" else "ignore"

    monkeypatch.setattr(client, "generate", generate)
    monkeypatch.setattr(client, "_prompt_generation_error", error_action)
    monkeypatch.setenv("TALEMATE_LOG_PROMPTS", "1")
    monkeypatch.setattr(base, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(ClientBase, "_prompt_log_file", None)
    task = asyncio.create_task(send(client))
    try:
        await asyncio.wait_for(started.wait(), 2)
        early = next(event for event in events if event["generation_parameters"])
        assert "temperature" in early["generation_parameters"]
        assert "thinking" not in early["generation_parameters"]
        if outcome == "cancelled":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        else:
            release.set()
            assert await asyncio.wait_for(task, 2) == (
                "" if outcome == "failed" else "answer"
            )
        terminal = events[-1]
        assert terminal["status"] == ("completed" if outcome == "retry" else outcome)
        assert terminal["generation_parameters"] == sent[-1]
        assert terminal["attempts"] == (2 if outcome == "retry" else 1)
        assert len({event["request_id"] for event in events}) == 1
        assert len([event for event in events if event["status"] != "active"]) == 1
        assert "temperature" in early["generation_parameters"]
        records = [
            json.loads(line)
            for line in (tmp_path / "prompt_log.jsonl").read_text().splitlines()
        ]
        assert records == [terminal]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if ClientBase._prompt_log_file:
            ClientBase._prompt_log_file.close()


@pytest.mark.asyncio
async def test_anthropic_effective_parameters_match_sdk_request(
    cfg_isolation, monkeypatch
):
    name = "anthropic-lifecycle"
    config_state.CONFIG.anthropic.api_key = "test-only-not-a-credential"
    config_state.CONFIG.clients[name] = anthropic.ClientConfig(
        name=name,
        type="anthropic",
        model="claude-opus-4-7",
        max_token_length=16384,
        reason_tokens=2048,
        reason_enabled=True,
        optimize_prompt_caching=True,
    )
    client = anthropic.AnthropicClient(name=name)
    events, sent = [], []

    async def status():
        client.connected = True

    async def error_action(*args, **kwargs):
        pytest.fail("Unexpected provider failure in mocked Anthropic request")

    async def stream():
        yield SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="test reasoning"),
        )
        yield SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="test answer"),
        )

    async def create(**kwargs):
        sent.append(deepcopy(kwargs))
        return stream()

    monkeypatch.setattr(client, "status", status)
    monkeypatch.setattr(client, "_prompt_generation_error", error_action)
    monkeypatch.setattr(
        anthropic,
        "AsyncAnthropic",
        lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    monkeypatch.setattr(
        base,
        "emit",
        lambda typ, **kw: events.append(kw["data"]) if typ == "prompt_sent" else None,
    )
    assert await asyncio.wait_for(send(client), 3) == "test answer"
    early = next(
        event["generation_parameters"]
        for event in events
        if event["generation_parameters"]
    )
    terminal = events[-1]
    effective = terminal["generation_parameters"]
    expected = {
        key: value
        for key, value in sent[0].items()
        if key not in ("model", "system", "messages", "stream")
    }
    assert effective == expected
    assert "temperature" in early
    assert "temperature" not in effective
    assert "top_p" not in effective
    assert "top_k" not in effective
    assert effective["thinking"] == {"type": "adaptive"}
    assert effective["output_config"] == {"effort": "high"}
    assert effective["cache_control"] == {"type": "ephemeral"}
    assert effective["max_tokens"] == client.api_max_output_tokens
    assert terminal["reasoning"] == "test reasoning"
    assert terminal["status"] == "completed"
