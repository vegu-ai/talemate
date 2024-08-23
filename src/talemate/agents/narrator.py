from __future__ import annotations

import dataclasses
import random
from functools import wraps
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import structlog

import talemate.client as client
from talemate.client.context import (
    client_context_attribute,
    set_client_context_attribute,
)
import talemate.emit.async_signals
import talemate.util as util
from talemate.agents.base import Agent, AgentAction, AgentActionConfig, AgentEmission
from talemate.agents.base import set_processing as _set_processing
from talemate.agents.world_state import TimePassageEmission
from talemate.emit import emit
from talemate.events import GameLoopActorIterEvent
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage

from talemate.instance import get_agent

from .registry import register

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character, Player

log = structlog.get_logger("talemate.agents.narrator")


@dataclasses.dataclass
class NarratorAgentEmission(AgentEmission):
    generation: list[str] = dataclasses.field(default_factory=list)


talemate.emit.async_signals.register("agent.narrator.generated")


def set_processing(fn):
    """
    Custom decorator that emits the agent status as processing while the function
    is running and then emits the result of the function as a NarratorAgentEmission
    """

    @_set_processing
    @wraps(fn)
    async def narration_wrapper(self, *args, **kwargs):
        response = await fn(self, *args, **kwargs)
        emission = NarratorAgentEmission(
            agent=self,
            generation=[response],
        )
        await talemate.emit.async_signals.get("agent.narrator.generated").send(emission)
        return emission.generation[0]

    return narration_wrapper


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
            "generation_override": AgentAction(
                enabled=True,
                label="Generation Settings",
                config={
                    "length": AgentActionConfig(
                        type="number",
                        label="Max. Generation Length (tokens)",
                        description="Maximum number of tokens to generate for narrative text. Some narrative actions generate longer or shorter texts. This value is used as a maximum limit.",
                        value=192,
                        min=32,
                        max=1024,
                        step=32,
                    ), 
                    "instructions": AgentActionConfig(
                        type="text",
                        label="Instructions",
                        value="Never wax poetic.",
                        description="Extra instructions to give to the AI for narrative generation.",
                    ),
                    "jiggle": AgentActionConfig(
                        type="number",
                        label="Jiggle (Increased Randomness)",
                        description="If > 0.0 will cause certain generation parameters to have a slight random offset applied to them. The bigger the number, the higher the potential offset.",
                        value=0.0,
                        min=0.0,
                        max=1.0,
                        step=0.1,
                    ),
                },
            ),
            "auto_break_repetition": AgentAction(
                enabled=True,
                label="Auto Break Repetition",
                description="Will attempt to automatically break AI repetition.",
            ),
            "narrate_time_passage": AgentAction(
                enabled=True,
                label="Narrate Time Passage",
                description="Whenever you indicate passage of time, narrate right after",
                config={
                    "ask_for_prompt": AgentActionConfig(
                        type="bool",
                        label="Guide time narration via prompt",
                        description="Ask the user for a prompt to generate the time passage narration",
                        value=True,
                    )
                },
            ),
            "narrate_dialogue": AgentAction(
                enabled=False,
                label="Narrate after Dialogue",
                description="Narrator will get a chance to narrate after every line of dialogue",
                config={
                    "ai_dialog": AgentActionConfig(
                        type="number",
                        label="AI Dialogue",
                        description="Chance to narrate after every line of dialogue, 1 = always, 0 = never",
                        value=0.0,
                        min=0.0,
                        max=1.0,
                        step=0.1,
                    ),
                    "player_dialog": AgentActionConfig(
                        type="number",
                        label="Player Dialogue",
                        description="Chance to narrate after every line of dialogue, 1 = always, 0 = never",
                        value=0.1,
                        min=0.0,
                        max=1.0,
                        step=0.1,
                    ),
                    "generate_dialogue": AgentActionConfig(
                        type="bool",
                        label="Allow Dialogue in Narration",
                        description="Allow the narrator to generate dialogue in narration",
                        value=False,
                    ),
                },
            ),
        }

    @property
    def extra_instructions(self) -> str:
        if self.actions["generation_override"].enabled:
            return self.actions["generation_override"].config["instructions"].value
        return ""

    @property
    def jiggle(self) -> float:
        if self.actions["generation_override"].enabled:
            return self.actions["generation_override"].config["jiggle"].value
        return 0.0

    @property
    def max_generation_length(self) -> int:
        if self.actions["generation_override"].enabled:
            return self.actions["generation_override"].config["length"].value
        return 128

    def clean_result(self, result:str, ensure_dialog_format:bool=True, force_narrative:bool=True) -> str:
        """
        Cleans the result of a narration
        """

        result = result.strip().strip(":").strip()

        if "#" in result:
            result = result.split("#")[0]

        character_names = [c.name for c in self.scene.get_characters()]

        cleaned = []
        for line in result.split("\n"):
            log.debug("clean_result", line=line)
            
            character_dialogue_detected = False
            
            for character_name in character_names:
                if line.lower().startswith(f"{character_name}:"):
                    character_dialogue_detected = True
                elif line.startswith(f"{character_name.upper()}"):
                    character_dialogue_detected = True
                    
                if character_dialogue_detected:
                    break
            
            if character_dialogue_detected:
                break
                
            cleaned.append(line)

        result = "\n".join(cleaned)
        
        result = util.strip_partial_sentences(result)
        
        if force_narrative:
            if "*" not in result and '"' not in result:
                result = f"*{result.strip()}*"
        
        if ensure_dialog_format:
            result = util.ensure_dialog_format(result)

        
        return result

    def connect(self, scene):
        """
        Connect to signals
        """

        super().connect(scene)
        talemate.emit.async_signals.get("agent.world_state.time").connect(
            self.on_time_passage
        )
        talemate.emit.async_signals.get("game_loop_actor_iter").connect(self.on_dialog)

    async def on_time_passage(self, event: TimePassageEmission):
        """
        Handles time passage narration, if enabled
        """

        if not self.actions["narrate_time_passage"].enabled:
            return

        response = await self.narrate_time_passage(
            event.duration, event.human_duration, event.narrative
        )
        narrator_message = NarratorMessage(
            response, source=f"narrate_time_passage:{event.duration};{event.narrative}"
        )
        emit("narrator", narrator_message)
        self.scene.push_history(narrator_message)

    async def on_dialog(self, event: GameLoopActorIterEvent):
        """
        Handles dialogue narration, if enabled
        """

        if not self.actions["narrate_dialogue"].enabled:
            return

        if event.game_loop.had_passive_narration:
            log.debug(
                "narrate on dialog",
                skip=True,
                had_passive_narration=event.game_loop.had_passive_narration,
            )
            return

        narrate_on_ai_chance = (
            self.actions["narrate_dialogue"].config["ai_dialog"].value
        )
        narrate_on_player_chance = (
            self.actions["narrate_dialogue"].config["player_dialog"].value
        )
        narrate_on_ai = random.random() < narrate_on_ai_chance
        narrate_on_player = random.random() < narrate_on_player_chance

        log.debug(
            "narrate on dialog",
            narrate_on_ai=narrate_on_ai,
            narrate_on_ai_chance=narrate_on_ai_chance,
            narrate_on_player=narrate_on_player,
            narrate_on_player_chance=narrate_on_player_chance,
        )

        if event.actor.character.is_player and not narrate_on_player:
            return

        if not event.actor.character.is_player and not narrate_on_ai:
            return

        response = await self.narrate_after_dialogue(event.actor.character)
        narrator_message = NarratorMessage(
            response, source=f"narrate_dialogue:{event.actor.character.name}"
        )
        emit("narrator", narrator_message)
        self.scene.push_history(narrator_message)

        event.game_loop.had_passive_narration = True

    @set_processing
    async def narrate_scene(self):
        """
        Narrate the scene
        """

        response = await Prompt.request(
            "narrator.narrate-scene",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "extra_instructions": self.extra_instructions,
            },
        )

        response = self.clean_result(response.strip())

        return response

    @set_processing
    async def progress_story(self, narrative_direction: str | None = None):
        """
        Narrate scene progression, moving the plot forward.
        
        Arguments:
        
        - narrative_direction: A string describing the direction the narrative should take. If not provided, will attempt to subtly move the story forward.
        """

        scene = self.scene
        pc = scene.get_player_character()
        npcs = list(scene.get_npc_characters())
        npc_names = ", ".join([npc.name for npc in npcs])

        if narrative_direction is None:
            narrative_direction = "Slightly move the current scene forward."

        self.scene.log.info(
            "narrative_direction", narrative_direction=narrative_direction
        )

        response = await Prompt.request(
            "narrator.narrate-progress",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "narrative_direction": narrative_direction,
                "player_character": pc,
                "npcs": npcs,
                "npc_names": npc_names,
                "extra_instructions": self.extra_instructions,
            },
        )

        self.scene.log.info("progress_story", response=response)

        response = self.clean_result(response.strip())
        
        return response

    @set_processing
    async def narrate_query(
        self, query: str, at_the_end: bool = False, as_narrative: bool = True
    ):
        """
        Narrate a specific query
        """
        response = await Prompt.request(
            "narrator.narrate-query",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "query": query,
                "at_the_end": at_the_end,
                "as_narrative": as_narrative,
                "extra_instructions": self.extra_instructions,
            },
        )
        response = self.clean_result(
            response.strip(), 
            ensure_dialog_format=False, 
            force_narrative=as_narrative
        )

        return response

    @set_processing
    async def narrate_character(self, character):
        """
        Narrate a specific character
        """

        response = await Prompt.request(
            "narrator.narrate-character",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "character": character,
                "max_tokens": self.client.max_token_length,
                "extra_instructions": self.extra_instructions,
            },
        )

        response = self.clean_result(response.strip(), ensure_dialog_format=False, force_narrative=True)

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
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "extra_instructions": self.extra_instructions,
            },
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
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "memory": memory_context,
                "questions": questions,
                "extra_instructions": self.extra_instructions,
            },
        )

        self.scene.log.info("context_answers", answers=answers)

        answers = [a for a in answers.split("\n") if a.strip()]

        # return questions and answers
        return list(zip(questions, answers))

    @set_processing
    async def narrate_time_passage(
        self, duration: str, time_passed: str, narrative: str
    ):
        """
        Narrate a specific character
        """

        response = await Prompt.request(
            "narrator.narrate-time-passage",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "duration": duration,
                "time_passed": time_passed,
                "narrative": narrative,
                "extra_instructions": self.extra_instructions,
            },
        )

        log.info("narrate_time_passage", response=response)

        response = self.clean_result(response.strip())

        return response

    @set_processing
    async def narrate_after_dialogue(self, character: Character):
        """
        Narrate after a line of dialogue
        """

        response = await Prompt.request(
            "narrator.narrate-after-dialogue",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "last_line": str(self.scene.history[-1]),
                "extra_instructions": self.extra_instructions,
            },
        )

        log.info("narrate_after_dialogue", response=response)

        response = self.clean_result(response.strip().strip("*"))
        response = f"*{response}*"

        allow_dialogue = (
            self.actions["narrate_dialogue"].config["generate_dialogue"].value
        )

        if not allow_dialogue:
            response = response.split('"')[0].strip()
            response = response.replace("*", "")
            response = util.strip_partial_sentences(response)
            response = f"*{response}*"

        return response

    @set_processing
    async def narrate_character_entry(
        self, character: Character, direction: str = None
    ):
        """
        Narrate a character entering the scene
        """

        response = await Prompt.request(
            "narrator.narrate-character-entry",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "direction": direction,
                "extra_instructions": self.extra_instructions,
            },
        )

        response = self.clean_result(response.strip().strip("*"))

        return response

    @set_processing
    async def narrate_character_exit(self, character: Character, direction: str = None):
        """
        Narrate a character exiting the scene
        """

        response = await Prompt.request(
            "narrator.narrate-character-exit",
            self.client,
            "narrate",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "direction": direction,
                "extra_instructions": self.extra_instructions,
            },
        )

        response = self.clean_result(response.strip().strip("*"))

        return response

    @set_processing
    async def paraphrase(self, narration: str):
        """
        Paraphrase a narration
        """

        response = await Prompt.request(
            "narrator.paraphrase",
            self.client,
            "narrate",
            vars={
                "text": narration,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            },
        )

        log.info("paraphrase", narration=narration, response=response)

        response = self.clean_result(response.strip().strip("*"))

        return response

    async def passthrough(self, narration: str) -> str:
        """
        Pass through narration message as is
        """
        narration = narration.replace("*", "")
        narration = f"*{narration}*"
        narration = util.ensure_dialog_format(narration)
        return narration

    def action_to_source(
        self,
        action_name: str,
        parameters: dict,
    ) -> str:
        """
        Generate a source string for a given action and parameters

        The source string is used to identify the source of a NarratorMessage
        and will also help regenerate the action and parameters from the source string
        later on
        """

        args = []

        if action_name == "paraphrase":
            args.append(parameters.get("narration"))
        elif action_name == "narrate_character_entry":
            args.append(parameters.get("character").name)
            # args.append(parameters.get("direction"))
        elif action_name == "narrate_character_exit":
            args.append(parameters.get("character").name)
            # args.append(parameters.get("direction"))
        elif action_name == "narrate_character":
            args.append(parameters.get("character").name)
        elif action_name == "narrate_query":
            args.append(parameters.get("query"))
        elif action_name == "narrate_time_passage":
            args.append(parameters.get("duration"))
            args.append(parameters.get("time_passed"))
            args.append(parameters.get("narrative"))
        elif action_name == "progress_story":
            args.append(parameters.get("narrative_direction"))
        elif action_name == "narrate_after_dialogue":
            args.append(parameters.get("character"))

        arg_str = ";".join(args) if args else ""

        return f"{action_name}:{arg_str}".rstrip(":")

    async def action_to_narration(
        self,
        action_name: str,
        emit_message: bool = False,
        **kwargs,
    ):
        # calls self[action_name] and returns the result as a NarratorMessage
        # that is pushed to the history

        fn = getattr(self, action_name)
        narration = await fn(**kwargs)
        source = self.action_to_source(action_name, kwargs)

        narrator_message = NarratorMessage(narration, source=source)
        self.scene.push_history(narrator_message)

        if emit_message:
            emit("narrator", narrator_message)

        return narrator_message

    # LLM client related methods. These are called during or after the client

    def inject_prompt_paramters(
        self, prompt_param: dict, kind: str, agent_function_name: str
    ):
        log.debug(
            "inject_prompt_paramters",
            prompt_param=prompt_param,
            kind=kind,
            agent_function_name=agent_function_name,
        )
        
        # depending on conversation format in the context, stopping strings
        # for character names may change format
        conversation_agent = get_agent("conversation")
        
        if conversation_agent.conversation_format == "movie_script":
            character_names = [f"\n{c.name.upper()}\n" for c in self.scene.get_characters()]
        else: 
            character_names = [f"\n{c.name}:" for c in self.scene.get_characters()]
        
        if prompt_param.get("extra_stopping_strings") is None:
            prompt_param["extra_stopping_strings"] = []
        prompt_param["extra_stopping_strings"] += character_names
        
        self.set_generation_overrides(prompt_param)

    def allow_repetition_break(
        self, kind: str, agent_function_name: str, auto: bool = False
    ):
        if auto and not self.actions["auto_break_repetition"].enabled:
            return False

        return True

    def set_generation_overrides(self, prompt_param: dict):
        if not self.actions["generation_override"].enabled:
            return

        prompt_param["max_tokens"] = min(prompt_param.get("max_tokens", 256), self.max_generation_length)

        if self.jiggle > 0.0:
            nuke_repetition = client_context_attribute("nuke_repetition")
            if nuke_repetition == 0.0:
                # we only apply the agent override if some other mechanism isn't already
                # setting the nuke_repetition value
                nuke_repetition = self.jiggle
                set_client_context_attribute("nuke_repetition", nuke_repetition)