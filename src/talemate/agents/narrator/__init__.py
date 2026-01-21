from __future__ import annotations

import dataclasses
import random
from functools import wraps
from typing import TYPE_CHECKING

import structlog

import talemate.client as client
from talemate.client.context import (
    client_context_attribute,
    set_client_context_attribute,
)
import talemate.emit.async_signals
import talemate.util as util
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    DynamicInstruction,
    store_context_state,
)
from talemate.agents.base import set_processing as _set_processing
from talemate.agents.context import active_agent
from talemate.agents.world_state import TimePassageEmission
from talemate.agents.memory.rag import MemoryRAGMixin
from talemate.emit import emit
from talemate.events import GameLoopActorIterEvent
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage

from talemate.instance import get_agent

from talemate.agents.registry import register

from .websocket_handler import NarratorWebsocketHandler

import talemate.agents.narrator.nodes

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger("talemate.agents.narrator")


@dataclasses.dataclass
class NarratorAgentEmission(AgentEmission):
    generation: list[str] = dataclasses.field(default_factory=list)
    response: str = dataclasses.field(default="")
    dynamic_instructions: list[DynamicInstruction] = dataclasses.field(
        default_factory=list
    )


talemate.emit.async_signals.register(
    "agent.narrator.before_generate",
    "agent.narrator.inject_instructions",
    "agent.narrator.generated",
)


def set_processing(fn):
    """
    Custom decorator that emits the agent status as processing while the function
    is running and then emits the result of the function as a NarratorAgentEmission
    """

    @_set_processing
    @wraps(fn)
    async def narration_wrapper(self, *args, **kwargs):
        agent_context = active_agent.get()
        emission: NarratorAgentEmission = NarratorAgentEmission(agent=self)

        if self.content_use_writing_style:
            self.set_context_states(writing_style=self.scene.writing_style)

        await talemate.emit.async_signals.get("agent.narrator.before_generate").send(
            emission
        )
        await talemate.emit.async_signals.get(
            "agent.narrator.inject_instructions"
        ).send(emission)

        agent_context.state["dynamic_instructions"] = emission.dynamic_instructions

        response = await fn(self, *args, **kwargs)
        emission.response = response
        await talemate.emit.async_signals.get("agent.narrator.generated").send(emission)
        return emission.response

    return narration_wrapper


