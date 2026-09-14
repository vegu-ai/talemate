"""Unit tests for `AgentConfigPlugin.handle_save_scene_overrides`.

Focus: the failure paths. The frontend (agent modal, agent-panel quick-toggle
chips) updates its copy of the overlay optimistically, so a refused save has to
leave both the running scene and the frontend on the stored values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import talemate.instance as instance
from _agent_override_test_helpers import override_agent_class
from talemate.scene_agent_settings import UNSET, SceneAgentSettings
from talemate.server.agent_config import (
    AgentConfigPlugin,
    strip_non_overridable_fields,
)

AGENT_TYPE = "override-test"

_OverrideAgent = override_agent_class(AGENT_TYPE)


class _Scene:
    """Minimal stand-in for the bits the handler touches."""

    def __init__(self, save_dir: Path, filename="scene.json", project_name="proj"):
        self.save_dir = str(save_dir)
        self.filename = filename
        self.project_name = project_name
        self.id = "scene-1"
        self.name = "Test Scene"
        self.agent_overrides = None
        self.agent_settings_file = None
        self.auto_save = True
        self.saved = True
        self.immutable_save = False
        self._agent_settings_opted_out = False
        self.saves = 0
        self.status_emissions = 0

    async def save(self, auto=False):
        self.saves += 1

    def emit_status(self, **kwargs):
        self.status_emissions += 1


class _WebsocketHandler:
    def __init__(self, scene):
        self.scene = scene
        self.messages = []

    def queue_put(self, message):
        self.messages.append(message)


@pytest.fixture
def wired(tmp_path: Path):
    scene = _Scene(tmp_path)
    agent = _OverrideAgent(scene)
    handler = _WebsocketHandler(scene)
    plugin = AgentConfigPlugin(handler)
    instance.AGENTS[AGENT_TYPE] = agent
    try:
        yield plugin, scene, agent, handler
    finally:
        instance.AGENTS.pop(AGENT_TYPE, None)


def _payload(enabled: bool, filename: str | None = None) -> dict:
    data = {
        "agent_type": AGENT_TYPE,
        "override": {"actions": {"container": {"enabled": enabled}}},
    }
    if filename:
        data["filename"] = filename
    return data


def _errors(handler: _WebsocketHandler) -> list[str]:
    return [m["error"]["message"] for m in handler.messages if "error" in m]


@pytest.mark.parametrize("filename", ["agent-settings.json", "custom.json"])
@pytest.mark.asyncio
async def test_first_save_links_file_and_saves_the_scene(wired, filename):
    plugin, scene, agent, handler = wired

    await plugin.handle_save_scene_overrides(_payload(False, filename))

    assert not _errors(handler)
    assert (Path(scene.save_dir) / "agent-settings" / filename).is_file()
    assert scene.agent_settings_file == filename
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    # linking writes `agent_settings_file` into the scene, so it is persisted
    assert scene.saves == 1


@pytest.mark.asyncio
async def test_read_only_scene_links_the_default_file_directly(wired):
    plugin, scene, agent, handler = wired
    scene.immutable_save = True

    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))

    # the load-time auto-link restores the default file, so no copy is needed
    assert not _errors(handler)
    assert (Path(scene.save_dir) / "agent-settings" / "agent-settings.json").is_file()
    assert scene.agent_settings_file == "agent-settings.json"
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    assert scene.saves == 1


@pytest.mark.parametrize(
    "filename, opted_out",
    [("custom.json", False), ("custom.json", True), ("agent-settings.json", True)],
)
@pytest.mark.asyncio
async def test_read_only_scene_refuses_a_link_it_cannot_reload(
    wired, filename, opted_out
):
    plugin, scene, agent, handler = wired
    scene.immutable_save = True
    scene._agent_settings_opted_out = opted_out
    emitted_before = agent.emitted

    await plugin.handle_save_scene_overrides(
        {**_payload(False, filename), "request_id": "link-1"}
    )

    refusal = handler.messages[-1]
    assert refusal["save_as_required"] is True
    assert refusal["request_id"] == "link-1"
    assert filename in refusal["error"]["message"]
    assert agent.emitted == emitted_before + 1
    # nothing changed: no link, no file, no scene save
    assert scene.agent_overrides is None
    assert scene.agent_settings_file is None
    assert scene._agent_settings_opted_out is opted_out
    assert not (Path(scene.save_dir) / "agent-settings").exists()
    assert scene.saves == 0


@pytest.mark.asyncio
async def test_read_only_scene_refuses_switching_to_another_file(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    scene.immutable_save = True
    scene.saves = 0

    await plugin.handle_save_scene_overrides(_payload(True, "custom.json"))

    assert handler.messages[-1]["save_as_required"] is True
    assert scene.agent_settings_file == "agent-settings.json"
    assert scene.agent_overrides.filename == "agent-settings.json"
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    assert not (Path(scene.save_dir) / "agent-settings" / "custom.json").exists()
    assert scene.saves == 0


@pytest.mark.asyncio
async def test_repeat_save_does_not_touch_the_scene(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    scene.saves = 0

    status_before = scene.status_emissions
    # what a quick-toggle chip flip sends: no filename, overlay already linked
    await plugin.handle_save_scene_overrides(_payload(True))

    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is True
    assert scene.saves == 0
    assert scene.saved is True
    assert scene.status_emissions == status_before + 1
    assert handler.messages[-1]["action"] == "operation_done"


@pytest.mark.asyncio
async def test_refused_save_emits_status_so_the_frontend_can_correct(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    # A restore re-links the overlay from `project_name` and then clears the
    # filename, so a scene can hold live overrides and still have no save file.
    scene.filename = None

    emitted_before = agent.emitted
    await plugin.handle_save_scene_overrides(_payload(True))

    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    assert agent.emitted == emitted_before + 1
    assert _errors(handler)


@pytest.mark.asyncio
async def test_failed_write_rolls_back_the_in_memory_overlay(wired, tmp_path: Path):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    overlay_path = Path(scene.agent_overrides.filepath)
    overlay_path.chmod(0o444)

    try:
        await plugin.handle_save_scene_overrides(_payload(True))
    finally:
        overlay_path.chmod(0o644)

    # memory must not run ahead of what reached disk
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    on_disk = await SceneAgentSettings(filepath=overlay_path).init_from_file()
    assert on_disk.get_enabled(AGENT_TYPE, "container") is False
    assert _errors(handler)


@pytest.mark.asyncio
async def test_failed_first_write_leaves_the_scene_unlinked(wired, tmp_path: Path):
    plugin, scene, agent, handler = wired
    # a scene the user deliberately opted out of per-scene overrides
    scene._agent_settings_opted_out = True
    # make the agent-settings dir unwritable so creating the file fails
    settings_dir = tmp_path / "agent-settings"
    settings_dir.mkdir()
    settings_dir.chmod(0o555)

    try:
        await plugin.handle_save_scene_overrides(_payload(True, "agent-settings.json"))
    finally:
        settings_dir.chmod(0o755)

    assert scene.agent_overrides is None
    assert scene.agent_settings_file is None
    # linking cleared the opt-out; a failed write must not leave it cleared,
    # or the next load silently auto-links the project's overrides
    assert scene._agent_settings_opted_out is True
    assert _errors(handler)


@pytest.mark.asyncio
async def test_save_drops_values_for_non_overridable_fields(wired):
    plugin, scene, agent, handler = wired

    await plugin.handle_save_scene_overrides(
        {
            "agent_type": AGENT_TYPE,
            "filename": "agent-settings.json",
            "override": {
                "actions": {
                    "container": {
                        "enabled": True,
                        "config": {
                            "fmt": {"value": "scene-fmt"},
                            "api_key": {"value": "scene-key"},
                        },
                    }
                }
            },
        }
    )

    overrides = scene.agent_overrides
    assert overrides.get_value(AGENT_TYPE, "container", "fmt") == "scene-fmt"
    assert overrides.get_value(AGENT_TYPE, "container", "api_key") is UNSET
    assert not _errors(handler)

    on_disk = await SceneAgentSettings(
        filepath=Path(overrides.filepath)
    ).init_from_file()
    assert on_disk.get_value(AGENT_TYPE, "container", "api_key") is UNSET


class TestStripNonOverridableFields:
    def _agent(self):
        return _OverrideAgent(scene=None)

    def _override(self, config: dict, action_key="container") -> dict:
        return {"actions": {action_key: {"config": config}}}

    def test_strips_declared_non_overridable_field(self):
        override = self._override(
            {"fmt": {"value": "a"}, "api_key": {"value": "secret"}}
        )
        stripped = strip_non_overridable_fields(self._agent(), override)
        assert stripped == ["container.api_key"]
        assert override["actions"]["container"]["config"] == {"fmt": {"value": "a"}}

    def test_unknown_config_key_passes_through(self):
        override = self._override({"gone_in_this_version": {"value": 1}})
        assert strip_non_overridable_fields(self._agent(), override) == []
        assert "gone_in_this_version" in override["actions"]["container"]["config"]

    def test_unknown_action_key_passes_through(self):
        """Dynamic children are only installed for the current config, so an
        unknown action is not proof the field is gone."""
        override = self._override({"api_key": {"value": "secret"}}, action_key="child")
        assert strip_non_overridable_fields(self._agent(), override) == []
        assert "api_key" in override["actions"]["child"]["config"]

    def test_enabled_only_override_is_untouched(self):
        override = {"actions": {"container": {"enabled": False}}}
        assert strip_non_overridable_fields(self._agent(), override) == []
        assert override == {"actions": {"container": {"enabled": False}}}

    def test_empty_override_is_untouched(self):
        override = {}
        assert strip_non_overridable_fields(self._agent(), override) == []
        assert override == {}


def _patch(
    patch: dict, *, filename: str | None = None, scene_identity: str | None = None
) -> dict:
    data = {"agent_type": AGENT_TYPE, "patch": patch}
    if filename:
        data["filename"] = filename
    if scene_identity:
        data["scene_identity"] = scene_identity
    return data


@pytest.mark.asyncio
async def test_patch_merges_the_named_keys_and_keeps_the_rest(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(True, "agent-settings.json"))

    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {"container": {"config": {"fmt": {"value": "patched"}}}}
                },
            }
        )
    )

    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "fmt") == "patched"
    # the enable override the replacement save installed is still there
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is True
    assert not _errors(handler)


@pytest.mark.asyncio
async def test_patch_clear_drops_only_the_named_keys(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(True, "agent-settings.json"))

    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "clear": [{"action": "container", "config": "fmt"}],
            }
        )
    )

    # fmt goes back to inheriting the global; the enable override stays
    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "fmt") is UNSET
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is True


@pytest.mark.asyncio
async def test_patch_clear_without_config_drops_the_enable_override_only(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {"container": {"config": {"fmt": {"value": "kept"}}}}
                },
            }
        )
    )

    await plugin.handle_save_scene_overrides(
        _patch({"clear": [{"action": "container"}]})
    )

    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is UNSET
    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "fmt") == "kept"


@pytest.mark.asyncio
async def test_patch_drops_non_overridable_fields(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {
                        "container": {"config": {"api_key": {"value": "scene-key"}}}
                    }
                },
            },
            filename="agent-settings.json",
        )
    )

    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "api_key") is UNSET
    assert not _errors(handler)


@pytest.mark.asyncio
async def test_patch_and_override_are_mutually_exclusive(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(
        {
            "agent_type": AGENT_TYPE,
            "override": {"actions": {}},
            "patch": {"set": {"actions": {}}},
        }
    )
    assert _errors(handler)


@pytest.mark.asyncio
async def test_patch_refuses_a_scene_identity_from_another_generation(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {"container": {"config": {"fmt": {"value": "patched"}}}}
                },
            },
            filename="agent-settings.json",
            scene_identity="some-other-scene",
        )
    )

    assert scene.agent_overrides is None
    assert _errors(handler)


@pytest.mark.asyncio
async def test_patch_accepts_the_current_scene_identity(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {"container": {"config": {"fmt": {"value": "patched"}}}}
                },
            },
            filename="agent-settings.json",
            scene_identity="scene-1",
        )
    )

    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "fmt") == "patched"
    assert not _errors(handler)


@pytest.mark.asyncio
async def test_patch_first_link_preserves_the_existing_file(wired, tmp_path: Path):
    plugin, scene, agent, handler = wired
    settings_dir = tmp_path / "agent-settings"
    settings_dir.mkdir()
    (settings_dir / "agent-settings.json").write_text(
        json.dumps(
            {
                "agents": {
                    "other": {"actions": {"thing": {"enabled": False}}},
                    AGENT_TYPE: {
                        "actions": {
                            "container": {"config": {"fmt": {"value": "existing"}}}
                        }
                    },
                }
            }
        )
    )

    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {"container": {"config": {"fmt": {"value": "patched"}}}}
                }
            },
            filename="agent-settings.json",
        )
    )

    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "fmt") == "patched"
    # the other agent's override was loaded first and survives the merge
    assert scene.agent_overrides.get_enabled("other", "thing") is False
    assert not _errors(handler)


@pytest.mark.asyncio
async def test_patch_first_link_refuses_a_corrupt_existing_file(wired, tmp_path: Path):
    plugin, scene, agent, handler = wired
    settings_dir = tmp_path / "agent-settings"
    settings_dir.mkdir()
    corrupt = settings_dir / "agent-settings.json"
    corrupt.write_text("{not json")

    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {"container": {"config": {"fmt": {"value": "patched"}}}}
                }
            },
            filename="agent-settings.json",
        )
    )

    assert scene.agent_overrides is None
    assert scene.agent_settings_file is None
    assert corrupt.read_text() == "{not json"
    assert _errors(handler)


# ---------------------------------------------------------------------------
# Round-1 review regressions: independent rollback, whole-patch validation and
# first-link status refresh.
# ---------------------------------------------------------------------------


def _failing_write(monkeypatch):
    async def boom(self):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(SceneAgentSettings, "write_to_file", boom)


@pytest.mark.asyncio
async def test_patch_failed_set_rolls_back_an_existing_slice(wired, monkeypatch):
    """A failed sparse set must not leave the live slice mutated: the rollback
    snapshot has to be an independent copy of the overlay."""
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    on_disk_before = Path(scene.agent_overrides.filepath).read_text()
    _failing_write(monkeypatch)

    await plugin.handle_save_scene_overrides(
        _patch({"set": {"actions": {"container": {"enabled": True}}}})
    )

    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    assert Path(scene.agent_overrides.filepath).read_text() == on_disk_before
    assert _errors(handler)


@pytest.mark.asyncio
async def test_patch_failed_clear_rolls_back_an_existing_slice(wired, monkeypatch):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    _failing_write(monkeypatch)

    await plugin.handle_save_scene_overrides(
        _patch({"clear": [{"action": "container"}]})
    )

    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    assert _errors(handler)


@pytest.mark.asyncio
async def test_patch_malformed_later_entry_is_refused_before_any_mutation(wired):
    """The whole patch is validated first, so an early valid entry is not
    applied when a later one is malformed."""
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))

    await plugin.handle_save_scene_overrides(
        _patch(
            {
                "set": {
                    "actions": {
                        "container": {
                            "config": {"fmt": {"value": "early"}, "api_key": 1}
                        }
                    }
                }
            }
        )
    )

    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "fmt") is UNSET
    assert _errors(handler)


@pytest.mark.asyncio
async def test_patch_unknown_action_is_refused_and_not_written(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))

    await plugin.handle_save_scene_overrides(
        _patch({"set": {"actions": {"ghost": {"config": {"x": {"value": 1}}}}}})
    )

    assert "ghost" not in scene.agent_overrides.agents
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    assert _errors(handler)


@pytest.mark.asyncio
async def test_patch_unknown_config_is_refused(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))

    await plugin.handle_save_scene_overrides(
        _patch({"set": {"actions": {"container": {"config": {"ghost": {"value": 1}}}}}})
    )

    assert scene.agent_overrides.get_value(AGENT_TYPE, "container", "ghost") is UNSET
    assert _errors(handler)


@pytest.mark.asyncio
async def test_patch_refusal_carries_the_request_id(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(
        {
            "agent_type": AGENT_TYPE,
            "request_id": "req-546",
            "patch": {"set": {"actions": {"ghost": {}}}},
        }
    )

    failures = [m for m in handler.messages if "error" in m]
    assert failures and failures[-1]["request_id"] == "req-546"


@pytest.mark.asyncio
async def test_first_link_refreshes_every_agent_it_loaded(wired, tmp_path: Path):
    """Loading an existing file on first link changes other agents' effective
    settings; each of them has to re-emit its status."""
    plugin, scene, agent, handler = wired
    other = _OverrideAgent(scene)
    instance.AGENTS["override-test-other"] = other
    try:
        settings_dir = tmp_path / "agent-settings"
        settings_dir.mkdir()
        (settings_dir / "agent-settings.json").write_text(
            json.dumps(
                {
                    "agents": {
                        "override-test-other": {
                            "actions": {"container": {"enabled": False}}
                        }
                    }
                }
            )
        )
        agent.emitted = 0
        other.emitted = 0

        await plugin.handle_save_scene_overrides(
            _patch(
                {
                    "set": {
                        "actions": {
                            "container": {"config": {"fmt": {"value": "patched"}}}
                        }
                    }
                },
                filename="agent-settings.json",
            )
        )

        assert agent.emitted >= 1
        assert other.emitted == 1
        # the loaded agent's override is live and preserved on disk
        assert (
            scene.agent_overrides.get_enabled("override-test-other", "container")
            is False
        )
        on_disk = await SceneAgentSettings(
            filepath=Path(scene.agent_overrides.filepath)
        ).init_from_file()
        assert on_disk.get_enabled("override-test-other", "container") is False
    finally:
        instance.AGENTS.pop("override-test-other", None)


@pytest.mark.asyncio
async def test_already_linked_patch_keeps_the_narrow_status_update(wired):
    """An ordinary patch on an already-linked scene refreshes only its agent."""
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    agent.emitted = 0

    await plugin.handle_save_scene_overrides(
        _patch({"set": {"actions": {"container": {"enabled": True}}}})
    )

    assert agent.emitted == 1
