"""A client whose API URL is blank must never build an OpenAI SDK client.

`AsyncOpenAI(base_url=None)` falls back to `https://api.openai.com/v1/`, so a
vision-enabled llama.cpp client with no URL sent the image bytes to OpenAI.
"""

from __future__ import annotations

import pytest

import talemate.config.state as config_state
from talemate.client import base as base_module
from talemate.client.koboldcpp import KoboldCppClient
from talemate.client.llamacpp import LlamaCppClient
from talemate.client.lmstudio import LMStudioClient
from talemate.client.openai_compat import OpenAICompatibleClient
from talemate.client.textgenwebui import TextGeneratorWebuiClient
from talemate.config.schema import resolve_config_cls

CLIENTS = [
    ("llamacpp", LlamaCppClient),
    ("koboldcpp", KoboldCppClient),
    ("textgenwebui", TextGeneratorWebuiClient),
    ("lmstudio", LMStudioClient),
    ("openai_compat", OpenAICompatibleClient),
]

BLANK_URLS = ["", None, "   "]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """A blank URL is a local misconfiguration — nothing in this module may
    reach a third party to diagnose it."""

    def _fail(model_name: str):
        raise AssertionError(f"queried HuggingFace for {model_name!r}")

    monkeypatch.setattr(
        base_module.model_prompt, "query_hf_for_prompt_template_suggestion", _fail
    )


def _client(client_type: str, cls, api_url: str | None, name: str = "blank"):
    config_state.CONFIG.clients[name] = resolve_config_cls(cls)(
        type=client_type, name=name, api_url=api_url, api_key="sk-1234"
    )
    client = cls(name=name)
    # the real emit_status would hit HuggingFace to guess a prompt template
    client.auto_determine_prompt_template = False
    return client


class TestMakeClientRefusesABlankUrl:
    @pytest.mark.parametrize("client_type,cls", CLIENTS)
    @pytest.mark.parametrize("api_url", BLANK_URLS)
    def test_make_client_raises(self, cfg_isolation, client_type, cls, api_url):
        client = _client(client_type, cls, api_url)

        with pytest.raises(ValueError):
            client.make_client()

    @pytest.mark.parametrize("client_type,cls", CLIENTS)
    def test_make_client_still_works_with_a_url(self, cfg_isolation, client_type, cls):
        client = _client(client_type, cls, "http://localhost:8080")

        assert "api.openai.com" not in str(client.make_client().base_url)


class TestBlankUrlMarksTheClientDisconnected:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("client_type,cls", CLIENTS)
    async def test_status_reports_an_error(self, cfg_isolation, client_type, cls):
        client = _client(client_type, cls, "")

        await client.status()

        assert client.connected is False
        assert client.current_status == "error"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("client_type,cls", CLIENTS)
    async def test_an_established_client_flips_on_the_second_sweep(
        self, cfg_isolation, client_type, cls
    ):
        client = _client(client_type, cls, "")
        client.connected = True
        client.remote_model_name = "some-model.gguf"

        await client.status()

        assert client.connected is True
        assert client.current_status == "idle"

        await client.status()

        assert client.connected is False
        assert client.current_status == "error"


class TestVisionAnalysisRefusesABlankUrl:
    @pytest.mark.asyncio
    async def test_analyze_image_raises_before_sending_anything(self, cfg_isolation):
        client = _client("llamacpp", LlamaCppClient, "")

        with pytest.raises(ValueError):
            await client.analyze_image(b"not-an-image", "describe this")
