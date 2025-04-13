from __future__ import annotations

import random
from typing import TYPE_CHECKING, List

import structlog

import talemate.emit.async_signals
import talemate.instance as instance
from talemate.agents.conversation import ConversationAgentEmission
from talemate.emit import emit
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage
from talemate.util import random_color

from talemate.agents.base import Agent, AgentAction, AgentActionConfig, set_processing
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin

from .guide import GuideSceneMixin
from .generate_choices import GenerateChoicesMixin
from .legacy_scene_instructions import LegacySceneInstructionsMixin
from .auto_direct import AutoDirectMixin
from .websocket_handler import DirectorWebsocketHandler

import talemate.agents.director.nodes

if TYPE_CHECKING:
    from talemate import Character

log = structlog.get_logger("talemate.agent.director")


@register()
class DirectorAgent(
    GuideSceneMixin,
    MemoryRAGMixin,
    GenerateChoicesMixin,
    AutoDirectMixin,
    LegacySceneInstructionsMixin,
    Agent
):
    agent_type = "director"
    verbose_name = "Director"
    websocket_handler = DirectorWebsocketHandler

    def __init__(self, client, **kwargs):
        self.is_enabled = True
        self.client = client
        self.next_direct_character = {}
        self.next_direct_scene = 0
        self.actions = {
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
        
        MemoryRAGMixin.add_actions(self)
        GenerateChoicesMixin.add_actions(self)
        GuideSceneMixin.add_actions(self)
        AutoDirectMixin.add_actions(self)

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

    @set_processing
    async def persist_characters_from_worldstate(
        self, exclude: list[str] = None
    ) -> List[Character]:
        created_characters = []

        for character_name in self.scene.world_state.characters.keys():

            if exclude and character_name.lower() in exclude:
                continue

            if character_name in self.scene.character_names:
                continue

            character = await self.persist_character(name=character_name)

            created_characters.append(character)

        self.scene.emit_status()

        return created_characters

    @set_processing
    async def persist_character(
        self,
        name: str,
        content: str = None,
        attributes: str = None,
        determine_name: bool = True,
    ) -> Character:
        world_state = instance.get_agent("world_state")
        creator = instance.get_agent("creator")

        self.scene.log.debug("persist_character", name=name)

        if determine_name:
            name = await creator.determine_character_name(name)
            self.scene.log.debug("persist_character", adjusted_name=name)

        character = self.scene.Character(name=name)
        character.color = random_color()

        if not attributes:
            attributes = await world_state.extract_character_sheet(
                name=name, text=content
            )
        else:
            attributes = world_state._parse_character_sheet(attributes)

        self.scene.log.debug("persist_character", attributes=attributes)

        character.base_attributes = attributes

        description = await creator.determine_character_description(character)

        character.description = description

        self.scene.log.debug("persist_character", description=description)

        dialogue_instructions = await creator.determine_character_dialogue_instructions(
            character
        )

        character.dialogue_instructions = dialogue_instructions

        self.scene.log.debug(
            "persist_character", dialogue_instructions=dialogue_instructions
        )

        actor = self.scene.Actor(
            character=character, agent=instance.get_agent("conversation")
        )

        await self.scene.add_actor(actor)
        self.scene.emit_status()

        return character

    async def log_action(self, action: str, action_description: str):
        message = DirectorMessage(message=action_description, action=action)
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