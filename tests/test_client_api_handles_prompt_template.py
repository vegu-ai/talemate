"""Unit tests for the `api_handles_prompt_template` option on the clients
that expose it (issues #65 and #67): TabbyAPI, OpenAI Compatible, Ollama,
Text-Generation-WebUI and llama.cpp.

Covers the pure-Python logic: the shared `ApiHandlesPromptTemplateMixin`
`prompt_template()` bypass, the shared `chat_messages_for_coercion()` message
assembly including coercion splitting, the transport payloads (mocked HTTP),
and the coercion pre-fill echo stripping. Live generation against real
backends is exercised separately.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import talemate.config.state as config_state
from talemate.client import llamacpp as llamacpp_module
from talemate.client import ollama as ollama_module
from talemate.client import openai_compat as openai_compat_module
from talemate.client import tabbyapi as tabbyapi_module
from talemate.client import textgenwebui as textgenwebui_module
from talemate.client.llamacpp import LlamaCppClient
from talemate.client.ollama import OllamaClient
from talemate.client.openai_compat import OpenAICompatibleClient
from talemate.client.tabbyapi import TabbyAPIClient
from talemate.client.textgenwebui import TextGeneratorWebuiClient
from talemate.context import ActiveScene
from talemate.exceptions import GenerationProcessingError


@pytest.fixture
def cfg_isolation():
    """Snapshot/restore the client config section these tests mutate."""
    saved_clients = dict(config_state.CONFIG.clients)
    yield
    config_state.CONFIG.clients.clear()
    config_state.CONFIG.clients.update(saved_clients)


def _register_llamacpp(name: str, **kwargs):
    cfg = llamacpp_module.ClientConfig(
        type="llamacpp", name=name, api_url="http://fake:8080", **kwargs
    )
    config_state.CONFIG.clients[name] = cfg
    return cfg


def _register_textgenwebui(name: str, **kwargs):
    cfg = textgenwebui_module.ClientConfig(
        type="textgenwebui", name=name, api_url="http://fake:5000", **kwargs
    )
    config_state.CONFIG.clients[name] = cfg
    return cfg


def _register_tabbyapi(name: str, **kwargs):
    cfg = tabbyapi_module.ClientConfig(
        type="tabbyapi", name=name, api_url="http://fake:5000/v1", **kwargs
    )
    config_state.CONFIG.clients[name] = cfg
    return cfg


def _register_openai_compat(name: str, **kwargs):
    cfg = openai_compat_module.ClientConfig(
        type="openai_compat", name=name, api_url="http://fake:5000", **kwargs
    )
    config_state.CONFIG.clients[name] = cfg
    return cfg


def _register_ollama(name: str, **kwargs):
    cfg = ollama_module.ClientConfig(
        type="ollama", name=name, api_url="http://fake:11434", **kwargs
    )
    config_state.CONFIG.clients[name] = cfg
    return cfg


# ---------------------------------------------------------------------------
# prompt_template bypass
# ---------------------------------------------------------------------------


class TestPromptTemplateBypass:
    def test_llamacpp_flag_off_applies_local_template(self, cfg_isolation):
        _register_llamacpp("lcpp_off")
        client = LlamaCppClient(name="lcpp_off")
        # no model loaded -> local templating falls back to "sysmsg\nprompt",
        # which is still distinct from the raw prompt
        assert client.prompt_template("SYS", "PROMPT") == "SYS\nPROMPT"

    def test_llamacpp_flag_on_returns_raw_prompt(self, cfg_isolation):
        _register_llamacpp("lcpp_on", api_handles_prompt_template=True)
        client = LlamaCppClient(name="lcpp_on")
        assert client.prompt_template("SYS", "PROMPT<|BOT|>Certainly:") == (
            "PROMPT<|BOT|>Certainly:"
        )

    def test_textgenwebui_flag_off_applies_local_template(self, cfg_isolation):
        _register_textgenwebui("tgw_off")
        client = TextGeneratorWebuiClient(name="tgw_off")
        assert client.prompt_template("SYS", "PROMPT") == "SYS\nPROMPT"

    def test_textgenwebui_flag_on_returns_raw_prompt(self, cfg_isolation):
        _register_textgenwebui("tgw_on", api_handles_prompt_template=True)
        client = TextGeneratorWebuiClient(name="tgw_on")
        assert client.prompt_template("SYS", "PROMPT<|BOT|>Certainly:") == (
            "PROMPT<|BOT|>Certainly:"
        )

    def test_tabbyapi_flag_off_applies_local_template(self, cfg_isolation):
        _register_tabbyapi("tabby_off")
        client = TabbyAPIClient(name="tabby_off")
        assert client.prompt_template("SYS", "PROMPT") == "SYS\nPROMPT"

    def test_tabbyapi_flag_on_returns_raw_prompt(self, cfg_isolation):
        _register_tabbyapi("tabby_on", api_handles_prompt_template=True)
        client = TabbyAPIClient(name="tabby_on")
        assert client.prompt_template("SYS", "PROMPT<|BOT|>Certainly:") == (
            "PROMPT<|BOT|>Certainly:"
        )

    def test_openai_compat_flag_off_applies_local_template(self, cfg_isolation):
        _register_openai_compat("oaic_off")
        client = OpenAICompatibleClient(name="oaic_off")
        assert client.prompt_template("SYS", "PROMPT") == "SYS\nPROMPT"

    def test_openai_compat_flag_on_returns_raw_prompt(self, cfg_isolation):
        _register_openai_compat("oaic_on", api_handles_prompt_template=True)
        client = OpenAICompatibleClient(name="oaic_on")
        assert client.prompt_template("SYS", "PROMPT<|BOT|>Certainly:") == (
            "PROMPT<|BOT|>Certainly:"
        )

    def test_ollama_flag_off_applies_local_template(self, cfg_isolation):
        _register_ollama("oll_off")
        client = OllamaClient(name="oll_off")
        assert client.prompt_template("SYS", "PROMPT") == "SYS\nPROMPT"

    def test_ollama_flag_on_returns_raw_prompt(self, cfg_isolation):
        _register_ollama("oll_on", api_handles_prompt_template=True)
        client = OllamaClient(name="oll_on")
        assert client.prompt_template("SYS", "PROMPT<|BOT|>Certainly:") == (
            "PROMPT<|BOT|>Certainly:"
        )

    def test_coercion_stays_enabled_with_flag_on(self, cfg_isolation):
        _register_llamacpp("lcpp_coerce", api_handles_prompt_template=True)
        _register_textgenwebui("tgw_coerce", api_handles_prompt_template=True)
        assert LlamaCppClient(name="lcpp_coerce").can_be_coerced
        assert TextGeneratorWebuiClient(name="tgw_coerce").can_be_coerced

    def test_ollama_coercion_disabled_with_flag_on(self, cfg_isolation):
        # ollama sends a raw prompt (no chat pre-fill), so coercion is only
        # possible when talemate renders the prompt template itself
        _register_ollama("oll_coerce", api_handles_prompt_template=True)
        assert not OllamaClient(name="oll_coerce").can_be_coerced


# ---------------------------------------------------------------------------
# ClientBase.chat_messages_for_coercion
# ---------------------------------------------------------------------------


class TestChatMessagesForCoercion:
    def test_coercion_appends_assistant_prefill(self, cfg_isolation):
        _register_tabbyapi("tabby_msgs", api_handles_prompt_template=True)
        client = TabbyAPIClient(name="tabby_msgs")

        messages, coercion = client.chat_messages_for_coercion(
            "Describe the room.<|BOT|>The room is ", "narrate"
        )

        assert [m["role"] for m in messages] == ["system", "user", "assistant"]
        assert messages[1]["content"] == "Describe the room."
        assert messages[2]["content"] == "The room is"
        assert coercion == "The room is"

    def test_no_coercion_returns_system_and_user_only(self, cfg_isolation):
        _register_openai_compat("oaic_msgs", api_handles_prompt_template=True)
        client = OpenAICompatibleClient(name="oaic_msgs")

        messages, coercion = client.chat_messages_for_coercion(
            "Describe the room.", "narrate"
        )

        assert [m["role"] for m in messages] == ["system", "user"]
        assert messages[1]["content"] == "Describe the room."
        assert coercion is None

    def test_double_coercion_prepended_to_prefill(self, cfg_isolation):
        _register_tabbyapi(
            "tabby_dc",
            api_handles_prompt_template=True,
            double_coercion="Sure thing!",
        )
        client = TabbyAPIClient(name="tabby_dc")

        messages, coercion = client.chat_messages_for_coercion(
            "Describe the room.<|BOT|>The room is", "narrate"
        )

        assert coercion == "Sure thing!\n\nThe room is"
        assert messages[2]["content"] == coercion


# ---------------------------------------------------------------------------
# llama.cpp /apply-template
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int = 200, data: dict | None = None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient capturing POST calls."""

    calls: list[dict] = []
    response: _FakeResponse = _FakeResponse()

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeAsyncClient.response


