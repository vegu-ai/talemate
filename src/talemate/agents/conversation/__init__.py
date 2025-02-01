from __future__ import annotations

import dataclasses
import random
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import structlog

import talemate.client as client
import talemate.emit.async_signals
import talemate.instance as instance
import talemate.util as util
from talemate.client.context import (
    client_context_attribute,
    set_client_context_attribute,
    set_conversation_context_attribute,
)
from talemate.events import GameLoopEvent
from talemate.exceptions import LLMAccuracyError
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, DirectorMessage

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentDetail,
    AgentEmission,
    set_processing,
    store_context_state,
)
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin
from talemate.agents.context import active_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character

log = structlog.get_logger("talemate.agents.conversation")


@dataclasses.dataclass
class ConversationAgentEmission(AgentEmission):
    actor: Actor
    character: Character
    generation: list[str]
    dynamic_instructions: list[str] = dataclasses.field(default_factory=list)


talemate.emit.async_signals.register(
    "agent.conversation.before_generate", 
    "agent.conversation.inject_instructions",
    "agent.conversation.generated"
)


@register()
class ConversationAgent(
    MemoryRAGMixin, 
    Agent
):
    """
    An agent that can be used to have a conversation with the AI

    Ideally used with a Pygmalion or GPT >= 3.5 model
    """

    agent_type = "conversation"
    verbose_name = "Conversation"

    min_dialogue_length = 75

    def __init__(
        self,
        client: client.TaleMateClient,
        kind: Optional[str] = "pygmalion",
        logging_enabled: Optional[bool] = True,
        **kwargs,
    ):
        self.client = client
        self.kind = kind
        self.logging_enabled = logging_enabled
        self.logging_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # several agents extend this class, but we only want to initialize
        # these actions for the conversation agent

        if self.agent_type != "conversation":
            return

        self.actions = {
            "generation_override": AgentAction(
                enabled=True,
                container=True,
                icon="mdi-atom-variant",
                label="Generation",
                config={
                    "format": AgentActionConfig(
                        type="text",
                        label="Format",
                        description="The generation format of the scene context, as seen by the AI.",
                        choices=[
                            {"label": "Screenplay", "value": "movie_script"},
                            {"label": "Chat (legacy)", "value": "chat"},
                        ],
                        value="movie_script",
                    ),
                    "length": AgentActionConfig(
                        type="number",
                        label="Generation Length (tokens)",
                        description="Maximum number of tokens to generate for a conversation response.",
                        value=128,
                        min=32,
                        max=512,
                        step=32,
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
                    "instructions": AgentActionConfig(
                        type="blob",
                        label="Task Instructions",
                        value="Write 1-3 sentences. Never wax poetic.",
                        description="Allows to extend the task instructions - placed above the context history.",
                    ),
                    "actor_instructions": AgentActionConfig(
                        type="blob",
                        label="Actor Instructions",
                        value="",
                        description="Allows to extend the actor instructions - placed towards the end of the context history.",
                    ),
                    "actor_instructions_offset": AgentActionConfig(
                        type="number",
                        label="Actor Instructions Offset",
                        value=3,
                        description="Offsets the actor instructions into the context history, shifting it up N number of messages. 0 = at the end of the context history.",
                        min=0,
                        max=20,
                        step=1,
                    ),
                    

                },
            ),
            "auto_break_repetition": AgentAction(
                enabled=True,
                label="Auto Break Repetition",
                description="Will attempt to automatically break AI repetition.",
            ),
            "natural_flow": AgentAction(
                enabled=True,
                label="Natural Flow",
                description="Will attempt to generate a more natural flow of conversation between multiple characters.",
                config={
                    "max_auto_turns": AgentActionConfig(
                        type="number",
                        label="Max. Auto Turns",
                        description="The maximum number of turns the AI is allowed to generate before it stops and waits for the player to respond.",
                        value=4,
                        min=1,
                        max=100,
                        step=1,
                    ),
                    "max_idle_turns": AgentActionConfig(
                        type="number",
                        label="Max. Idle Turns",
                        description="The maximum number of turns a character can go without speaking before they are considered overdue to speak.",
                        value=8,
                        min=1,
                        max=100,
                        step=1,
                    ),
                },
            ),
        }
        
        MemoryRAGMixin.add_actions(self)

    @property
    def conversation_format(self):
        if self.actions["generation_override"].enabled:
            return self.actions["generation_override"].config["format"].value
        return "movie_script"

    @property
    def conversation_format_label(self):
        value = self.conversation_format

        choices = self.actions["generation_override"].config["format"].choices

        for choice in choices:
            if choice["value"] == value:
                return choice["label"]

        return value

    @property
    def agent_details(self) -> dict:

        details = {
            "client": AgentDetail(
                icon="mdi-network-outline",
                value=self.client.name if self.client else None,
                description="The client to use for prompt generation",
            ).model_dump(),
            "format": AgentDetail(
                icon="mdi-format-float-none",
                value=self.conversation_format_label,
                description="Generation format of the scene context, as seen by the AI",
            ).model_dump(),
        }

        return details

    @property
    def generation_settings_task_instructions(self):
        return self.actions["generation_override"].config["instructions"].value

    @property
    def generation_settings_actor_instructions(self):
        return self.actions["generation_override"].config["actor_instructions"].value

    @property
    def generation_settings_actor_instructions_offset(self):
        return self.actions["generation_override"].config["actor_instructions_offset"].value

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop").connect(self.on_game_loop)

    def last_spoken(self):
        """
        Returns the last time each character spoke
        """

        last_turn = {}
        turns = 0
        character_names = self.scene.character_names
        max_idle_turns = self.actions["natural_flow"].config["max_idle_turns"].value

        for idx in range(len(self.scene.history) - 1, -1, -1):
            if isinstance(self.scene.history[idx], CharacterMessage):
                if turns >= max_idle_turns:
                    break

                character = self.scene.history[idx].character_name

                if character in character_names:
                    last_turn[character] = turns
                    character_names.remove(character)

                if not character_names:
                    break

                turns += 1

        if character_names and turns >= max_idle_turns:
            for character in character_names:
                last_turn[character] = max_idle_turns

        return last_turn

    def repeated_speaker(self):
        """
        Counts the amount of times the most recent speaker has spoken in a row
        """
        character_name = None
        count = 0
        for idx in range(len(self.scene.history) - 1, -1, -1):
            if isinstance(self.scene.history[idx], CharacterMessage):
                if character_name is None:
                    character_name = self.scene.history[idx].character_name
                if self.scene.history[idx].character_name == character_name:
                    count += 1
                else:
                    break
        return count

    async def on_game_loop(self, event: GameLoopEvent):
        await self.apply_natural_flow()

    async def apply_natural_flow(self, force: bool = False, npcs_only: bool = False):
        """
        If the natural flow action is enabled, this will attempt to determine
        the ideal character to talk next.

        This will let the AI pick a character to talk to, but if the AI can't figure
        it out it will apply rules based on max_idle_turns and max_auto_turns.

        If all fails it will just pick a random character.

        Repetition is also taken into account, so if a character has spoken twice in a row
        they will not be picked again until someone else has spoken.
        """

        scene = self.scene

        if not scene.auto_progress and not force:
            # we only apply natural flow if auto_progress is enabled
            return

        if self.actions["natural_flow"].enabled and len(scene.character_names) > 2:
            # last time each character spoke (turns ago)
            max_idle_turns = self.actions["natural_flow"].config["max_idle_turns"].value
            max_auto_turns = self.actions["natural_flow"].config["max_auto_turns"].value
            last_turn = self.last_spoken()
            player_name = scene.get_player_character().name
            last_turn_player = last_turn.get(player_name, 0)

            if last_turn_player >= max_auto_turns and not npcs_only:
                self.scene.next_actor = scene.get_player_character().name
                log.debug(
                    "conversation_agent.natural_flow",
                    next_actor="player",
                    overdue=True,
                    player_character=scene.get_player_character().name,
                )
                return

            log.debug("conversation_agent.natural_flow", last_turn=last_turn)

            # determine random character to talk, this will be the fallback in case
            # the AI can't figure out who should talk next

            if scene.prev_actor:
                # we dont want to talk to the same person twice in a row
                character_names = scene.character_names
                character_names.remove(scene.prev_actor)

                if npcs_only:
                    character_names = [c for c in character_names if c != player_name]

                random_character_name = random.choice(character_names)
            else:
                character_names = scene.character_names
                # no one has talked yet, so we just pick a random character

                if npcs_only:
                    character_names = [c for c in character_names if c != player_name]

                random_character_name = random.choice(scene.character_names)

            overdue_characters = [
                character
                for character, turn in last_turn.items()
                if turn >= max_idle_turns
            ]

            if npcs_only:
                overdue_characters = [c for c in overdue_characters if c != player_name]

            if overdue_characters and self.scene.history:
                # Pick a random character from the overdue characters
                scene.next_actor = random.choice(overdue_characters)
            elif scene.history:
                scene.next_actor = None

                # AI will attempt to figure out who should talk next
                next_actor = await self.select_talking_actor(character_names)
                next_actor = next_actor.split("\n")[0].strip().strip('"').strip(".")

                for character_name in scene.character_names:
                    if (
                        next_actor.lower() in character_name.lower()
                        or character_name.lower() in next_actor.lower()
                    ):
                        scene.next_actor = character_name
                        break

                if not scene.next_actor:
                    # AI couldn't figure out who should talk next, so we just pick a random character
                    log.debug(
                        "conversation_agent.natural_flow",
                        next_actor="random",
                        random_character_name=random_character_name,
                    )
                    scene.next_actor = random_character_name
                else:
                    log.debug(
                        "conversation_agent.natural_flow",
                        next_actor="picked",
                        ai_next_actor=scene.next_actor,
                    )
            else:
                # always start with main character (TODO: configurable?)
                player_character = scene.get_player_character()
                log.debug(
                    "conversation_agent.natural_flow",
                    next_actor="main_character",
                    main_character=player_character,
                )
                scene.next_actor = (
                    player_character.name if player_character else random_character_name
                )

            scene.log.debug(
                "conversation_agent.natural_flow", next_actor=scene.next_actor
            )

            # same character cannot go thrice in a row, if this is happening, pick a random character that
            # isnt the same as the last character

            if (
                self.repeated_speaker() >= 2
                and self.scene.prev_actor == self.scene.next_actor
            ):
                scene.next_actor = random.choice(
                    [c for c in scene.character_names if c != scene.prev_actor]
                )
                scene.log.debug(
                    "conversation_agent.natural_flow",
                    next_actor="random (repeated safeguard)",
                    random_character_name=scene.next_actor,
                )

        else:
            scene.next_actor = None

    @set_processing
    async def select_talking_actor(self, character_names: list[str] = None):
        result = await Prompt.request(
            "conversation.select-talking-actor",
            self.client,
            "conversation_select_talking_actor",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character_names": character_names or self.scene.character_names,
                "character_names_formatted": ", ".join(
                    character_names or self.scene.character_names
                ),
            },
        )

        return result

    async def build_prompt_default(
        self,
        character: Character,
        char_message: Optional[str] = "",
        instruction: Optional[str] = None,
    ):
        """
        Builds the prompt that drives the AI's conversational response
        """
        # the amount of tokens we can use
        # we subtract 200 to account for the response

        scene = character.actor.scene

        total_token_budget = self.client.max_token_length - 200
        scene_and_dialogue_budget = total_token_budget - 500

        scene_and_dialogue = scene.context_history(
            budget=scene_and_dialogue_budget,
            keep_director=True,
            sections=False,
        )

        main_character = scene.main_character.character

        character_names = [c.name for c in scene.characters if not c.is_player]

        if len(character_names) > 1:
            formatted_names = (
                ", ".join(character_names[:-1]) + " or " + character_names[-1]
                if character_names
                else ""
            )
        else:
            formatted_names = character_names[0] if character_names else ""

        try:
            director_message = isinstance(scene_and_dialogue[-1], DirectorMessage)
        except IndexError:
            director_message = False
            
        
        inject_instructions_emission = ConversationAgentEmission(
            agent=self,
            generation="", 
            actor=None, 
            character=character, 
        )
        await talemate.emit.async_signals.get(
            "agent.conversation.inject_instructions"
        ).send(inject_instructions_emission)
        
        agent_context = active_agent.get()
        agent_context.state["dynamic_instructions"] = inject_instructions_emission.dynamic_instructions
        
        conversation_format = self.conversation_format
        prompt = Prompt.get(
            f"conversation.dialogue-{conversation_format}",
            vars={
                "scene": scene,
                "max_tokens": self.client.max_token_length,
                "scene_and_dialogue_budget": scene_and_dialogue_budget,
                "scene_and_dialogue": scene_and_dialogue,
                "memory": None, # DEPRECATED VARIABLE
                "characters": list(scene.get_characters()),
                "main_character": main_character,
                "formatted_names": formatted_names,
                "talking_character": character,
                "partial_message": char_message,
                "director_message": director_message,
                "extra_instructions": self.generation_settings_task_instructions, #backward compatibility
                "task_instructions": self.generation_settings_task_instructions,
                "actor_instructions": self.generation_settings_actor_instructions,
                "actor_instructions_offset": self.generation_settings_actor_instructions_offset,
                "direct_instruction": instruction,
                "decensor": self.client.decensor_enabled,
            },
        )

        return str(prompt)

    async def build_prompt(self, character, char_message: str = "", instruction:str = None):
        fn = self.build_prompt_default

        return await fn(character, char_message=char_message, instruction=instruction)

    def clean_result(self, result, character):
        if "#" in result:
            result = result.split("#")[0]

        if "(Internal" in result:
            result = result.split("(Internal")[0]

        result = result.replace(" :", ":")

        result = util.handle_endofline_special_delimiter(result)
        result = util.remove_trailing_markers(result)

        return result

    def set_generation_overrides(self):
        if not self.actions["generation_override"].enabled:
            return

        set_conversation_context_attribute(
            "length", self.actions["generation_override"].config["length"].value
        )

        if self.actions["generation_override"].config["jiggle"].value > 0.0:
            nuke_repetition = client_context_attribute("nuke_repetition")
            if nuke_repetition == 0.0:
                # we only apply the agent override if some other mechanism isn't already
                # setting the nuke_repetition value
                nuke_repetition = (
                    self.actions["generation_override"].config["jiggle"].value
                )
                set_client_context_attribute("nuke_repetition", nuke_repetition)

    @set_processing
    @store_context_state('instruction')
    async def converse(self, actor, only_generate:bool = False, instruction:str = None) -> list[str] | list[CharacterMessage]:
        """
        Have a conversation with the AI
        """

        character = actor.character

        emission = ConversationAgentEmission(
            agent=self, generation="", actor=actor, character=character
        )
        await talemate.emit.async_signals.get(
            "agent.conversation.before_generate"
        ).send(emission)

        self.set_generation_overrides()

        result = await self.client.send_prompt(await self.build_prompt(character, instruction=instruction))

        result = self.clean_result(result, character)

        # Set max limit of loops
        max_loops = self.client.conversation_retries
        loop_count = 0
        total_result = result

        empty_result_count = 0

        # Validate AI response
        while loop_count < max_loops and len(total_result) < self.min_dialogue_length:
            log.debug("conversation agent", result=result)
            result = await self.client.send_prompt(
                await self.build_prompt(character, char_message=total_result)
            )

            result = self.clean_result(result, character)

            total_result += " " + result

            if len(total_result) == 0 and max_loops < 10:
                max_loops += 1

            loop_count += 1

            if len(total_result) > self.min_dialogue_length:
                break

            # if result is empty, increment empty_result_count
            # and if we get 2 empty responses in a row, break

            if result == "":
                empty_result_count += 1
                if empty_result_count >= 2:
                    break

        # if result is empty, raise an error
        if not total_result:
            raise LLMAccuracyError("Received empty response from AI")

        result = result.replace(" :", ":")

        total_result = total_result.split("#")[0].strip()

        total_result = util.handle_endofline_special_delimiter(total_result)

        log.info("conversation agent", total_result=total_result)

        if total_result.startswith(":\n") or total_result.startswith(": "):
            total_result = total_result[2:]

        # movie script format
        # {uppercase character name}
        # {dialogue}
        total_result = total_result.replace(f"{character.name.upper()}\n", f"")

        # chat format
        # {character name}: {dialogue}
        total_result = total_result.replace(f"{character.name}:", "")

        # Removes partial sentence at the end
        total_result = util.clean_dialogue(total_result, main_name=character.name)

        # Check if total_result starts with character name, if not, prepend it
        if not total_result.startswith(character.name+":"):
            total_result = f"{character.name}: {total_result}"

        total_result = total_result.strip()

        if total_result == "" or total_result == f"{character.name}:":
            log.warn("conversation agent", result="Empty result")

        # replace any white space betwen {self.charactrer.name}: and the first word with a single space
        total_result = re.sub(
            rf"{character.name}:\s+", f"{character.name}: ", total_result
        )

        response_message = util.parse_messages_from_str(total_result, [character.name])

        log.info("conversation agent", result=response_message)
        
        if only_generate:
            return response_message

        emission = ConversationAgentEmission(
            agent=self, generation=response_message, actor=actor, character=character
        )
        await talemate.emit.async_signals.get("agent.conversation.generated").send(
            emission
        )

        # log.info("conversation agent", generation=emission.generation)

        messages = [CharacterMessage(message) for message in emission.generation]

        # Add message and response to conversation history
        actor.scene.push_history(messages)

        return messages

    def allow_repetition_break(
        self, kind: str, agent_function_name: str, auto: bool = False
    ):
        if auto and not self.actions["auto_break_repetition"].enabled:
            return False

        return agent_function_name == "converse"

    def inject_prompt_paramters(
        self, prompt_param: dict, kind: str, agent_function_name: str
    ):
        if prompt_param.get("extra_stopping_strings") is None:
            prompt_param["extra_stopping_strings"] = []
        prompt_param["extra_stopping_strings"] += ["#"]
