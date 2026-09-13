import builtins
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import talemate.instance as instance
import talemate.tale_mate as tale_mate
from talemate.load import load_scene_from_data
from talemate.scene_message import NarratorMessage
from talemate.server.world_state_manager import WorldStateManagerPlugin
from talemate.server.agent_config import AgentConfigPlugin


@pytest.fixture
def save_scene(persistence_scene_factory):
    scene = persistence_scene_factory()
    scene.name = "Infinity Quests"
    scene.project_name = "quest"
    scene.history = [NarratorMessage("Progress to keep", source="ai")]
    scene.saved = False
    messages = []
    plugin = WorldStateManagerPlugin(
        SimpleNamespace(scene=scene, queue_put=messages.append)
    )
    payload = {
        "action": "save_scene",
        "save_as": "my-quest",
        "project_name": "quest",
        "request_id": "save-1",
        "scene_identity": str(scene.id),
    }
    return scene, plugin, messages, payload


async def test_save_receipt_follows_real_persistence_and_reload(
    save_scene, persistence_scene_factory
):
    scene, plugin, messages, payload = save_scene
    await plugin.handle(payload)
    assert messages == [
        {
            "type": "world_state_manager",
            "action": "scene_saved",
            "request_id": "save-1",
            "scene_identity": str(scene.id),
        }
    ]
    saved_path = Path(scene.full_path)
    data = json.loads(saved_path.read_text())
    fresh = persistence_scene_factory()
    await load_scene_from_data(fresh, data, name=str(saved_path))
    assert fresh.history[0].message == "Progress to keep"


async def test_first_save_failure_keeps_identity_dirty_and_can_retry(
    save_scene, monkeypatch
):
    scene, plugin, messages, payload = save_scene
    original_open = builtins.open
    original_name, original_filename = scene.name, scene.filename
    emitted = []
    monkeypatch.setattr(
        tale_mate, "emit", lambda *args, **kwargs: emitted.append(kwargs)
    )

    def fail_scene_write(file, mode="r", *args, **kwargs):
        if str(file).endswith("my-quest.json") and "w" in mode:
            raise OSError("disk full")
        return original_open(file, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", fail_scene_write)
        await plugin.handle(payload)
    assert messages[-1]["request_id"] == "save-1"
    assert "disk full" in messages[-1]["error"]["message"]
    assert not any(message.get("action") == "scene_saved" for message in messages)
    assert scene.filename == original_filename
    assert scene.name == original_name
    assert not scene.saved
    assert not any(frame.get("message") == "Saved scene" for frame in emitted)
    assert scene.history[0].message == "Progress to keep"

    await plugin.handle({**payload, "request_id": "retry"})
    assert messages[-1]["action"] == "scene_saved"
    assert messages[-1]["request_id"] == "retry"
    assert (
        json.loads(Path(scene.full_path).read_text())["history"][0]["message"]
        == "Progress to keep"
    )


@pytest.mark.parametrize("failure_stage", ["memory", "disk"])
@pytest.mark.parametrize("auto", [False, True])
async def test_failed_save_as_preserves_protected_source_on_next_save(
    save_scene, monkeypatch, failure_stage, auto
):
    scene, plugin, messages, payload = save_scene
    scene.filename = "protected.json"
    scene.immutable_save = scene.hidden = scene.deprecated = True
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    scene.history.append(NarratorMessage("Unsaved progress", source="ai"))
    scene.saved = False

    async def fail_memory():
        raise OSError("memory write failed")

    with monkeypatch.context() as patch:
        if failure_stage == "memory":
            patch.setattr(scene, "commit_to_memory", fail_memory)
        else:
            (source.parent / "my-quest.json").mkdir()
        await plugin.handle(payload)

    assert messages[-1]["error"]
    assert not any(message.get("action") == "scene_saved" for message in messages)
    assert scene.filename == "protected.json"
    assert scene.immutable_save and scene.hidden and scene.deprecated
    assert not scene.can_auto_save()
    assert not scene.saved
    assert scene.history[-1].message == "Unsaved progress"

    await scene.save(auto=auto)
    assert source.read_bytes() == original
    if not auto:
        assert Path(scene.full_path) != source
        assert (
            json.loads(Path(scene.full_path).read_text())["history"][-1]["message"]
            == "Unsaved progress"
        )

    await plugin.handle({**payload, "save_as": "retry", "request_id": "retry"})
    assert messages[-1]["action"] == "scene_saved"
    assert messages[-1]["request_id"] == "retry"
    assert not scene.immutable_save and not scene.hidden and not scene.deprecated
    assert source.read_bytes() == original
    assert (
        json.loads(Path(scene.full_path).read_text())["history"][-1]["message"]
        == "Unsaved progress"
    )


async def test_first_save_then_hub_override_survives_reload(
    save_scene, persistence_scene_factory
):
    scene, plugin, messages, payload = save_scene
    await plugin.handle(payload)
    overrides = AgentConfigPlugin(plugin.websocket_handler)
    await overrides.handle(
        {
            "action": "save_scene_overrides",
            "agent_type": "conversation",
            "scene_identity": str(scene.id),
            "request_id": "knowledge-1",
            "filename": "agent-settings.json",
            "patch": {
                "set": {
                    "actions": {
                        "character_knowledge": {"config": {"ledger": {"value": True}}}
                    }
                },
                "clear": [],
            },
        }
    )
    assert messages[-1]["request_id"] == "knowledge-1"
    assert "error" not in messages[-1]
    saved_path = Path(scene.full_path)
    data = json.loads(saved_path.read_text())
    assert data["agent_settings_file"] == "agent-settings.json"
    fresh = persistence_scene_factory()
    await load_scene_from_data(fresh, data, name=str(saved_path))
    assert (
        fresh.agent_overrides.get_value("conversation", "character_knowledge", "ledger")
        is True
    )
    assert instance.get_agent("conversation").scene is fresh


async def test_save_for_another_scene_is_refused_without_writing(save_scene):
    scene, plugin, messages, payload = save_scene
    await plugin.handle({**payload, "scene_identity": "another-scene"})
    assert messages[-1]["failed_action"] == "save_scene"
    assert messages[-1]["request_id"] == "save-1"
    assert not scene.filename
    assert not list(Path(scene.save_dir).glob("*.json"))
