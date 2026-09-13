import asyncio
from types import SimpleNamespace

import pytest
import yaml

import talemate.config.state as config_state
from talemate.agents.context import ActiveAgent
from talemate.client.base import ClientBase, DEFAULT_REASONING_PATTERN
from talemate.client.context import ClientContext
from talemate.client.model_prompts import model_prompt
from talemate.config.schema import Client as ClientConfig


class PatternClient(ClientBase):
    client_type = "llamacpp"

    @property
    def supported_parameters(self):
        return ["temperature", "max_tokens"]

    async def status(self):
        self.connected = True

    async def generate(self, prompt, parameters, kind):
        raise AssertionError("The test must provide a controlled provider response")


@pytest.fixture
def pattern_client(monkeypatch, tmp_path):
    cfg = config_state.CONFIG.model_copy(deep=True)
    cfg.clients = {
        "patterns": ClientConfig(
            name="patterns",
            type="llamacpp",
            reason_enabled=True,
            reason_tokens=1024,
            reason_failure_behavior="fail",
        )
    }
    monkeypatch.setattr(config_state, "CONFIG", cfg)
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")
    templates = {
        name: model_prompt.env.from_string(
            model_prompt.get_std_template_content(f"{name}.jinja2")
        )
        for name in ("Qwen3.5", "Gemma4", "ChatML")
    }
    monkeypatch.setattr(
        model_prompt,
        "get_template",
        lambda name: (templates[name], f"std/{name}.jinja2"),
    )
    client = PatternClient(name="patterns")
    client.remote_model_name = "Qwen3.5"
    client.connected = True
    return client


def configured(client):
    return (
        client.client_config.reason_response_pattern,
        client.client_config.reason_validation_pattern,
    )


@pytest.mark.parametrize("custom", [False, True])
def test_model_switch_and_unrelated_save_preserve_overrides(pattern_client, custom):
    client = pattern_client
    if custom:
        client.client_config.reason_response_pattern = "CUSTOM_END"
        client.client_config.reason_validation_pattern = "CUSTOM_START"
    original = configured(client)
    expected = {
        "Qwen3.5": (DEFAULT_REASONING_PATTERN, "<think>"),
        "Gemma4": (r".*?<channel\|>", r"<\|channel>thought"),
        "ChatML": (DEFAULT_REASONING_PATTERN, None),
    }
    for model in ("Qwen3.5", "Gemma4", "ChatML", "Qwen3.5"):
        client.remote_model_name = model
        client.prompt_template("system", "scene prompt")
        client.emit_status()
        assert client.effective_reasoning_patterns() == (
            original if custom else expected[model]
        )
        assert configured(client) == original
        client.client_config.max_token_length += 1
        config_state.save_config()
        disk = yaml.safe_load(config_state.CONFIG_FILE.read_text())["clients"][
            "patterns"
        ]
        assert (
            disk.get("reason_response_pattern"),
            disk.get("reason_validation_pattern"),
        ) == original
        config_state.CONFIG = config_state._load_config()
        assert configured(client) == original
    client.client_config.reason_response_pattern = ""
    client.client_config.reason_validation_pattern = ""
    client.remote_model_name = "Gemma4"
    assert client.effective_reasoning_patterns() == expected["Gemma4"]
    assert configured(client) == ("", "")


def test_explicit_fields_override_independently_and_clear_to_current_template(
    pattern_client,
):
    client = pattern_client
    client.remote_model_name = "Gemma4"
    client.client_config.reason_response_pattern = "CUSTOM_END"
    assert client.effective_reasoning_patterns() == (
        "CUSTOM_END",
        r"<\|channel>thought",
    )
    client.client_config.reason_response_pattern = ""
    client.client_config.reason_validation_pattern = "CUSTOM_START"
    assert client.effective_reasoning_patterns() == (r".*?<channel\|>", "CUSTOM_START")
    client.client_config.reason_validation_pattern = ""
    assert client.strip_reasoning("<|channel>thoughtsecret<channel|>answer") == (
        "answer",
        "<|channel>thoughtsecret<channel|>",
    )
    client.remote_model_name = "Qwen3.5"
    assert client.strip_reasoning("<think>secret</think>answer") == (
        "answer",
        "<think>secret</think>",
    )


async def send(client, text):
    agent = SimpleNamespace(
        agent_type="narrator",
        verbose_name="Narrator",
        allow_repetition_break=lambda *args, **kwargs: False,
        inject_prompt_paramters=lambda *args: None,
    )

    def narrate():
        pass

    with ActiveAgent(agent, narrate), ClientContext(requires_active_scene=False):
        return await client.send_prompt(text)


@pytest.mark.asyncio
async def test_overlapping_model_requests_keep_their_rendered_patterns(
    pattern_client, monkeypatch
):
    client = pattern_client
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def generate(prompt, parameters, kind):
        if "first request" in prompt:
            calls.append("Qwen3.5")
            started.set()
            await asyncio.wait_for(release.wait(), 5)
            return "<think>first secret</think>first answer"
        calls.append("Gemma4")
        return "<|channel>thoughtsecond secret<channel|>second answer"

    monkeypatch.setattr(client, "generate", generate)
    first = asyncio.create_task(send(client, "first request"))
    try:
        await asyncio.wait_for(started.wait(), 5)
        client.remote_model_name = "Gemma4"
        assert (
            await asyncio.wait_for(send(client, "second request"), 5) == "second answer"
        )
        client.client_config.reason_response_pattern = "new explicit override"
        client.client_config.reason_validation_pattern = "new explicit start"
        release.set()
        assert await asyncio.wait_for(first, 5) == "first answer"
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
    assert calls == ["Qwen3.5", "Gemma4"]
    assert configured(client) == ("new explicit override", "new explicit start")
