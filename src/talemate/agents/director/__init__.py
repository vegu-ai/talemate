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
from talemate.character import deactivate_character
from talemate.status import LoadingStatus
from talemate.exceptions import GenerationCancelled

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
    from talemate import Character, Scene

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
        return actions

    def __init__(self, client, **kwargs):
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
        templates: list[str] = None,
        active: bool = True,
        narrate_entry: bool = False,
        narrate_entry_direction: str = "",
        augment_attributes: str = "",
    ) -> Character:
        world_state = instance.get_agent("world_state")
        creator = instance.get_agent("creator")
        narrator = instance.get_agent("narrator")
        memory = instance.get_agent("memory")
        scene: "Scene" = self.scene
        any_attribute_templates = False
        
        loading_status = LoadingStatus(max_steps=None, cancellable=True)
        
        # Start of character creation
        log.debug("persist_character", name=name)


        # Determine the character's name (or clarify if it's already set)
        if determine_name:
            loading_status("Determining character name")
            name = await creator.determine_character_name(name, instructions=content)
            log.debug("persist_character", adjusted_name=name)

        # Create the blank character
        character:Character = self.scene.Character(name=name)

        # Add the character to the scene
        character.color = random_color()
        actor = self.scene.Actor(
            character=character, agent=instance.get_agent("conversation")
        )
        await self.scene.add_actor(actor)
        
        try:

            # Apply any character generation templates
            if templates:
                loading_status("Applying character generation templates")
                templates = scene.world_state_manager.template_collection.collect_all(templates)
                log.debug("persist_character", applying_templates=templates)
                await scene.world_state_manager.apply_templates(
                    templates.values(), 
                    character_name=character.name,
                    information=content
                )
                
                # if any of the templates are attribute templates, then we no longer need to
                # generate a character sheet
                any_attribute_templates = any(template.template_type == "character_attribute" for template in templates.values())
                log.debug("persist_character", any_attribute_templates=any_attribute_templates)
                
                if any_attribute_templates and augment_attributes:
                    log.debug("persist_character", augmenting_attributes=augment_attributes)
                    loading_status("Augmenting character attributes")
                    additional_attributes = await world_state.extract_character_sheet(
                        name=name,
                        text=content,
                        augmentation_instructions=augment_attributes
                    )
                    character.base_attributes.update(additional_attributes)

            # Generate a character sheet if there are no attribute templates
            if not any_attribute_templates:
                loading_status("Generating character sheet")
                log.debug("persist_character", extracting_character_sheet=True)
                if not attributes:
                    attributes = await world_state.extract_character_sheet(
                        name=name, text=content
                    )
                else:
                    attributes = world_state._parse_character_sheet(attributes)

                log.debug("persist_character", attributes=attributes)
                character.base_attributes = attributes
                
            # Generate a description for the character
            loading_status("Generating character description")
            description = await creator.determine_character_description(character, information=content)
            character.description = description
            log.debug("persist_character", description=description)

            # Generate a dialogue instructions for the character
            loading_status("Generating acting instructions")
            dialogue_instructions = await creator.determine_character_dialogue_instructions(
                character,
                information=content
            )
            character.dialogue_instructions = dialogue_instructions
            log.debug(
                "persist_character", dialogue_instructions=dialogue_instructions
            )
            
            # Narrate the character's entry if the option is selected
            if active and narrate_entry:
                loading_status("Narrating character entry")
                is_present = await world_state.is_character_present(name)
                if not is_present:
                    await narrator.action_to_narration(
                        "narrate_character_entry",
                        emit_message=True,
                        character=character,
                        narrative_direction=narrate_entry_direction
                    )
            
            # Deactivate the character if not active
            if not active:
                await deactivate_character(scene, character)
                
            # Commit the character's details to long term memory
            await character.commit_to_memory(memory)
            self.scene.emit_status()
            self.scene.world_state.emit()
            
            loading_status.done(message=f"{character.name} added to scene", status="success")
            return character
        except GenerationCancelled:
            loading_status.done(message="Character creation cancelled", status="idle")
            await scene.remove_actor(actor)
        except Exception as e:
            loading_status.done(message="Character creation failed", status="error")
            await scene.remove_actor(actor)
            log.exception("Error persisting character", error=e)

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