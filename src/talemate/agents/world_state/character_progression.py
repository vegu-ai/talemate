from typing import TYPE_CHECKING
import structlog
import re
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig
)
from talemate.prompts import Prompt
from talemate.instance import get_agent
from talemate.events import GameLoopEvent
from talemate.status import set_loading
from talemate.emit import emit

import talemate.emit.async_signals
import talemate.game.focal as focal
import talemate.world_state.templates as world_state_templates
from talemate.world_state.manager import WorldStateManager
from talemate.world_state import Suggestion

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger()

class CharacterProgressionMixin:
    
    """
    World-state manager agent mixin that handles tracking of character progression
    and proposal of updates to character profiles.
    """

    @classmethod
    def add_actions(cls, summarizer):
        summarizer.actions["character_progression"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            quick_toggle=True,
            experimental=True,
            label="Character Progression",
            icon="mdi-account-switch",
            description="Tracks and proposes updates to character profiles, based on scene progression.",
            config={
                "frequency": AgentActionConfig(
                    type="number",
                    label="Frequency of checks",
                    description="Number of rounds to wait before checking for character progression.",
                    value=15,
                    min=1,
                    max=100,
                    step=1,
                ),
                "as_suggestions": AgentActionConfig(
                    type="bool",
                    label="Propose as suggestions",
                    description="Propose changes as suggestions that need to be manually accepted.",
                    value=True
                ),
                "player_character": AgentActionConfig(
                    type="bool",
                    label="Player character",
                    description="Track the player character's progression.",
                    value=True
                ),
                "max_changes": AgentActionConfig(
                    type="number",
                    label="Max. number of changes proposed / applied",
                    description="Maximum number of changes to propose or apply per character.",
                    value=1,
                    min=1,
                    max=5,
                )
            }
        )
        
    # config property helpers 
    
    @property
    def character_progression_enabled(self) -> bool:
        return self.actions["character_progression"].enabled
    
    @property
    def character_progression_frequency(self) -> int:
        return self.actions["character_progression"].config["frequency"].value

    @property
    def character_progression_player_character(self) -> bool:
        return self.actions["character_progression"].config["player_character"].value

    @property
    def character_progression_max_changes(self) -> int:
        return self.actions["character_progression"].config["max_changes"].value
    
    @property
    def character_progression_as_suggestions(self) -> bool:
        return self.actions["character_progression"].config["as_suggestions"].value

    # signal connect

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop").connect(self.on_game_loop_track_character_progression)


    async def on_game_loop_track_character_progression(self, emission: GameLoopEvent):
        """
        Called when a conversation is generated
        """

        if not self.enabled or not self.character_progression_enabled:
            return
        
        log.debug("on_game_loop_track_character_progression", scene=self.scene)
        
        rounds_since_last_check = self.get_scene_state("rounds_since_last_character_progression_check", 0)
        
        if rounds_since_last_check < self.character_progression_frequency:
            rounds_since_last_check += 1
            self.set_scene_states(rounds_since_last_character_progression_check=rounds_since_last_check)
            return
        
        self.set_scene_states(rounds_since_last_character_progression_check=0)
        
        for character in self.scene.characters:
            
            if character.is_player and not self.character_progression_player_character:
                continue
            
            calls:list[focal.Call] = await self.determine_character_development(character)
            await self.character_progression_process_calls(
                character = character,
                calls = calls,
                as_suggestions = self.character_progression_as_suggestions,
            )
        
    # methods
    
    @set_processing
    async def character_progression_process_calls(self, character:"Character", calls:list[focal.Call], as_suggestions:bool=True):
        
        world_state_manager:WorldStateManager = self.scene.world_state_manager
        if as_suggestions:
            await world_state_manager.add_suggestion(
                Suggestion(
                    name=character.name,
                    type="character",
                    id=f"character-{character.name}",
                    proposals=calls
                )
            )
        else:
            for call in calls:
                # changes will be applied directly to the character
                if call.name in ["add_attribute", "update_attribute"]:
                    await character.set_base_attribute(call.arguments["name"], call.result)
                elif call.name == "remove_attribute":
                    await character.set_base_attribute(call.arguments["name"], None)
                elif call.name == "update_description":
                    await character.set_description(call.result)
                
    @set_processing
    async def determine_character_development(
        self, 
        character: "Character",
        generation_options: world_state_templates.GenerationOptions | None = None,
        instructions: str = None,
    ) -> list[focal.Call]:
        """
        Determine character development
        """
        
        log.debug("determine_character_development", character=character, generation_options=generation_options)
        
        creator = get_agent("creator")
        
        @set_loading("Generating character attribute", cancellable=True)
        async def add_attribute(name: str, instructions: str) -> str:
            return await creator.generate_character_attribute(
                character,
                attribute_name = name,
                instructions = instructions,
                generation_options = generation_options,
            )
            
        @set_loading("Generating character attribute", cancellable=True)
        async def update_attribute(name: str, instructions: str) -> str:
            return await creator.generate_character_attribute(
                character,
                attribute_name = name,
                instructions = instructions,
                original = character.base_attributes.get(name),
                generation_options = generation_options,
            )
        
        async def remove_attribute(name: str, reason:str) -> str:
            return None
            
        @set_loading("Generating character description", cancellable=True)
        async def update_description(instructions: str) -> str:
            return await creator.generate_character_detail(
                character,
                detail_name = "description",
                instructions = instructions,
                original = character.description,
                length=1024,
                generation_options = generation_options,
            )
                 
        focal_handler = focal.Focal(
            self.client,
            
            # callbacks
            callbacks = [
                focal.Callback(
                    name = "add_attribute",
                    arguments = [
                        focal.Argument(name="name", type="str"),
                        focal.Argument(name="instructions", type="str"),
                    ],
                    fn = add_attribute
                ),
                focal.Callback(
                    name = "update_attribute",
                    arguments = [
                        focal.Argument(name="name", type="str"),
                        focal.Argument(name="instructions", type="str"),
                    ],
                    fn = update_attribute
                ),
                focal.Callback(
                    name = "remove_attribute",
                    arguments = [
                        focal.Argument(name="name", type="str"),
                        focal.Argument(name="reason", type="str"),
                    ],
                    fn = remove_attribute
                ),
                focal.Callback(
                    name = "update_description",
                    arguments = [
                        focal.Argument(name="instructions", type="str"),
                    ],
                    fn = update_description,
                    multiple=False
                ),
            ],
            
            max_calls = self.character_progression_max_changes,
            
            # context
            character = character,
            scene = self.scene,
            instructions = instructions,
        )
        
        await focal_handler.request(
            "world_state.determine-character-development",
        )
        
        log.debug("determine_character_development", calls=focal_handler.state.calls)
        
        return focal_handler.state.calls