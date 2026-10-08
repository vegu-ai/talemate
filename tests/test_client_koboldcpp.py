"""Tests for the KoboldCpp client."""

from __future__ import annotations

import asyncio
import json
import math

import httpx
import pytest
from structlog.testing import capture_logs

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client import koboldcpp as koboldcpp_module
from talemate.client.base import PROMPT_TOKEN_SAFETY_FACTOR, STOPPING_STRINGS
from talemate.client.context import ClientContext, set_client_context_attribute
from talemate.client.koboldcpp import MAX_STOPPING_STRINGS, KoboldCppClient


@pytest.fixture
def preset_isolation():
    """Snapshot/restore the inference presets, yielding the live ones."""
    saved = config_state.CONFIG.presets.inference.model_copy(deep=True)
    yield config_state.CONFIG.presets.inference
    config_state.CONFIG.presets.inference = saved


def _make_client(name: str, api_url: str) -> KoboldCppClient:
    """`is_openai` keys off the api_url, which is read from the registered
    client config - constructing without one leaves api_url unset."""
    config_state.CONFIG.clients[name] = koboldcpp_module.ClientConfig(
        type="koboldcpp", name=name, api_url=api_url
    )
    return KoboldCppClient(name=name)


def _active_agent_context():
    """Return an ActiveAgent CM with an agent that injects no parameters.

    `tune_prompt_parameters` always reads the active agent context.
    """

    class _Agent:
        agent_type = "noop"
        verbose_name = "NoOp"

        def inject_prompt_paramters(self, parameters, kind, action):
            pass

    def _fn():
        pass

    return ActiveAgent(_Agent(), _fn)


class TestStoppingStrings:
    def test_extra_stopping_strings_reach_stop_sequence(self, cfg_isolation):
        client = _make_client("kcpp_stop", "http://fake:5001/api/v1")
        assert not client.is_openai
        parameters = {"extra_stopping_strings": ["Bob: "], "max_tokens": 50}

        with _active_agent_context():
            client.tune_prompt_parameters(parameters, "narrate")

        assert parameters["stopping_strings"] == STOPPING_STRINGS + ["Bob: "]

        client.clean_prompt_parameters(parameters)

        assert parameters["stop_sequence"] == STOPPING_STRINGS + ["Bob: "]
        assert parameters["max_length"] == 50
        assert "stopping_strings" not in parameters
        # send_prompt pops this before clean runs; clean drops it too since it
        # is not a supported parameter
        assert "extra_stopping_strings" not in parameters

    def test_stop_sequence_is_truncated_to_cap(self, cfg_isolation):
        client = _make_client("kcpp_stop_cap", "http://fake:5001/api/v1")
        extra = [f"Char{i}: " for i in range(20)]
        parameters = {"extra_stopping_strings": list(extra), "max_tokens": 50}

        with _active_agent_context():
            with capture_logs() as logs:
                client.tune_prompt_parameters(parameters, "narrate")

        client.clean_prompt_parameters(parameters)

        # pins the documented united-api limit
        assert MAX_STOPPING_STRINGS == 16

        expected = (STOPPING_STRINGS + extra)[:MAX_STOPPING_STRINGS]
        assert len(parameters["stop_sequence"]) == MAX_STOPPING_STRINGS
        assert parameters["stop_sequence"] == expected

        warnings = [entry for entry in logs if entry["log_level"] == "warning"]
        assert len(warnings) == 1
        assert warnings[0]["client_type"] == "koboldcpp"
        assert warnings[0]["max_stopping_strings"] == MAX_STOPPING_STRINGS
        assert (
            warnings[0]["dropped"] == (STOPPING_STRINGS + extra)[MAX_STOPPING_STRINGS:]
        )

    def test_openai_mode_sends_capped_stop_parameter(self, cfg_isolation):
        client = _make_client("kcpp_openai", "http://fake:5001/v1")
        assert client.is_openai
        extra = [f"Char{i}: " for i in range(20)]
        parameters = {"extra_stopping_strings": list(extra), "max_tokens": 50}

        with _active_agent_context():
            client.tune_prompt_parameters(parameters, "narrate")

        client.clean_prompt_parameters(parameters)

        assert parameters["stop"] == (STOPPING_STRINGS + extra)[:MAX_STOPPING_STRINGS]
        assert "stop_sequence" not in parameters
        assert parameters["max_tokens"] == 50


