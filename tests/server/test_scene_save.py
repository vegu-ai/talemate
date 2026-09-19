import asyncio
import builtins
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import talemate.instance as instance
import talemate.tale_mate as tale_mate
from talemate.load import load_scene_from_data
from talemate.scene_message import NarratorMessage
from talemate.server.scene_message import SceneMessagePlugin
from talemate.server.world_state_manager import WorldStateManagerPlugin
from talemate.server.agent_config import AgentConfigPlugin
from talemate.agents.visual.websocket_handler import VisualWebsocketHandler


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
                        "character_knowledge": {
                            "config": {"memory_pass": {"value": True}}
                        }
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
        fresh.agent_overrides.get_value(
            "conversation", "character_knowledge", "memory_pass"
        )
        is True
    )
    assert instance.get_agent("conversation").scene is fresh


def _knowledge_patch(key: str) -> dict:
    return {
        "set": {"actions": {"character_knowledge": {"config": {key: {"value": True}}}}},
        "clear": [],
    }


@pytest.fixture
def stock_scene(save_scene, monkeypatch):
    scene, plugin, messages, payload = save_scene
    monkeypatch.setattr(type(scene), "auto_save", True)
    scene.filename = "infinity-quest.json"
    scene.immutable_save = scene.hidden = scene.deprecated = True
    return scene, plugin, messages, payload


async def test_autosave_with_no_changes_on_immutable_scene_marks_unsaved(stock_scene):
    scene, *_ = stock_scene
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    scene.saved = True

    await scene.save(auto=True)
    await scene.attempt_auto_save()

    assert scene.filename == "infinity-quest.json"
    assert scene.immutable_save and scene.hidden and scene.deprecated
    # no scene data changed; a read-only autosave still reports it unsaved
    assert not scene.saved
    assert source.read_bytes() == original
    assert [path.name for path in Path(scene.save_dir).glob("*.json")] == [source.name]


async def test_delete_message_on_stock_scene_marks_it_unsaved(stock_scene, monkeypatch):
    scene, plugin, messages, payload = stock_scene
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    scene.saved = True
    scene.active = True

    emitted = []
    monkeypatch.setattr(
        tale_mate, "emit", lambda *args, **kwargs: emitted.append(kwargs)
    )

    await SceneMessagePlugin(plugin.websocket_handler).handle_delete(
        {"id": scene.history[0].id}
    )
    await asyncio.sleep(0.05)

    assert scene.history == []
    assert scene.saved is False
    assert any(
        frame.get("data", {}).get("saved") is False
        for frame in emitted
        if "data" in frame
    )
    assert source.read_bytes() == original


async def test_restore_status_keeps_restored_flag_with_autosave_on(
    persistence_scene_factory, monkeypatch
):
    scene = persistence_scene_factory()
    scene.name = "Infinity Quests"
    scene.project_name = "quest"
    scene.history = [NarratorMessage("Before restore", source="ai")]
    await scene.save(force=True)
    await scene.save_restore("initial.json")
    scene.restore_from = "initial.json"
    scene.active = True
    monkeypatch.setattr(type(scene), "auto_save", True)
    monkeypatch.setattr(scene, "reset_memory", AsyncMock())
    monkeypatch.setattr(scene, "commit_to_memory", AsyncMock())
    messages = []
    plugin = WorldStateManagerPlugin(
        SimpleNamespace(scene=scene, queue_put=messages.append)
    )

    emitted = []
    monkeypatch.setattr(
        tale_mate, "emit", lambda *args, **kwargs: emitted.append(kwargs)
    )

    await plugin.handle_restore_scene({})
    await asyncio.sleep(0.05)

    status_frames = [frame for frame in emitted if "saved" in (frame.get("data") or {})]
    assert status_frames
    # the read-only autosave that signal_operation_done triggers must not
    # cancel the restore's pending flag
    assert status_frames[-1]["data"]["restored"] is True
    assert status_frames[-1]["data"]["saved"] is False

    # the flag is consumed by the frame: a later status is not a restore
    scene.emit_status()
    await asyncio.sleep(0.05)
    status_frames = [frame for frame in emitted if "saved" in (frame.get("data") or {})]
    assert status_frames[-1]["data"]["restored"] is False