@pytest.fixture
def fake_httpx(monkeypatch):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(200, {"prompt": "TEMPLATED"})
    monkeypatch.setattr(llamacpp_module.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


class TestLlamaCppApplyRemoteTemplate:
    @pytest.mark.asyncio
    async def test_posts_messages_and_returns_templated_prompt(
        self, cfg_isolation, fake_httpx
    ):
        _register_llamacpp("lcpp_tpl", api_handles_prompt_template=True)
        client = LlamaCppClient(name="lcpp_tpl")

        result = await client.apply_remote_template(
            "Describe the room.<|BOT|>The room is", "narrate"
        )

        assert result == "TEMPLATED"
        assert len(fake_httpx.calls) == 1
        call = fake_httpx.calls[0]
        assert call["url"] == "http://fake:8080/apply-template"
        messages = call["json"]["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant"]
        assert messages[1]["content"] == "Describe the room."
        assert messages[2]["content"] == "The room is"

    @pytest.mark.asyncio
    async def test_no_coercion_omits_assistant_message(self, cfg_isolation, fake_httpx):
        _register_llamacpp("lcpp_tpl2", api_handles_prompt_template=True)
        client = LlamaCppClient(name="lcpp_tpl2")

        await client.apply_remote_template("Describe the room.", "narrate")

        messages = fake_httpx.calls[0]["json"]["messages"]
        assert [m["role"] for m in messages] == ["system", "user"]

    @pytest.mark.asyncio
    async def test_thinking_disabled_when_reasoning_off(
        self, cfg_isolation, fake_httpx
    ):
        _register_llamacpp("lcpp_nothink", api_handles_prompt_template=True)
        client = LlamaCppClient(name="lcpp_nothink")

        await client.apply_remote_template("Describe the room.", "narrate")

        payload = fake_httpx.calls[0]["json"]
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}

    @pytest.mark.asyncio
    async def test_thinking_left_to_template_when_reasoning_on(
        self, cfg_isolation, fake_httpx
    ):
        _register_llamacpp(
            "lcpp_think", api_handles_prompt_template=True, reason_enabled=True
        )
        client = LlamaCppClient(name="lcpp_think")

        await client.apply_remote_template("Describe the room.", "narrate")

        payload = fake_httpx.calls[0]["json"]
        assert "chat_template_kwargs" not in payload

    @pytest.mark.asyncio
    async def test_error_status_raises(self, cfg_isolation, fake_httpx):
        _register_llamacpp("lcpp_tpl3", api_handles_prompt_template=True)
        client = LlamaCppClient(name="lcpp_tpl3")
        fake_httpx.response = _FakeResponse(500)

        with pytest.raises(GenerationProcessingError):
            await client.apply_remote_template("Describe the room.", "narrate")