class TestSamplerParameters:
    @pytest.mark.parametrize(
        "api_url, token_key",
        [
            ("http://fake:5001/api/v1", "max_length"),
            ("http://fake:5001/v1", "max_tokens"),
        ],
    )
    def test_both_modes_send_native_samplers(self, cfg_isolation, api_url, token_key):
        client = _make_client("kcpp_samplers", api_url)
        parameters = {
            "max_tokens": 50,
            "top_k": 40,
            "min_p": 0.1,
            "repetition_penalty": 1.1,
            "repetition_penalty_range": 512,
            "dry_multiplier": 0.8,
            "dry_sequence_breakers": '"\\n", ":", "\\"", "*"',
        }

        with _active_agent_context():
            client.tune_prompt_parameters(parameters, "narrate")
        client.clean_prompt_parameters(parameters)

        assert parameters[token_key] == 50
        assert parameters["top_k"] == 40
        assert parameters["min_p"] == 0.1
        assert parameters["rep_pen"] == 1.1
        assert parameters["rep_pen_range"] == 512
        assert parameters["dry_multiplier"] == 0.8
        assert parameters["dry_sequence_breakers"] == ["\n", ":", '"', "*"]


class TestEmbeddingFunction:
    def test_embedding_request_sends_api_key(self, cfg_isolation, monkeypatch):
        name = "kcpp_embed_auth"
        config_state.CONFIG.clients[name] = koboldcpp_module.ClientConfig(
            type="koboldcpp", name=name, api_url="http://fake:5001", api_key="secret"
        )
        client = KoboldCppClient(name=name)
        calls = []

        class _Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"embedding": [0.1, 0.2]}]}

        def _fake_post(url, json=None, headers=None):
            calls.append({"url": url, "headers": headers})
            return _Response()

        monkeypatch.setattr(koboldcpp_module.requests, "post", _fake_post)

        vectors = client.embeddings_function(["text"])
        assert len(vectors) == 1
        assert list(vectors[0]) == pytest.approx([0.1, 0.2])
        assert calls[0]["headers"]["Authorization"] == "Bearer secret"


