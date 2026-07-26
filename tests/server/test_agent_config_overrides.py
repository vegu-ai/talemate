"""Unit tests for `AgentConfigPlugin.handle_save_scene_overrides`.

Focus: the failure paths. The frontend (agent modal, agent-panel quick-toggle
chips) updates its copy of the overlay optimistically, so a refused save has to
leave both the running scene and the frontend on the stored values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import talemate.instance as instance
from talemate.agents.base import Agent, AgentAction
from talemate.scene_agent_settings import SceneAgentSettings
from talemate.server.agent_config import AgentConfigPlugin

AGENT_TYPE = "override-test"


class _OverrideAgent(Agent):
    agent_type = AGENT_TYPE
    verbose_name = "Override Test"
    requires_llm_client = False

    def __init__(self, scene):
        self.actions = {
            "container": AgentAction(
                enabled=True,
                label="Container",
                container=True,
                can_be_disabled=True,
            )
        }
        self.scene = scene
        self.processing = 0
        self.emitted = 0

    async def emit_status(self, processing: bool = None):
        self.emitted += 1


class _Scene:
    """Minimal stand-in for the bits the handler touches."""

    def __init__(self, save_dir: Path, filename="scene.json", project_name="proj"):
        self.save_dir = str(save_dir)
        self.filename = filename
        self.project_name = project_name
        self.name = "Test Scene"
        self.agent_overrides = None
        self.agent_settings_file = None
        self.auto_save = True
        self.saved = True
        self._agent_settings_opted_out = False
        self.saves = 0

    async def save(self, auto=False):
        self.saves += 1

    def emit_status(self, **kwargs):
        pass


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


@pytest.mark.asyncio
async def test_first_save_links_file_and_saves_the_scene(wired):
    plugin, scene, agent, handler = wired

    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))

    assert scene.agent_settings_file == "agent-settings.json"
    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is False
    # linking writes `agent_settings_file` into the scene, so it is persisted
    assert scene.saves == 1


@pytest.mark.asyncio
async def test_repeat_save_does_not_touch_the_scene(wired):
    plugin, scene, agent, handler = wired
    await plugin.handle_save_scene_overrides(_payload(False, "agent-settings.json"))
    scene.saves = 0

    # what a quick-toggle chip flip sends: no filename, overlay already linked
    await plugin.handle_save_scene_overrides(_payload(True))

    assert scene.agent_overrides.get_enabled(AGENT_TYPE, "container") is True
    assert scene.saves == 0
    assert scene.saved is True


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
