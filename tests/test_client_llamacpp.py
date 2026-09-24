import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import httpx
import httpx2
import pytest
import pytest_asyncio
import yaml

import talemate.config.state as config_state
from talemate.client import base, llamacpp
from talemate.client.model_prompts import PromptSpec
from talemate.config.schema import Config
from talemate.exceptions import GenerationProcessingError

MODEL = "team/model:Q4 + special&tag"


@pytest.fixture
def server(monkeypatch, cfg_isolation):
    state = {
        "props": {"role": "router", "models_autoload": True},
        "props_code": 200,
        "models": [{"id": MODEL, "status": {"value": "unloaded"}}, {"id": "second"}],
        "requests": [],
    }
    native_client = httpx.AsyncClient
    openai_client = llamacpp.AsyncOpenAI

    async def respond(request, response_type):
        state["requests"].append(request)
        path = request.url.path
        if state.get("pause") == path:
            state["started"].set()
            try:
                await asyncio.Future()
            finally:
                state["cancelled"] = True
        if state.get("error_path") == path:
            return response_type(
                state["error_code"], json={"error": {"message": state["error_message"]}}
            )
        if path == "/props":
            if state.get("props_unreachable"):
                raise httpx.ConnectError("unreachable", request=request)
            return response_type(state["props_code"], json=state["props"])
        if path == "/v1/models":
            return response_type(200, json={"data": state["models"], "object": "list"})
        if path == "/apply-template":
            return response_type(200, json={"prompt": "TEMPLATED"})
        if path == "/completion":
            return response_type(
                200,
                text='data: {"content":"Hello"}\n\ndata: {"content":" world","stop":true}\n\ndata: [DONE]\n\n',
            )
        if path == "/v1/chat/completions":
            return response_type(
                200,
                json={
                    "id": "vision",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "An image"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def native(request):
        return await respond(request, httpx.Response)

    async def sdk(request):
        return await respond(request, httpx2.Response)

    class NativeClient(native_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(native), **kwargs)

    monkeypatch.setattr(llamacpp.httpx, "AsyncClient", NativeClient)
    monkeypatch.setattr(
        llamacpp,
        "AsyncOpenAI",
        lambda **kw: openai_client(
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(sdk)), **kw
        ),
    )
    return state


@pytest.fixture
def client_factory(server):
    def make(name="router", router_mode=True, **kwargs):
        config_state.CONFIG.clients[name] = llamacpp.ClientConfig(
            name=name,
            type="llamacpp",
            api_url="http://llama.test:8080",
            router_mode=router_mode,
            **kwargs,
        )
        client = llamacpp.LlamaCppClient(name=name)
        client.auto_determine_prompt_template = False
        return client

    return make


def test_router_mode_defaults_to_off():
    assert not llamacpp.ClientConfig(type="llamacpp", name="new").router_mode


@pytest.mark.asyncio
@pytest.mark.parametrize("router_mode", [False, True])
@pytest.mark.parametrize("remote_template", [False, True])
async def test_only_checkbox_enables_routing_on_detected_router(
    server, client_factory, router_mode, remote_template
):
    server["models"].insert(0, {"id": "/models/first.gguf"})
    client = client_factory(
        router_mode=router_mode,
        model=MODEL,
        api_handles_prompt_template=remote_template,
    )
    await client.status()
    assert client.finalize_status({})["router_detected"]
    assert client.model == MODEL
    if router_mode:
        assert client.model_name == MODEL
        assert client.status_details() == ("idle", None)
    else:
        assert client.model_name is None
        assert client.status_details() == (
            "warning",
            "Router detected. Turn on Router mode to pick a model.",
        )
    await client.generate("Hi", {}, "narrate")
    posts = [r for r in server["requests"] if r.method == "POST"]
    assert len(posts) == (2 if remote_template else 1)
    for request in posts:
        payload = json.loads(request.content)
        if router_mode:
            assert payload["model"] == MODEL
        else:
            assert "model" not in payload


@pytest.mark.asyncio
async def test_checkbox_toggle_retains_exact_selection(server, client_factory):
    client = client_factory(model=MODEL)
    for enabled in (True, False, True):
        client.client_config.router_mode = enabled
        await client.status()
        await client.generate("Hi", {}, "narrate")
        assert client.model == MODEL
        assert client.finalize_status({})["configured_model"] == MODEL
        payload = json.loads(server["requests"][-1].content)
        assert payload.get("model") == (MODEL if enabled else None)


@pytest.mark.asyncio
async def test_router_probe_requests_selection_without_loading(server, client_factory):
    client = client_factory()
    await client.status()
    assert client.connected
    assert client.current_status == "warning"
    assert client.status_details()[1] == "Select a router model"
    assert client.model is None
    assert client.finalize_status({})["manual_model_choices"] == [MODEL, "second"]
    assert [(r.method, r.url.path, str(r.url.query)) for r in server["requests"]] == [
        ("GET", "/props", "b''"),
        ("GET", "/v1/models", "b''"),
    ]


@pytest.mark.asyncio
async def test_detected_router_off_status_matches_frontend_choices_fixture(
    server, client_factory, monkeypatch
):
    emit = Mock()
    monkeypatch.setattr(base, "emit", emit)
    client = client_factory(router_mode=False)
    await client.status()
    emit.assert_called_once()
    assert emit.call_args.args == ("client_status",)
    assert emit.call_args.kwargs["details"] is None
    assert emit.call_args.kwargs["status"] == "warning"
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "talemate_frontend/tests/unit/fixtures/llamacppDetectedRouterOff.json"
    )
    fixture = json.loads(fixture_path.read_text())
    data = emit.call_args.kwargs["data"]
    assert {key: data[key] for key in fixture} == fixture
    assert client.connected
    assert client.model is None
    assert [(r.method, r.url.path, r.url.query) for r in server["requests"]] == [
        ("GET", "/props", b""),
        ("GET", "/v1/models", b""),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_model", [None, MODEL])
async def test_detected_router_off_status_skips_automatic_template_lookup(
    client_factory, monkeypatch, configured_model
):
    query = Mock(side_effect=AssertionError("Unexpected template lookup"))
    monkeypatch.setattr(
        llamacpp.model_prompt, "query_hf_for_prompt_template_suggestion", query
    )
    client = client_factory(router_mode=False, model=configured_model)
    client.auto_determine_prompt_template = True
    client.remote_model_name = "gemma"
    client.auto_determine_prompt_template_attempt = "previous-model"
    monkeypatch.setattr(
        client,
        "prompt_template_example",
        lambda: (None, client.default_prompt_template, PromptSpec()),
    )
    await client.status()
    await client.status()
    assert client.model_name is None
    assert client.remote_model_name is None
    assert client.model == configured_model
    assert client.status_details() == (
        "warning",
        "Router detected. Turn on Router mode to pick a model.",
    )
    assert client.auto_determine_prompt_template_attempt is None
    assert not client._prompt_template_tasks
    query.assert_not_called()


@pytest.mark.asyncio
async def test_single_model_status_keeps_synchronous_template_lookup(
    server, client_factory, monkeypatch
):
    server.update(props={}, models=[{"id": "/models/single.gguf"}])
    thread_ids = []

    def lookup(model):
        thread_ids.append(threading.get_ident())

    query = Mock(side_effect=lookup)
    monkeypatch.setattr(
        llamacpp.model_prompt, "query_hf_for_prompt_template_suggestion", query
    )
    client = client_factory(router_mode=False)
    client.auto_determine_prompt_template = True
    monkeypatch.setattr(
        client,
        "prompt_template_example",
        lambda: (None, client.default_prompt_template, PromptSpec()),
    )
    await client.status()
    assert client.model_name == "single.gguf"
    assert client.current_status == "idle"
    assert client.finalize_status({})["manual_model_choices"] == []
    query.assert_called_once_with("single.gguf")
    assert thread_ids == [threading.get_ident()]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "props,code",
    [({}, 200), ({"role": "future"}, 200), ([], 200), ({}, 404), ({}, 503)],
)
async def test_unknown_detection_preserves_single_model_discovery(
    server, client_factory, props, code
):
    server.update(
        props=props, props_code=code, models=[{"id": "C:\\models\\single.gguf"}]
    )
    client = client_factory(router_mode=False)
    await client.status()
    assert client.connected
    assert client.model_name == "single.gguf"
    assert not client.router_mode
    assert client.finalize_status({})["server_role"] == "unknown"
    assert not client.client_config.router_mode


