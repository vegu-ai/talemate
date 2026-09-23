import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from conftest import MockScene, bootstrap_engine
from talemate.agents.help import settings as help_settings
from talemate.agents.visual.backends import comfyui
from talemate.config import get_config
from talemate.config.schema import Config
import talemate.config.state as config_state
from talemate.context import ActiveScene
import talemate.instance as instance
from talemate.server.config import ConfigPlugin
from talemate.server.websocket_server import WebsocketHandler
import talemate.emit.async_signals as async_signals


@pytest.fixture
def apply_env(monkeypatch, isolate_signals, tmp_path):
    monkeypatch.setattr(config_state, "CONFIG", Config())
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")
    config_state.PENDING_APPLY.clear()
    bootstrap_engine()
    isolate_signals("config.changed", "config.changed.follow")
    monkeypatch.setattr(instance, "ensure_agent_llm_client", AsyncMock())
    for agent in instance.AGENTS.values():
        monkeypatch.setattr(agent, "emit_status", AsyncMock())
    handler = Mock()
    handler.scene = None

    async def broadcast(config):
        await WebsocketHandler.on_config_changed(handler, config)

    async_signals.get("config.changed").connect(broadcast)
    return ConfigPlugin(handler)


async def save_setting(plugin, via, agent_type, action, setting, value):
    if via == "help":
        return await help_settings.update_agent_setting(
            agent_type, action, setting, value
        )
    data = get_config().model_dump()
    data["agents"][agent_type]["actions"][action]["config"][setting]["value"] = value
    plugin.websocket_handler.queue_put.reset_mock()
    await plugin.handle_save({"config": data, "request_id": "retry-test"})
    return [call.args[0] for call in plugin.websocket_handler.queue_put.call_args_list]


def assert_save_failed(result, via):
    if via == "help":
        assert "applying it to the running agent failed" in result
        assert "Open Settings and press Save to retry" in result
        assert "Restart Talemate" not in result
    else:
        assert any(message.get("stage") == "apply" for message in result)


def assert_save_succeeded(result, via):
    if via == "help":
        assert result["applied"] is True
    else:
        assert any(message.get("action") == "save_complete" for message in result)


@pytest.mark.parametrize("first_via", ["help", "settings"])
@pytest.mark.parametrize("retry_via", ["help", "settings"])
@pytest.mark.asyncio
async def test_memory_reimports_after_failed_apply_even_with_unchanged_fingerprint(
    apply_env, monkeypatch, first_via, retry_via
):
    memory = instance.get_agent("memory")
    await memory.save_config()
    scene = MockScene()
    scene.active = True
    scene.immutable_save = True
    scene.commit_to_memory = AsyncMock(
        side_effect=[RuntimeError("embedding load failed"), None]
    )
    close_db = Mock()
    monkeypatch.setattr(memory, "close_db", close_db)
    with ActiveScene(scene):
        failed = await save_setting(
            apply_env, first_via, "memory", "_config", "device", "cuda"
        )
        assert_save_failed(failed, first_via)
        assert memory.device == "cuda"
        assert memory.config_apply_failed is True
        broadcasts = [
            call.args[0]
            for call in apply_env.websocket_handler.queue_put.call_args_list
        ]
        assert [message for message in broadcasts if message["type"] == "app_config"][
            -1
        ]["agent_apply_pending"] is True
        assert config_state.PENDING_APPLY == {"agents"}
        scene.commit_to_memory.assert_awaited_once()
        succeeded = await save_setting(
            apply_env, retry_via, "memory", "_config", "device", "cuda"
        )
        assert_save_succeeded(succeeded, retry_via)
        assert scene.commit_to_memory.await_count == 2
        assert close_db.call_count == 2
        assert memory.config_apply_failed is False
        broadcasts = [
            call.args[0]
            for call in apply_env.websocket_handler.queue_put.call_args_list
        ]
        assert [message for message in broadcasts if message["type"] == "app_config"][
            -1
        ]["agent_apply_pending"] is False
        await apply_env.handle_save({"config": get_config().model_dump()})
        assert not config_state.PENDING_APPLY
        assert scene.commit_to_memory.await_count == 2


