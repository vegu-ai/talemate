from __future__ import annotations

import re
import asyncio
import random
import structlog
from typing import TYPE_CHECKING, Callable

import talemate.util as util
from talemate.emit import emit
from talemate.prompts import Prompt, LoopedPrompt
from talemate.exceptions import LLMAccuracyError

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger("talemate.agents.creator.character")

def validate(k,v):
    if k and k.lower() == "gender":
        return v.lower().strip()
    if k and k.lower() == "age":
        try:
            return int(v.split("\n")[0].strip())
        except (ValueError, TypeError):
            raise LLMAccuracyError("Was unable to get a valid age from the response", model_name=None)
            
    return v.strip().strip("\n")

DEFAULT_CONTENT_CONTEXT="a fun and engaging adventure aimed at an adult audience."

class CharacterCreatorMixin:
    """
    Adds character creation functionality to the creator agent
    """
    
    ## NEW
    
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
        
        try:
            await self.emit_status(processing=True)
            
            def spice(prompt, spices):
                # generate number from 0 to 1 and if its smaller than use_spice
                # select a random spice from the list and return it formatted
                # in the prompt
                if random.random() < use_spice:
                    spice = random.choice(spices)
                    return prompt.format(spice=spice)
                return ""    
            
            # drop any empty attributes from predefined_attributes
            
            predefined_attributes = {k:v for k,v in predefined_attributes.items() if v}
            
            prompt = Prompt.get(f"creator.character-attributes-{template}", vars={
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
            })
            await prompt.loop(self.client, "character_sheet", kind="create_concise")
            
            return prompt.vars["character_sheet"].generated
        
        finally:
            await self.emit_status(processing=False)
    
    
    async def create_character_description(
        self, 
        character:Character, 
        content_context: str = DEFAULT_CONTENT_CONTEXT,
    ):
        
        try:
            await self.emit_status(processing=True)
            description = await Prompt.request(f"creator.character-description", self.client, "create", vars={
                "character": character,
                "content_context": content_context,
            })
            
            return description.strip()
        finally:
            await self.emit_status(processing=False)
        
    
    async def create_character_details(
        self, 
        character: Character,
        template: str,
        detail_callback: Callable = lambda question, answer: None,
        questions: list[str] = None,
        content_context: str = DEFAULT_CONTENT_CONTEXT,
    ):
        try:
            await self.emit_status(processing=True)
            prompt = Prompt.get(f"creator.character-details-{template}", vars={
                "character_details": LoopedPrompt(
                    validate_value=validate,
                    on_update=detail_callback,
                ),
                "template": template,
                "content_context": content_context,
                "character": character,
                "custom_questions": questions or [],
            })
            await prompt.loop(self.client, "character_details", kind="create_concise")
            return prompt.vars["character_details"].generated
        finally:
            await self.emit_status(processing=False)
    
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
        
        try:
            await self.emit_status(processing=True)
        
            dialogue_rules = await Prompt.request(f"creator.character-dialogue-rules", self.client, "create", vars={
                "guide": guide,
                "character": character,
                "examples": examples or [],
                "content_context": content_context,
            })
            
            log.info("dialogue_rules", dialogue_rules=dialogue_rules)
            
            if rules_callback:
                rules_callback(dialogue_rules)
                
            example_dialogue_prompt = Prompt.get(f"creator.character-example-dialogue-{template}", vars={
                "guide": guide,
                "character": character,
                "examples": examples or [],
                "content_context": content_context,
                "dialogue_rules": dialogue_rules,
                "generated_examples": LoopedPrompt(
                    validate_value=validate,
                    on_update=example_callback,
                ),
            })
            
            await example_dialogue_prompt.loop(self.client, "generated_examples", kind="create")
            
            return example_dialogue_prompt.vars["generated_examples"].generated
        finally:
            await self.emit_status(processing=False)
            
            
    async def determine_content_context_for_character(
        self,
        character: Character,
    ):
        
        try:
            await self.emit_status(processing=True)
            content_context = await Prompt.request(f"creator.determine-content-context", self.client, "create", vars={
                "character": character,
            })
            return content_context.strip()
        finally:
            await self.emit_status(processing=False)
            
    async def determine_character_attributes(
        self,
        character: Character,
    ):
        
        try:
            await self.emit_status(processing=True)
            attributes = await Prompt.request(f"creator.determine-character-attributes", self.client, "analyze_long", vars={
                "character": character,
            })
            return attributes
        finally:
            await self.emit_status(processing=False)