from __future__ import annotations

import asyncio
import re
import random
import structlog
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.util as util
from talemate.emit import wait_for_input, emit
import talemate.emit.async_signals
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage, DirectorMessage
from talemate.automated_action import AutomatedAction
import talemate.automated_action as automated_action
from talemate.agents.conversation import ConversationAgentEmission
from .registry import register
from .base import set_processing, AgentAction, AgentActionConfig, Agent
from talemate.events import GameLoopActorIterEvent
import talemate.instance as instance

if TYPE_CHECKING:
    from talemate import Actor, Character, Player, Scene

log = structlog.get_logger("talemate")

@register()
class DirectorAgent(Agent):
    agent_type = "director"
    verbose_name = "Director"
    
    def __init__(self, client, **kwargs):
        self.is_enabled = False
        self.client = client
        self.next_direct = 0
        self.actions = {
            "direct": AgentAction(enabled=True, label="Direct", description="Will attempt to direct the scene. Runs automatically after AI dialogue (n turns).", config={
                "turns": AgentActionConfig(type="number", label="Turns", description="Number of turns to wait before directing the sceen", value=5, min=1, max=100, step=1),
                "prompt": AgentActionConfig(type="text", label="Instructions", description="Instructions to the director", value="", scope="scene")
            }),
        }
        
    @property
    def enabled(self):
        return self.is_enabled
    
    @property
    def has_toggle(self):
        return True
        
    @property
    def experimental(self):
        return True
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.conversation.before_generate").connect(self.on_conversation_before_generate)
        talemate.emit.async_signals.get("game_loop_actor_iter").connect(self.on_player_dialog)
        
    async def on_conversation_before_generate(self, event:ConversationAgentEmission):
        log.info("on_conversation_before_generate", director_enabled=self.enabled)
        if not self.enabled:
            return
        
        await self.direct(event.character)
    
    async def on_player_dialog(self, event:GameLoopActorIterEvent):
    
        if not self.enabled:
            return
        
        if not self.scene.game_state.has_scene_instructions:
            return

        if not event.actor.character.is_player:
            return
        
        if event.game_loop.had_passive_narration:
            log.debug("director.on_player_dialog", skip=True, had_passive_narration=event.game_loop.had_passive_narration)
            return

        event.game_loop.had_passive_narration = await self.direct(None)
        
    async def direct(self, character: Character) -> bool:
        
        if not self.actions["direct"].enabled:
            return False
        
        prompt = self.actions["direct"].config["prompt"].value
        
        # TODO: old way, will be replaced with game_state.director_instructions
        if not prompt and character:
            log.info("direct_scene", skip=True, reason="no prompt for character")
            return False
        
        always_direct = (not self.scene.npc_character_names)
        
        if self.next_direct % self.actions["direct"].config["turns"].value != 0 or self.next_direct == 0:
            if not always_direct:
                log.info("direct_scene", skip=True, next_direct=self.next_direct)
                self.next_direct += 1
                return False
            
        self.next_direct = 0
        
        await self.direct_scene(character, prompt)
        return True
        
    @set_processing
    async def direct_scene(self, character: Character, prompt:str):
        
        if not character and self.scene.game_state.game_won:
            # we are not directing a character, and the game has been won
            # so we don't need to direct the scene any further
            return
        
        response = await Prompt.request("director.direct-scene", self.client, "director", vars={
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "prompt": prompt,
            "character": character,
            "player_character": self.scene.get_player_character(),
            "game_state": self.scene.game_state,
        })
        
        if "#" in response:
            response = response.split("#")[0]
        
        log.info("direct_scene", character=character, prompt=prompt, response=response)
        
        if character:
            response = response.strip().split("\n")[0].strip()
            response += f" (current story goal: {prompt})"
            message = DirectorMessage(response, source=character.name)
            emit("director", message, character=character)
            self.scene.push_history(message)
        else:
            response = response.split('"')[0].strip()
            response = util.strip_partial_sentences(response).strip()
            response = response.replace('*','').strip()
            
            if not response:
                return
            
            response = f"*{response}*"
            message = NarratorMessage(response, source="__director__")
            emit("narrator", message)
            
            self.scene.push_history(message)        


    @set_processing
    async def persist_character(
        self, 
        name:str, 
        content:str = None,
        attributes:str = None,
    ):
        
        world_state = instance.get_agent("world_state")
        creator = instance.get_agent("creator")
        self.scene.log.debug("persist_character", name=name)

        character = self.scene.Character(name=name)
        character.color = random.choice(['#F08080', '#FFD700', '#90EE90', '#ADD8E6', '#DDA0DD', '#FFB6C1', '#FAFAD2', '#D3D3D3', '#B0E0E6', '#FFDEAD'])

        if not attributes:
            attributes = await world_state.extract_character_sheet(name=name, text=content)
        else:
            attributes = world_state._parse_character_sheet(attributes)
        
        self.scene.log.debug("persist_character", attributes=attributes)

        character.base_attributes = attributes

        description = await creator.determine_character_description(character)

        character.description = description

        self.scene.log.debug("persist_character", description=description)

        actor = self.scene.Actor(character=character, agent=instance.get_agent("conversation"))

        await self.scene.add_actor(actor)
        self.emit("system", f"Added character {name} to the scene.")
        self.scene.emit_status()
        
    @set_processing
    async def update_content_context(self, content:str=None, extra_choices:list[str]=None):
        
        if not content:
            content = "\n".join(self.scene.context_history(sections=False, min_dialogue=25, budget=2048))
            
        response = await Prompt.request("world_state.determine-content-context", self.client, "analyze_freeform", vars={
            "content": content,
            "extra_choices": extra_choices or [],
        })
        
        self.scene.context = response.strip()
        self.scene.emit_status()
        
        
    def inject_prompt_paramters(self, prompt_param: dict, kind: str, agent_function_name: str):
        log.debug("inject_prompt_paramters", prompt_param=prompt_param, kind=kind, agent_function_name=agent_function_name)
        character_names = [f"\n{c.name}:" for c in self.scene.get_characters()]
        if prompt_param.get("extra_stopping_strings") is None:
            prompt_param["extra_stopping_strings"] = []
        prompt_param["extra_stopping_strings"] += character_names + ["#"]
        if agent_function_name == "update_content_context":
            prompt_param["extra_stopping_strings"] += ["\n"]
        
    def allow_repetition_break(self, kind: str, agent_function_name: str, auto:bool=False):
        return True