@pytest.mark.asyncio
async def test_unreachable_props_falls_back_to_models(server, client_factory):
    server.update(props_unreachable=True, models=[{"id": "/models/single.gguf"}])
    client = client_factory(router_mode=False)
    await client.status()
    assert client.model_name == "single.gguf"
    assert client.current_status == "idle"


@pytest.mark.asyncio
async def test_router_mode_uses_exact_selection_when_detection_unavailable(
    server, client_factory
):
    server["props_code"] = 404
    client = client_factory(router_mode=True, model=MODEL)
    await client.status()
    assert client.model_name == MODEL
    assert client.current_status == "idle"
    assert await client.generate("Hi", {}, "narrate") == "Hello world"
    assert json.loads(server["requests"][-1].content)["model"] == MODEL


@pytest.mark.asyncio
async def test_status_reconnect_and_disk_roundtrip_keep_two_selections(
    server, client_factory, tmp_path
):
    clients = [client_factory(model=MODEL), client_factory("other", model="second")]
    for _ in range(2):
        for client in clients:
            await client.status()
    path = tmp_path / "config.yaml"
    saved = Config(clients={c.name: c.client_config for c in clients})
    path.write_text(yaml.safe_dump(saved.model_dump(mode="json")))
    reloaded = Config.model_validate(yaml.safe_load(path.read_text()))
    for name, cfg in reloaded.clients.items():
        config_state.CONFIG.clients[name] = cfg
        client = llamacpp.LlamaCppClient(name=name)
        client.auto_determine_prompt_template = False
        await client.status()
        assert client.model_name == cfg.model
        assert client.finalize_status({})["configured_model"] == cfg.model
    assert reloaded.clients["router"].model == MODEL
    assert reloaded.clients["other"].model == "second"
    assert all(r.method == "GET" and not r.url.query for r in server["requests"])


