"""Unit tests for talemate.game.engine.nodes.agent.

Focused on `ToggleAgentAction`, whose contract depends on whether the target
action declares `can_be_disabled` (issue #174): a disableable action is
toggled and reports the effective value, a non-disableable one is refused
outright rather than silently doing nothing.
"""

from __future__ import annotations

import pytest

from _node_test_helpers import run_node

from talemate.agents.base import Agent, AgentAction
from talemate.game.engine.nodes.agent import ToggleAgentAction
from talemate.game.engine.nodes.core import InputValueError
from talemate.scene_agent_settings import SceneAgentSettings
from talemate.tale_mate import Scene


class _TogglableAgent(Agent):
    """Real Agent subclass carrying one action of each kind."""

    agent_type = "toggle-node-test"
    verbose_name = "Toggle Node Test"
    requires_llm_client = False

    def __init__(self, scene=None):
        self.actions = {
            "toggleable": AgentAction(
                enabled=True,
                label="Toggleable",
                container=True,
                can_be_disabled=True,
            ),
            "locked": AgentAction(
                enabled=True,
                label="Locked",
                container=True,
                can_be_disabled=False,
            ),
        }
        self.scene = scene
        self.processing = 0


@pytest.mark.asyncio
async def test_toggles_a_disableable_action_and_reports_it():
    agent = _TogglableAgent()
    outputs = await run_node(
        ToggleAgentAction(),
        inputs={"agent": agent, "action_name": "toggleable", "enabled": False},
    )
    assert agent.actions["toggleable"].enabled is False
    assert outputs["enabled"] is False
    assert outputs["action_name"] == "toggleable"


@pytest.mark.asyncio
async def test_refuses_to_toggle_a_non_disableable_action():
    """Silently doing nothing would leave a graph author with no signal."""
    agent = _TogglableAgent()
    with pytest.raises(InputValueError, match="cannot be toggled") as exc:
        await run_node(
            ToggleAgentAction(),
            inputs={"agent": agent, "action_name": "locked", "enabled": False},
        )
    # names the agent, not its object repr — this message is user-facing
    assert "toggle-node-test" in str(exc.value)
    assert "object at 0x" not in str(exc.value)
    assert agent.actions["locked"].enabled is True


@pytest.mark.asyncio
async def test_reports_the_effective_value_when_a_scene_override_takes_the_write(
    tmp_path,
):
    """The write routes to the active override, leaving the global flag alone —
    so the output reflects the override, not the agent's global setting."""
    overrides = SceneAgentSettings(filepath=tmp_path / "x.json")
    overrides.set_enabled("toggle-node-test", "toggleable", True)
    scene = Scene()
    scene.agent_overrides = overrides
    agent = _TogglableAgent(scene=scene)

    outputs = await run_node(
        ToggleAgentAction(),
        inputs={"agent": agent, "action_name": "toggleable", "enabled": False},
    )

    assert overrides.get_enabled("toggle-node-test", "toggleable") is False
    # global flag untouched — the override took the write
    assert agent.actions["toggleable"].enabled is True
    assert outputs["enabled"] is False


@pytest.mark.asyncio
async def test_unknown_action_raises():
    agent = _TogglableAgent()
    with pytest.raises(InputValueError, match="Could not find action"):
        await run_node(
            ToggleAgentAction(),
            inputs={"agent": agent, "action_name": "nope", "enabled": False},
        )
