from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import talemate.client as client
import talemate.util as util
import structlog
from talemate.emit import emit
from talemate.scene_message import CharacterMessage, DirectorMessage
from talemate.prompts import Prompt

from .base import Agent, set_processing
from .registry import register

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene
    
log = structlog.get_logger("talemate.agents.conversation")

@register()
class ConversationAgent(Agent):
    """
    An agent that can be used to have a conversation with the AI

    Ideally used with a Pygmalion or GPT >= 3.5 model
    """

    agent_type = "conversation"
    verbose_name = "Conversation"
    
    min_dialogue_length = 75

    def __init__(
        self,
        client: client.TaleMateClient,
        kind: Optional[str] = "pygmalion",
        logging_enabled: Optional[bool] = True,
        **kwargs,
    ):
        self.client = client
        self.kind = kind
        self.logging_enabled = logging_enabled
        self.logging_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.current_memory_context = None


    async def build_prompt_default(
        self,
        character: Character,
        char_message: Optional[str] = "",
    ):
        """
        Builds the prompt that drives the AI's conversational response
        """
        # the amount of tokens we can use
        # we subtract 200 to account for the response

        scene = character.actor.scene
        
        total_token_budget = self.client.max_token_length - 200
        scene_and_dialogue_budget = total_token_budget - 500
        long_term_memory_budget = min(int(total_token_budget * 0.05), 200)
        
        scene_and_dialogue = scene.context_history(
            budget=scene_and_dialogue_budget, 
            min_dialogue=25, 
            keep_director=True,
            sections=False,
            insert_bot_token=10
        )
        
        memory = await self.build_prompt_default_memory(
            scene, long_term_memory_budget, 
            scene_and_dialogue + [f"{character.name}: {character.description}" for character in scene.get_characters()]
        )

        main_character = scene.main_character.character

        character_names = [c.name for c in scene.characters if not c.is_player]

        if len(character_names) > 1:
            formatted_names = (
                ", ".join(character_names[:-1]) + " or " + character_names[-1]
                if character_names
                else ""
            )
        else:
            formatted_names = character_names[0] if character_names else ""
            
        # if there is more than 10 lines in scene_and_dialogue insert
        # a <|BOT|> token at -10, otherwise insert it at 0

        try:
            director_message = isinstance(scene_and_dialogue[-1], DirectorMessage)
        except IndexError:
            director_message = False

        prompt = Prompt.get("conversation.dialogue", vars={
            "scene": scene,
            "max_tokens": self.client.max_token_length,
            "scene_and_dialogue_budget": scene_and_dialogue_budget,
            "scene_and_dialogue": scene_and_dialogue,
            "memory": memory,
            "characters": list(scene.get_characters()),
            "main_character": main_character,
            "formatted_names": formatted_names,
            "talking_character": character,
            "partial_message": char_message,
            "director_message": director_message,
        })
        
        return str(prompt)
    
    async def build_prompt_default_memory(
        self, scene: Scene, budget: int, existing_context: list
    ):
        """
        Builds long term memory for the conversation prompt

        This will take the last 3 messages from the history and feed them into the memory as queries
        in order to extract relevant information from the memory.

        This will only add as much as can fit into the budget. (token budget)

        Also it will only add information that is not already in the existing context.
        """

        memory = scene.get_helper("memory").agent

        if not memory:
            return []

        if self.current_memory_context:
            return self.current_memory_context

        self.current_memory_context = []

        # feed the last 3 history message into multi_query
        history_length = len(scene.history)
        i = history_length - 1
        while i >= 0 and i >= len(scene.history) - 3:
            self.current_memory_context += await memory.multi_query(
                [scene.history[i]],
                filter=lambda x: x
                not in self.current_memory_context + existing_context,
            )
            i -= 1

        return self.current_memory_context
    

    async def build_prompt(self, character, char_message: str = ""):
        fn = self.build_prompt_default

        return await fn(character, char_message=char_message)

    def clean_result(self, result, character):
        
        log.debug("clean result", result=result)
        
        if "#" in result:
            result = result.split("#")[0]
        
        result = result.replace(" :", ":")
        result = result.strip().strip('"').strip()
        result = result.replace("[", "*").replace("]", "*")
        result = result.replace("(", "*").replace(")", "*")
        result = result.replace("**", "*")

        # if there is an uneven number of '*' add one to the end

        if result.count("*") % 2 == 1:
            result += "*"

        return result

    @set_processing
    async def converse(self, actor, editor=None):
        """
        Have a conversation with the AI
        """

        history = actor.history
        self.current_memory_context = None

        character = actor.character

        result = await self.client.send_prompt(await self.build_prompt(character))

        result = self.clean_result(result, character)

        # Set max limit of loops
        max_loops = self.client.conversation_retries
        loop_count = 0
        total_result = result

        empty_result_count = 0

        # Validate AI response
        while loop_count < max_loops and len(total_result) < self.min_dialogue_length:
            log.debug("conversation agent", result=result)
            result = await self.client.send_prompt(
                await self.build_prompt(character, char_message=total_result)
            )

            result = self.clean_result(result, character)

            total_result += " "+result

            if len(total_result) == 0 and max_loops < 10:
                max_loops += 1

            loop_count += 1

            if len(total_result) > self.min_dialogue_length:
                break

            # if result is empty, increment empty_result_count
            # and if we get 2 empty responses in a row, break

            if result == "":
                empty_result_count += 1
                if empty_result_count >= 2:
                    break

        result = result.replace(" :", ":")

        total_result = total_result.split("#")[0]

        # Removes partial sentence at the end
        total_result = util.strip_partial_sentences(total_result)
        
        # Remove "{character.name}:" - all occurences
        total_result = total_result.replace(f"{character.name}:", "")

        if total_result.count("*") % 2 == 1:
            total_result += "*"

        # Check if total_result starts with character name, if not, prepend it
        if not total_result.startswith(character.name):
            total_result = f"{character.name}: {total_result}"

        total_result = total_result.strip()

        if total_result == "" or total_result == f"{character.name}:":
            log.warn("conversation agent", result="Empty result")

        # replace any white space betwen {self.charactrer.name}: and the first word with a single space
        total_result = re.sub(
            rf"{character.name}:\s+", f"{character.name}: ", total_result
        )

        response_message = util.parse_messages_from_str(total_result, [character.name])

        if editor:
            response_message = [
                editor.help_edit(character, message) for message in response_message
            ]

        messages = [CharacterMessage(message) for message in response_message]

        # Add message and response to conversation history
        actor.scene.push_history(messages)

        return messages