@pytest.mark.asyncio
async def test_failed_probe_retains_router_hint_but_new_endpoint_does_not(
    server, client_factory
):
    client = client_factory(router_mode=False, model=MODEL)
    await client.status()
    server["props_code"] = 503
    await client.status()
    assert not client.router_mode
    assert client.finalize_status({})["router_detected"]
    assert client.status_details() == (
        "warning",
        "Router detected. Turn on Router mode to pick a model.",
    )
    assert client.finalize_status({})["server_role"] == "unknown"
    client.client_config.api_url = "http://another.test:8080"
    server["models"] = [{"id": "/path/single.gguf"}]
    await client.status()
    assert not client.router_mode
    assert not client.finalize_status({})["router_detected"]
    assert client.current_status == "idle"
    assert client.model_name == "single.gguf"
    assert client.model == MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selected,state,autoload,expected,message",
    [
        (None, "loaded", True, "warning", "Select a router model"),
        ("unknown", "loaded", True, "warning", "Selected model is not available"),
        (MODEL, "loading", True, "busy", "Model is loading"),
        (MODEL, "unloaded", False, "warning", "autoload is disabled"),
        (MODEL, "unloaded", True, "idle", None),
        (MODEL, "sleeping", False, "idle", None),
        (MODEL, "loaded", False, "idle", None),
    ],
)
async def test_router_status_is_not_a_connection_error(
    server, client_factory, selected, state, autoload, expected, message
):
    server["models"][0]["status"]["value"] = state
    server["props"]["models_autoload"] = autoload
    client = client_factory(model=selected)
    await client.status()
    assert client.connected
    assert client.current_status == expected
    if message:
        assert message in client.status_details()[1]
    else:
        assert client.status_details()[1] is None


@pytest.mark.asyncio
async def test_alias_is_not_replaced_with_canonical_id(server, client_factory):
    server["models"][0]["aliases"] = ["my/alias:Q4"]
    client = client_factory(model="my/alias:Q4")
    await client.status()
    assert client.current_status == "idle"
    await client.generate("Hi", {}, "narrate")
    assert json.loads(server["requests"][-1].content)["model"] == "my/alias:Q4"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/props", "/v1/models"])
@pytest.mark.parametrize("code", [401, 403])
async def test_authentication_failures_are_not_hidden(
    server, client_factory, path, code
):
    server.update(error_path=path, error_code=code, error_message="Invalid API key")
    client = client_factory(model=MODEL)
    await client.status()
    assert not client.connected
    assert client.current_status == "error"
    assert client.status_details()[1] == f"Invalid API key ({code})"
    assert server["requests"][-1].url.path == path


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403])
async def test_single_model_sdk_authentication_status(server, client_factory, code):
    server.update(
        props={},
        error_path="/v1/models",
        error_code=code,
        error_message="Invalid API key",
    )
    client = client_factory(router_mode=False)
    await client.status()
    assert not client.connected
    assert client.status_details() == ("error", f"Invalid API key ({code})")


