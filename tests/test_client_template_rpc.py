from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import talemate.server.config as server_config
from talemate.client.model_prompts import ModelPrompt
from talemate.server.config import ConfigPlugin


@pytest.fixture
def template_rpc(monkeypatch):
    handler = SimpleNamespace(queue_put=Mock(), scene=None)
    plugin = ConfigPlugin(handler)
    prompt = Mock(spec=ModelPrompt, return_value=("example", "chosen.jinja2"))
    prompt.create_user_override.return_value = "override"
    monkeypatch.setattr(server_config, "model_prompt", prompt)
    return plugin, handler.queue_put, prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [None, "template-request-568"])
async def test_set_template_echoes_request_identity(template_rpc, request_id):
    plugin, queued, prompt = template_rpc
    await plugin.handle_set_llm_template(
        {
            "request_id": request_id,
            "data": {
                "model": "test-model",
                "template_file": "ChatML.jinja2",
            },
        }
    )
    message = queued.call_args.args[0]
    assert message["action"] == "set_llm_template_complete"
    assert message["request_id"] == request_id
    assert message["data"]["template_file"] == "chosen.jinja2"


@pytest.mark.asyncio
@pytest.mark.parametrize("suggestion", [None, "ChatML.jinja2"])
async def test_determine_template_carries_identity_through_both_replies(
    template_rpc, suggestion
):
    plugin, queued, prompt = template_rpc
    prompt.query_hf_for_prompt_template_suggestion.return_value = suggestion
    await plugin.handle_determine_llm_template(
        {"data": {"model": "test-model"}, "request_id": "determine-568"}
    )
    messages = [call.args[0] for call in queued.call_args_list]
    expected = ["determine_llm_template_complete"]
    if suggestion:
        expected.insert(0, "set_llm_template_complete")
    assert [message["action"] for message in messages] == expected
    assert all(message["request_id"] == "determine-568" for message in messages)
    assert messages[-1]["data"]["template"] == suggestion


@pytest.mark.asyncio
async def test_template_error_uses_the_same_request_identity(template_rpc):
    plugin, queued, prompt = template_rpc
    prompt.create_user_override.side_effect = OSError("write failed")
    await plugin.handle(
        {
            "action": "set_llm_template",
            "request_id": "failed-template-568",
            "data": {"model": "test-model", "template_file": "ChatML.jinja2"},
        }
    )
    message = queued.call_args.args[0]
    assert message["action"] == "operation_done"
    assert message["request_id"] == "failed-template-568"
    assert "write failed" in message["error"]["message"]


@pytest.fixture
def rpc_client(monkeypatch):
    import talemate.config.state as config_state
    from talemate.client.base import ClientBase
    from talemate.client.model_prompts import model_prompt as real_model_prompt
    from talemate.config.schema import Client as ClientConfig

    class _Client(ClientBase):
        client_type = "stub"

    template = real_model_prompt.env.from_string(
        real_model_prompt.get_std_template_content("Gemma4.jinja2")
    )
    monkeypatch.setattr(
        real_model_prompt, "get_template", lambda name: (template, "std/Gemma4.jinja2")
    )

    def make(**config):
        cfg = config_state.CONFIG.model_copy(deep=True)
        cfg.clients["rpc"] = ClientConfig(type="stub", name="rpc", **config)
        monkeypatch.setattr(config_state, "CONFIG", cfg)
        client = _Client(name="rpc")
        monkeypatch.setattr(server_config, "get_client", lambda name: client)
        return client

    return make


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_template", [False, True])
@pytest.mark.parametrize(
    "config, expected_user, expected_model",
    [
        ({}, "{prompt}", "<|channel>thought\n<channel|>{LLM coercion}"),
        (
            {"double_coercion": "Stay in character."},
            "{prompt}",
            "<|channel>thought\n<channel|>Stay in character.\n\n{LLM coercion}",
        ),
        (
            {"reason_enabled": True, "reason_tokens": 1024},
            "{prompt}\nAfter thinking about it, start your answer with: {LLM coercion}",
            "",
        ),
        (
            {
                "reason_enabled": True,
                "reason_tokens": 1024,
                "reason_prefill": "<think>",
            },
            "{prompt}\nAfter thinking about it, start your answer with: {LLM coercion}",
            "<think>",
        ),
    ],
)
async def test_set_template_example_shows_what_the_client_sends(
    template_rpc, rpc_client, lock_template, config, expected_user, expected_model
):
    plugin, queued, prompt = template_rpc
    rpc_client(**config)

    await plugin.handle_set_llm_template(
        {
            "data": {
                "model": "test-model",
                "template_file": "Gemma4.jinja2",
                "client_name": "rpc",
                "lock_template": lock_template,
            },
        }
    )

    think = "<|think|>\n" if config.get("reason_enabled") else ""
    data = queued.call_args.args[0]["data"]
    assert data["prompt_template_example"] == (
        f"<|turn>system\n{think}{{sysmsg}}<turn|>\n"
        f"<|turn>user\n{expected_user}<turn|>\n"
        f"<|turn>model\n{expected_model}"
    )
    assert data["template_file"] == "std/Gemma4.jinja2"
    prompt.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client_name, lock_template, override_name",
    [
        ("rpc", False, "test-model"),
        ("rpc", True, "rpc__LOCK"),
        (None, True, "test-model"),
    ],
)
async def test_set_template_override_follows_the_lock_flag(
    template_rpc, rpc_client, client_name, lock_template, override_name
):
    plugin, queued, prompt = template_rpc
    rpc_client()

    await plugin.handle_set_llm_template(
        {
            "data": {
                "model": "test-model",
                "template_file": "Gemma4.jinja2",
                "client_name": client_name,
                "lock_template": lock_template,
            },
        }
    )

    prompt.create_user_override.assert_called_once_with("Gemma4.jinja2", override_name)


@pytest.mark.asyncio
async def test_set_template_without_a_known_client_renders_the_plain_template(
    template_rpc, monkeypatch
):
    plugin, queued, prompt = template_rpc

    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(server_config, "get_client", missing)

    await plugin.handle_set_llm_template(
        {
            "data": {
                "model": "test-model",
                "template_file": "Gemma4.jinja2",
                "client_name": "gone",
            },
        }
    )

    assert prompt.call_args.args[:3] == (
        "test-model",
        "{sysmsg}",
        "{prompt}<|BOT|>{LLM coercion}",
    )
    assert queued.call_args.args[0]["data"]["prompt_template_example"] == "example"
