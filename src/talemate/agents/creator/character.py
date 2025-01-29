from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from talemate.agents.base import set_processing
from talemate.prompts import Prompt

import talemate.game.focal as focal

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger("talemate.agents.creator.character")

DEFAULT_CONTENT_CONTEXT = "a fun and engaging adventure aimed at an adult audience."


class CharacterCreatorMixin:

    @set_processing
    async def determine_content_context_for_character(
        self,
        character: Character,
    ):
        content_context = await Prompt.request(
            f"creator.determine-content-context",
            self.client,
            "create",
            vars={
                "character": character,
            },
        )
        return content_context.strip()

    @set_processing
    async def determine_character_dialogue_instructions(
        self,
        character: Character,
        instructions: str = "",
    ):
        instructions = await Prompt.request(
            f"creator.determine-character-dialogue-instructions",
            self.client,
            "create_concise",
            vars={
                "character": character,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "instructions": instructions,
            },
        )

        r = instructions.strip().split("\n")[0].strip('"').strip()
        return r

    @set_processing
    async def determine_character_attributes(
        self,
        character: Character,
    ):
        attributes = await Prompt.request(
            f"creator.determine-character-attributes",
            self.client,
            "analyze_long",
            vars={
                "character": character,
            },
        )
        return attributes

    @set_processing
    async def determine_character_name(
        self,
        character_name: str,
        allowed_names: list[str] = None,
        group: bool = False,
    ) -> str:
        name = await Prompt.request(
            f"creator.determine-character-name",
            self.client,
            "analyze_freeform_short",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character_name": character_name,
                "allowed_names": allowed_names or [],
                "group": group,
            },
        )
        return name.split('"', 1)[0].strip().strip(".").strip()

    @set_processing
    async def determine_character_description(
        self, character: Character, text: str = ""
    ):
        description = await Prompt.request(
            f"creator.determine-character-description",
            self.client,
            "create",
            vars={
                "character": character,
                "scene": self.scene,
                "text": text,
                "max_tokens": self.client.max_token_length,
            },
        )
        return description.strip()

    @set_processing
    async def determine_character_goals(
        self,
        character: Character,
        goal_instructions: str,
    ):
        goals = await Prompt.request(
            f"creator.determine-character-goals",
            self.client,
            "create",
            vars={
                "character": character,
                "scene": self.scene,
                "goal_instructions": goal_instructions,
                "npc_name": character.name,
                "player_name": self.scene.get_player_character().name,
                "max_tokens": self.client.max_token_length,
            },
        )

        log.debug("determine_character_goals", goals=goals, character=character)
        await character.set_detail("goals", goals.strip())

        return goals.strip()