async def test_hub_changes_on_stock_scene_keep_its_save_identity(stock_scene):
    scene, plugin, messages, payload = stock_scene
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    overrides = AgentConfigPlugin(plugin.websocket_handler)
    request = {
        "action": "save_scene_overrides",
        "agent_type": "conversation",
        "scene_identity": str(scene.id),
    }

    await overrides.handle(
        {
            **request,
            "request_id": "link",
            "filename": "agent-settings.json",
            "patch": _knowledge_patch("memory_pass"),
        }
    )
    assert messages[-1] == {
        "type": "agent_config",
        "action": "operation_done",
        "data": {},
        "request_id": "link",
    }
    assert scene.filename == "infinity-quest.json"
    assert scene.immutable_save and scene.hidden and scene.deprecated

    await overrides.handle(
        {**request, "request_id": "second", "patch": _knowledge_patch("memory_pass")}
    )
    assert "error" not in messages[-1]
    assert messages[-1]["request_id"] == "second"
    assert scene.filename == "infinity-quest.json"
    assert scene.immutable_save and scene.hidden and scene.deprecated
    assert source.read_bytes() == original
    stored = json.loads(scene.agent_overrides.filepath.read_text())
    knowledge = stored["agents"]["conversation"]["actions"]["character_knowledge"][
        "config"
    ]
    assert knowledge["memory_pass"]["value"] is True
    assert knowledge["memory_pass"]["value"] is True

    await plugin.handle(payload)
    assert messages[-1]["action"] == "scene_saved"
    assert scene.filename == "my-quest.json"
    assert not scene.immutable_save and not scene.hidden and not scene.deprecated
    copy = json.loads(Path(scene.full_path).read_text())
    assert not any(copy[flag] for flag in ("immutable_save", "hidden", "deprecated"))
    assert source.read_bytes() == original
    source_data = json.loads(original)
    assert source_data["immutable_save"] is True


@pytest.mark.parametrize("auto_save", [True, False])
async def test_stock_scene_link_goes_into_a_save_as_copy(
    stock_scene, persistence_scene_factory, monkeypatch, auto_save
):
    scene, plugin, messages, payload = stock_scene
    monkeypatch.setattr(type(scene), "auto_save", auto_save)
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    overrides = AgentConfigPlugin(plugin.websocket_handler)
    link = {
        "action": "save_scene_overrides",
        "agent_type": "conversation",
        "filename": "custom.json",
        "override": {
            "actions": {
                "character_knowledge": {"config": {"memory_pass": {"value": True}}}
            }
        },
    }

    await overrides.handle({**link, "request_id": "link"})
    assert messages[-1]["request_id"] == "link"
    assert messages[-1]["save_as_required"] is True
    assert scene.agent_settings_file is None
    assert scene.agent_overrides is None
    assert not (Path(scene.save_dir) / "agent-settings" / "custom.json").exists()
    assert source.read_bytes() == original

    await plugin.handle(payload)
    assert messages[-1]["action"] == "scene_saved"
    assert not scene.immutable_save

    await overrides.handle({**link, "request_id": "link-copy"})
    assert messages[-1]["request_id"] == "link-copy"
    assert "error" not in messages[-1]
    if not auto_save:
        assert not scene.saved
        await scene.save()

    copy_path = Path(scene.full_path)
    assert copy_path.name == "my-quest.json"
    copy_data = json.loads(copy_path.read_text())
    assert copy_data["agent_settings_file"] == "custom.json"
    fresh = persistence_scene_factory()
    await load_scene_from_data(fresh, copy_data, name=str(copy_path))
    assert fresh.agent_settings_file == "custom.json"
    assert (
        fresh.agent_overrides.get_value(
            "conversation", "character_knowledge", "memory_pass"
        )
        is True
    )

    assert source.read_bytes() == original
    stock = persistence_scene_factory()
    await load_scene_from_data(stock, json.loads(original), name=str(source))
    assert stock.agent_settings_file is None
    assert stock.agent_overrides is None