class TestOpenAIStreaming:
    @pytest.mark.asyncio
    async def test_completions_are_streamed(self, cfg_isolation, monkeypatch):
        client = _make_client("kcpp_stream", "http://fake:5001/v1")
        requests_seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            if request.url.path == "/api/extra/tokencount":
                return httpx.Response(200, json={"value": 2, "ids": [1, 2]})
            body = (
                'data: {"choices": [{"text": "Hello"}]}\n\n'
                'data: {"choices": [{"text": " world"}]}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=body)

        native_client = httpx.AsyncClient

        class _MockClient(native_client):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(koboldcpp_module.httpx, "AsyncClient", _MockClient)
        client.new_request()

        response = await client.generate("Say hello", {"max_tokens": 10}, "narrate")

        assert response == "Hello world"
        completion = next(r for r in requests_seen if r.url.path == "/v1/completions")
        assert json.loads(completion.content)["stream"] is True
        assert client.request_information.tokens > 0


class _OfflineKoboldCppClient(KoboldCppClient):
    """KoboldCpp client that records the parameters `generate` receives and
    returns a canned response, so `send_prompt` can run without a backend."""

    # the real emit_status would hit HuggingFace to guess a prompt template
    auto_determine_prompt_template: bool = False

    def __init__(self, response: str, **kwargs):
        super().__init__(**kwargs)
        self._response = response
        self.generate_parameters = None
        self.generate_prompt = None

    async def status(self):
        self.connected = True

    async def get_model_name(self):
        return self.remote_model_name

    async def generate(self, prompt: str, parameters: dict, kind: str):
        self.generate_parameters = parameters
        self.generate_prompt = prompt
        return self._response


class TestSendPromptCapFallback:
    @pytest.mark.asyncio
    async def test_cap_dropped_string_still_cuts_the_response(
        self, cfg_isolation, preset_isolation
    ):
        """A stopping string that lost its native slot to the cap is still
        applied to the response after generation."""
        name = "kcpp_fallback"
        config_state.CONFIG.clients[name] = koboldcpp_module.ClientConfig(
            type="koboldcpp", name=name, api_url="http://fake:5001/api/v1"
        )
        # 2 STOPPING_STRINGS + 15 preset entries = 17, one over the cap of 16
        kept = [f"<<KEPT_{i}>>" for i in range(14)]
        dropped = "<<DROPPED>>"
        preset_isolation.conversation.extra_stopping_strings = kept + [dropped]
        client = _OfflineKoboldCppClient(
            name=name, response=f"useful answer{dropped}garbage tail"
        )
        client.connected = True
        client.remote_model_name = "some-model"
        assert not client.is_openai

        with _active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                out = await client.send_prompt("hi", kind="conversation")

        assert out == "useful answer"
        # proves the cut came from the fallback, not from a native stop slot
        assert client.generate_parameters["stop_sequence"] == STOPPING_STRINGS + kept
        assert dropped not in client.generate_parameters["stop_sequence"]


class TestEmbeddingsProbe:
    @pytest.fixture
    def kcpp_server(self, monkeypatch):
        state = {"embeddings_error": None, "release": None, "requests": []}

        async def handler(request: httpx.Request) -> httpx.Response:
            state["requests"].append(request.url.path)
            if request.url.path.endswith("/api/extra/version"):
                return httpx.Response(200, json={"embeddings": True})
            if request.url.path.endswith("/api/extra/embeddings"):
                if state["release"] is not None:
                    await state["release"].wait()
                if state["embeddings_error"]:
                    raise state["embeddings_error"]
                return httpx.Response(200, json={"model": "embed-model", "data": []})
            return httpx.Response(200, json={"result": "koboldcpp/text-model"})

        native_client = httpx.AsyncClient

        class _MockClient(native_client):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(koboldcpp_module.httpx, "AsyncClient", _MockClient)
        return state

    @pytest.mark.asyncio
    async def test_slow_probe_does_not_hold_up_status(self, cfg_isolation, kcpp_server):
        kcpp_server["release"] = asyncio.Event()
        client = _make_client("kcpp_probe_slow", "http://fake:5001")

        assert await client.get_model_name() == "text-model"
        assert client.embeddings_model_name is None

        kcpp_server["release"].set()
        await client._embeddings_probe_task
        assert client._probed_embeddings_model_name == "embed-model"
        await client.destroy()

    @pytest.mark.asyncio
    async def test_failed_probe_keeps_client_connected(
        self, cfg_isolation, kcpp_server
    ):
        kcpp_server["embeddings_error"] = httpx.ReadTimeout("slow")
        client = _make_client("kcpp_probe_fail", "http://fake:5001")

        assert await client.get_model_name() == "text-model"
        await client._embeddings_probe_task

        assert client.embeddings_model_name is None
        assert client._probed_embeddings_model_name is None

    @pytest.mark.asyncio
    async def test_probe_result_is_reused_while_suggestion_is_unseen(
        self, cfg_isolation, kcpp_server
    ):
        client = _make_client("kcpp_probe_reuse", "http://fake:5001")

        for _ in range(2):
            await client.get_model_name()
            await client._embeddings_probe_task

        embedding_calls = [p for p in kcpp_server["requests"] if "embeddings" in p]
        assert embedding_calls == ["/api/v1/api/extra/embeddings"]

    @pytest.mark.asyncio
    async def test_reset_forgets_probed_name(self, cfg_isolation, kcpp_server):
        client = _make_client("kcpp_probe_reset", "http://fake:5001")
        await client.get_model_name()
        await client._embeddings_probe_task
        assert client._probed_embeddings_model_name == "embed-model"

        await client.reset_embeddings()

        assert client._probed_embeddings_model_name is None
        assert client.embeddings_model_name is None

    @pytest.mark.asyncio
    async def test_disable_cancels_pending_probe(self, cfg_isolation, kcpp_server):
        kcpp_server["release"] = asyncio.Event()
        client = _make_client("kcpp_probe_disable", "http://fake:5001")
        suggestions = []

        async def on_available(emission):
            suggestions.append(emission)

        signal = koboldcpp_module.async_signals.get("client.embeddings_available")
        signal.connect(on_available)
        try:
            await client.get_model_name()
            probe = client._embeddings_probe_task
            await client.disable()
            kcpp_server["release"].set()
            await asyncio.sleep(0)
        finally:
            signal.disconnect(on_available)

        assert probe.cancelled()
        assert suggestions == []


class TestAbortGeneration:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_url", ["http://fake:5001/v1", "http://fake:5001/api/v1"]
    )
    async def test_abort_reaches_server_in_both_modes(
        self, cfg_isolation, monkeypatch, api_url
    ):
        config_state.CONFIG.clients["kcpp_abort"] = koboldcpp_module.ClientConfig(
            type="koboldcpp", name="kcpp_abort", api_url=api_url, api_key="secret"
        )
        client = KoboldCppClient(name="kcpp_abort")
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(
                (request.method, request.url.path, request.headers.get("authorization"))
            )
            return httpx.Response(200, json={"success": True})

        native_client = httpx.AsyncClient

        class _MockClient(native_client):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(koboldcpp_module.httpx, "AsyncClient", _MockClient)

        await client.abort_generation()

        assert seen == [("POST", "/api/extra/abort", "Bearer secret")]


