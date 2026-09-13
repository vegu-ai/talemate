from collections import deque
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

import talemate.agents.help.storage as storage
import talemate.config.state as config_state
import talemate.instance as instance
from talemate.agents.director import DirectorAgent
from talemate.agents.help import HelpAgent
from talemate.client import openrouter
from talemate.config.schema import Config


@pytest.fixture
def chat_transport(tmp_path, monkeypatch):
    config = Config()
    config.openrouter.api_key = "test-placeholder"
    config.clients["test"] = openrouter.ClientConfig(
        type="openrouter",
        name="test",
        model="synthetic-model",
        max_token_length=32768,
        reason_enabled=True,
    )
    monkeypatch.setattr(config_state, "CONFIG", config)
    monkeypatch.setattr(storage, "HELP_CHATS_DIR", tmp_path)
    monkeypatch.setattr(storage, "HELP_CHATS_FILE", tmp_path / "help.json")
    monkeypatch.setattr(openrouter, "fetch_available_models", AsyncMock())
    monkeypatch.setattr(openrouter, "fetch_available_providers", AsyncMock())
    client = openrouter.OpenRouterClient(name="test")
    agent = HelpAgent(client=client)
    instance.AGENTS["help"] = agent
    instance.AGENTS["director"] = DirectorAgent(client=client)
    agent.actions["chat"].config["doc_lookup_iterations"].value = 1
    requests = []
    replies = deque()

    class HTTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            assert method == "POST" and url.endswith("/chat/completions")
            requests.append(deepcopy(kwargs["json"]))

            class Response:
                status_code = 200

                async def aiter_text(self):
                    yield (
                        "data: "
                        + json.dumps(
                            {"choices": [{"delta": {"content": replies.popleft()}}]}
                        )
                        + "\n\n"
                    )

            yield Response()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", HTTP)
    chat = agent.chat_create()
    chat.title = "Synthetic cache regression"
    return agent, chat, requests, replies


def stable_prefix(request):
    assert [m["role"] for m in request["messages"]] == ["system", "user"]
    text = request["messages"][1]["content"]
    return text.split("## Chat history - this is what you respond to")[0]


async def test_user_turns_keep_tools_before_changing_view(chat_transport):
    agent, chat, requests, replies = chat_transport
    replies.extend(["First answer.", "Second answer."])
    await agent.chat_send(
        chat.id,
        "Explain presets.",
        ux_snapshot={
            "active_tab": "settings",
            "app_settings_modal": {"page": "clients", "dirty": False},
        },
    )
    await agent.chat_send(
        chat.id,
        "Explain action presets.",
        ux_snapshot={
            "active_tab": "settings",
            "app_settings_modal": {"page": "presets", "dirty": True},
        },
    )
    assert len(requests) == 2
    assert requests[0]["messages"][0] == requests[1]["messages"][0]
    assert stable_prefix(requests[0]) == stable_prefix(requests[1])
    prefix = stable_prefix(requests[1])
    assert '"function": "read_app_config"' in prefix
    assert "page: clients" not in prefix and "page: presets" not in prefix
    assert "dirty: true" in requests[1]["messages"][1]["content"]
    assert "page: presets" in requests[1]["messages"][1]["content"]


async def test_final_tool_continuation_keeps_the_same_tool_prefix(chat_transport):
    agent, chat, requests, replies = chat_transport
    replies.extend(
        [
            '```json\n{"function":"read_app_config","arguments":{"section":"game","path":["general"],"fields":["auto_save"]}}\n```',
            "Auto-save is enabled.",
        ]
    )
    await agent.chat_send(
        chat.id,
        "Read whether auto-save is enabled.",
        ux_snapshot={"active_tab": "settings"},
    )
    assert len(requests) == 2
    assert stable_prefix(requests[0]) == stable_prefix(requests[1])
    final = requests[1]["messages"][1]["content"]
    assert '"auto_save": true' in final
    assert "Do NOT call any functions." in final
    assert '"function": "read_app_config"' in final


async def test_permission_and_config_changes_remain_current(chat_transport):
    agent, chat, requests, replies = chat_transport
    call = '```json\n{"function":"read_app_config","arguments":{"section":"game","path":["general"],"fields":["auto_save"]}}\n```'
    replies.extend([call, "Enabled.", call, "Disabled."])
    await agent.chat_send(chat.id, "Read auto-save.")
    config_state.CONFIG.game.general.auto_save = False
    agent.actions["permissions"].config["allow_settings_changes"].value = True
    await agent.chat_send(chat.id, "Read it again.")
    assert len(requests) == 4
    assert '"function": "update_inference_presets"' not in stable_prefix(requests[0])
    assert '"function": "update_inference_presets"' in stable_prefix(requests[2])
    assert '"auto_save": false' in requests[3]["messages"][1]["content"]
    assert '"auto_save": true' in requests[1]["messages"][1]["content"]
    assert stable_prefix(requests[2]) == stable_prefix(requests[3])