async def test_hub_change_on_opted_out_stock_scene_is_refused(stock_scene):
    scene, plugin, messages, payload = stock_scene
    scene._agent_settings_opted_out = True
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    overrides = AgentConfigPlugin(plugin.websocket_handler)
    request = {
        "action": "save_scene_overrides",
        "agent_type": "conversation",
        "scene_identity": str(scene.id),
        "filename": "agent-settings.json",
        "patch": _knowledge_patch("memory_pass"),
    }

    await overrides.handle({**request, "request_id": "hub"})
    assert messages[-1]["request_id"] == "hub"
    assert messages[-1]["save_as_required"] is True
    assert scene._agent_settings_opted_out is True
    assert scene.agent_overrides is None
    assert not (Path(scene.save_dir) / "agent-settings").exists()
    assert source.read_bytes() == original

    await plugin.handle(payload)
    await overrides.handle({**request, "request_id": "hub-copy"})
    assert "error" not in messages[-1]
    copy_data = json.loads(Path(scene.full_path).read_text())
    assert copy_data["agent_settings_file"] == "agent-settings.json"
    assert copy_data["agent_settings_opted_out"] is False
    assert source.read_bytes() == original


@pytest.mark.parametrize("immutable", [False, True])
async def test_autosave_as_without_copy_name_keeps_filename(stock_scene, immutable):
    scene, *_ = stock_scene
    scene.immutable_save = scene.hidden = scene.deprecated = immutable
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()

    await scene.save(auto=True, save_as=True)

    assert scene.filename == "infinity-quest.json"
    assert scene.immutable_save is immutable
    assert not scene.saved
    assert source.read_bytes() == original
    assert [path.name for path in Path(scene.save_dir).glob("*.json")] == [source.name]


async def test_save_for_another_scene_is_refused_without_writing(save_scene):
    scene, plugin, messages, payload = save_scene
    await plugin.handle({**payload, "scene_identity": "another-scene"})
    assert messages[-1]["failed_action"] == "save_scene"
    assert messages[-1]["request_id"] == "save-1"
    assert not scene.filename
    assert not list(Path(scene.save_dir).glob("*.json"))


@pytest.mark.parametrize("style", ["new-art-style", None])
async def test_art_style_update_preserves_stock_settings_and_autosave(
    stock_scene, style
):
    scene, plugin, _, _ = stock_scene
    scene.experimental = True
    scene.writing_style_template = "writing-style"
    scene.visual_style_template = "original-art-style"
    scene.restore_from = "initial.json"
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()

    await VisualWebsocketHandler(plugin.websocket_handler).handle_update_art_style(
        {"visual_style_template": style}
    )

    assert scene.visual_style_template == style
    assert scene.immutable_save is True
    assert scene.experimental is True
    assert scene.writing_style_template == "writing-style"
    assert scene.restore_from == "initial.json"
    scene.saved = False
    await scene.attempt_auto_save()
    assert source.read_bytes() == original
    assert scene.filename == source.name


@pytest.mark.parametrize(
    "copy_name",
    ["infinity-quest", "infinity-quest.json", None, ""],
)
async def test_save_as_cannot_overwrite_current_read_only_file(stock_scene, copy_name):
    scene, plugin, messages, payload = stock_scene
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    previous_identity = scene.memory_id, scene.memory_session_id

    await plugin.handle({**payload, "save_as": copy_name})

    assert messages[-1] == {
        "type": "world_state_manager",
        "action": "operation_done",
        "error": {
            "message": "This scene file is read-only. Choose a different name for Save As."
        },
        "request_id": payload["request_id"],
        "failed_action": "save_scene",
    }
    assert scene.filename == source.name
    assert scene.immutable_save and scene.hidden and scene.deprecated
    assert (scene.memory_id, scene.memory_session_id) == previous_identity
    assert source.read_bytes() == original

    await plugin.handle({**payload, "request_id": "corrected-name"})
    assert messages[-1]["action"] == "scene_saved"
    assert messages[-1]["request_id"] == "corrected-name"
    assert scene.filename == "my-quest.json"
    assert not scene.immutable_save
    assert source.read_bytes() == original
    assert Path(scene.full_path).is_file()


