from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.util as util
from talemate.emit import wait_for_input
from talemate.prompts import Prompt
from talemate.agents.base import set_processing, Agent
import talemate.client as client

from .registry import register

@register()
class NarratorAgent(Agent):
    agent_type = "narrator"
    verbose_name = "Narrator"
    
    def __init__(
        self,
        client: client.TaleMateClient,
        **kwargs,
    ):
        self.client = client
        
    def clean_result(self, result):
        
        result = result.strip().strip(":").strip()
        
        if "#" in result:
            result = result.split("#")[0]
        
        cleaned = []
        for line in result.split("\n"):
            if ":" in line.strip():
                break
            cleaned.append(line)

        return "\n".join(cleaned)

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