@pytest.mark.asyncio
async def test_model_listing_connection_failure_preserves_selection(
    server, client_factory
):
    server.update(error_path="/v1/models", error_code=503, error_message="Unavailable")
    client = client_factory(model=MODEL)
    await client.status()
    assert not client.connected
    assert client.current_status == "error"
    assert client.model == MODEL
    assert client.finalize_status({})["configured_model"] == MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_template", [False, True])
async def test_native_stream_auth_sampling_and_template_use_exact_model(
    server, client_factory, remote_template
):
    client = client_factory(
        model=MODEL,
        api_key="unit-test-key",
        api_handles_prompt_template=remote_template,
    )
    assert (
        await client.generate(
            "Hi<|BOT|>Yes",
            {"temperature": 0.4, "n_predict": 12, "stop": ["END"]},
            "narrate",
        )
        == "Hello world"
    )
    posts = [r for r in server["requests"] if r.method == "POST"]
    assert len(posts) == (2 if remote_template else 1)
    for request in server["requests"]:
        assert request.headers["authorization"] == "Bearer unit-test-key"
    for request in posts:
        assert json.loads(request.content)["model"] == MODEL
    payload = json.loads(posts[-1].content)
    assert payload["stream"] is True
    assert payload["temperature"] == 0.4
    assert payload["n_predict"] == 12
    assert payload["stop"] == ["END"]
    if remote_template:
        template = json.loads(posts[0].content)
        assert template["messages"][-1] == {"role": "assistant", "content": "Yes"}
        assert payload["prompt"] == "TEMPLATED"
        assert posts[0].extensions["timeout"]["read"] is None
    assert client._returned_response_tokens > 0


@pytest.mark.asyncio
async def test_single_model_completion_and_template_payloads_are_unchanged(
    server, client_factory
):
    server["props"] = {"model_path": "/models/single.gguf"}
    server["models"] = [{"id": "/models/single.gguf"}]
    client = client_factory(router_mode=False, api_handles_prompt_template=True)
    await client.status()
    assert await client.generate("Hi", {"n_predict": 8}, "narrate") == "Hello world"
    posts = [r for r in server["requests"] if r.method == "POST"]
    assert all("model" not in json.loads(r.content) for r in posts)
    assert posts[0].extensions["timeout"]["read"] == llamacpp.APPLY_TEMPLATE_TIMEOUT
    assert client.model_name == "single.gguf"