async def test_save_as_allows_current_filename_for_mutable_scene(stock_scene):
    scene, plugin, messages, payload = stock_scene
    await scene.save(force=True)
    scene.immutable_save = False
    await plugin.handle({**payload, "save_as": "infinity-quest"})
    assert messages[-1]["action"] == "scene_saved"
    assert scene.filename == "infinity-quest.json"


@pytest.mark.parametrize("locked_on_disk", [False, True])
async def test_world_editor_authoring_save_persists_lock_and_reload(
    stock_scene, persistence_scene_factory, locked_on_disk
):
    scene, plugin, messages, payload = stock_scene
    scene.immutable_save = locked_on_disk
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    scene.history.append(NarratorMessage("Authored change", source="ai"))

    await plugin.handle_update_scene_settings({"immutable_save": True})
    assert scene.immutable_save
    assert source.read_bytes() == original
    await plugin.handle({**payload, "save_as": None, "authoring": True})

    assert messages[-1]["action"] == "scene_saved"
    assert scene.filename == source.name
    saved = json.loads(source.read_text())
    assert saved["immutable_save"] is True
    assert saved["history"][-1]["message"] == "Authored change"
    fresh = persistence_scene_factory()
    await load_scene_from_data(fresh, saved, name=str(source))
    assert fresh.immutable_save
    assert fresh.filename == source.name

    fresh_messages = []
    fresh_plugin = WorldStateManagerPlugin(
        SimpleNamespace(scene=fresh, queue_put=fresh_messages.append)
    )
    saved_bytes = source.read_bytes()
    await fresh_plugin.handle(
        {"action": "save_scene", "save_as": source.stem, "authoring": True}
    )
    assert "read-only" in fresh_messages[-1]["error"]["message"]
    assert source.read_bytes() == saved_bytes


async def test_authoring_does_not_bypass_another_read_only_destination(stock_scene):
    scene, plugin, messages, payload = stock_scene
    await scene.save_restore("baseline.json")
    baseline = Path(scene.save_dir) / "baseline.json"
    original = baseline.read_bytes()
    await plugin.handle({**payload, "save_as": "baseline", "authoring": True})
    assert "read-only" in messages[-1]["error"]["message"]
    assert baseline.read_bytes() == original


async def test_stock_without_project_name_lists_existing_overrides_after_load_and_copy(
    save_scene, persistence_scene_factory
):
    scene, plugin, messages, payload = save_scene
    data = scene.serialize
    data.pop("project_name", None)
    data["immutable_save"] = True
    await load_scene_from_data(scene, data, name="stock.json")
    assert not scene._project_name
    target = Path(scene.save_dir) / "agent-settings" / "custom.json"
    target.parent.mkdir()
    target.write_text('{"agents": {}}')

    fresh = persistence_scene_factory()
    await load_scene_from_data(fresh, data, name="stock.json")
    plugin.websocket_handler.scene = fresh
    assert not fresh._project_name
    assert fresh.agent_settings_files == ["custom.json"]
    await plugin.handle({**payload, "scene_identity": str(fresh.id)})
    assert messages[-1]["action"] == "scene_saved"
    assert not fresh._project_name
    assert fresh.agent_settings_files == ["custom.json"]


@pytest.mark.parametrize(
    "immutable, filename", [(False, "new.json"), (True, "agent-settings.json")]
)
async def test_first_link_batch_succeeds_and_lists_file_for_stock_project(
    save_scene, monkeypatch, immutable, filename
):
    scene, plugin, messages, _ = save_scene
    data = scene.serialize
    data.pop("project_name", None)
    data["immutable_save"] = immutable
    await load_scene_from_data(scene, data, name="stock.json")
    assert not scene._project_name
    await scene.save(force=True)
    save = AsyncMock(wraps=scene.save)
    monkeypatch.setattr(scene, "save", save)
    overrides = AgentConfigPlugin(plugin.websocket_handler)
    edits = {
        "conversation": {
            "character_knowledge": {"config": {"memory_pass": {"value": True}}}
        },
        "memory": {"retrieval": {"config": {"recency_weight": {"value": 0.3}}}},
    }
    for agent, actions in edits.items():
        await overrides.handle(
            {
                "action": "save_scene_overrides",
                "agent_type": agent,
                "filename": filename,
                "override": {"actions": actions},
                "request_id": agent,
            }
        )

    assert not [message for message in messages if "error" in message]
    assert {message.get("request_id") for message in messages} >= set(edits)
    save.assert_awaited_once_with(auto=True)
    stored = json.loads(
        (Path(scene.save_dir) / "agent-settings" / filename).read_text()
    )
    for agent, actions in edits.items():
        assert stored["agents"][agent]["actions"] == actions
    assert scene.agent_overrides.filename == filename
    assert scene.agent_settings_files == [filename]
    assert scene.immutable_save is immutable


