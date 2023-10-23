from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.data_objects as data_objects
import talemate.emit.async_signals
import talemate.util as util
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage

from .base import Agent, set_processing, AgentAction, AgentActionConfig
from .registry import register

import structlog

import time
import re

if TYPE_CHECKING:
    from talemate.agents.conversation import ConversationAgentEmission
    

log = structlog.get_logger("talemate.agents.world_state")

@register()
class WorldStateAgent(Agent):
    """
    An agent that handles world state related tasks.
    """

    agent_type = "world_state"
    verbose_name = "World State"

    def __init__(self, client, **kwargs):
        self.client = client
        self.is_enabled = True
        self.actions = {
            "update_world_state": AgentAction(enabled=True, label="Update world state", description="Will attempt to update the world state based on the current scene. Runs automatically after AI dialogue (n turns).", config={
                "turns": AgentActionConfig(type="number", label="Turns", description="Number of turns to wait before updating the world state.", value=5, min=1, max=100, step=1)
            }),
        }
        
        self.next_update = 0
        
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
        talemate.emit.async_signals.get("agent.conversation.generated").connect(self.on_conversation_generated)

    async def on_conversation_generated(self, emission:ConversationAgentEmission):
        """
        Called when a conversation is generated
        """
        
        if not self.enabled:
            return
        
        for _ in emission.generation:
            await self.update_world_state()
            

    async def update_world_state(self):
        if not self.enabled:
            return
        
        if not self.actions["update_world_state"].enabled:
            return
        
        log.debug("update_world_state", next_update=self.next_update, turns=self.actions["update_world_state"].config["turns"].value)
        
        scene = self.scene
        
        if self.next_update % self.actions["update_world_state"].config["turns"].value != 0 or self.next_update == 0:
            self.next_update += 1
            return
        
        self.next_update = 0
        await scene.world_state.request_update()
        

    @set_processing
    async def request_world_state(self):

        t1 = time.time()

        _, world_state = await Prompt.request(
            "world_state.request-world-state",
            self.client,
            "analyze",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "object_type": "character",
                "object_type_plural": "characters",
            }
        )
        
        self.scene.log.debug("request_world_state", response=world_state, time=time.time() - t1)
        
        return world_state

    @set_processing
    async def request_world_state_inline(self):
        
        """
        EXPERIMENTAL, Overall the one shot request seems about as coherent as the inline request, but the inline request is is about twice as slow and would need to run on every dialogue line.
        """

        t1 = time.time()

        # first, we need to get the marked items (objects etc.)

        marked_items_response = await Prompt.request(
            "world_state.request-world-state-inline-items",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            }
        )
        
        self.scene.log.debug("request_world_state_inline", marked_items=marked_items_response, time=time.time() - t1)
        
        return marked_items_response

    @set_processing
    async def analyze_time_passage(
        self,
        text: str,
    ):
        
        response = await Prompt.request(
            "world_state.analyze-time-passage",
            self.client,
            "analyze_freeform_short",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
            }
        )
        
        duration = response.split("\n")[0].split(" ")[0].strip()
        
        if not duration.startswith("P"):
            duration = "P"+duration
        
        return duration

    @set_processing
    async def analyze_text_and_answer_question(
        self,
        text: str,
        query: str,
    ):
        
        response = await Prompt.request(
            "world_state.analyze-text-and-answer-question",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "query": query,
            }
        )
        
        log.debug("analyze_text_and_answer_question", query=query, text=text, response=response)
        
        return response
    
    @set_processing
    async def identify_characters(
        self,
        text: str = None,
    ):
        
        """
        Attempts to identify characters in the given text.
        """
        
        _, data = await Prompt.request(
            "world_state.identify-characters",
            self.client,
            "analyze",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
            }
        )
        
        log.debug("identify_characters", text=text, data=data)
        
        return data
    
    @set_processing
    async def extract_character_sheet(
        self,
        name:str,
        text:str = None,
    ):
        
        """
        Attempts to extract a character sheet from the given text.
        """
        
        response = await Prompt.request(
            "world_state.extract-character-sheet",
            self.client,
            "analyze_creative",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "name": name,
            }
        )
        
        # loop through each line in response and if it contains a : then extract
        # the left side as an attribute name and the right side as the value
        #
        # break as soon as a non-empty line is found that doesn't contain a :
        
        data = {}
        for line in response.split("\n"):
            if not line.strip():
                continue
            if not ":" in line:
                break
            name, value = line.split(":", 1)
            data[name.strip()] = value.strip()
        
        return data