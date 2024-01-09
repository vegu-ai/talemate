from __future__ import annotations
import dataclasses

from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.emit.async_signals
import talemate.util as util
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage, ReinforcementMessage
from talemate.emit import emit
from talemate.events import GameLoopEvent
from talemate.instance import get_agent

from .base import Agent, set_processing, AgentAction, AgentActionConfig, AgentEmission
from .registry import register

import structlog
import isodate
import time


log = structlog.get_logger("talemate.agents.world_state")

talemate.emit.async_signals.register("agent.world_state.time")

@dataclasses.dataclass
class WorldStateAgentEmission(AgentEmission):
    """
    Emission class for world state agent
    """
    pass

@dataclasses.dataclass
class TimePassageEmission(WorldStateAgentEmission):
    """
    Emission class for time passage
    """
    duration: str
    narrative: str
    

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
        talemate.emit.async_signals.get("game_loop").connect(self.on_game_loop)

    async def advance_time(self, duration:str, narrative:str=None):
        """
        Emit a time passage message
        """
        
        isodate.parse_duration(duration)
        msg_text = narrative or util.iso8601_duration_to_human(duration, suffix=" later")
        message = TimePassageMessage(ts=duration, message=msg_text)
        
        log.debug("world_state.advance_time", message=message)
        self.scene.push_history(message)
        self.scene.emit_status()
        
        emit("time", message)
        
        await talemate.emit.async_signals.get("agent.world_state.time").send(
            TimePassageEmission(agent=self, duration=duration, narrative=msg_text)
        )
        

    async def on_game_loop(self, emission:GameLoopEvent):
        """
        Called when a conversation is generated
        """
        
        if not self.enabled:
            return
        
        await self.update_world_state()
        await self.update_reinforcements()
            

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
            "world_state.request-world-state-v2",
            self.client,
            "analyze_long",
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

        _, marked_items_response = await Prompt.request(
            "world_state.request-world-state-inline-items",
            self.client,
            "analyze_long",
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
    async def analyze_text_and_extract_context(
        self,
        text: str,
        goal: str,
    ):
        
        response = await Prompt.request(
            "world_state.analyze-text-and-extract-context",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "goal": goal,
            }
        )
        
        log.debug("analyze_text_and_extract_context", goal=goal, text=text, response=response)
        
        return response
    
    @set_processing
    async def analyze_text_and_extract_context_via_queries(
        self,
        text: str,
        goal: str,
    ) -> list[str]:
        
        response = await Prompt.request(
            "world_state.analyze-text-and-generate-rag-queries",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "goal": goal,
            }
        )
        
        queries = response.split("\n")
        
        memory_agent = get_agent("memory")
        
        context = await memory_agent.multi_query(queries, iterate=2)
        
        log.debug("analyze_text_and_extract_context_via_queries", goal=goal, text=text, queries=queries, context=context)
        
        return context
    
    @set_processing
    async def analyze_and_follow_instruction(
        self,
        text: str,
        instruction: str,
    ):
        
        response = await Prompt.request(
            "world_state.analyze-text-and-follow-instruction",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "instruction": instruction,
            }
        )
        
        log.debug("analyze_and_follow_instruction", instruction=instruction, text=text, response=response)
        
        return response

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
    
    def _parse_character_sheet(self, response):
        
        data = {}
        for line in response.split("\n"):
            if not line.strip():
                continue
            if not ":" in line:
                break
            name, value = line.split(":", 1)
            data[name.strip()] = value.strip()
        
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
            "create",
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
        
        return self._parse_character_sheet(response)
        
    
    @set_processing
    async def match_character_names(self, names:list[str]):
        
        """
        Attempts to match character names.
        """
        
        _, response = await Prompt.request(
            "world_state.match-character-names",
            self.client,
            "analyze_long",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "names": names,
            }
        )
        
        log.debug("match_character_names", names=names, response=response)
        
        return response
    
    
    @set_processing
    async def update_reinforcements(self, force:bool=False):
        
        """
        Queries due worldstate re-inforcements
        """
        
        for reinforcement in self.scene.world_state.reinforce:
            if reinforcement.due <= 0 or force:
                await self.update_reinforcement(reinforcement.question, reinforcement.character)
            else:
                reinforcement.due -= 1
                
    
    @set_processing
    async def update_reinforcement(self, question:str, character:str=None):
        
        """
        Queries a single re-inforcement
        """
        
        idx, reinforcement = await self.scene.world_state.find_reinforcement(question, character)
        
        if not reinforcement:
            return
        
        answer = await Prompt.request(
            "world_state.update-reinforcements",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "question": reinforcement.question,
                "instructions": reinforcement.instructions or "",
                "character": self.scene.get_character(reinforcement.character) if reinforcement.character else None,
                "answer": reinforcement.answer or "",
            }
        )
        
        reinforcement.answer = answer
        reinforcement.due = reinforcement.interval
        
        source = f"{reinforcement.question}:{reinforcement.character if reinforcement.character else ''}"
        message = ReinforcementMessage(message=answer, source=source)
        
        # remove previous reinforcement message with same question
        self.scene.pop_history(typ="reinforcement", source=source)
        
        log.debug("update_reinforcement", message=message)
        self.scene.push_history(message)
        
        # if reinforcement has a character name set, update the character detail
        if reinforcement.character:
            character = self.scene.get_character(reinforcement.character)
            await character.set_detail(reinforcement.question, answer)
        
        return message  