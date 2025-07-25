from __future__ import annotations

import structlog

from talemate.emit import emit
from talemate.scene_message import DirectorMessage, Flags

from talemate.agents.base import Agent, AgentAction, AgentActionConfig
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin
from talemate.client import ClientBase

from .guide import GuideSceneMixin
from .generate_choices import GenerateChoicesMixin
from .legacy_scene_instructions import LegacySceneInstructionsMixin
from .auto_direct import AutoDirectMixin
from .websocket_handler import DirectorWebsocketHandler
from .character_management import CharacterManagementMixin
import talemate.agents.director.nodes  # noqa: F401

log = structlog.get_logger("talemate.agent.director")


@register()
class DirectorAgent(
    GuideSceneMixin,
    MemoryRAGMixin,
    GenerateChoicesMixin,
    AutoDirectMixin,
    LegacySceneInstructionsMixin,
    CharacterManagementMixin,
    Agent,
):
    agent_type = "director"
    verbose_name = "Director"
    websocket_handler = DirectorWebsocketHandler

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "direct": AgentAction(
                enabled=True,
                can_be_disabled=False,
                label="Direct",
                description="Direction settings",
                config={
                    "actor_direction_mode": AgentActionConfig(
                        type="text",
                        label="Actor Direction Mode",
                        description="The mode to use when directing actors",
                        value="direction",
                        choices=[
                            {
                                "label": "Direction",
                                "value": "direction",
                            },
                            {
                                "label": "Inner Monologue",
                                "value": "internal_monologue",
                            },
                        ],
                    ),
                },
            ),
        }
        MemoryRAGMixin.add_actions(actions)
        GenerateChoicesMixin.add_actions(actions)
        GuideSceneMixin.add_actions(actions)
        AutoDirectMixin.add_actions(actions)
        CharacterManagementMixin.add_actions(actions)
        return actions

    def __init__(self, client: ClientBase | None = None, **kwargs):
        self.is_enabled = True
        self.client = client
        self.next_direct_character = {}
        self.next_direct_scene = 0
        self.actions = DirectorAgent.init_actions()

    @property
    def enabled(self):
        return self.is_enabled

    @property
    def has_toggle(self):
        return True

    @property
    def experimental(self):
        return True

    @property
    def actor_direction_mode(self):
        return self.actions["direct"].config["actor_direction_mode"].value

    async def log_action(
        self, action: str, action_description: str, console_only: bool = False
    ):
        message = DirectorMessage(
            message=action_description,
            action=action,
            flags=Flags.HIDDEN if console_only else Flags.NONE,
        )
        self.scene.push_history(message)
        emit("director", message)

    def inject_prompt_paramters(
        self, prompt_param: dict, kind: str, agent_function_name: str
    ):
        if prompt_param.get("extra_stopping_strings") is None:
            prompt_param["extra_stopping_strings"] = []

    def allow_repetition_break(
        self, kind: str, agent_function_name: str, auto: bool = False
    ):
        return False
