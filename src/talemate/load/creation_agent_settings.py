"""Request-owned settings, effective during creation and persisted on success."""

import asyncio
import copy
import uuid
from pathlib import Path

from talemate.instance import AGENTS
from talemate.scene_agent_settings import SceneAgentSettings, agent_settings_dir
from talemate.scene_agent_settings_patch import (
    apply_scene_override_plan,
    plan_scene_override_patch,
)


class CreationAgentSettings:
    def __init__(self, values: dict, is_current):
        self.is_current = is_current
        self.scene = None
        self.overlay = None
        self.filename = f"creation-{uuid.uuid4().hex}.json"
        self.plans = {}
        for name, override in values.items():
            agent = AGENTS.get(name)
            if agent is None:
                raise ValueError(f"Unknown creation settings agent: {name}")
            plan = plan_scene_override_patch(agent, {"set": override})
            if plan["stripped"]:
                raise ValueError(f"Creation settings are not overridable: {name}")
            for kind, action, _, _ in plan["sets"]:
                if (
                    kind == "enabled"
                    and not agent.actions[action].enabled_scene_overridable
                ):
                    raise ValueError(
                        f"Creation action is not overridable: {name}.{action}"
                    )
            self.plans[name] = plan

    def check_current(self):
        task = asyncio.current_task()
        if not self.is_current() or (task is not None and task.cancelling()):
            raise asyncio.CancelledError()

    def install(self, scene):
        self.check_current()
        if self.scene is not None:
            raise ValueError("Creation settings have already been installed")
        self.scene = scene
        self.overlay = SceneAgentSettings(
            filepath=Path(self.filename),
            pending=True,
            agents=copy.deepcopy(scene.agent_overrides.agents)
            if scene.agent_overrides is not None
            else {},
        )
        for name, plan in self.plans.items():
            if AGENTS[name].scene is not scene:
                raise ValueError(
                    f"Creation agent is not bound to the new scene: {name}"
                )
            apply_scene_override_plan(self.overlay, name, plan)
        scene.agent_overrides = self.overlay
        scene.agent_settings_file = self.filename
        scene._agent_settings_opted_out = False

    async def persist(self, scene):
        self.check_current()
        if self.scene is not scene or scene.agent_overrides is not self.overlay:
            raise ValueError("Creation settings do not belong to the loaded scene")
        self.overlay.filepath = agent_settings_dir(scene.save_dir) / self.filename
        try:
            self.overlay.pending = False
            await self.overlay.write_to_file()
            self.check_current()
        except BaseException:
            self.overlay.pending = True
            self.overlay.filepath.unlink(missing_ok=True)
            raise
