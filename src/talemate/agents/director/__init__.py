from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from talemate.emit import emit
from talemate.scene_message import DirectorMessage, Flags

from talemate.agents.base import Agent, AgentAction, AgentActionConfig
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin
from talemate.client import ClientBase
from talemate.game.focal.schema import Call
from talemate.game.engine.nodes.core import GraphState
from .guide import GuideSceneMixin
from .generate_choices import GenerateChoicesMixin
from .legacy_scene_instructions import LegacySceneInstructionsMixin
from .auto_direct import AutoDirectMixin
from .websocket_handler import DirectorWebsocketHandler
from .chat.mixin import DirectorChatMixin
from .character_management import CharacterManagementMixin
from .scene_direction.mixin import SceneDirectionMixin
import talemate.agents.director.nodes  # noqa: F401

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.agent.director")


@register()
class DirectorAgent(
    DirectorChatMixin,
    SceneDirectionMixin,
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
                        label="Character Direction Style",
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
                    "direction_stickiness": AgentActionConfig(
                        type="number",
                        label="Direction Stickiness",
                        description="How many scene messages to look back for a character direction. Higher values make directions persist longer. Directions are always cleared on time passage.",
                        value=5,
                        min=1,
                        max=20,
                        step=1,
                    ),
                },
            ),
        }
        MemoryRAGMixin.add_actions(actions)
        GenerateChoicesMixin.add_actions(actions)
        GuideSceneMixin.add_actions(actions)
        AutoDirectMixin.add_actions(actions)
        CharacterManagementMixin.add_actions(actions)
        DirectorChatMixin.add_actions(actions)
        SceneDirectionMixin.add_scene_direction_actions(actions)
        return actions

    @classmethod
    async def init_nodes(cls, scene: "Scene", state: GraphState):
        await super(DirectorAgent, cls).init_nodes(scene, state)
        await DirectorChatMixin.chat_init_nodes(scene, state)

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

    @property
    def direction_stickiness(self):
        return int(self.actions["direct"].config["direction_stickiness"].value)

    async def log_function_call(self, call: Call):
        log.debug("director.log_function_call", call=call)
        message = DirectorMessage(
            message=f"Called {call.name}",
            action=call.name,
            flags=Flags.HIDDEN,
            subtype="function_call",
        )
        emit("director", message, data={"function_call": call.model_dump()})

    async def log_action(
        self, action: str, action_description: str, console_only: bool = False
    ):
        message = DirectorMessage(
            message=action_description,
            action=action,
            flags=Flags.HIDDEN if console_only else Flags.NONE,
        )
        await self.scene.push_history(message)
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