async def test_save_as_refuses_alias_of_loaded_read_only_file(stock_scene):
    scene, plugin, messages, payload = stock_scene
    scene.immutable_save = False
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    alias = source.with_name("Infinity-Quest.json")
    os.link(source, alias)
    scene.immutable_save = True

    await plugin.handle({**payload, "save_as": "Infinity-Quest"})

    assert "read-only" in messages[-1]["error"]["message"]
    assert scene.filename == source.name
    assert scene.immutable_save
    assert source.read_bytes() == alias.read_bytes() == original


async def test_save_as_refuses_read_only_restore_destination(stock_scene):
    scene, plugin, messages, payload = stock_scene
    await scene.save(force=True)
    source = Path(scene.full_path)
    source_bytes = source.read_bytes()
    await scene.save_restore("restore.json")
    scene.restore_from = "restore.json"
    restore = source.with_name("restore.json")
    original = restore.read_bytes()

    await plugin.handle({**payload, "save_as": "restore"})

    assert "read-only" in messages[-1]["error"]["message"]
    assert messages[-1]["request_id"] == payload["request_id"]
    assert scene.filename == source.name
    assert scene.immutable_save
    assert restore.read_bytes() == original
    assert source.read_bytes() == source_bytes


async def test_save_as_from_writable_copy_cannot_replace_stock(stock_scene):
    scene, plugin, messages, payload = stock_scene
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    await plugin.handle(payload)
    assert not scene.immutable_save
    copy = Path(scene.full_path)
    copy_bytes = copy.read_bytes()

    await plugin.handle({**payload, "save_as": source.stem})

    assert "read-only" in messages[-1]["error"]["message"]
    assert scene.filename == copy.name
    assert not scene.immutable_save
    assert source.read_bytes() == original
    assert copy.read_bytes() == copy_bytes


@pytest.mark.parametrize("immutable", [False, True])
async def test_save_as_can_replace_writable_checkpoint(stock_scene, immutable):
    scene, plugin, messages, payload = stock_scene
    scene.immutable_save = immutable
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()
    checkpoint = source.with_name("checkpoint.json")
    checkpoint.write_text(json.dumps({"immutable_save": False, "history": []}))

    await plugin.handle({**payload, "save_as": "checkpoint.json"})

    assert messages[-1]["action"] == "scene_saved"
    assert scene.filename == checkpoint.name
    assert not scene.immutable_save
    assert json.loads(checkpoint.read_text())["history"]
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "name",
    ["./infinity-quest.json", "../escape", "folder/copy", "folder\\copy", "/absolute"],
)
async def test_save_as_rejects_path_separators(stock_scene, name):
    scene, plugin, messages, payload = stock_scene
    await scene.save(force=True)
    source = Path(scene.full_path)
    original = source.read_bytes()

    await plugin.handle({**payload, "save_as": name})

    assert "without path separators" in messages[-1]["error"]["message"]
    assert messages[-1]["request_id"] == payload["request_id"]
    assert scene.filename == source.name
    assert scene.immutable_save
    assert source.read_bytes() == original


@pytest.mark.parametrize("contents", ["broken JSON", "[]"])
async def test_save_as_refuses_unreadable_destination(stock_scene, contents):
    scene, plugin, messages, payload = stock_scene
    destination = Path(scene.save_dir) / "checkpoint.json"
    destination.write_text(contents)

    await plugin.handle({**payload, "save_as": destination.name})

    assert "Cannot read the destination" in messages[-1]["error"]["message"]
    assert destination.read_text() == contents
    assert scene.immutable_save