class TestResponseLengthCap:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_url, cap_key",
        [
            ("http://fake:5001/api/v1", "max_length"),
            ("http://fake:5001/v1", "max_tokens"),
        ],
    )
    @pytest.mark.parametrize(
        "mode, capped",
        [
            ("cap_tokens_and_instructions", True),
            ("instructions", False),
            ("uncapped", False),
        ],
    )
    async def test_cap_follows_response_length_mode(
        self, cfg_isolation, preset_isolation, api_url, cap_key, mode, capped
    ):
        name = "kcpp_cap"
        config_state.CONFIG.clients[name] = koboldcpp_module.ClientConfig(
            type="koboldcpp", name=name, api_url=api_url, enforce_response_length=mode
        )
        client = _OfflineKoboldCppClient(name=name, response="answer")
        client.connected = True
        client.remote_model_name = "some-model"

        with _active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                await client.send_prompt("hi", kind="narrate")

        sent = client.generate_parameters
        assert (cap_key in sent) is capped
        assert "max_tokens" not in sent or cap_key == "max_tokens"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["cap_tokens_and_instructions", "instructions"])
    async def test_united_attaches_length_instruction(
        self, cfg_isolation, preset_isolation, monkeypatch, mode
    ):
        """United mode used to read the cap under max_length before the
        reroute, found none and attached no length instruction."""
        name = "kcpp_instruct"
        config_state.CONFIG.clients[name] = koboldcpp_module.ClientConfig(
            type="koboldcpp",
            name=name,
            api_url="http://fake:5001/api/v1",
            enforce_response_length=mode,
        )
        client = _OfflineKoboldCppClient(name=name, response="answer")
        client.connected = True
        client.remote_model_name = "some-model"
        attached = []
        attach = client.attach_response_length_instruction

        def _spy(prompt, response_length):
            result = attach(prompt, response_length)
            attached.append((response_length, result[len(prompt) :].strip()))
            return result

        monkeypatch.setattr(client, "attach_response_length_instruction", _spy)

        with _active_agent_context():
            with ClientContext(requires_active_scene=False):
                set_client_context_attribute("requires_active_scene", False)
                await client.send_prompt("hi", kind="narrate")

        [(response_length, instruction)] = attached
        assert response_length > 0
        assert instruction
        assert instruction in client.generate_prompt


