"""
Functions for the creator agent
"""
from typing import TYPE_CHECKING

import pydantic

from talemate.game.engine.api.base import ScopedAPI, run_async
from talemate.game.engine.api.exceptions import UnknownCharacter
from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

def create(scene: "Scene") -> "ScopedAPI":
    class API(ScopedAPI):
        
        def determine_content_context_for_description(
            self,
            description:str,
        ) -> str:
            """
            Determines the content context for a description
            
            This will be a short description like "A sci-fi story with a twist"
            
            Arguments:
            
            - description: str - The description to determine the content context for
            
            Returns:
            
            - str - The generated content context
            """
            
            class Arguments(pydantic.BaseModel):
                description: str
                
            validated = Arguments(
                description=description
            )
            
            creator = get_agent("creator")
            
            return run_async(
                creator.determine_content_context_for_description(
                    description=validated.description
                )
            )
            
        def contextual_generate_from_args(
            self,
            context_type: str,
            instructions: str = "",
            length: int = 100,
            character: str | None = None,
            original: str | None = None,
            partial: str = "",
            uid: str | None = None,
            context_aware: bool = True,
            history_aware: bool = True,
        ):
            """
            Generate content based on context and instructions
            
            Arguments:
            
            - context_type: str - The type of context to generate content for
              This should be a string containing a left and right part delimited by a ':'
              such as "character attribute:appearance" or "scene:title"
            - instructions: str - Extra instructions for the generation
            - length: int - The length of the content to generate (tokens)
            - character: str | None - The character to generate content for
            - original: str | None - The original content to generate content from
            - partial: str - Continue the partial content
            - uid: str | None - The UID of the content to generate
            - context_aware: bool - Whether to be context aware during generation
            - history_aware: bool - Whether to be history aware during generation
            
            Context Type explained:
            
            While this can be free-form type and name, there are some pre-defined types that should
            be used when possible. These are:
            
            - character attribute:attribute_name
            - character detail:detail_name
            - scene intro:
            - character dialogue:character_name - for example dialogue generation
            - list:list_name_or_description - for generating a list of items
            
            Returns:
            
            - str - The generated content
            """
            
            class Arguments(pydantic.BaseModel):
                context_type: str
                instructions: str
                length: int
                character: str | None
                original: str | None
                partial: str
                uid: str | None
                context_aware: bool
                history_aware: bool
                
            validated = Arguments(
                context_type=context_type,
                instructions=instructions,
                length=length,
                character=character,
                original=original,
                partial=partial,
                uid=uid,
                context_aware=context_aware,
                history_aware=history_aware
            )
            
            creator = get_agent("creator")
            
            return run_async(
                creator.contextual_generate_from_args(
                    context=validated.context_type,
                    instructions=validated.instructions,
                    length=validated.length,
                    character=validated.character,
                    original=validated.original,
                    partial=validated.partial,
                    uid=validated.uid,
                    context_aware=validated.context_aware,
                    history_aware=validated.history_aware
                )
            )
            
        def determine_character_description(
            self,
            character_name:str,
        ) -> str:
            """
            Determines the description for a character
            
            Arguments:
            
            - character_name: str - The name of the character
            
            Returns:
            
            - str - The generated description
            
            Raises:
            
            - UnknownCharacter - If the character is not found
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                
            validated = Arguments(
                character_name=character_name
            )
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
            
            creator = get_agent("creator")
            
            return run_async(
                creator.determine_character_description(
                    character=character
                )
            )
            

        def determine_character_name(
            self,
            instructions: str,
            allowed_names: list[str] = None,
            group: bool = False,
        ) -> str:
            
            """
            Determines a fitting name based on an existing name or descriptive name
            
            Ideally this will take a name like `David` and return the same name, but
            when give `Stranger with a sword` it will return `David` or another fitting name 
            (depending on the context in the scene).
            
            Arguments:
            
            - instructions: str - The descriptive character name or description and any instructions
              to guide the name generation
            - allowed_names: list[str] - A list of names that are allowed to be returned
            - group: bool - Whether `character_name` describes a group of characters
            
            Returns:
            
            - str - The determined name
            """
            
            class Arguments(pydantic.BaseModel):
                instructions: str
                allowed_names: list[str]
                group: bool
                
            validated = Arguments(
                instructions=instructions,
                allowed_names=allowed_names or [],
                group=group
            )
            
            creator = get_agent("creator")
            
            return run_async(
                creator.determine_character_name(
                    character_name=validated.instructions,
                    allowed_names=validated.allowed_names,
                    group=validated.group
                )
            )
        
    return API()