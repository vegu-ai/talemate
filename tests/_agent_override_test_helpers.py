"""
Shared stubs for the per-scene agent override tests
(tests/server/test_agent_config_overrides.py,
tests/server/test_websocket_disconnect.py).

Both files need the same agent shape: a real ``Agent`` subclass with one
container action holding an overridable field (``fmt``) and a field the
schema forces to non-overridable (``api_key``, a password), so the real
override plumbing — payload building, resolvers, save path — runs against
it. The agent type differs per file, since each registers its stub into the
process-wide ``talemate.instance.AGENTS`` under a test-only key, hence the
class factory.
"""

from __future__ import annotations

from pathlib import Path

from talemate.agents.base import Agent, AgentAction, AgentActionConfig
from talemate.scene_agent_settings import SceneAgentSettings

# turns the container action off and overrides `fmt`
CONTAINER_OVERRIDE = {
    "actions": {
        "container": {
            "enabled": False,
            "config": {"fmt": {"value": "scene-fmt"}},
        }
    }
}


def override_agent_class(type_name: str) -> type[Agent]:
    """An ``Agent`` subclass answering to ``type_name``.

    ``emit_status`` counts calls in ``emitted`` instead of reaching the
    websocket.
    """

    class _OverrideAgent(Agent):
        agent_type = type_name
        verbose_name = "Override Test"
        requires_llm_client = False

        def __init__(self, scene):
            self.actions = {
                "container": AgentAction(
                    enabled=True,
                    label="Container",
                    container=True,
                    can_be_disabled=True,
                    config={
                        "fmt": AgentActionConfig(
                            type="text", label="fmt", value="global-fmt"
                        ),
                        "api_key": AgentActionConfig(
                            type="password", label="api key", value="global-key"
                        ),
                    },
                )
            }
            self.scene = scene
            self.processing = 0
            self.emitted = 0

        async def emit_status(self, processing: bool = None):
            self.emitted += 1

    return _OverrideAgent


def scene_overlay(
    filepath: Path, agent_type: str, override: dict | None = None
) -> SceneAgentSettings:
    """A real overlay holding one agent's overrides, defaulting to
    ``CONTAINER_OVERRIDE``."""
    overrides = SceneAgentSettings(filepath=filepath)
    overrides.replace_agent_overrides(agent_type, override or CONTAINER_OVERRIDE)
    return overrides