@register()
class NarratorAgent(MemoryRAGMixin, Agent):
    """
    Handles narration of the story
    """

    agent_type = "narrator"
    verbose_name = "Narrator"
    set_processing = set_processing

    websocket_handler = NarratorWebsocketHandler

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "generation_override": AgentAction(
                enabled=True,
                label="Generation Settings",
                config={
                    "length": AgentActionConfig(
                        type="number",
                        label="Max. Generation Length (tokens)",
                        description="Maximum number of tokens to generate for narrative text. Some narrative actions generate longer or shorter texts. This value is used as a maximum limit.",
                        value=256,
                        min=32,
                        max=4096,
                        step=32,
                    ),
                    "instructions": AgentActionConfig(
                        type="text",
                        label="Instructions",
                        value="",
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
            "content": AgentAction(
                enabled=True,
                can_be_disabled=False,
                container=True,
                label="Content",
                icon="mdi-script-text",
                description="Content control settings",
                config={
                    "use_scene_intent": AgentActionConfig(
                        type="bool",
                        label="Use Scene Intent",
                        description="Include the scene intent in the prompt",
                        value=True,
                    ),
                    "use_writing_style": AgentActionConfig(
                        type="bool",
                        label="Use Writing Style",
                        description="Use the writing style selected in the scene settings",
                        value=True,
                    ),
                },
            ),
            "narrate_time_passage": AgentAction(
                enabled=True,
                container=True,
                can_be_disabled=True,
                label="Narrate Time Passage",
                icon="mdi-clock-fast",
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
                container=True,
                can_be_disabled=True,
                label="Narrate after Dialogue",
                icon="mdi-forum-plus-outline",
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
                },
            ),
        }

        MemoryRAGMixin.add_actions(actions)
        return actions

    def __init__(
        self,
        client: client.ClientBase | None = None,
        **kwargs,
    ):
        self.client = client

        # agent actions
        self.actions = NarratorAgent.init_actions()

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

    @property
    def narrate_time_passage_enabled(self) -> bool:
        return self.actions["narrate_time_passage"].enabled

    @property
    def narrate_dialogue_enabled(self) -> bool:
        return self.actions["narrate_dialogue"].enabled

    @property
    def narrate_dialogue_ai_chance(self) -> float:
        return self.actions["narrate_dialogue"].config["ai_dialog"].value

    @property
    def narrate_dialogue_player_chance(self) -> float:
        return self.actions["narrate_dialogue"].config["player_dialog"].value

    @property
    def content_use_scene_intent(self) -> bool:
        return self.actions["content"].config["use_scene_intent"].value

    @property
    def content_use_writing_style(self) -> bool:
        return self.actions["content"].config["use_writing_style"].value

    def calc_response_length(self, value: int | None, default: int) -> int:
        max_length = self.max_generation_length
        if not value or value < 0:
            return min(max_length, default)
        return min(max_length, value)

    def clean_result(
        self,
        result: str,
        ensure_dialog_format: bool = True,
        force_narrative: bool = True,
    ) -> str:
        """
        Cleans the result of a narration
        """

        result = result.strip().strip(":").strip()

        character_names = [c.name for c in self.scene.get_characters()]

        cleaned = []
        for line in result.split("\n"):
            # skip lines that start with a #
            if line.startswith("#"):
                continue

            log.debug("clean_result", line=line)

            character_dialogue_detected = False

            for character_name in character_names:
                if not character_name:
                    continue
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
        editor = get_agent("editor")

        if ensure_dialog_format or force_narrative:
            if editor.fix_exposition_enabled and editor.fix_exposition_narrator:
                result = editor.fix_exposition_in_text(result)

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
            response,
            meta={
                "agent": "narrator",
                "function": "narrate_time_passage",
                "arguments": {
                    "duration": event.duration,
                    "time_passed": event.human_duration,
                    "narrative_direction": event.narrative,
                },
            },
        )
        emit("narrator", narrator_message)
        await self.scene.push_history(narrator_message)

    async def on_dialog(self, event: GameLoopActorIterEvent):
        """
        Handles dialogue narration, if enabled
        """

        if not self.narrate_dialogue_enabled:
            return

        if event.game_loop.had_passive_narration:
            log.debug(
                "narrate on dialog",
                skip=True,
                had_passive_narration=event.game_loop.had_passive_narration,
            )
            return

        narrate_on_ai_chance = self.narrate_dialogue_ai_chance
        narrate_on_player_chance = self.narrate_dialogue_player_chance
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
            response,
            meta={
                "agent": "narrator",
                "function": "narrate_after_dialogue",
                "arguments": {
                    "character": event.actor.character.name,
                },
            },
        )
        emit("narrator", narrator_message)
        await self.scene.push_history(narrator_message)

        event.game_loop.had_passive_narration = True

    @set_processing
    @store_context_state(
        "narrative_direction", "response_length", visual_narration=True
    )
    async def narrate_scene(
        self, narrative_direction: str | None = None, response_length: int | None = None
    ):
        """
        Narrate the scene
        """

        response_length = self.calc_response_length(response_length, 256)

        response = await Prompt.request(
            "narrator.narrate-scene",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "extra_instructions": self.extra_instructions,
                "narrative_direction": narrative_direction,
                "response_length": response_length,
            },
        )

        response = self.clean_result(response.strip())

        return response

    @set_processing
    @store_context_state("narrative_direction", "response_length")
    async def progress_story(
        self, narrative_direction: str | None = None, response_length: int | None = None
    ):
        """
        Narrate scene progression, moving the plot forward.

        Arguments:

        - narrative_direction: A string describing the direction the narrative should take. If not provided, will attempt to subtly move the story forward.
        """

        scene = self.scene
        pc = scene.get_player_character()
        npcs = list(scene.get_npc_characters())
        npc_names = ", ".join([npc.name for npc in npcs])

        response_length = self.calc_response_length(
            response_length, self.max_generation_length
        )

        if narrative_direction is None:
            narrative_direction = "Slightly move the current scene forward."

        log.debug("narrative_direction", narrative_direction=narrative_direction)

        response = await Prompt.request(
            "narrator.narrate-progress",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "narrative_direction": narrative_direction,
                "player_character": pc,
                "npcs": npcs,
                "npc_names": npc_names,
                "extra_instructions": self.extra_instructions,
                "response_length": response_length,
            },
        )

        log.debug("progress_story", response=response)

        response = self.clean_result(response.strip())

        return response

    @set_processing
    @store_context_state("query", "response_length", query_narration=True)
    async def narrate_query(
        self,
        query: str,
        at_the_end: bool = False,
        as_narrative: bool = True,
        extra_context: str = None,
        response_length: int | None = None,
    ):
        """
        Narrate a specific query
        """

        response_length = self.calc_response_length(response_length, 512)

        response = await Prompt.request(
            "narrator.narrate-query",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "query": query,
                "at_the_end": at_the_end,
                "as_narrative": as_narrative,
                "extra_instructions": self.extra_instructions,
                "extra_context": extra_context,
            },
        )
        response = self.clean_result(
            response.strip(), ensure_dialog_format=False, force_narrative=as_narrative
        )

        return response

    @set_processing
    @store_context_state(
        "character", "narrative_direction", "response_length", visual_narration=True
    )
    async def narrate_character(
        self,
        character: "Character",
        narrative_direction: str = None,
        response_length: int | None = None,
    ):
        """
        Narrate a specific character
        """

        response_length = self.calc_response_length(response_length, 256)

        response = await Prompt.request(
            "narrator.narrate-character",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "character": character,
                "max_tokens": self.client.max_token_length,
                "extra_instructions": self.extra_instructions,
                "narrative_direction": narrative_direction,
                "response_length": response_length,
            },
        )

        response = self.clean_result(
            response.strip(), ensure_dialog_format=False, force_narrative=True
        )

        return response

    @set_processing
    @store_context_state("narrative_direction", "response_length", time_narration=True)
    async def narrate_time_passage(
        self,
        duration: str,
        time_passed: str,
        narrative_direction: str,
        response_length: int | None = None,
    ):
        """
        Narrate a specific character
        """

        response_length = self.calc_response_length(response_length, 256)

        response = await Prompt.request(
            "narrator.narrate-time-passage",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "duration": duration,
                "time_passed": time_passed,
                "narrative": narrative_direction,  # backwards compatibility
                "narrative_direction": narrative_direction,
                "extra_instructions": self.extra_instructions,
                "response_length": response_length,
            },
        )

        log.debug("narrate_time_passage", response=response)

        response = self.clean_result(response.strip())

        return response

    @set_processing
    @store_context_state(
        "narrative_direction", "response_length", sensory_narration=True
    )
    async def narrate_after_dialogue(
        self,
        character: Character,
        narrative_direction: str = None,
        response_length: int | None = None,
    ):
        """
        Narrate after a line of dialogue
        """

        response_length = self.calc_response_length(response_length, 256)

        response = await Prompt.request(
            "narrator.narrate-after-dialogue",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "extra_instructions": self.extra_instructions,
                "narrative_direction": narrative_direction,
                "response_length": response_length,
            },
        )

        log.debug("narrate_after_dialogue", response=response)

        response = self.clean_result(response.strip())
        return response

    async def narrate_environment(
        self, narrative_direction: str = None, response_length: int | None = None
    ):
        """
        Narrate the environment

        Wraps narrate_after_dialogue with the player character
        as the perspective character
        """

        pc = self.scene.get_player_character()
        return await self.narrate_after_dialogue(
            pc, narrative_direction, response_length
        )

    @set_processing
    @store_context_state("narrative_direction", "character", "response_length")
    async def narrate_character_entry(
        self,
        character: Character,
        narrative_direction: str = None,
        response_length: int | None = None,
    ):
        """
        Narrate a character entering the scene
        """

        response_length = self.calc_response_length(response_length, 256)

        response = await Prompt.request(
            "narrator.narrate-character-entry",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "narrative_direction": narrative_direction,
                "extra_instructions": self.extra_instructions,
                "response_length": response_length,
            },
        )

        response = self.clean_result(response.strip().strip("*"))

        return response

    @set_processing
    @store_context_state("narrative_direction", "character", "response_length")
    async def narrate_character_exit(
        self,
        character: Character,
        narrative_direction: str = None,
        response_length: int | None = None,
    ):
        """
        Narrate a character exiting the scene
        """

        response_length = self.calc_response_length(response_length, 256)

        response = await Prompt.request(
            "narrator.narrate-character-exit",
            self.client,
            f"narrate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character": character,
                "narrative_direction": narrative_direction,
                "extra_instructions": self.extra_instructions,
                "response_length": response_length,
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

        log.debug("paraphrase", narration=narration, response=response)

        response = self.clean_result(response.strip().strip("*"))

        return response

    async def passthrough(self, narration: str) -> str:
        """
        Pass through narration message as is
        """
        editor = get_agent("editor")
        if editor.fix_exposition_enabled and editor.fix_exposition_narrator:
            narration = editor.fix_exposition_in_text(narration)
        return narration

    def action_to_meta(
        self,
        action_name: str,
        parameters: dict,
    ) -> dict:
        """
        Generate a source string for a given action and parameters

        The source string is used to identify the source of a NarratorMessage
        and will also help regenerate the action and parameters from the source string
        later on
        """
        args = parameters.copy()

        if args.get("character") and isinstance(
            args["character"], self.scene.Character
        ):
            args["character"] = args["character"].name

        return {
            "agent": "narrator",
            "function": action_name,
            "arguments": args,
        }

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

        narrator_message = NarratorMessage(
            narration, meta=self.action_to_meta(action_name, kwargs)
        )
        await self.scene.push_history(narrator_message)

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
            character_names = [
                f"\n{c.name.upper()}\n" for c in self.scene.get_characters()
            ]
        else:
            character_names = [f"\n{c.name}:" for c in self.scene.get_characters()]

        if prompt_param.get("extra_stopping_strings") is None:
            prompt_param["extra_stopping_strings"] = []
        prompt_param["extra_stopping_strings"] += character_names

        self.set_generation_overrides(prompt_param)

    def allow_repetition_break(
        self, kind: str, agent_function_name: str, auto: bool = False
    ):
        return True

    def set_generation_overrides(self, prompt_param: dict):
        if not self.actions["generation_override"].enabled:
            return

        if self.jiggle > 0.0:
            nuke_repetition = client_context_attribute("nuke_repetition")
            if nuke_repetition == 0.0:
                # we only apply the agent override if some other mechanism isn't already
                # setting the nuke_repetition value
                nuke_repetition = self.jiggle
                set_client_context_attribute("nuke_repetition", nuke_repetition)
