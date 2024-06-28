"""
Functions for the narrator agent
"""
from typing import TYPE_CHECKING

import pydantic

from talemate.scene_message import NarratorMessage
from talemate.game.engine.api.base import ScopedAPI, run_async
from talemate.game.engine.api.exceptions import UnknownAgentAction, UnknownCharacter
import talemate.game.engine.api.schema as schema
from talemate.emit import emit
from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "create"
]

def create(scene: "Scene") -> "ScopedAPI":
    class API(ScopedAPI):
        
        def action_to_narration(
            self,
            action_name: str,
            emit_message: bool = False,
            **kwargs,
        ) -> schema.NarratorMessageSchema:
            
            """
            Runs a narrator action and immediatelty converts it to a narration
            ading it to the scene history
            
            Arguments:
            
            - action_name: str - The name of the action to run
            - emit_message: bool - Whether to emit the message to the scene
            - **kwargs: dict - The arguments to pass to the action
            
            Returns:
            
            - schema.NarratorMessageSchema - The narration message
            
            Raises:
            
            - UnknownAgentAction - If the action is not found
            """
            
            narrator = get_agent("narrator")
            
            fn = getattr(self, action_name)
            
            if not fn:
                raise UnknownAgentAction("narrator", action_name)
            
            narration = fn(**kwargs)
            source = narrator.action_to_source(action_name, {k:str(v) for k,v in kwargs.items()})

            narrator_message = NarratorMessage(narration, source=source)
            scene.push_history(narrator_message)

            if emit_message:
                emit("narrator", narrator_message)

            return schema.NarratorMessageSchema.from_message(narrator_message)   
        
        def paraphrase(
            self,
            narration: str,
        ) -> str:
            """
            Paraphrase a narration
            
            Arguments:
            
            - narration: str - The narration to paraphrase
            
            Returns:
            
            - str - The paraphrased narration
            """
            
            class Arguments(pydantic.BaseModel):
                narration: str
                
            validated = Arguments(narration=narration)
            
            narrator = get_agent("narrator")
            return run_async(narrator.paraphrase(validated.narration))
        
        def passthrough(
            self,
            narration: str,
        ) -> str:
            """
            Pass through a narration message as is
            
            Arguments:
            
            - narration: str - The narration to pass through
            
            Returns:
            
            - str - The passed through narration
            """
            
            class Arguments(pydantic.BaseModel):
                narration: str
                
            validated = Arguments(narration=narration)
            narrator = get_agent("narrator")
            return run_async(narrator.passthrough(validated.narration))
        
        def progress_story(
            self,
            narrative_direction: str,
        ) -> str:
            """
            Progress the story in a given direction
            
            Arguments:
            
            - narrative_direction: str - The direction to progress the story
            
            Returns:
            
            - str - The generated narration
            """
            class Arguments(pydantic.BaseModel):
                narrative_direction: str
            validated = Arguments(narrative_direction=narrative_direction)
            narrator = get_agent("narrator")
            return run_async(narrator.progress_story(validated.narrative_direction))
            
        def narrate_scene(
            self,
        ) -> str:
            """
            Narrate a scene
            
            Returns:
            
            - str - The generated narration
            """
            
            narrator = get_agent("narrator")
            return run_async(narrator.narrate_scene())
        
        def narrate_query(
            self,
            query: str,
            at_the_end: bool = False,
        ) -> str:
            
            """
            Query the narrator for a narration based on a question
            or instruction
            
            Arguments:
            
            - query: str - The query to ask the narrator
            - at_the_end: bool - Whether the narration should consider the end of the scene
            as the source of truth

            Returns:
            
            - str - The generated narration
            """
            
            class Arguments(pydantic.BaseModel):
                query: str
                at_the_end: bool
                
            validated = Arguments(query=query, at_the_end=at_the_end)
            narrator = get_agent("narrator")
            return run_async(narrator.narrate_query(validated.query, validated.at_the_end))
        
        def narrate_character(
            self,
            character_name: str,
        ) -> str:
            """
            Narrate a character
            
            Arguments:
            
            - character_name: str - The name of the character to narrate
            
            Returns:
            
            - str - The generated narration
            
            Raises:
            
            - UnknownCharacter - If the character is not found
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                
            validated = Arguments(character_name=character_name)
            narrator = get_agent("narrator")
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
                
            return run_async(narrator.narrate_character(character))
            
            
        def narrate_time_passage(
            self,
            duration: str,
            time_passed: str,
            narrative: str,
        ) -> str:
            """
            Narrate a specific character
            
            Arguments:
            
            - duration: str - The duration of the time passage
            - time_passed: str - The time passed 
            - narrative: str - The narrative to narrate
            
            Returns:
            
            - str - The generated narration
            """
            
            class Arguments(pydantic.BaseModel):
                duration: str
                time_passed: str
                narrative: str
                
            validated = Arguments(duration=duration, time_passed=time_passed, narrative=narrative)
            narrator = get_agent("narrator")
            return run_async(narrator.narrate_time_passage(validated.duration, validated.time_passed, validated.narrative))
            
            
        def narrate_after_dialogue(
            self,
            character_name: str,
        ) -> str:
            """
            Narrate after a line of dialogue
            
            Arguments:
            
            - character_name: str - The name of the character
            
            Returns:
            
            - str - The generated narration
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                
            validated = Arguments(character_name=character_name)
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
            
            narrator = get_agent("narrator")
            return run_async(narrator.narrate_after_dialogue(character))
        
        
        def narrate_character_entry(
            self,
            character_name: str,
            direction: str = None,
        ) -> str:
            """
            Narrate a character entering the scene
            
            Arguments:
            
            - character_name: str - The name of the character
            - direction: str - The direction the character is entering from
            
            Returns:
            
            - str - The generated narration
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                direction: str
                
            validated = Arguments(character_name=character_name, direction=direction)
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
            
            narrator = get_agent("narrator")
            return run_async(narrator.narrate_character_entry(character, validated.direction))
        
        
        def narrate_character_exit(
            self,
            character_name: str,
            direction: str = None,
        ) -> str:
            """
            Narrate a character exiting the scene
            
            Arguments:
            
            - character_name: str - The name of the character
            - direction: str - The direction the character is exiting to
            
            Returns:
            
            - str - The generated narration
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                direction: str
                
            validated = Arguments(character_name=character_name, direction=direction)
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
            
            narrator = get_agent("narrator")
            return run_async(narrator.narrate_character_exit(character, validated.direction))
        
        
            
    return API()