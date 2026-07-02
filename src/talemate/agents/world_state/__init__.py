from __future__ import annotations

import isodate
import structlog

import talemate.emit.async_signals
import talemate.util as util
from talemate.emit import emit
from talemate.instance import get_agent
from talemate.client import ClientBase
from talemate.prompts import Prompt
from talemate.scene_message import TimePassageMessage

from talemate.util.response import extract_list

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentEmission,
    DynamicInstruction,
    optimize_prompt_caching_action,
    set_processing,
)
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin


from .character_progression import CharacterProgressionMixin
from .avatars import AvatarMixin
from .snapshot import WorldStateSnapshotMixin
from .snapshot import SNAPSHOT_TASK as SNAPSHOT_TASK
from .reinforcements import WorldStateReinforcementsMixin
from .pin_conditions import WorldStatePinConditionsMixin
from .websocket_handler import WorldStateWebsocketHandler
import talemate.agents.world_state.nodes

log = structlog.get_logger("talemate.agents.world_state")

talemate.emit.async_signals.register("agent.world_state.time")


class WorldStateAgentEmission(AgentEmission):
    """
    Emission class for world state agent
    """

    pass


class TimePassageEmission(WorldStateAgentEmission):
    """
    Emission class for time passage
    """

    duration: str
    narrative: str | None = None
    human_duration: str | None = None


@register()
class WorldStateAgent(
    MemoryRAGMixin,
    WorldStateSnapshotMixin,
    WorldStateReinforcementsMixin,
    WorldStatePinConditionsMixin,
    CharacterProgressionMixin,
    AvatarMixin,
    Agent,
):
    """
    An agent that handles world state related tasks.
    """

    agent_type = "world_state"
    verbose_name = "World State"
    websocket_handler = WorldStateWebsocketHandler

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "prompt_caching": optimize_prompt_caching_action(),
        }
        # add_actions calls are ordered to match the action list shown in the UI.
        WorldStateSnapshotMixin.add_actions(actions)
        WorldStateReinforcementsMixin.add_actions(actions)
        WorldStatePinConditionsMixin.add_actions(actions)
        MemoryRAGMixin.add_actions(actions)
        CharacterProgressionMixin.add_actions(actions)
        AvatarMixin.add_actions(actions)
        return actions

    def __init__(self, client: ClientBase | None = None, **kwargs):
        self.client = client
        self.is_enabled = True
        self.next_update = 0
        self.next_pin_check = 0
        self.actions = WorldStateAgent.init_actions()

    @property
    def enabled(self):
        return self.is_enabled

    @property
    def has_toggle(self):
        return True

    @property
    def experimental(self):
        return True

    async def advance_time(
        self, duration: str, narrative: str = None
    ) -> TimePassageMessage:
        """
        Emit a time passage message
        """

        isodate.parse_duration(duration)
        human_duration = util.iso8601_duration_to_human(duration, suffix=" later")
        message = TimePassageMessage(ts=duration, message=human_duration)

        log.debug("world_state.advance_time", message=message)
        await self.scene.push_history(message)
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

        return message

    @set_processing
    async def analyze_text_and_extract_context(
        self,
        text: str,
        goal: str,
        include_character_context: bool = False,
        response_length=1024,
        num_queries=1,
        extra_context: list[str] = [],
    ):
        response, extracted = await Prompt.request(
            "world_state.analyze-text-and-extract-context",
            self.client,
            f"investigate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "goal": goal,
                "include_character_context": include_character_context,
                "response_length": response_length,
                "num_queries": num_queries,
                "extra_context": extra_context,
            },
        )

        log.debug(
            "analyze_text_and_extract_context", goal=goal, text=text, response=response
        )

        return extracted["response"]

    @set_processing
    async def analyze_text_and_extract_context_via_queries(
        self,
        text: str,
        goal: str,
        include_character_context: bool = False,
        response_length=1024,
        num_queries=1,
        extra_context: list[str] = [],
    ) -> list[str]:
        response, extracted = await Prompt.request(
            "world_state.analyze-text-and-generate-rag-queries",
            self.client,
            f"investigate_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "goal": goal,
                "include_character_context": include_character_context,
                "response_length": response_length,
                "num_queries": num_queries,
                "extra_context": extra_context,
            },
        )

        queries = extract_list(extracted["response"])

        memory_agent = get_agent("memory")

        context = await memory_agent.multi_query(queries, iterate=3)

        # log.debug(
        #    "analyze_text_and_extract_context_via_queries",
        #    goal=goal,
        #    text=text,
        #    queries=queries,
        #    context=context,
        # )

        return context

    @set_processing
    async def analyze_and_follow_instruction(
        self,
        text: str,
        instruction: str,
        short: bool = False,
    ):
        kind = "analyze_freeform_short" if short else "analyze_freeform"

        response, extracted = await Prompt.request(
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

        return extracted["response"]

    @set_processing
    async def analyze_text_and_answer_question(
        self,
        text: str,
        query: str,
        response_length: int = 512,
    ):
        kind = f"investigate_{response_length}"
        response, extracted = await Prompt.request(
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

        return extracted["response"]

    @set_processing
    async def analyze_history_and_follow_instructions(
        self,
        entries: list[dict],
        instructions: str,
        analysis: str = "",
        response_length: int = 512,
    ) -> str:
        """
        Takes a list of archived_history or layered_history entries
        and follows the instructions to generate a response.
        """

        response, extracted = await Prompt.request(
            "world_state.analyze-history-and-follow-instructions",
            self.client,
            f"investigate_{response_length}",
            vars={
                "instructions": instructions,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "entries": entries,
                "analysis": analysis,
                "response_length": response_length,
            },
        )

        return extracted["response"].strip()

    @set_processing
    async def answer_query_true_or_false(
        self,
        query: str,
        text: str,
    ) -> bool:
        query = f"{query} Answer with a yes or no."
        response = await self.analyze_text_and_answer_question(
            query=query, text=text, response_length=10
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

    def _parse_character_sheet(
        self, response, max_attributes: int | None = None
    ) -> dict[str, str]:
        data = {}
        for line in response.split("\n"):
            if not line.strip():
                continue
            if ":" not in line:
                break
            name, value = line.split(":", 1)
            data[name.strip()] = value.strip()

            # Enforce max_attributes limit if set
            if max_attributes and max_attributes > 0 and len(data) >= max_attributes:
                break

        return data

    @set_processing
    async def extract_character_sheet(
        self,
        name: str,
        text: str = None,
        alteration_instructions: str = None,
        augmentation_instructions: str = None,
        dynamic_instructions: list[DynamicInstruction] = [],
        max_attributes: int | None = None,
    ) -> dict[str, str]:
        """
        Attempts to extract a character sheet from the given text.
        """

        response, extracted = await Prompt.request(
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
                "augmentation_instructions": augmentation_instructions or "",
                "dynamic_instructions": dynamic_instructions,
                "max_attributes": max_attributes,
            },
        )

        # loop through each line in response and if it contains a : then extract
        # the left side as an attribute name and the right side as the value
        #
        # break as soon as a non-empty line is found that doesn't contain a :

        return self._parse_character_sheet(
            extracted["response"], max_attributes=max_attributes
        )

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
            extra_context=[extra_context],
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
                "pin_only": True,
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
            query=f"Is {character} present AND active in the current scene? Answer with 'yes' or 'no'.",
            response_length=10,
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
            query=f"Is {character} leaving the current scene? Answer with 'yes' or 'no'.",
            response_length=10,
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
