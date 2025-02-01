from typing import TYPE_CHECKING
import random
import structlog
from functools import wraps
import dataclasses
from talemate.agents.base import (
    set_processing as _set_processing,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
)
from talemate.events import GameLoopStartEvent
from talemate.scene_message import NarratorMessage, CharacterMessage
from talemate.prompts import Prompt
import talemate.util as util
import talemate.emit.async_signals
from talemate.emit import emit

__all__ = [
    "GenerateChoicesMixin",
]

log = structlog.get_logger()

talemate.emit.async_signals.register(
    "agent.director.generate_choices.before_generate", 
    "agent.director.generate_choices.inject_instructions",
    "agent.director.generate_choices.generated",
)

if TYPE_CHECKING:
    from talemate.tale_mate import Character

@dataclasses.dataclass
class GenerateChoicesEmission(AgentEmission):
    generation: str = ""

def set_processing(fn):
    """
    Custom decorator that emits the agent status as processing while the function
    is running and then emits the result of the function as a GenerateChoicesEmission
    """

    @_set_processing
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        emission: GenerateChoicesEmission = GenerateChoicesEmission(agent=self)
        
        await talemate.emit.async_signals.get("agent.director.generate_choices.before_generate").send(emission)
        await talemate.emit.async_signals.get("agent.director.generate_choices.inject_instructions").send(emission)
        
        response = await fn(self, *args, **kwargs)
        emission.generation = [response]
        
        await talemate.emit.async_signals.get("agent.director.generate_choices.generated").send(emission)
        return emission.generation[0]

    return wrapper


class GenerateChoicesMixin:
    
    """
    Director agent mixin that provides functionality for automatically guiding
    the actors or the narrator during the scene progression.
    """
    
    @classmethod
    def add_actions(cls, director):
        director.actions["_generate_choices"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=True,
            experimental=True,
            label="Dynamic Actions",
            icon="mdi-tournament",
            description="Allows the director to generate clickable choices for the player.",
            config={
                "chance": AgentActionConfig(
                    type="number",
                    label="Chance",
                    description="The chance to generate actions. 0 = never, 1 = always",
                    value=0.3,
                    min=0,
                    max=1,
                    step=0.1,
                ),
                
                "num_choices": AgentActionConfig(
                    type="number",
                    label="Number of Actions",
                    description="The number of actions to generate",
                    value=3,
                    min=1,
                    max=10,
                    step=1,
                ),
                
                "never_auto_progress": AgentActionConfig(
                    type="bool",
                    label="Never Auto Progress on Action Selection",
                    description="If enabled, the scene will not auto progress after you select an action.",
                    value=False,
                ),
                
                "instructions": AgentActionConfig(
                    type="blob",
                    label="Instructions",
                    description="Provide some instructions to the director for generating actions.",
                    value="",
                ),
            }
        )
    
    # config property helpers
        
    @property
    def generate_choices_enabled(self):
        return self.actions["_generate_choices"].enabled
    
    @property
    def generate_choices_chance(self):
        return self.actions["_generate_choices"].config["chance"].value
    
    @property
    def generate_choices_num_choices(self):
        return self.actions["_generate_choices"].config["num_choices"].value

    @property
    def generate_choices_never_auto_progress(self):
        return self.actions["_generate_choices"].config["never_auto_progress"].value

    @property
    def generate_choices_instructions(self):
        return self.actions["_generate_choices"].config["instructions"].value

    # signal connect
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("player_turn_start").connect(self.on_player_turn_start)
        
    async def on_player_turn_start(self, event: GameLoopStartEvent):
        if not self.enabled:
            return
        
        if self.generate_choices_enabled:
            
            # look backwards through history and abort if we encounter
            # a character message with source "player" before either
            # a character message with a different source or a narrator message
            #
            # this is so choices aren't generated when the player message was
            # the most recent content in the scene
            
            for i in range(len(self.scene.history) - 1, -1, -1):
                message = self.scene.history[i]
                if isinstance(message, NarratorMessage):
                    break
                if isinstance(message, CharacterMessage):
                    if message.source == "player":
                        return
                    break
                            
            if random.random() < self.generate_choices_chance:
                await self.generate_choices() 
            
    # methods
    

    @set_processing
    async def generate_choices(
        self,
        instructions: str = None,
        character: "Character | str | None" = None,
    ):
        
        log.info("generate_choices")
        
        if isinstance(character, str):
            character = self.scene.get_character(character)
            
        if not character:
            character = self.scene.get_player_character()
        
        response = await Prompt.request(
            "director.generate-choices",
            self.client,
            "direction_long",
            vars={
                "max_tokens": self.client.max_token_length,
                "scene": self.scene,
                "character": character,
                "num_choices": self.generate_choices_num_choices,
                "instructions": instructions or self.generate_choices_instructions,
            },
        )

        try:
            choice_text = response.split("ACTIONS:", 1)[1]
            choices = util.extract_list(choice_text)
            # strip quotes
            choices = [choice.strip().strip('"') for choice in choices]
            
            # limit to num_choices
            choices = choices[:self.generate_choices_num_choices]
        
        except Exception as e:
            log.error("generate_choices failed", error=str(e), response=response)
            return

        log.info("generate_choices done", choices=choices)
        
        emit(
            "player_choice",
            response,
            data = {
                "choices": choices,
                "character": character.name,
            },
            websocket_passthrough=True
        )