@pytest.mark.parametrize("first_via", ["help", "settings"])
@pytest.mark.parametrize("retry_via", ["help", "settings"])
@pytest.mark.asyncio
async def test_visual_retry_rebuilds_failed_comfyui_url_without_reimporting_memory(
    apply_env, monkeypatch, first_via, retry_via
):
    visual = instance.get_agent("visual")
    memory = instance.get_agent("memory")
    await memory.save_config()
    memory_rebuild = AsyncMock()
    monkeypatch.setattr(memory, "handle_embeddings_change", memory_rebuild)
    await visual.apply_config(
        actions={"_config": {"config": {"backend": {"value": "comfyui"}}}}, enabled=True
    )
    await visual.save_config()
    old_backend = visual.backend
    original_init = comfyui.Backend.__init__
    attempts = []

    def failing_init(self, **kwargs):
        attempts.append(kwargs["api_url"])
        if len(attempts) == 1:
            raise RuntimeError("backend construction failed")
        original_init(self, **kwargs)

    monkeypatch.setattr(comfyui.Backend, "__init__", failing_init)
    new_url = "http://retry.local:8188"
    failed = await save_setting(
        apply_env, first_via, "visual", "comfyui_image_create", "api_url", new_url
    )
    assert_save_failed(failed, first_via)
    assert visual.actions["comfyui_image_create"].config["api_url"].value == new_url
    assert visual.backend is old_backend
    assert visual.config_apply_failed is True
    succeeded = await save_setting(
        apply_env, retry_via, "visual", "comfyui_image_create", "api_url", new_url
    )
    assert_save_succeeded(succeeded, retry_via)
    assert attempts == [new_url, new_url]
    assert visual.backend is not old_backend
    assert visual.backend.api_url == new_url
    assert visual.config_apply_failed is False
    memory_rebuild.assert_not_awaited()
    rebuilt = visual.backend
    await apply_env.handle_save({"config": get_config().model_dump()})
    assert not config_state.PENDING_APPLY
    assert visual.backend is rebuilt
    memory_rebuild.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_failures_keep_retry_mark_until_success(apply_env, monkeypatch):
    memory = instance.get_agent("memory")
    await memory.save_config()
    rebuild = AsyncMock(
        side_effect=[RuntimeError("first failure"), RuntimeError("retry failed"), None]
    )
    monkeypatch.setattr(memory, "handle_embeddings_change", rebuild)
    for expected_calls in (1, 2):
        result = await save_setting(
            apply_env, "settings", "memory", "_config", "device", "cuda"
        )
        assert_save_failed(result, "settings")
        assert memory.config_apply_failed
        assert rebuild.await_count == expected_calls
    result = await save_setting(
        apply_env, "settings", "memory", "_config", "device", "cuda"
    )
    assert_save_succeeded(result, "settings")
    assert rebuild.await_count == 3
    assert memory.config_apply_failed is False
    assert not config_state.PENDING_APPLY


@pytest.mark.asyncio
async def test_failed_agent_can_retry_with_corrected_setting(apply_env, monkeypatch):
    memory = instance.get_agent("memory")
    await memory.save_config()
    rebuild = AsyncMock(side_effect=[RuntimeError("no CUDA"), None])
    monkeypatch.setattr(memory, "handle_embeddings_change", rebuild)
    failed = await save_setting(
        apply_env, "help", "memory", "_config", "device", "cuda"
    )
    assert_save_failed(failed, "help")
    succeeded = await save_setting(
        apply_env, "settings", "memory", "_config", "device", "cpu"
    )
    assert_save_succeeded(succeeded, "settings")
    assert memory.device == "cpu"
    assert rebuild.await_count == 2
    assert memory.config_apply_failed is False


@pytest.mark.asyncio
async def test_cancelled_apply_is_retried_by_next_settings_save(apply_env, monkeypatch):
    memory = instance.get_agent("memory")
    await memory.save_config()
    rebuild = AsyncMock(side_effect=[asyncio.CancelledError(), None])
    monkeypatch.setattr(memory, "handle_embeddings_change", rebuild)
    with pytest.raises(asyncio.CancelledError):
        await save_setting(apply_env, "settings", "memory", "_config", "device", "cuda")
    assert memory.config_apply_failed
    succeeded = await save_setting(
        apply_env, "settings", "memory", "_config", "device", "cuda"
    )
    assert_save_succeeded(succeeded, "settings")
    assert rebuild.await_count == 2
    assert memory.config_apply_failed is False
