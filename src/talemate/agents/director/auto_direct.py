from typing import TYPE_CHECKING
import structlog
import pydantic
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    AgentTemplateEmission,
)
from talemate.status import set_loading
import talemate.game.focal as focal
from talemate.prompts import Prompt
import talemate.emit.async_signals as async_signals
from talemate.scene_message import CharacterMessage, TimePassageMessage, DirectorMessage, NarratorMessage
from talemate.scene.schema import ScenePhase, SceneType, SceneIntent
from talemate.scene.intent import set_scene_phase
from talemate.world_state.manager import WorldStateManager
from talemate.world_state.templates.scene import SceneType as TemplateSceneType
import talemate.agents.director.auto_direct_nodes

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

log = structlog.get_logger("talemate.agents.conversation.direct")


#talemate.emit.async_signals.register(
#)

class AutoDirectMixin:
    
    """
    Director agent mixin for automatic scene direction.
    """
    
    @classmethod
    def add_actions(cls, summarizer):
        summarizer.actions["auto_direct"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=True,
            experimental=True,
            quick_toggle=True,
            label="Auto Direction",
            icon="mdi-bullhorn",
            description="Automatic direction based on scene intention and the natural flow of the current scene.",
            config={
                "max_auto_turns": AgentActionConfig(
                    type="number",
                    label="Max. Auto Turns",
                    description="The maximum number of turns the AI is allowed to generate before it stops and waits for the user to perform an action.",
                    value=3,
                    min=1,
                    max=100,
                    step=1,
                ),
                "max_idle_turns": AgentActionConfig(
                    type="number",
                    label="Max. Idle Turns",
                    description="The maximum number of turns any actor can go without performing an action before they are considered overdue to do something.",
                    value=8,
                    min=1,
                    max=100,
                    step=1,
                ),
                "max_repeat_turns": AgentActionConfig(
                    type="number",
                    label="Max. Repeat Turns",
                    description="The maximum number of turns an actor can go in a row before they are disqualifed from performing another action.",
                    value=1,
                    min=1,
                    max=10,
                    step=1,
                ),
                "instruct_actors": AgentActionConfig(
                    type="bool",
                    label="Instruct Actors",
                    description="Whether to instruct actors on what to do next.",
                    value=False,
                ),
                "instruct_narrator": AgentActionConfig(
                    type="bool",
                    label="Instruct Narrator",
                    description="Whether to instruct the narrator on what to do next.",
                    value=False,
                ),
                "instruct_frequency": AgentActionConfig(
                    type="number",
                    label="Instruct Frequency",
                    description="The frequency at which to instruct actors and the narrator.",
                    value=5,
                    min=1,
                    max=25,
                    step=1,
                ),
                "evaluate_scene_intention": AgentActionConfig(
                    type="number",
                    label="Evaluate Scene Intention",
                    description="Whether to evaluate the scene intention and adjust the direction accordingly. This can be 0 for never, or the frequency at which to evaluate the scene intention. Time skips will also trigger an evaluation.",
                    value=0,
                    min=0,
                    max=25,
                    step=1,
                ),
            },
        )
        
    # config property helpers
    
    @property
    def auto_direct_enabled(self) -> bool:
        return self.actions["auto_direct"].enabled
    
    @property
    def auto_direct_max_auto_turns(self) -> int:
        return self.actions["auto_direct"].config["max_auto_turns"].value
    
    @property
    def auto_direct_max_idle_turns(self) -> int:
        return self.actions["auto_direct"].config["max_idle_turns"].value
    
    @property
    def auto_direct_max_repeat_turns(self) -> int:
        return self.actions["auto_direct"].config["max_repeat_turns"].value
    
    @property
    def auto_direct_instruct_actors(self) -> bool:
        return self.actions["auto_direct"].config["instruct_actors"].value
    
    @property
    def auto_direct_instruct_narrator(self) -> bool:
        return self.actions["auto_direct"].config["instruct_narrator"].value
    
    @property
    def auto_direct_instruct_frequency(self) -> int:
        return self.actions["auto_direct"].config["instruct_frequency"].value
    
    @property
    def auto_direct_evaluate_scene_intention(self) -> int:
        return self.actions["auto_direct"].config["evaluate_scene_intention"].value
    
    @property
    def auto_direct_instruct_any(self) -> bool:
        """
        Will check whether actor or narrator instructions are enabled.
        
        For narrator instructions to be enabled instruct_narrator needs to be enabled as well.
        
        Returns:
            bool: True if either actor or narrator instructions are enabled.
        """
        
        return self.auto_direct_instruct_actors or self.auto_direct_instruct_narrator
        
    
    # signal connect

    def connect(self, scene):
        super().connect(scene)
        async_signals.get("game_loop").connect(self.on_game_loop)
    
    async def on_game_loop(self, event):
        if not self.auto_direct_enabled:
            return
        
        if self.auto_direct_evaluate_scene_intention > 0:
            evaluation_due = self.get_scene_state("evaluated_scene_intention", 0)
            if evaluation_due == 0:
                await self.auto_direct_set_scene_intent()
                self.set_scene_states(evaluated_scene_intention=self.auto_direct_evaluate_scene_intention)
            else:
                self.set_scene_states(evaluated_scene_intention=evaluation_due - 1)

    # helpers
    
    def auto_direct_is_due_for_instruction(self, actor_name:str) -> bool:
        """
        Check if the actor is due for instruction.
        """
        
        if self.auto_direct_instruct_frequency == 1:
            return True
        
        last_instruction = self.scene.last_message_of_type(
            "director",
            character_name=actor_name,
            max_iterations=25,
        )
        
        if not last_instruction:
            return True
        
        last_message_id = self.scene.history[-1].id

        return last_message_id - last_instruction.id >= self.auto_direct_instruct_frequency
        
    def auto_direct_candidates(self) -> list["Character"]:
        """
        Returns a list of characters who are valid candidates to speak next.
        based on the max_idle_turns, max_repeat_turns, and the most recent character.
        """
        
        scene:"Scene" = self.scene
        
        most_recent_character = None
        repeat_count = 0
        last_player_turn = None
        consecutive_auto_turns = 0
        candidates = {}
        active_charcters = list(scene.characters)
        active_character_names = [character.name for character in active_charcters]
        instruct_narrator = self.auto_direct_instruct_narrator
        
        # if there is only one character then they are the only candidate
        if len(active_charcters) == 1:
            return active_charcters
        
        BACKLOG_LIMIT = 50
        
        player_character_active = scene.player_character_exists
        
        # check the last BACKLOG_LIMIT entries in the scene history and collect into
        # a dictionary of character names and the number of turns since they last spoke.
        
        len_history = len(scene.history) - 1
        num = 0
        for idx in range(len_history, -1, -1):
            message = scene.history[idx]
            turns = len_history - idx
            
            num += 1
            
            if num > BACKLOG_LIMIT:
                break
            
            if isinstance(message, TimePassageMessage):
                break
            
            if not isinstance(message, (CharacterMessage, NarratorMessage)):
                continue
            
            # if character message but character is not in the active characters list then skip
            if isinstance(message, CharacterMessage) and message.character_name not in active_character_names:
                continue
            
            if isinstance(message, NarratorMessage):
                if not instruct_narrator:
                    continue
                character = scene.narrator_character_object
            else:
                character = scene.get_character(message.character_name)
        
            if not character:
                continue
            
            if character.is_player and last_player_turn is None:
                last_player_turn = turns
            elif not character.is_player and last_player_turn is None:
                consecutive_auto_turns += 1
        
            if not most_recent_character:
                most_recent_character = character
                repeat_count += 1
            elif character == most_recent_character:
                repeat_count += 1
                
            if character.name not in candidates:
                candidates[character.name] = turns
        
        # add any characters that have not spoken yet
        for character in active_charcters:
            if character.name not in candidates:
                candidates[character.name] = 0
        
        # explicitly add narrator if enabled and not already in candidates
        if instruct_narrator and scene.narrator_character_object:
            narrator = scene.narrator_character_object
            if narrator.name not in candidates:
                candidates[narrator.name] = 0
        
        log.debug(f"auto_direct_candidates: {candidates}", most_recent_character=most_recent_character, repeat_count=repeat_count, last_player_turn=last_player_turn, consecutive_auto_turns=consecutive_auto_turns)
        
        if not most_recent_character:
            log.warning("auto_direct_candidates: No most recent character found.")
            return list(scene.characters)
        
        # if player has not spoken in a while then they are favored
        if player_character_active and consecutive_auto_turns >= self.auto_direct_max_auto_turns:
            log.debug("auto_direct_candidates: User controlled character has not spoken in a while.")
            return [scene.get_player_character()]
        
        # check if most recent character has spoken too many times in a row
        # if so then remove from candidates
        if repeat_count >= self.auto_direct_max_repeat_turns:
            log.debug("auto_direct_candidates: Most recent character has spoken too many times in a row.", most_recent_character=most_recent_character
            )
            candidates.pop(most_recent_character.name, None)

        # check if any characters have gone too long without speaking
        # if so collect into new list of candidates
        favored_candidates = []
        for name, turns in candidates.items():
            if turns > self.auto_direct_max_idle_turns:
                log.debug("auto_direct_candidates: Character has gone too long without speaking.", character_name=name, turns=turns)
                favored_candidates.append(scene.get_character(name))
        
        if favored_candidates:
            return favored_candidates
        
        return [scene.get_character(character_name) for character_name in candidates.keys()]

    # actions
        
    @set_processing
    async def auto_direct_set_scene_intent(self) -> ScenePhase | None:
        
        async def set_scene_intention(type:str, intention:str) -> ScenePhase:
            await set_scene_phase(self.scene, type, intention)
            self.scene.emit_status()
            return self.scene.intent_state.phase
        
        async def do_nothing(*args, **kwargs) -> None:
            return None
        
        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="set_scene_intention",
                    arguments=[
                        focal.Argument(name="type", type="str"),
                        focal.Argument(name="intention", type="str"),
                    ],
                    fn=set_scene_intention,
                    multiple=False,
                ),
                focal.Callback(
                    name="do_nothing",
                    fn=do_nothing,
                    multiple=False,
                ),
            ],
            max_calls=1,
            scene=self.scene,
            scene_type_ids=", ".join([f'"{scene_type.id}"' for scene_type in self.scene.intent_state.scene_types.values()]),
            retries=1,
        )
        
        await focal_handler.request(
            "director.direct-determine-scene-intent",
        )
        
        return self.scene.intent_state.phase
    
    @set_processing
    async def auto_direct_generate_scene_types(
        self, 
        instructions:str,
        max_scene_types:int=1,
    ):
        
        world_state_manager:WorldStateManager = self.scene.world_state_manager
        
        scene_type_templates = await world_state_manager.get_templates(types=["scene_type"])
        
        async def add_from_template(id:str) -> SceneType:
            template:TemplateSceneType = scene_type_templates[id]
            return template.apply_to_scene(self.scene)
            
        async def generate_scene_type(
            id:str = None,
            name:str = None,
            description:str = None,
            instructions:str = None,
        ) -> SceneType:
            
            if not id or not name:
                return None
            
            scene_type = SceneType(
                id=id,
                name=name,
                description=description,
                instructions=instructions,
            )
            
            self.scene.intent_state.scene_types[id] = scene_type
            
            return scene_type
        
        
        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="generate_scene_type",
                    arguments=[
                        focal.Argument(name="id", type="str"),
                        focal.Argument(name="name", type="str"),
                        focal.Argument(name="description", type="str"),
                        focal.Argument(name="instructions", type="str"),
                    ],
                    fn=generate_scene_type,
                    multiple=True,
                ),
                focal.Callback(
                    name="add_from_template",
                    arguments=[
                        focal.Argument(name="id", type="str"),
                    ],
                    fn=add_from_template,
                    multiple=True,
                ),
            ],
            max_calls=max_scene_types,
            retries=1,
            scene=self.scene,
            instructions=instructions,
            scene_type_templates=scene_type_templates.templates,
        )
        
        await focal_handler.request(
            "director.generate-scene-types",
        )