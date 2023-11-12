from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional, Union
import structlog
import random
import talemate.util as util
from talemate.emit import emit
import talemate.emit.async_signals
from talemate.prompts import Prompt
from talemate.agents.base import set_processing, Agent, AgentAction, AgentActionConfig
from talemate.agents.world_state import TimePassageEmission
from talemate.scene_message import NarratorMessage
from talemate.events import GameLoopActorIterEvent
import talemate.client as client

from .registry import register

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Player

log = structlog.get_logger("talemate.agents.narrator")

@register()
class NarratorAgent(Agent):
    
    """
    Handles narration of the story
    """
    
    agent_type = "narrator"
    verbose_name = "Narrator"
    
    def __init__(
        self,
        client: client.TaleMateClient,
        **kwargs,
    ):
        self.client = client
        
        # agent actions
        
        self.actions = {
            "narrate_time_passage": AgentAction(enabled=True, label="Narrate Time Passage", description="Whenever you indicate passage of time, narrate right after"),
            "narrate_dialogue": AgentAction(
                enabled=True, 
                label="Narrate Dialogue", 
                description="Narrator will get a chance to narrate after every line of dialogue",
                config = {
                    "ai_dialog": AgentActionConfig(
                        type="number",
                        label="AI Dialogue", 
                        description="Chance to narrate after every line of dialogue, 1 = always, 0 = never",
                        value=0.3,
                        min=0.0,
                        max=1.0,
                        step=0.1,
                    ),
                    "player_dialog": AgentActionConfig(
                        type="number",
                        label="Player Dialogue", 
                        description="Chance to narrate after every line of dialogue, 1 = always, 0 = never",
                        value=0.3,
                        min=0.0,
                        max=1.0,
                        step=0.1,
                    ),
                }
            ),
        }
        
    def clean_result(self, result):
        
        """
        Cleans the result of a narration
        """
        
        result = result.strip().strip(":").strip()
        
        if "#" in result:
            result = result.split("#")[0]
        
        cleaned = []
        for line in result.split("\n"):
            if ":" in line.strip():
                break
            cleaned.append(line)

        result = "\n".join(cleaned)
        result = util.strip_partial_sentences(result)
        return result

    def connect(self, scene):
        
        """
        Connect to signals
        """
        
        super().connect(scene)
        talemate.emit.async_signals.get("agent.world_state.time").connect(self.on_time_passage)
        talemate.emit.async_signals.get("game_loop_actor_iter").connect(self.on_dialog)

    async def on_time_passage(self, event:TimePassageEmission):
        
        """
        Handles time passage narration, if enabled
        """
        
        if not self.actions["narrate_time_passage"].enabled:
            return
        
        response = await self.narrate_time_passage(event.duration, event.narrative)
        narrator_message = NarratorMessage(response, source=f"narrate_time_passage:{event.duration};{event.narrative}")
        emit("narrator", narrator_message)
        self.scene.push_history(narrator_message)
        
    async def on_dialog(self, event:GameLoopActorIterEvent):
        
        """
        Handles dialogue narration, if enabled
        """
        
        if not self.actions["narrate_dialogue"].enabled:
            return
        
        narrate_on_ai_chance = random.random() < self.actions["narrate_dialogue"].config["ai_dialog"].value
        narrate_on_player_chance = random.random() < self.actions["narrate_dialogue"].config["player_dialog"].value
        
        log.debug("narrate on dialog", narrate_on_ai_chance=narrate_on_ai_chance, narrate_on_player_chance=narrate_on_player_chance)
        
        if event.actor.character.is_player and not narrate_on_player_chance:
            return
        
        if not event.actor.character.is_player and not narrate_on_ai_chance:
            return
        
        response = await self.narrate_after_dialogue(event.actor)
        narrator_message = NarratorMessage(response, source=f"narrate_dialogue:{event.actor.character.name}")
        emit("narrator", narrator_message)
        self.scene.push_history(narrator_message)

    @set_processing
    async def narrate_scene(self):
        """
        Narrate the scene
        """

        response = await Prompt.request(
            "narrator.narrate-scene",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            }
        )
        
        response = response.strip("*")
        response = util.strip_partial_sentences(response)
        
        response = f"*{response.strip('*')}*"

        return response

    @set_processing
    async def progress_story(self, narrative_direction:str=None):
        """
        Narrate the scene
        """

        scene = self.scene
        director = scene.get_helper("director").agent
        pc = scene.get_player_character()
        npcs = list(scene.get_npc_characters())
        npc_names=  ", ".join([npc.name for npc in npcs])
        
        #summarized_history = await scene.summarized_dialogue_history(
        #    budget = self.client.max_token_length - 300,
        #    min_dialogue = 50,
        #)
        
        #augmented_context = await self.augment_context()

        if narrative_direction is None:
            #narrative_direction = await director.direct_narrative(
            #    scene.context_history(budget=self.client.max_token_length - 500, min_dialogue=20),
            #)
            narrative_direction = "Slightly move the current scene forward."
        
        self.scene.log.info("narrative_direction", narrative_direction=narrative_direction)

        response = await Prompt.request(
            "narrator.narrate-progress",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                #"summarized_history": summarized_history,
                #"augmented_context": augmented_context,
                "max_tokens": self.client.max_token_length,
                "narrative_direction": narrative_direction,
                "player_character": pc,
                "npcs": npcs,
                "npc_names": npc_names,
            }
        )

        self.scene.log.info("progress_story", response=response)

        response = self.clean_result(response.strip())

        response = response.strip().strip("*")
        response = f"*{response}*"
        if response.count("*") % 2 != 0:
            response = response.replace("*", "")
            response = f"*{response}*"
        
        return response

    @set_processing
    async def narrate_query(self, query:str, at_the_end:bool=False, as_narrative:bool=True):
        """
        Narrate a specific query
        """
        response = await Prompt.request(
            "narrator.narrate-query",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "query": query,
                "at_the_end": at_the_end,
                "as_narrative": as_narrative,
            }
        )

        response = self.clean_result(response.strip())
        if as_narrative:
            response = f"*{response}*"
        
        return response

    @set_processing
    async def narrate_character(self, character):
        """
        Narrate a specific character
        """

        budget = self.client.max_token_length - 300

        memory_budget = min(int(budget * 0.05), 200)
        memory = self.scene.get_helper("memory").agent
        query = [
            f"What does {character.name} currently look like?",
            f"What is {character.name} currently wearing?",
        ]
        memory_context = await memory.multi_query(
            query, iterate=1, max_tokens=memory_budget
        )
        response = await Prompt.request(
            "narrator.narrate-character",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                "character": character,
                "max_tokens": self.client.max_token_length,
                "memory": memory_context,
            }
        )

        response = self.clean_result(response.strip())
        response = f"*{response}*"

        return response

    @set_processing
    async def augment_context(self):
        
        """
        Takes a context history generated via scene.context_history() and augments it with additional information
        by asking and answering questions with help from the long term memory.
        """
        memory = self.scene.get_helper("memory").agent
        
        questions = await Prompt.request(
            "narrator.context-questions",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            }
        )
        
        self.scene.log.info("context_questions", questions=questions)
        
        questions = [q for q in questions.split("\n") if q.strip()]
        
        memory_context = await memory.multi_query(
            questions, iterate=2, max_tokens=self.client.max_token_length - 1000
        )
        
        answers = await Prompt.request(
            "narrator.context-answers",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "memory": memory_context,
                "questions": questions,
            }
        )
        
        self.scene.log.info("context_answers", answers=answers)
        
        answers = [a for a in answers.split("\n") if a.strip()]
        
        # return questions and answers
        return list(zip(questions, answers))
    
    @set_processing
    async def narrate_time_passage(self, duration:str, narrative:str=None):
        """
        Narrate a specific character
        """

        response = await Prompt.request(
            "narrator.narrate-time-passage",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "duration": duration,
                "narrative": narrative,
            }
        )
        
        log.info("narrate_time_passage", response=response)

        response = self.clean_result(response.strip())
        response = f"*{response}*"

        return response
    
    
    @set_processing
    async def narrate_after_dialogue(self, actor:Actor):
        """
        Narrate after a line of dialogue
        """

        response = await Prompt.request(
            "narrator.narrate-after-dialogue",
            self.client,
            "narrate",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "actor": actor,
                "last_line": str(self.scene.history[-1])
            }
        )
        
        log.info("narrate_after_dialogue", response=response)

        response = self.clean_result(response.strip().strip("*"))
        response = f"*{response}*"

        return response