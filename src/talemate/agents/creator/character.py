from __future__ import annotations

from typing import TYPE_CHECKING

import re
import structlog

from talemate.agents.base import set_processing
from talemate.prompts import Prompt
from talemate.game import focal

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
            "creator.determine-content-context",
            self.client,
            "create_192",
            vars={
                "character": character,
            },
        )
        return content_context.split("\n")[0].strip()

    @set_processing
    async def determine_character_dialogue_instructions(
        self,
        character: Character,
        instructions: str = "",
        information: str = "",
        update_existing: bool = False,
    ):
        instructions = await Prompt.request(
            "creator.determine-character-dialogue-instructions",
            self.client,
            "create_concise",
            vars={
                "character": character,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "instructions": instructions,
                "information": information,
                "update_existing": update_existing,
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
            "creator.determine-character-attributes",
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
        instructions: str = "",
    ) -> str:
        name = await Prompt.request(
            "creator.determine-character-name",
            self.client,
            "analyze_freeform_short",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "character_name": character_name,
                "allowed_names": allowed_names or [],
                "group": group,
                "instructions": instructions,
            },
        )

        # Extract name from <NAME></NAME> tags
        names = re.findall(r"<NAME>(.*?)</NAME>", name, re.DOTALL)
        if names:
            extracted_name = min([n.strip() for n in names], key=len)
        else:
            # Fallback to old parsing method
            extracted_name = name.split('"', 1)[0].strip()

        return extracted_name.strip(".").strip()

    @set_processing
    async def determine_character_description(
        self,
        character: Character,
        text: str = "",
        instructions: str = "",
        information: str = "",
        dynamic_instructions: list = None,
    ):
        vars_dict = {
            "character": character,
            "scene": self.scene,
            "text": text,
            "max_tokens": self.client.max_token_length,
            "instructions": instructions,
            "information": information,
        }

        if dynamic_instructions:
            vars_dict["dynamic_instructions"] = dynamic_instructions

        description = await Prompt.request(
            "creator.determine-character-description",
            self.client,
            "create",
            vars=vars_dict,
        )
        return description.strip()

    @set_processing
    async def determine_character_goals(
        self,
        character: Character,
        goal_instructions: str,
    ):
        goals = await Prompt.request(
            "creator.determine-character-goals",
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

    @set_processing
    async def determine_character_dialogue_examples(
        self,
        character: Character,
        text: str = "",
        dynamic_instructions: list = None,
        max_examples: int = 5,
    ) -> list[str]:
        """Extract or generate dialogue examples for a character from given text.

        Args:
            character: The character to extract dialogue examples for
            text: Text containing dialogue examples and relevant character information
            dynamic_instructions: Optional dynamic instructions for context
            max_examples: Maximum number of dialogue examples to generate (default: 5)

        Returns:
            List of dialogue examples (up to max_examples), formatted as "Character Name: ..."
        """
        dialogue_examples = []

        async def add_dialogue_example(example: str) -> str:
            """Add a dialogue example for the character."""
            # Ensure example starts with character name if not already present
            character_prefix = f"{character.name}:"
            if not example.strip().startswith(character_prefix):
                formatted_example = f"{character_prefix} {example.strip()}"
            else:
                formatted_example = example.strip()

            dialogue_examples.append(formatted_example)
            return formatted_example

        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="add_dialogue_example",
                    arguments=[
                        focal.Argument(
                            name="example", type="str", preserve_newlines=True
                        ),
                    ],
                    fn=add_dialogue_example,
                ),
            ],
            max_calls=max_examples,
            character=character,
            scene=self.scene,
            text=text,
            max_examples=max_examples,
            existing_examples=character.example_dialogue[:3]
            if character.example_dialogue
            else [],
            max_tokens=self.client.max_token_length,
        )

        if dynamic_instructions:
            focal_handler.context["dynamic_instructions"] = dynamic_instructions

        await focal_handler.request(
            "creator.determine-character-dialogue-examples",
        )

        log.debug(
            "determine_character_dialogue_examples",
            character=character.name,
            count=len(dialogue_examples),
            examples=dialogue_examples,
        )

        return dialogue_examples
