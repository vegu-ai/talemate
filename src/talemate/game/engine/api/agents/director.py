"""
Functions for the director agent
"""
from typing import TYPE_CHECKING

import pydantic

from talemate.game.engine.api.base import ScopedAPI, run_async
from talemate.instance import get_agent
import talemate.game.engine.api.schema as schema

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    
__all__ = [
    "create"
]

def create(scene: "Scene") -> "ScopedAPI":
    class API(ScopedAPI):

        def persist_character(
            self,
            character_name: str,
            content: str,
            determine_name: bool = True,
        ) -> schema.CharacterSchema:
            
            """
            Persists a character in the scene
            
            Arguments:
            
            - character_name: str - The name of the character
            - content: str - The content for the character (e.g. a description, attributes, etc. in free form text)
            - determine_name: bool - Whether to determine the name
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                content: str
                determine_name: bool
                
            validated = Arguments(
                character_name=character_name,
                content=content,
                determine_name=determine_name
            )
            
            director = get_agent("director")
            
            character = run_async(
                director.persist_character(
                    name=validated.character_name,
                    content=validated.content,
                    determine_name=validated.determine_name
                )
            )
            
            return schema.CharacterSchema.from_character(character)
            
            
        
        def log_action(self, action:str, action_description:str):
            """
            Logs a game director action.
            
            This will indicate to the user that the director has taken an action.
            
            Arguments:
            
            - action: str - The action taken
            - action_description: str - A description of the action taken
            """
            
            class Arguments(pydantic.BaseModel):
                action: str
                action_description: str
                
            validated = Arguments(
                action=action,
                action_description=action_description
            )
            
            director = get_agent("director")
            
            run_async(
                director.log_action(
                    action=validated.action,
                    action_description=validated.action_description
                )
            )
    
    return API()
            