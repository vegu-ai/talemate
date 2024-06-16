from typing import TYPE_CHECKING
import pydantic
from talemate.game.engine.api.base import ScopedAPI, run_async
import talemate.game.engine.api.schema as schema
from talemate.game.engine.api.exceptions import UnknownCharacter, SceneInactive


if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "create"
]

def create(scene: "Scene") -> "ScopedAPI":
    class API(ScopedAPI):
        
        help_text = """Functions for scene direction and manipulation"""
        
        @property
        def player_characters(self) -> list[schema.CharacterSchema]:
            
            """
            Returns a list of all active characters currently controlled by the
            user in the scene
            """
            
            character = scene.get_player_character()
            
            if not character:
                return []
            
            return [schema.CharacterSchema.from_character(character)]
        
        
        @property
        def npc_characters(self) -> list[schema.CharacterSchema]:
            
            """
            Returns a list of all active non-player characters in the scene
            """
            
            return [
                schema.CharacterSchema.from_character(character) 
                for character in scene.get_npc_characters()
            ]
            
        
        @property
        def npc_character_names(self) -> list[str]:
            
            """
            Returns a list of all active non-player character names in the scene
            """
            
            return [character.name for character in scene.get_npc_characters()]
        
        @property
        def npc_character_count(self) -> int:
            
            """
            Returns the number of active non-player characters in the scene
            """
            
            return len(scene.get_npc_characters())
        
        @property
        def last_player_message(self) -> schema.CharacterMessageSchema | None:
            
            """
            Returns the last message sent by the player
            """
            
            last_player_message = scene.last_player_message()
            
            if not last_player_message:
                return None
            
            return schema.CharacterMessageSchema.from_message(last_player_message)
        
        def context_history(self, budget: int = 2048, keep_director: bool | str = False) -> list[str]:
        
            """
            Returns the context history for the scene
            
            Arguments:
            
            - budget: int - The maximum number of tokens to return
            - keep_director: bool | str - Whether to keep the director messages
            
            Returns:
            
            - list[str] - The context history
            """
            
            class Arguments(pydantic.BaseModel):
                budget: int
                keep_director: bool | str
                
            validated = Arguments(
                budget=budget,
                keep_director=keep_director
            )
            
            return scene.context_history(validated.budget, validated.keep_director)
            
        
        def get_player_character(self) -> schema.CharacterSchema | None:
                
            """
            Returns the player character
            """
            
            player_character = scene.get_player_character()
            
            if not player_character:
                return None
            
            return schema.CharacterSchema.from_character(player_character)
        
        def get_character(self, character_name:str, raise_errors:bool=False) -> schema.CharacterSchema | None:
            """
            Returns a character by name
            
            Arguments:
            
            - character_name: str - The name of the character
            - raise_errors: bool - Whether to raise an error if the character is not found
            
            Raises:
            
            - UnknownCharacter - If the character is not found
            """
            
            character = scene.get_character(character_name)
            
            if not character:
                if raise_errors:
                    raise UnknownCharacter(character_name)
                return None
            
            return schema.CharacterSchema.from_character(character)
        
        def hide_message(self, message_id: int):
            
            """
            Hides a message by ID
            
            Arguments:
            
            - message_id: int - The ID of the message to hide
            """
            
            class Arguments(pydantic.BaseModel):
                message_id: int
                
            validated = Arguments(
                message_id=message_id
            )
            
            idx = scene.message_index(validated.message_id)
            
            if idx == -1:
                return
            
            message = scene.history[idx]
            message.hide()
            
            

        
        def pop_history(self, typ:str | schema.MessageTypes, all:bool, reverse:bool=False):
            """
            Removes the last message from the history
            
            Arguments:
            
            - typ: str - The type of message to remove (e.g., 'character', 'narrator', 'director', 'time_passage', 'reinforcement')
            - all: bool - Whether to remove all messages of the specified type
            - reverse: bool - Whether to remove the first message instead of the last
            """
            
            class Arguments(pydantic.BaseModel):
                typ: schema.MessageTypes
                all: bool
                reverse: bool
                
            validated = Arguments(
                typ=typ,
                all=all,
                reverse=reverse
            )
            
            scene.pop_history(validated.typ, validated.all, validated.reverse)

        def restore(self):
            """
            Restores the scene to its original state
            
            The scene needs to have its `restore_from` property specified
            """
            
            run_async(scene.restore())

        def set_content_context(self, context:str):
            
            """
            Sets the content context for the scene
            
            Arguments:
            
            - context: str - The content context to set
            """
            
            class Arguments(pydantic.BaseModel):
                context: str
                
            validated = Arguments(
                context=context
            )
            
            scene.set_content_context(validated.context)


        def set_character_description(
            self,
            character_name: str,
            description:str
        ):
            
            """
            Sets the description for a character
            
            Arguments:
            
            - character_name: str - The name of the characte
            - description: str - The description to set
            
            Raises:
            
            - UnknownCharacter - If the character is not found
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                description: str
                
            validated = Arguments(
                character_name=character_name,
                description=description
            )
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
            
            character.update(description=validated.description)

        
        def set_character_attributes(
            self,
            character_name: str,
            attributes: dict[str, str]
        ):
            
            """
            Sets the attributes for a character
            
            Arguments:
            
            - character_name: str - The name of the character
            - attributes: dict[str, str] - The attributes to set
            
            Raises:
            
            - UnknownCharacter - If the character is not found
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                attributes: dict[str, str]
                
            validated = Arguments(
                character_name=character_name,
                attributes=attributes
            )
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
            
            character.update(base_attributes=validated.attributes)

        def set_character_name(
            self,
            character_name: str,
            new_name: str
        ):
            
            """
            Renames a character
            
            Arguments:
            
            - character_name: str - The name of the character
            - new_name: str - The new name to set
            
            Raises:
            
            - UnknownCharacter - If the character is not found
            """
            
            class Arguments(pydantic.BaseModel):
                character_name: str
                new_name: str
                
            validated = Arguments(
                character_name=character_name,
                new_name=new_name
            )
            
            character = scene.get_character(validated.character_name)
            
            if not character:
                raise UnknownCharacter(validated.character_name)
            
            character.rename(validated.new_name)
            
        
            
        def set_description(self, description:str):
            
            """
            Sets the description for the scene
            
            Arguments:
            
            - description: str - The description to set
            """
            
            class Arguments(pydantic.BaseModel):
                description: str
                
            validated = Arguments(
                description=description
            )
            
            scene.set_description(validated.description)
            
            
        def set_intro(self, intro:str):
            
            """
            Sets the intro for the scene
            
            Arguments:
            
            - intro: str - The intro to set
            """
            
            class Arguments(pydantic.BaseModel):
                intro: str
                
            validated = Arguments(
                intro=intro
            )
            
            scene.set_intro(validated.intro)
            

            
        def set_title(self, title:str):
            
            """
            Sets the title for the scene
            
            Arguments:
            
            - title: str - The title to set
            """
            
            class Arguments(pydantic.BaseModel):
                title: str
                
            validated = Arguments(
                title=title
            )
            
            scene.set_title(validated.title)
            
        def show_message(self, message_id: int):
            
            """
            Shows a message by ID
            
            Arguments:
            
            - message_id: int - The ID of the message to show
            """
            
            class Arguments(pydantic.BaseModel):
                message_id: int
                
            validated = Arguments(
                message_id=message_id
            )
            
            idx = scene.message_index(validated.message_id)
            
            if idx == -1:
                return
            
            message = scene.history[idx]
            message.show()
            
    return API()