@pytest.mark.asyncio
async def test_inherited_vision_uses_exact_model(server, client_factory):
    client = client_factory(model=MODEL, vision_enabled=True, api_key="unit-test-key")
    assert await client.analyze_image(b"image", "Describe") == "An image"
    request = server["requests"][-1]
    assert request.url.path == "/v1/chat/completions"
    assert json.loads(request.content)["model"] == MODEL
    assert request.headers["authorization"] == "Bearer unit-test-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,remote_template",
    [("generate", False), ("generate", True), ("analyze_image", False)],
)
async def test_missing_model_rejected_before_routed_request(
    server, client_factory, method, remote_template
):
    client = client_factory(api_handles_prompt_template=remote_template)
    args = {
        "generate": ("Hi", {}, "narrate"),
        "analyze_image": (b"image", "Describe"),
    }
    with pytest.raises(GenerationProcessingError, match="select a model first"):
        await getattr(client, method)(*args[method])
    assert all(r.method == "GET" for r in server["requests"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,code,message",
    [
        ("/apply-template", 400, "model is not loaded"),
        ("/apply-template", 400, "model not found"),
        ("/apply-template", 401, "Invalid API key"),
        ("/completion", 400, "model is not loaded"),
        ("/completion", 400, "model not found"),
        ("/completion", 403, "Invalid API key"),
    ],
)
async def test_server_generation_errors_retain_meaning(
    server, client_factory, path, code, message
):
    server.update(error_path=path, error_code=code, error_message=message)
    client = client_factory(
        model=MODEL, api_handles_prompt_template=path == "/apply-template"
    )
    with pytest.raises(GenerationProcessingError, match=message):
        await client.generate("Hi", {}, "narrate")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/apply-template", "/completion"])
async def test_cold_load_can_be_cancelled(server, client_factory, path):
    server.update(pause=path, started=asyncio.Event())
    client = client_factory(
        model=MODEL, api_handles_prompt_template=path == "/apply-template"
    )
    task = asyncio.create_task(client.generate("Hi", {}, "narrate"))
    try:
        await asyncio.wait_for(server["started"].wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert server["cancelled"]
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_unknown_optional_metadata_does_not_hide_router_role(
    server, client_factory
):
    server["props"]["models_autoload"] = "not-a-boolean"
    client = client_factory(model=MODEL)
    await client.status()
    assert client.router_mode
    assert client.finalize_status({})["router_detected"]
    assert client.model_name == MODEL
    assert client.finalize_status({})["models_autoload"] is None


@pytest.mark.asyncio
async def test_model_selection_is_snapshotted_across_template_await(
    server, client_factory, monkeypatch
):
    client = client_factory(model=MODEL, api_handles_prompt_template=True)
    apply_template = client.apply_remote_template

    async def change_selection(prompt, kind, model):
        rendered = await apply_template(prompt, kind, model)
        client.client_config.model = "second"
        return rendered

    monkeypatch.setattr(client, "apply_remote_template", change_selection)
    await client.generate("Hi", {}, "narrate")
    posts = [r for r in server["requests"] if r.method == "POST"]
    assert [json.loads(r.content)["model"] for r in posts] == [MODEL, MODEL]
    assert client.model == "second"


@pytest.mark.asyncio
async def test_cancelling_active_stream_closes_response(
    server, client_factory, monkeypatch
):
    started = asyncio.Event()
    closed = asyncio.Event()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"content":"Hello"}\n\n'
            started.set()
            await asyncio.Future()

        async def aclose(self):
            closed.set()

    async def respond(request):
        if request.url.path == "/props":
            return httpx.Response(200, json={"role": "router"})
        assert json.loads(request.content)["model"] == MODEL
        return httpx.Response(200, stream=SlowStream())

    native_client = httpx.AsyncClient.__bases__[0]

    class StreamingClient(native_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(llamacpp.httpx, "AsyncClient", StreamingClient)
    client = client_factory(model=MODEL)
    task = asyncio.create_task(client.generate("Hi", {}, "narrate"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
    finally:
        task.cancel()


@pytest_asyncio.fixture
async def template_lookup(monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def lookup(model):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise TimeoutError("Test did not release the template lookup")
        return "ChatML.jinja2"

    query = Mock(side_effect=lookup)
    create = Mock()
    monkeypatch.setattr(
        llamacpp.model_prompt, "query_hf_for_prompt_template_suggestion", query
    )
    monkeypatch.setattr(llamacpp.model_prompt, "create_user_override", create)
    try:
        yield started, release, query, create
    finally:
        release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "model", "api_url", "template", "disabled"])
async def test_router_template_lookup_keeps_status_and_generation_responsive(
    client_factory, template_lookup, monkeypatch, change
):
    started, release, query, create = template_lookup
    client = client_factory(model=MODEL)
    client.auto_determine_prompt_template = True
    example = Mock(return_value=(None, client.default_prompt_template, PromptSpec()))
    monkeypatch.setattr(client, "prompt_template_example", example)
    try:
        await client.status()
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(client.status(), 1)
        assert (
            await asyncio.wait_for(client.generate("Hi", {}, "narrate"), 1)
            == "Hello world"
        )
        assert not release.is_set()
        query.assert_called_once_with(MODEL)

        if change == "model":
            client.client_config.model = "second"
        elif change == "api_url":
            client.client_config.api_url = "http://another.test:8080"
        elif change == "template":
            example.return_value = (None, "user-choice.jinja2", PromptSpec())
        elif change == "disabled":
            client.client_config.enabled = False

        release.set()
        await asyncio.wait_for(client._prompt_template_tasks[MODEL], 1)
        assert MODEL not in client._prompt_template_tasks
        if change is None:
            create.assert_called_once_with("ChatML.jinja2", MODEL)
            await client.status()
            query.assert_called_once_with(MODEL)
        else:
            create.assert_not_called()
    finally:
        release.set()
        await client.destroy()


@pytest.mark.asyncio
async def test_router_template_lookup_retries_after_model_switch_back(
    client_factory, template_lookup, monkeypatch
):
    started, release, query, create = template_lookup
    client = client_factory(model=MODEL)
    client.auto_determine_prompt_template = True
    monkeypatch.setattr(
        client,
        "prompt_template_example",
        lambda: (None, client.default_prompt_template, PromptSpec()),
    )
    try:
        await client.status()
        first = client._prompt_template_tasks[MODEL]
        await asyncio.wait_for(started.wait(), 1)
        client.client_config.model = "second"
        await client.status()
        second = client._prompt_template_tasks["second"]
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        create.assert_called_once_with("ChatML.jinja2", "second")
        assert client.auto_determine_prompt_template_attempt == "second"
        assert not client._prompt_template_tasks

        client.client_config.model = MODEL
        await client.status()
        await asyncio.wait_for(client._prompt_template_tasks[MODEL], 1)
        assert [call.args[0] for call in query.call_args_list] == [
            MODEL,
            "second",
            MODEL,
        ]
        create.assert_called_with("ChatML.jinja2", MODEL)
        assert not client._prompt_template_tasks
    finally:
        release.set()
        await client.destroy()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["api_url", "disabled", "template"])
async def test_router_template_lookup_retries_after_setting_restored(
    client_factory, template_lookup, monkeypatch, change
):
    started, release, query, create = template_lookup
    client = client_factory(model=MODEL)
    client.auto_determine_prompt_template = True
    example = Mock(return_value=(None, client.default_prompt_template, PromptSpec()))
    monkeypatch.setattr(client, "prompt_template_example", example)
    original_url = client.api_url
    try:
        await client.status()
        first = client._prompt_template_tasks[MODEL]
        await asyncio.wait_for(started.wait(), 1)
        if change == "api_url":
            client.client_config.api_url = "http://another.test:8080"
        elif change == "disabled":
            client.client_config.enabled = False
        else:
            example.return_value = (None, "user-choice.jinja2", PromptSpec())
        await client.status()
        release.set()
        await asyncio.wait_for(first, 1)
        create.assert_not_called()
        assert client.auto_determine_prompt_template_attempt is None
        assert not client._prompt_template_tasks

        client.client_config.api_url = original_url
        client.client_config.enabled = True
        example.return_value = (None, client.default_prompt_template, PromptSpec())
        await client.status()
        await asyncio.wait_for(client._prompt_template_tasks[MODEL], 1)
        assert [call.args[0] for call in query.call_args_list] == [MODEL, MODEL]
        create.assert_called_once_with("ChatML.jinja2", MODEL)
        assert not client._prompt_template_tasks
    finally:
        release.set()
        await client.destroy()


@pytest.mark.asyncio
async def test_no_template_suggestion_does_not_repeat_on_each_status(
    client_factory, template_lookup, monkeypatch
):
    _, _, query, create = template_lookup
    query.side_effect = None
    query.return_value = None
    client = client_factory(model=MODEL)
    client.auto_determine_prompt_template = True
    monkeypatch.setattr(
        client,
        "prompt_template_example",
        lambda: (None, client.default_prompt_template, PromptSpec()),
    )
    try:
        await client.status()
        await asyncio.wait_for(client._prompt_template_tasks[MODEL], 1)
        assert not client._prompt_template_tasks
        await client.status()
        query.assert_called_once_with(MODEL)
        create.assert_not_called()
        assert client.auto_determine_prompt_template_attempt == MODEL
    finally:
        await client.destroy()


@pytest.mark.asyncio
async def test_destroy_cancels_router_template_lookup(client_factory, template_lookup):
    started, release, query, create = template_lookup
    client = client_factory(model=MODEL, router_mode=True)
    client.determine_prompt_template()
    await asyncio.wait_for(started.wait(), 1)
    task = client._prompt_template_tasks[MODEL]
    await asyncio.wait_for(client.destroy(), 1)
    assert task.cancelled()
    assert not client._prompt_template_tasks
    release.set()
    create.assert_not_called()


@pytest.mark.asyncio
async def test_template_lookup_failure_does_not_fail_status(
    client_factory, template_lookup, monkeypatch
):
    _, _, query, create = template_lookup
    query.side_effect = RuntimeError("lookup failed")
    client = client_factory(model=MODEL, router_mode=True)
    warning = Mock()
    monkeypatch.setattr(client.log, "warning", warning)
    client.determine_prompt_template()
    await client._prompt_template_tasks[MODEL]
    await client.status()
    assert client.current_status == "idle"
    create.assert_not_called()
    warning.assert_called_once()
    await client.destroy()


def test_single_model_template_lookup_keeps_existing_behavior(
    client_factory, monkeypatch
):
    client = client_factory(router_mode=False)
    determine = Mock()
    monkeypatch.setattr(llamacpp.ClientBase, "determine_prompt_template", determine)
    client.determine_prompt_template()
    determine.assert_called_once_with()
