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
