"""
Contains the legacy creator functions that will be removed
soon.

These functions are used to create characters and scenarios and have been replaced
by the new ContextualGenerate functionality.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable

import structlog

from talemate.agents.base import set_processing
from talemate.exceptions import LLMAccuracyError
from talemate.prompts import LoopedPrompt, Prompt

if TYPE_CHECKING:
    from talemate.tale_mate import Character
    
__all__ = [
    "LegacyCharacterCreatorMixin",
    "LegacyScenarioCreatorMixin",
]

log = structlog.get_logger("talemate.agents.creator.character")

DEFAULT_CONTENT_CONTEXT = "a fun and engaging adventure aimed at an adult audience."

def validate(k, v):
    if k and k.lower() == "gender":
        return v.lower().strip()
    if k and k.lower() == "age":
        try:
            return int(v.split("\n")[0].strip())
        except (ValueError, TypeError):
            raise LLMAccuracyError(
                "Was unable to get a valid age from the response", model_name=None
            )

    return v.strip().strip("\n")


class LegacyCharacterCreatorMixin:

    """
    Adds character creation functionality to the creator agent
    """

    @set_processing
    async def create_character_attributes(
        self,
        character_prompt: str,
        template: str,
        use_spice: float = 0.15,
        attribute_callback: Callable = lambda x: x,
        content_context: str = DEFAULT_CONTENT_CONTEXT,
        custom_attributes: dict[str, str] = dict(),
        predefined_attributes: dict[str, str] = dict(),
    ):
        def spice(prompt, spices):
            # generate number from 0 to 1 and if its smaller than use_spice
            # select a random spice from the list and return it formatted
            # in the prompt
            if random.random() < use_spice:
                spice = random.choice(spices)
                return prompt.format(spice=spice)
            return ""

        # drop any empty attributes from predefined_attributes

        predefined_attributes = {k: v for k, v in predefined_attributes.items() if v}

        prompt = Prompt.get(
            f"creator.character-attributes-{template}",
            vars={
                "character_prompt": character_prompt,
                "template": template,
                "spice": spice,
                "content_context": content_context,
                "custom_attributes": custom_attributes,
                "character_sheet": LoopedPrompt(
                    validate_value=validate,
                    on_update=attribute_callback,
                    generated=predefined_attributes,
                ),
            },
        )
        await prompt.loop(self.client, "character_sheet", kind="create_concise")

        return prompt.vars["character_sheet"].generated

    @set_processing
    async def create_character_description(
        self,
        character: Character,
        content_context: str = DEFAULT_CONTENT_CONTEXT,
    ):
        description = await Prompt.request(
            f"creator.character-description",
            self.client,
            "create",
            vars={
                "character": character,
                "content_context": content_context,
            },
        )

        return description.strip()

    @set_processing
    async def create_character_details(
        self,
        character: Character,
        template: str,
        detail_callback: Callable = lambda question, answer: None,
        questions: list[str] = None,
        content_context: str = DEFAULT_CONTENT_CONTEXT,
    ):
        prompt = Prompt.get(
            f"creator.character-details-{template}",
            vars={
                "character_details": LoopedPrompt(
                    validate_value=validate,
                    on_update=detail_callback,
                ),
                "template": template,
                "content_context": content_context,
                "character": character,
                "custom_questions": questions or [],
            },
        )
        await prompt.loop(self.client, "character_details", kind="create_concise")
        return prompt.vars["character_details"].generated
    
    
    @set_processing
    async def create_character_example_dialogue(
        self,
        character: Character,
        template: str,
        guide: str,
        examples: list[str] = None,
        content_context: str = DEFAULT_CONTENT_CONTEXT,
        example_callback: Callable = lambda example: None,
        rules_callback: Callable = lambda rules: None,
    ):
        """
        All of this functionality has been moved to ContextualGenerate
        Keeping this here for now for backwards compatibility with
        the legacy creative toolset.
        """
        
        dialogue_rules = await Prompt.request(
            f"creator.character-dialogue-rules",
            self.client,
            "create",
            vars={
                "guide": guide,
                "character": character,
                "examples": examples or [],
                "content_context": content_context,
            },
        )

        log.info("dialogue_rules", dialogue_rules=dialogue_rules)

        if rules_callback:
            rules_callback(dialogue_rules)

        example_dialogue_prompt = Prompt.get(
            f"creator.character-example-dialogue-{template}",
            vars={
                "guide": guide,
                "character": character,
                "examples": examples or [],
                "content_context": content_context,
                "dialogue_rules": dialogue_rules,
                "generated_examples": LoopedPrompt(
                    validate_value=validate,
                    on_update=example_callback,
                ),
            },
        )

        await example_dialogue_prompt.loop(
            self.client, "generated_examples", kind="create"
        )

        return example_dialogue_prompt.vars["generated_examples"].generated
    
    
class LegacyScenarioCreatorMixin:
    
    @set_processing
    async def create_scene_description(
        self,
        prompt: str,
        content_context: str,
    ):
        """
        Creates a new scene.

        Arguments:

            prompt (str): The prompt to use to create the scene.

            content_context (str): The content context to use for the scene.

            callback (callable): A callback to call when the scene has been created.
        """
        scene = self.scene

        description = await Prompt.request(
            "creator.scenario-description",
            self.client,
            "create",
            vars={
                "prompt": prompt,
                "content_context": content_context,
                "max_tokens": self.client.max_token_length,
                "scene": scene,
            },
        )
        description = description.strip()

        return description

    @set_processing
    async def create_scene_name(
        self,
        prompt: str,
        content_context: str,
        description: str,
    ):
        """
        Generates a scene name.

        Arguments:

            prompt (str): The prompt to use to generate the scene name.

            content_context (str): The content context to use for the scene.

            description (str): The description of the scene.
        """
        scene = self.scene

        name = await Prompt.request(
            "creator.scenario-name",
            self.client,
            "create",
            vars={
                "prompt": prompt,
                "content_context": content_context,
                "description": description,
                "scene": scene,
            },
        )
        name = name.strip().strip(".!").replace('"', "")
        return name

    @set_processing
    async def create_scene_intro(
        self,
        prompt: str,
        content_context: str,
        description: str,
        name: str,
    ):
        """
        Generates a scene introduction.

        Arguments:

            prompt (str): The prompt to use to generate the scene introduction.

            content_context (str): The content context to use for the scene.

            description (str): The description of the scene.

            name (str): The name of the scene.
        """

        scene = self.scene

        intro = await Prompt.request(
            "creator.scenario-intro",
            self.client,
            "create",
            vars={
                "prompt": prompt,
                "content_context": content_context,
                "description": description,
                "name": name,
                "scene": scene,
            },
        )
        intro = intro.strip()
        return intro