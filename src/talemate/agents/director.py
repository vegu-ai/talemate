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
                "turns": AgentActionConfig(type="number", label="Turns", description="Number of turns to wait before directing the sceen", value=10, min=0, max=100, step=1),
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
        
    async def on_conversation_before_generate(self, event:ConversationAgentEmission):
        log.info("on_conversation_before_generate", director_enabled=self.enabled)
        if not self.enabled:
            return
        
        await self.direct_scene(event.character)
        
    async def direct_scene(self, character: Character):
        
        if not self.actions["direct"].enabled:
            log.info("direct_scene", skip=True, enabled=self.actions["direct"].enabled)
            return
        
        prompt = self.actions["direct"].config["prompt"].value
        
        if not prompt:
            log.info("direct_scene", skip=True, prompt=prompt)
            return
        
        if self.next_direct % self.actions["direct"].config["turns"].value != 0 or self.next_direct == 0:
            
            log.info("direct_scene", skip=True, next_direct=self.next_direct)
            self.next_direct += 1
            return
        
        self.next_direct = 0
        
        await self.direct_character(character, prompt)
        
    @set_processing
    async def direct_character(self, character: Character, prompt:str):
        
        response = await Prompt.request("director.direct-scene", self.client, "director", vars={
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "prompt": prompt,
            "character": character,
        })
        
        response = response.strip().split("\n")[0].strip()
        
        response += f" (current story goal: {prompt})"
        
        log.info("direct_scene", response=response)
        
        
        message = DirectorMessage(response, source=character.name)
        emit("director", message, character=character)
        
        self.scene.push_history(message)