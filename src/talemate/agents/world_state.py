from __future__ import annotations

import dataclasses
import json
import time
import uuid
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import isodate
import structlog

import talemate.emit.async_signals
import talemate.util as util
from talemate.emit import emit
from talemate.events import GameLoopEvent
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.scene_message import (
    DirectorMessage,
    ReinforcementMessage,
    TimePassageMessage,
)
from talemate.world_state import InsertionMode

from .base import Agent, AgentAction, AgentActionConfig, AgentEmission, set_processing
from .registry import register

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
    human_duration: str = None


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
            "update_world_state": AgentAction(
                enabled=True,
                label="Update world state",
                description="Will attempt to update the world state based on the current scene. Runs automatically every N turns.",
                config={
                    "turns": AgentActionConfig(
                        type="number",
                        label="Turns",
                        description="Number of turns to wait before updating the world state.",
                        value=5,
                        min=1,
                        max=100,
                        step=1,
                    )
                },
            ),
            "update_reinforcements": AgentAction(
                enabled=True,
                label="Update state reinforcements",
                description="Will attempt to update any due state reinforcements.",
                config={},
            ),
            "check_pin_conditions": AgentAction(
                enabled=True,
                label="Update conditional context pins",
                description="Will evaluate context pins conditions and toggle those pins accordingly. Runs automatically every N turns.",
                config={
                    "turns": AgentActionConfig(
                        type="number",
                        label="Turns",
                        description="Number of turns to wait before checking conditions.",
                        value=2,
                        min=1,
                        max=100,
                        step=1,
                    )
                },
            ),
        }

        self.next_update = 0
        self.next_pin_check = 0

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

    async def advance_time(self, duration: str, narrative: str = None):
        """
        Emit a time passage message
        """

        isodate.parse_duration(duration)
        human_duration = util.iso8601_duration_to_human(duration, suffix=" later")
        message = TimePassageMessage(ts=duration, message=human_duration)

        log.debug("world_state.advance_time", message=message)
        self.scene.push_history(message)
        self.scene.emit_status()

        emit("time", message)

        await talemate.emit.async_signals.get("agent.world_state.time").send(
            TimePassageEmission(
                agent=self,
                duration=duration,
                narrative=narrative,
                human_duration=human_duration,
            )
        )

    async def on_game_loop(self, emission: GameLoopEvent):
        """
        Called when a conversation is generated
        """

        if not self.enabled:
            return

        await self.update_world_state()
        await self.auto_update_reinforcments()
        await self.auto_check_pin_conditions()

    async def auto_update_reinforcments(self):
        if not self.enabled:
            return

        if not self.actions["update_reinforcements"].enabled:
            return

        await self.update_reinforcements()

    async def auto_check_pin_conditions(self):
        if not self.enabled:
            return

        if not self.actions["check_pin_conditions"].enabled:
            return

        if (
            self.next_pin_check
            % self.actions["check_pin_conditions"].config["turns"].value
            != 0
            or self.next_pin_check == 0
        ):
            self.next_pin_check += 1
            return

        self.next_pin_check = 0

        await self.check_pin_conditions()

    async def update_world_state(self, force: bool = False):
        if not self.enabled:
            return

        if not self.actions["update_world_state"].enabled:
            return

        log.debug(
            "update_world_state",
            next_update=self.next_update,
            turns=self.actions["update_world_state"].config["turns"].value,
        )

        scene = self.scene

        if (
            self.next_update % self.actions["update_world_state"].config["turns"].value
            != 0
            or self.next_update == 0
        ) and not force:
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
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "object_type": "character",
                "object_type_plural": "characters",
            },
        )

        self.scene.log.debug(
            "request_world_state", response=world_state, time=time.time() - t1
        )

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
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            },
        )

        self.scene.log.debug(
            "request_world_state_inline",
            marked_items=marked_items_response,
            time=time.time() - t1,
        )

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
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
            },
        )

        duration = response.split("\n")[0].split(" ")[0].strip()

        if not duration.startswith("P"):
            duration = "P" + duration

        return duration

    @set_processing
    async def analyze_text_and_extract_context(
        self,
        text: str,
        goal: str,
        include_character_context: bool = False,
    ):
        response = await Prompt.request(
            "world_state.analyze-text-and-extract-context",
            self.client,
            "analyze_freeform_long",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "goal": goal,
                "include_character_context": include_character_context,
            },
        )

        log.debug(
            "analyze_text_and_extract_context", goal=goal, text=text, response=response
        )

        return response

    @set_processing
    async def analyze_text_and_extract_context_via_queries(
        self,
        text: str,
        goal: str,
        include_character_context: bool = False,
    ) -> list[str]:
        response = await Prompt.request(
            "world_state.analyze-text-and-generate-rag-queries",
            self.client,
            "analyze_freeform",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "goal": goal,
                "include_character_context": include_character_context,
            },
        )

        queries = response.split("\n")

        memory_agent = get_agent("memory")

        context = await memory_agent.multi_query(queries, iterate=3)

        log.debug(
            "analyze_text_and_extract_context_via_queries",
            goal=goal,
            text=text,
            queries=queries,
            context=context,
        )

        return context

    @set_processing
    async def analyze_and_follow_instruction(
        self,
        text: str,
        instruction: str,
        short: bool = False,
    ):

        kind = "analyze_freeform_short" if short else "analyze_freeform"

        response = await Prompt.request(
            "world_state.analyze-text-and-follow-instruction",
            self.client,
            kind,
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "instruction": instruction,
            },
        )

        log.debug(
            "analyze_and_follow_instruction",
            instruction=instruction,
            text=text,
            response=response,
        )

        return response

    @set_processing
    async def analyze_text_and_answer_question(
        self,
        text: str,
        query: str,
        short: bool = False,
    ):
        kind = "analyze_freeform_short" if short else "analyze_freeform"
        response = await Prompt.request(
            "world_state.analyze-text-and-answer-question",
            self.client,
            kind,
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "query": query,
            },
        )

        log.debug(
            "analyze_text_and_answer_question",
            query=query,
            text=text,
            response=response,
        )

        return response

    @set_processing
    async def answer_query_true_or_false(
        self,
        query: str,
        text: str,
    ) -> bool:
        query = f"{query} Answer with a yes or no."
        response = await self.analyze_text_and_answer_question(
            query=query, text=text, short=True
        )
        return response.lower().startswith("y")

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
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
            },
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
        name: str,
        text: str = None,
        alteration_instructions: str = None,
    ):
        """
        Attempts to extract a character sheet from the given text.
        """

        response = await Prompt.request(
            "world_state.extract-character-sheet",
            self.client,
            "create",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "name": name,
                "character": self.scene.get_character(name),
                "alteration_instructions": alteration_instructions or "",
            },
        )

        # loop through each line in response and if it contains a : then extract
        # the left side as an attribute name and the right side as the value
        #
        # break as soon as a non-empty line is found that doesn't contain a :

        return self._parse_character_sheet(response)

    @set_processing
    async def match_character_names(self, names: list[str]):
        """
        Attempts to match character names.
        """

        _, response = await Prompt.request(
            "world_state.match-character-names",
            self.client,
            "analyze_long",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "names": names,
            },
        )

        log.debug("match_character_names", names=names, response=response)

        return response

    @set_processing
    async def update_reinforcements(self, force: bool = False, reset: bool = False):
        """
        Queries due worldstate re-inforcements
        """

        for reinforcement in self.scene.world_state.reinforce:
            if reinforcement.due <= 0 or force:
                await self.update_reinforcement(
                    reinforcement.question, reinforcement.character, reset=reset
                )
            else:
                reinforcement.due -= 1

    @set_processing
    async def update_reinforcement(
        self, question: str, character: str = None, reset: bool = False
    ):
        """
        Queries a single re-inforcement
        """
        message = None
        idx, reinforcement = await self.scene.world_state.find_reinforcement(
            question, character
        )

        if not reinforcement:
            return

        source = f"{reinforcement.question}:{reinforcement.character if reinforcement.character else ''}"

        if reset and reinforcement.insert == "sequential":
            self.scene.pop_history(typ="reinforcement", source=source, all=True)

        if reinforcement.insert == "sequential":
            kind = "analyze_freeform_medium_short"
        else:
            kind = "analyze_freeform"

        answer = await Prompt.request(
            "world_state.update-reinforcements",
            self.client,
            kind,
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "question": reinforcement.question,
                "instructions": reinforcement.instructions or "",
                "character": (
                    self.scene.get_character(reinforcement.character)
                    if reinforcement.character
                    else None
                ),
                "answer": (reinforcement.answer if not reset else None) or "",
                "reinforcement": reinforcement,
            },
        )

        # sequential reinforcment should be single sentence so we
        # split on line breaks and take the first line in case the
        # LLM did not understand the request and returned a longer response

        if reinforcement.insert == "sequential":
            answer = answer.split("\n")[0]

        reinforcement.answer = answer
        reinforcement.due = reinforcement.interval

        # remove any recent previous reinforcement message with same question
        # to avoid overloading the near history with reinforcement messages
        if not reset:
            self.scene.pop_history(
                typ="reinforcement", source=source, max_iterations=10
            )

        if reinforcement.insert == "sequential":
            # insert the reinforcement message at the current position
            message = ReinforcementMessage(message=answer, source=source)
            log.debug("update_reinforcement", message=message, reset=reset)
            self.scene.push_history(message)

        # if reinforcement has a character name set, update the character detail
        if reinforcement.character:
            character = self.scene.get_character(reinforcement.character)
            await character.set_detail(reinforcement.question, answer)

        else:
            # set world entry
            await self.scene.world_state_manager.save_world_entry(
                reinforcement.question,
                reinforcement.as_context_line,
                {},
            )

        self.scene.world_state.emit()

        return message

    @set_processing
    async def check_pin_conditions(
        self,
    ):
        """
        Checks if any context pin conditions
        """

        pins_with_condition = {
            entry_id: {
                "condition": pin.condition,
                "state": pin.condition_state,
            }
            for entry_id, pin in self.scene.world_state.pins.items()
            if pin.condition
        }

        if not pins_with_condition:
            return

        first_entry_id = list(pins_with_condition.keys())[0]

        _, answers = await Prompt.request(
            "world_state.check-pin-conditions",
            self.client,
            "analyze",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "previous_states": json.dumps(pins_with_condition, indent=2),
                "coercion": {first_entry_id: {"condition": ""}},
            },
        )

        world_state = self.scene.world_state
        state_change = False

        for entry_id, answer in answers.items():
            if entry_id not in world_state.pins:
                log.warning(
                    "check_pin_conditions",
                    entry_id=entry_id,
                    answer=answer,
                    msg="entry_id not found in world_state.pins (LLM failed to produce a clean response)",
                )
                continue

            log.info("check_pin_conditions", entry_id=entry_id, answer=answer)
            state = answer.get("state")
            if state is True or (
                isinstance(state, str) and state.lower() in ["true", "yes", "y"]
            ):
                prev_state = world_state.pins[entry_id].condition_state

                world_state.pins[entry_id].condition_state = True
                world_state.pins[entry_id].active = True

                if prev_state != world_state.pins[entry_id].condition_state:
                    state_change = True
            else:
                if world_state.pins[entry_id].condition_state is not False:
                    world_state.pins[entry_id].condition_state = False
                    world_state.pins[entry_id].active = False
                    state_change = True

        if state_change:
            await self.scene.load_active_pins()
            self.scene.emit_status()

    @set_processing
    async def summarize_and_pin(self, message_id: int, num_messages: int = 3) -> str:
        """
        Will take a message index and then walk back N messages
        summarizing the scene and pinning it to the context.
        """

        creator = get_agent("creator")
        summarizer = get_agent("summarizer")

        message_index = self.scene.message_index(message_id)

        text = self.scene.snapshot(lines=num_messages, start=message_index)

        extra_context = self.scene.snapshot(
            lines=50, start=message_index - num_messages
        )

        summary = await summarizer.summarize(
            text,
            extra_context=extra_context,
            method="short",
            extra_instructions="Pay particularly close attention to decisions, agreements or promises made.",
        )

        entry_id = util.clean_id(await creator.generate_title(summary))

        ts = self.scene.ts

        log.debug(
            "summarize_and_pin",
            message_id=message_id,
            message_index=message_index,
            num_messages=num_messages,
            summary=summary,
            entry_id=entry_id,
            ts=ts,
        )

        await self.scene.world_state_manager.save_world_entry(
            entry_id,
            summary,
            {
                "ts": ts,
            },
        )

        await self.scene.world_state_manager.set_pin(
            entry_id,
            active=True,
        )

        await self.scene.load_active_pins()
        self.scene.emit_status()

    @set_processing
    async def is_character_present(self, character: str) -> bool:
        """
        Check if a character is present in the scene

        Arguments:

        - `character`: The character to check.
        """

        if len(self.scene.history) < 10:
            text = self.scene.intro + "\n\n" + self.scene.snapshot(lines=50)
        else:
            text = self.scene.snapshot(lines=50)

        is_present = await self.analyze_text_and_answer_question(
            text=text,
            query=f"Is {character} present AND active in the current scene? Answert with 'yes' or 'no'.",
        )

        return is_present.lower().startswith("y")

    @set_processing
    async def is_character_leaving(self, character: str) -> bool:
        """
        Check if a character is leaving the scene

        Arguments:

        - `character`: The character to check.
        """

        if len(self.scene.history) < 10:
            text = self.scene.intro + "\n\n" + self.scene.snapshot(lines=50)
        else:
            text = self.scene.snapshot(lines=50)

        is_leaving = await self.analyze_text_and_answer_question(
            text=text,
            query=f"Is {character} leaving the current scene? Answert with 'yes' or 'no'.",
        )

        return is_leaving.lower().startswith("y")

    @set_processing
    async def manager(self, action_name: str, *args, **kwargs):
        """
        Executes a world state manager action through self.scene.world_state_manager
        """

        manager = self.scene.world_state_manager

        try:
            fn = getattr(manager, action_name, None)

            if not fn:
                raise ValueError(f"Unknown action: {action_name}")

            return await fn(*args, **kwargs)
        except Exception as e:
            log.error(
                "worldstate.manager",
                action_name=action_name,
                args=args,
                kwargs=kwargs,
                error=e,
            )
            raise