# ---------------------------------------------------------------------------
# textgenwebui chat/completions
# ---------------------------------------------------------------------------


class _FakeSSEEvent:
    def __init__(self, data: str):
        self.data = data


class _FakeSSEClient:
    """Stand-in for sseclient.SSEClient yielding canned chat chunks."""

    chunks: list[str] = []

    def __init__(self, response):
        pass

    def events(self):
        for chunk in self.chunks:
            yield _FakeSSEEvent(chunk)


def _chat_chunk(content: str) -> str:
    return json.dumps({"choices": [{"delta": {"content": content}}]})


@pytest.fixture
def fake_tgw_transport(monkeypatch):
    """Mocks requests.post + sseclient.SSEClient in the textgenwebui module."""
    calls = []

    class _FakeStreamResponse:
        def raise_for_status(self):
            pass

    def _fake_post(url, json=None, timeout=None, headers=None, stream=False):
        calls.append({"url": url, "json": json})
        return _FakeStreamResponse()

    monkeypatch.setattr(textgenwebui_module.requests, "post", _fake_post)
    monkeypatch.setattr(textgenwebui_module.sseclient, "SSEClient", _FakeSSEClient)
    return calls


class TestTextGenWebuiChatGenerate:
    def test_coerced_generation_uses_continue_and_strips_prefill(
        self, cfg_isolation, fake_tgw_transport
    ):
        _register_textgenwebui("tgw_chat", api_handles_prompt_template=True)
        client = TextGeneratorWebuiClient(name="tgw_chat")

        _FakeSSEClient.chunks = [
            _chat_chunk("The room is"),
            _chat_chunk(" dark and quiet."),
            "[DONE]",
        ]

        messages = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "Describe the room."},
            {"role": "assistant", "content": "The room is"},
        ]
        response = client._generate_chat(messages, "The room is", {"temperature": 0.7})

        assert response == " dark and quiet."

        call = fake_tgw_transport[0]
        assert call["url"] == "http://fake:5000/v1/chat/completions"
        payload = call["json"]
        assert payload["mode"] == "instruct"
        assert payload["continue_"] is True
        assert payload["stream"] is True
        messages = payload["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant"]
        assert messages[0]["content"] == "SYS"
        assert messages[1]["content"] == "Describe the room."
        assert messages[2]["content"] == "The room is"

    def test_reasoning_content_captured_separately(
        self, cfg_isolation, fake_tgw_transport
    ):
        _register_textgenwebui("tgw_reason", api_handles_prompt_template=True)
        client = TextGeneratorWebuiClient(name="tgw_reason")

        _FakeSSEClient.chunks = [
            json.dumps(
                {"choices": [{"delta": {"reasoning_content": "Thinking about "}}]}
            ),
            json.dumps({"choices": [{"delta": {"reasoning_content": "the room."}}]}),
            _chat_chunk("The room is dark."),
            "[DONE]",
        ]

        messages = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "Describe the room."},
        ]
        response = client._generate_chat(messages, None, {"temperature": 0.7})

        assert response == "The room is dark."
        assert client._reasoning_response == "Thinking about the room."

    def test_requires_reasoning_pattern_follows_flag(self, cfg_isolation):
        _register_textgenwebui("tgw_rp_on", api_handles_prompt_template=True)
        _register_textgenwebui("tgw_rp_off")
        assert not TextGeneratorWebuiClient(name="tgw_rp_on").requires_reasoning_pattern
        assert TextGeneratorWebuiClient(name="tgw_rp_off").requires_reasoning_pattern

    def test_uncoerced_generation_has_no_continue(
        self, cfg_isolation, fake_tgw_transport
    ):
        _register_textgenwebui("tgw_chat2", api_handles_prompt_template=True)
        client = TextGeneratorWebuiClient(name="tgw_chat2")

        _FakeSSEClient.chunks = [
            _chat_chunk("The room is dark."),
            "[DONE]",
        ]

        messages = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "Describe the room."},
        ]
        response = client._generate_chat(messages, None, {"temperature": 0.7})

        assert response == "The room is dark."

        payload = fake_tgw_transport[0]["json"]
        assert "continue_" not in payload
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]

    @pytest.mark.asyncio
    async def test_generate_resolves_personas_across_executor_boundary(
        self, cfg_isolation, fake_tgw_transport
    ):
        """Persona instructions come from the active_scene contextvar, which
        run_in_executor does not propagate - generate() must resolve the
        system message on the event loop before dispatching to the thread."""
        _register_textgenwebui("tgw_persona", api_handles_prompt_template=True)
        client = TextGeneratorWebuiClient(name="tgw_persona")

        _FakeSSEClient.chunks = [_chat_chunk("The room is dark."), "[DONE]"]

        persona = SimpleNamespace(
            formatted=lambda field, scene, agent_type: "PERSONA INSTRUCTIONS"
        )
        scene = SimpleNamespace(agent_personas={"narrator": persona})

        with ActiveScene(scene):
            await client.generate("Describe the room.", {"temperature": 0.7}, "narrate")

        system_message = fake_tgw_transport[0]["json"]["messages"][0]["content"]
        assert "PERSONA INSTRUCTIONS" in system_message
