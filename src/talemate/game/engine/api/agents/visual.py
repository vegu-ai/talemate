"""
Functions for the world visual agent
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
        def generate_character_portrait(
            self,
            character_name: str,
        ):
            """
            Generates a portrait for a character

            Arguments:

            - character_name: str - The name of the character
            """

            class Arguments(pydantic.BaseModel):
                character_name: str

            validated = Arguments(character_name=character_name)

            agent = get_agent("visual")

            if not agent.enabled or not agent.allow_automatic_generation:
                return

            return run_async(
                agent.generate_character_portrait(
                    character_name=validated.character_name
                )
            )

    return API()
