from __future__ import annotations

import asyncio
import re
import random
import structlog
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.util as util
from talemate.emit import wait_for_input, emit
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage, DirectorMessage
from talemate.automated_action import AutomatedAction
import talemate.automated_action as automated_action
from .conversation import ConversationAgent
from .registry import register
from .base import set_processing, AgentAction, AgentActionConfig

if TYPE_CHECKING:
    from talemate import Actor, Character, Player, Scene

log = structlog.get_logger("talemate")

@register()
class DirectorAgent(ConversationAgent):
    agent_type = "director"
    verbose_name = "Director"
    
    def __init__(self, client, **kwargs):
        super().__init__(client, **kwargs)
        self.is_enabled = True
        self.actions = {
            "direct": AgentAction(enabled=False, label="Direct", description="Will attempt to direct the scene. Runs automatically after AI dialogue (n turns).", config={
                "turns": AgentActionConfig(type="number", label="Turns", description="Number of turns to wait before directing the sceen", value=10, min=1, max=100, step=1)
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
    
    def get_base_prompt(self, character: Character, budget:int):
        return [character.description, character.base_attributes.get("scenario_context", "")] + self.scene.context_history(budget=budget, keep_director=False)

    
    async def decide_action(self, character: Character, goal_override:str=None):
        
        """
        Pick an action to perform to move the story towards the current story goal
        """
        
        current_goal = goal_override or await self.select_goal(self.scene)
        current_goal = f"Current story goal: {current_goal}" if current_goal else current_goal
        
        response, action_eval, prompt = await self.decide_action_analyze(character, current_goal)
        # action_eval will hold {'narrate': N, 'direct': N, 'watch': N, ...}
        # where N is a number, action with the highest number wins, default action is watch
        # if there is no clear winner
        
        watch_action = action_eval.get("watch", 0)
        action = max(action_eval, key=action_eval.get)
        
        if action_eval[action] <= watch_action:
            action = "watch"
        
        log.info("decide_action", action=action, action_eval=action_eval)
        
        return response, current_goal, action
        
        
    async def decide_action_analyze(self, character: Character, goal:str):

        prompt = Prompt.get("director.decide-action-analyze", vars={
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "current_goal": goal,
            "character": character,
        })

        response, evaluation = await prompt.send(self.client, kind="director")
        
        log.info("question_direction", response=response)
        return response, evaluation, prompt
        
    @set_processing
    async def direct(self, character: Character, goal_override:str=None):
        
        analysis, current_goal, action = await self.decide_action(character, goal_override=goal_override)
        
        if action == "watch":
            return None
        
        if action == "direct":
            return await self.direct_character_with_self_reflection(character, analysis, goal_override=current_goal)
        
        if action.startswith("narrate"):
            
            narration_type = action.split(":")[1] 
            
            direct_narrative = await self.direct_narrative(analysis, narration_type=narration_type, goal=current_goal)
            if direct_narrative:
                narrator = self.scene.get_helper("narrator").agent
                narrator_response = await narrator.progress_story(direct_narrative)
                if not narrator_response:
                    return None
                narrator_message = NarratorMessage(narrator_response, source="progress_story")
                self.scene.push_history(narrator_message)
                emit("narrator", narrator_message)
                return True
            
            
    @set_processing
    async def direct_narrative(self, analysis:str, narration_type:str="progress", goal:str=None):
        
        if goal is None:
            goal = await self.select_goal(self.scene)
        
        prompt = Prompt.get("director.direct-narrative", vars={
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "narration_type": narration_type,
            "analysis": analysis,
            "current_goal": goal,
        })
        
        response = await prompt.send(self.client, kind="director")
        response = response.strip().split("\n")[0].strip()
                
        if not response:
            return None
            
        return response
    
    @set_processing
    async def direct_character_with_self_reflection(self, character: Character, analysis:str, goal_override:str=None):
        
        max_retries = 3
        num_retries = 0
        keep_direction = False
        response = None
        self_reflection = None
        
        while num_retries < max_retries:
            
            response, direction_prompt = await self.direct_character(
                character, 
                analysis, 
                goal_override=goal_override, 
                previous_direction=response,
                previous_direction_feedback=self_reflection
            )
            
            keep_direction, self_reflection = await self.direct_character_self_reflect(
                response, character, goal_override, direction_prompt
            )
            
            if keep_direction:
                break
            
            num_retries += 1
            
        log.info("direct_character_with_self_reflection", response=response, keep_direction=keep_direction)
            
        if not keep_direction:
            return None
        
        #character_agreement = f" *{character.name} agrees with the director and progresses the story accordingly*"
        #
        #if "accordingly" not in response:
        #   response += character_agreement
        #
        
        #response = await self.transform_character_direction_to_inner_monologue(character, response)
        
        return response
        
    @set_processing
    async def transform_character_direction_to_inner_monologue(self, character:Character, direction:str):
        
        inner_monologue = await Prompt.request(
            "conversation.direction-to-inner-monologue",
            self.client,
            "conversation_long",
            vars={
                "max_tokens": self.client.max_token_length,
                "scene": self.scene,
                "character": character,
                "director_instructions": direction,
            }
        )
        
        return inner_monologue
        
        
    @set_processing
    async def direct_character(
        self, 
        character: Character, 
        analysis:str, 
        goal_override:str=None,
        previous_direction:str=None,
        previous_direction_feedback:str=None,
    ):
        """
        Direct the scene
        """
        
        if goal_override:
            current_goal = goal_override
        else:
            current_goal = await self.select_goal(self.scene)
            
        if current_goal and not current_goal.startswith("Current story goal: "):
            current_goal = f"Current story goal: {current_goal}"
        
        prompt = Prompt.get("director.direct-character", vars={
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "character": character,
            "current_goal": current_goal,
            "previous_direction": previous_direction,
            "previous_direction_feedback": previous_direction_feedback,
            "analysis": analysis,
        })
        
        response = await prompt.send(self.client, kind="director")
        response = response.strip().split("\n")[0].strip()
        
        log.info(
            "direct_character", 
            direction=response, 
            previous_direction=previous_direction, 
            previous_direction_feedback=previous_direction_feedback
        )
                
        if not response:
            return None

        if not response.startswith(prompt.prepared_response):
            response = prompt.prepared_response + response

        return response, "\n".join(prompt.as_list[:-1])
    
    
    
    @set_processing
    async def direct_character_self_reflect(self, direction:str, character: Character, goal:str, direction_prompt:Prompt) -> (bool, str):
        
        change_matches = ["change", "retry", "alter", "reconsider"]
        
        prompt = Prompt.get("director.direct-character-self-reflect", vars={
            "direction_prompt": str(direction_prompt),
            "direction": direction,
            "analysis": await self.direct_character_analyze(direction, character, goal, direction_prompt),
            "character": character,
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
        })
        
        response = await prompt.send(self.client, kind="director")
        
        parse_choice = response[len(prompt.prepared_response):].lower().split(" ")[0]
        
        keep = not parse_choice in change_matches
        
        log.info("direct_character_self_reflect", keep=keep, response=response, parsed=parse_choice)
        
        return keep, response
    
    
    @set_processing
    async def direct_character_analyze(self, direction:str, character: Character, goal:str, direction_prompt:Prompt):
        
        prompt = Prompt.get("director.direct-character-analyze", vars={
            "direction_prompt": str(direction_prompt),
            "direction": direction,
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "character": character,
        })
        
        analysis = await prompt.send(self.client, kind="director")
        
        log.info("direct_character_analyze", analysis=analysis)
        
        return analysis

    async def select_goal(self, scene: Scene):
        
        if not scene.goals:
            return ""
        
        if isinstance(self.scene.goal, int):
            # fixes legacy goal format
            self.scene.goal = self.scene.goals[self.scene.goal]

        while True:

            # get current goal position in goals
        
            current_goal = scene.goal
            current_goal_positon = None
            if current_goal:
                try:
                    current_goal_positon = self.scene.goals.index(current_goal)
                except ValueError:
                    pass
            elif self.scene.goals:
                current_goal = self.scene.goals[0]
                current_goal_positon = 0
            else:
                return ""
                
                
            # if current goal is set but not found, its a custom goal override
            
            custom_goal = (current_goal and current_goal_positon is None)
        
            log.info("select_goal", current_goal=current_goal, current_goal_positon=current_goal_positon, custom_goal=custom_goal)

            if current_goal:
                current_goal_met = await self.goal_analyze(current_goal)
                
                log.info("select_goal", current_goal_met=current_goal_met)
                if current_goal_met is not True:
                    return current_goal + f"\nThe goal has {current_goal_met})"
                try:
                    self.scene.goal = self.scene.goals[current_goal_positon + 1]
                    continue
                except IndexError:
                    return ""
            
            else:
                return ""
    
    @set_processing
    async def goal_analyze(self, goal:str):
        
        prompt = Prompt.get("director.goal-analyze", vars={
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "current_goal": goal,
        })
        
        response = await prompt.send(self.client, kind="director")
    
        log.info("goal_analyze", response=response)
        
        if "not satisfied" in response.lower().strip() or "not been satisfied" in response.lower().strip():
            goal_met = response
        else:
            goal_met = True
        
        return goal_met