class TestUncappedLimit:
    @pytest.fixture
    def tokencount(self, monkeypatch):
        state = {"value": 900, "available": True, "counted": []}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/extra/tokencount":
                if not state["available"]:
                    return httpx.Response(404)
                state["counted"].append(json.loads(request.content)["prompt"])
                return httpx.Response(200, json={"value": state["value"], "ids": []})
            return httpx.Response(
                200, text='data: {"choices": [{"text": "ok"}]}\n\ndata: [DONE]\n\n'
            )

        native_client = httpx.AsyncClient

        class _MockClient(native_client):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(koboldcpp_module.httpx, "AsyncClient", _MockClient)
        return state

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_url, limit_key",
        [
            ("http://fake:5001/api/v1", "max_length"),
            ("http://fake:5001/v1", "max_tokens"),
        ],
    )
    @pytest.mark.parametrize("value", [900, 7300])
    async def test_uncapped_request_fills_counted_context(
        self, cfg_isolation, monkeypatch, tokencount, api_url, limit_key, value
    ):
        tokencount["value"] = value
        config_state.CONFIG.clients["kcpp_fill"] = koboldcpp_module.ClientConfig(
            type="koboldcpp", name="kcpp_fill", api_url=api_url, max_token_length=8192
        )
        client = KoboldCppClient(name="kcpp_fill")
        client.new_request()
        sent = {}
        monkeypatch.setattr(
            client,
            "_generate_kcpp_stream",
            lambda prompt, parameters, kind: sent.update(parameters) or "ok",
        )

        parameters = {}
        await client.generate("prompt", parameters, "narrate")

        assert parameters[limit_key] == 8192 - value

    @pytest.mark.asyncio
    async def test_capped_request_keeps_its_limit(
        self, cfg_isolation, monkeypatch, tokencount
    ):
        client = _make_client("kcpp_capped", "http://fake:5001/api/v1")
        monkeypatch.setattr(
            client, "_generate_kcpp_stream", lambda prompt, parameters, kind: "ok"
        )
        parameters = {"max_length": 300}

        await client.generate("prompt", parameters, "narrate")

        assert parameters["max_length"] == 300

    @pytest.mark.asyncio
    async def test_uncapped_request_counts_the_prompt_once(
        self, cfg_isolation, tokencount
    ):
        tokencount["value"] = 900
        client = _make_client("kcpp_once", "http://fake:5001/v1")
        client.new_request()
        client._returned_prompt_tokens = None
        parameters = {}

        await client.generate("prompt", parameters, "narrate")

        # the prompt for the limit, then the response for the statistics
        assert tokencount["counted"] == ["prompt", "ok"]
        assert client._returned_prompt_tokens == 900
        assert parameters["max_tokens"] == client.max_token_length - 900

    @pytest.mark.asyncio
    async def test_capped_request_counts_the_prompt_once(
        self, cfg_isolation, tokencount
    ):
        tokencount["value"] = 900
        client = _make_client("kcpp_capped_once", "http://fake:5001/v1")
        client.new_request()
        client._returned_prompt_tokens = None
        parameters = {"max_tokens": 300}

        await client.generate("prompt", parameters, "narrate")

        # no limit to fill, so the prompt is counted for the statistics only
        assert tokencount["counted"] == ["prompt", "ok"]
        assert client._returned_prompt_tokens == 900
        assert parameters["max_tokens"] == 300

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_url, limit_key",
        [
            ("http://fake:5001/api/v1", "max_length"),
            ("http://fake:5001/v1", "max_tokens"),
        ],
    )
    async def test_estimate_without_room_sends_no_limit(
        self, cfg_isolation, monkeypatch, tokencount, api_url, limit_key
    ):
        """A server without tokencount (KoboldAI United) falls back to the
        estimate; when it leaves no room the request goes without a limit."""
        tokencount["available"] = False
        config_state.CONFIG.clients["kcpp_est"] = koboldcpp_module.ClientConfig(
            type="koboldcpp", name="kcpp_est", api_url=api_url, max_token_length=4096
        )
        client = KoboldCppClient(name="kcpp_est")
        client.new_request()
        monkeypatch.setattr(
            client, "_generate_kcpp_stream", lambda prompt, parameters, kind: "ok"
        )
        prompt = "hello " * 4000
        assert client.count_tokens(prompt) * PROMPT_TOKEN_SAFETY_FACTOR > 4096

        parameters = {}
        with capture_logs() as logs:
            await client.generate(prompt, parameters, "narrate")

        assert limit_key not in parameters
        assert any("without a limit" in e["event"] for e in logs)

    @pytest.mark.asyncio
    async def test_estimate_with_room_sends_padded_limit(
        self, cfg_isolation, monkeypatch, tokencount
    ):
        tokencount["available"] = False
        config_state.CONFIG.clients["kcpp_est"] = koboldcpp_module.ClientConfig(
            type="koboldcpp",
            name="kcpp_est",
            api_url="http://fake:5001/api/v1",
            max_token_length=4096,
        )
        client = KoboldCppClient(name="kcpp_est")
        client.new_request()
        monkeypatch.setattr(
            client, "_generate_kcpp_stream", lambda prompt, parameters, kind: "ok"
        )
        prompt = "hello " * 100

        parameters = {}
        await client.generate(prompt, parameters, "narrate")

        assert parameters["max_length"] == 4096 - math.ceil(
            client.count_tokens(prompt.strip(" ")) * PROMPT_TOKEN_SAFETY_FACTOR
        )
