"""
Functions for the world state agent
"""

from typing import TYPE_CHECKING

import pydantic

from talemate.game.engine.api.base import ScopedAPI, run_async
from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["create"]


def create(scene: "Scene") -> "ScopedAPI":
    class API(ScopedAPI):
        def activate_character(self, character_name: str):
            """
            Activates a character.

            Activated characters will be available for interactions.

            Arguments:

            - character_name: str - The name of the character

            Raises:

            - UnknownCharacter - If the character is not found
            """

            class Arguments(pydantic.BaseModel):
                character_name: str

            validated = Arguments(character_name=character_name)

            world_state = get_agent("world_state")

            run_async(
                world_state.manager(
                    action_name="activate_character",
                    character_name=validated.character_name,
                )
            )

        def add_detail_reinforcement(
            self,
            character_name: str | None,
            detail: str,
            instructions: str,
            interval: int,
            run_immediately: bool,
        ):
            """
            Adds a detail reinforcement

            Arguments:

            - character_name: str - The name of the character
            - detail: str - The detail to reinforce (question or detail name)
            - instructions: str - The instructions for reinforcement
            - interval: int - The interval for reinforcement
            - run_immediately: bool - Whether to run the reinforcement immediately
            """

            class Arguments(pydantic.BaseModel):
                character_name: str
                detail: str
                instructions: str
                interval: int
                run_immediately: bool

            validated = Arguments(
                character_name=character_name,
                detail=detail,
                instructions=instructions,
                interval=interval,
                run_immediately=run_immediately,
            )

            agent = get_agent("world_state")

            run_async(
                agent.manager(
                    action_name="add_detail_reinforcement",
                    character_name=validated.character_name,
                    question=validated.detail,
                    instructions=validated.instructions,
                    interval=validated.interval,
                    run_immediately=validated.run_immediately,
                )
            )

        def answer_query_true_or_false(self, query: str, text: str) -> bool:
            """
            Prompt the world state agent to answer a query with a True or False response.

            Arguments:

            - query: str - The query to answer
            - text: str - The text to analyze

            Returns:

            - bool - True if the response is affirmative, False otherwise
            """

            class Arguments(pydantic.BaseModel):
                query: str
                text: str

            validated = Arguments(query=query, text=text)

            agent = get_agent("world_state")
            return run_async(
                agent.answer_query_true_or_false(
                    query=query,
                    text=validated.text,
                )
            )

        def deactivate_character(self, character_name: str):
            """
            Deactivates a character.

            Deactivated characters will not be available for interactions, but can
            be reactivated at a later time.

            Arguments:

            - character_name: str - The name of the character

            Raises:

            - UnknownCharacter - If the character is not found
            """

            class Arguments(pydantic.BaseModel):
                character_name: str

            validated = Arguments(character_name=character_name)

            world_state = get_agent("world_state")

            run_async(
                world_state.manager(
                    action_name="deactivate_character",
                    character_name=validated.character_name,
                )
            )

        def extract_character_sheet(
            self, name: str, text: str, alteration_instructions: str
        ) -> dict:
            """
            Extracts a character sheet from text

            Arguments:

            - name: str - The name of the character
            - text: str - The text to extract from
            - alteration_instructions: str - Instructions for altering the sheet

            Returns:

            - dict - The extracted character sheet where each key is an attribute name and the value is the attribute value
            """

            class Arguments(pydantic.BaseModel):
                name: str
                text: str
                alteration_instructions: str

            validated = Arguments(
                name=name, text=text, alteration_instructions=alteration_instructions
            )

            agent = get_agent("world_state")

            return run_async(
                agent.extract_character_sheet(
                    name=validated.name,
                    text=validated.text,
                    alteration_instructions=validated.alteration_instructions,
                )
            )

        def save_world_entry(self, entry_id: str, text: str, meta: dict, pin: bool):
            """
            Saves a world entry

            Arguments:

            - entry_id: str - The unique identifier for the entry
            - text: str - The text to save
            - meta: dict - Any meta information to save
            - pin: bool - Whether to pin the entry
            """

            class Arguments(pydantic.BaseModel):
                entry_id: str
                text: str
                meta: dict
                pin: bool

            validated = Arguments(entry_id=entry_id, text=text, meta=meta, pin=pin)

            agent = get_agent("world_state")

            run_async(
                agent.manager(
                    action_name="save_world_entry",
                    entry_id=validated.entry_id,
                    text=validated.text,
                    meta=validated.meta,
                    pin=validated.pin,
                )
            )

        def update_world_state(self, force: bool = False):
            """
            Updates the world state

            Arguments:

            - force: bool - Whether to force the update
            """

            class Arguments(pydantic.BaseModel):
                force: bool

            validated = Arguments(force=force)

            world_state = get_agent("world_state")

            run_async(world_state.update_world_state(force=validated.force))

    return API()
