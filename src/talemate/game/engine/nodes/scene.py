import structlog
from typing import TYPE_CHECKING, ClassVar
from .core import (
    Loop,
    Node, 
    Entry, 
    GraphState, 
    UNRESOLVED, 
    LoopBreak, 
    LoopContinue, 
    NodeVerbosity, 
    InputValueError, 
    PropertyField,
    Trigger,
)
import dataclasses
from .registry import register
from .event import connect_listeners, disconnect_listeners
import talemate.events as events
from talemate.emit import wait_for_input, emit
from talemate.exceptions import ActedAsCharacter, AbortWaitForInput, GenerationCancelled
from talemate.context import active_scene, InteractionState
from talemate.instance import get_agent
from talemate.character import activate_character, deactivate_character
import talemate.scene_message as scene_message
import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

log = structlog.get_logger("talemate.game.engine.nodes.scene")

async_signals.register(
    "scene_loop_start_cycle",
    "scene_loop_end_cycle",
    "scene_loop_error",
    "scene_loop_init",
)

@dataclasses.dataclass
class SceneLoopEvent(events.Event):
    scene: "Scene"
    event_type: str

@register("scene/GetSceneState")
class GetSceneState(Node):
    
    """
    Gets some basic information about the scene
    
    Outputs:
    
    - characters: A list of characters in the scene
    - active: Whether the scene is active
    - auto_save: Whether auto save is enabled
    - auto_progress: Whether auto progress is enabled
    - scene: The scene instance
    """
    
    def __init__(self, title="Get Scene State", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        
        # scene state
        self.add_output("characters", socket_type="list")
        
        # scene settings
        self.add_output("active", socket_type="bool")
        self.add_output("auto_save", socket_type="bool")
        self.add_output("auto_progress", socket_type="bool")
        self.add_output("scene", socket_type="scene")
        
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        self.set_output_values({
            "characters": scene.characters,
            "active": scene.active,
            "auto_save": scene.auto_save,
            "auto_progress": scene.auto_progress,
            "scene": scene
        })


@register("scene/MakeCharacter")
class MakeCharacter(Node):
    """
    Make a character
    
    Inputs:
    
    - name: The name of the character
    - description: The description of the character
    - color: The color of the character name
    - base_attributes: The base attributes of the character
    - is_player: Whether the character is the player character
    - add_to_scene: Whether to add the character to the scene
    - is_active: Whether the character is active
    
    Properties:
    
    - name: The name of the character
    - description: The description of the character
    - color: The color of the character name
    - base_attributes: The base attributes of the character
    - is_player: Whether the character is the player character
    - add_to_scene: Whether to add the character to the scene
    - is_active: Whether the character is active
    
    Outputs:
    
    - character: The character object
    - actor: The actor object
    """
    
    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the character",
            type="str",
            default=UNRESOLVED
        )
        
        description = PropertyField(
            name="description",
            description="The description of the character",
            type="text",
            default=""
        )
        
        color = PropertyField(
            name="color",
            description="The color of the character name",
            type="color",
            default=UNRESOLVED
        )
        
        base_attributes = PropertyField(
            name="base_attributes",
            description="The base attributes of the character",
            type="dict",
            default=UNRESOLVED
        )
        
        is_player = PropertyField(
            name="is_player",
            description="Whether the character is the player character",
            type="bool",
            default=False
        )
        
        add_to_scene = PropertyField(
            name="add_to_scene",
            description="Whether to add the character to the scene",
            type="bool",
            default=True
        )
        
        is_active = PropertyField(
            name="is_active",
            description="Whether the character is active",
            type="bool",
            default=True
        )
        
    def __init__(self, title="Make Character", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("name", socket_type="str")
        self.add_input("description", socket_type="text", optional=True)
        self.add_input("color", socket_type="color", optional=True)
        self.add_input("base_attributes", socket_type="dict", optional=True)
        self.add_input("is_player", socket_type="bool", optional=True)
        self.add_input("add_to_scene", socket_type="bool", optional=True)
        self.add_input("is_active", socket_type="bool", optional=True)
        
        self.set_property("name", UNRESOLVED)
        self.set_property("description", "")
        self.set_property("color", UNRESOLVED)
        self.set_property("base_attributes", UNRESOLVED)
        self.set_property("is_player", False)
        self.set_property("add_to_scene", True)
        self.set_property("is_active", True)
        
        self.add_output("character", socket_type="character")
        self.add_output("actor", socket_type="actor")
    
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        name = self.require_input("name")
        description = self.normalized_input_value("description")
        color = self.normalized_input_value("color")
        base_attributes = self.normalized_input_value("base_attributes")
        is_player = self.normalized_input_value("is_player")
        add_to_scene = self.normalized_input_value("add_to_scene")
        is_active = self.normalized_input_value("is_active")
        character = scene.Character(
            name=name,
            description=description,
            color=color,
            base_attributes=base_attributes,
            is_player=is_player
        )
        
        log.warning("Make character", character=character)
        
        self.set_output_values({
            "character": character
        })
        
        if is_player:
            ActorCls = scene.Player
        else:
            ActorCls = scene.Actor
        
        actor = ActorCls(character, get_agent("conversation"))
        
        if add_to_scene:
            await scene.add_actor(actor)
            if not is_active:
                await deactivate_character(character)
        
        self.set_output_values({
            "actor": actor,
            "character": character
        })

@register("scene/GetCharacter")
class GetCharacter(Node):
    
    """
    Returns a character object from the scene by name
    
    Inputs:
    
    - character_name: The name of the character
    
    Outputs:
    
    - character: The character object
    """
    
    def __init__(self, title="Get Character", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("character_name", socket_type="str")
        self.add_output("character", socket_type="character")
        
    async def run(self, state: GraphState):
        character_name = self.get_input_value("character_name")
        scene:"Scene" = active_scene.get()
        
        character = scene.get_character(character_name)
        
        self.set_output_values({
            "character": character
        })

@register("scene/IsPlayerCharacter")
class IsPlayerCharacter(Node):
    
    """
    Returns whether a character is the player character
    
    Inputs:
    
    - character: The character object
    
    Outputs:
    
    - yes: True if the character is the player character
    - no: True if the character is not the player character
    - character: The character object
    """
    
    def __init__(self, title="Is Player Character", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_output("yes", socket_type="bool")
        self.add_output("no", socket_type="bool")
        self.add_output("character", socket_type="character")
        
        
    async def run(self, state: GraphState):
        character:"Character" = self.get_input_value("character")
        self.outputs[0].deactivated = not character.is_player
        self.outputs[1].deactivated = character.is_player
        
        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Is player character", character=character, is_player=character.is_player)
        
        self.set_output_values({
            "yes": True if character.is_player else UNRESOLVED,
            "no": True if not character.is_player else UNRESOLVED,
            "character": character
        })
        
@register("scene/GetPlayerCharacter")
class GetPlayerCharacter(Node):
    
    """
    Get the main player character from the scene
    
    Outputs:
    
    - character: The player character
    """
    
    def __init__(self, title="Get Player Character", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_output("character", socket_type="character")
        
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        character = scene.get_player_character()
        
        self.set_output_values({
            "character": character
        })

@register("scene/UpdateCharacterData")
class UpdateCharacterData(Node):
    """
    Update the data of a character
    
    Inputs:
    
    - character: The character object
    - base_attributes: The base attributes dictionary
    - details: The details dictionary
    - description: The description string
    - color: The color of the character name
    
    Outputs:
    
    - character: The updated character object
    """
    
    class Fields:
        description = PropertyField(
            name="description",
            description="The character description",
            type="str",
            default=UNRESOLVED
        )
        
        name = PropertyField(
            name="name",
            description="The character name",
            type="str",
            default=UNRESOLVED
        )
        
        color = PropertyField(
            name="color",
            description="The color of the character name",
            type="str",
            default=UNRESOLVED
        )

    def __init__(self, title="Update Character Data", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_input("base_attributes", socket_type="dict", optional=True)
        self.add_input("details", socket_type="dict", optional=True)
        self.add_input("description", socket_type="str", optional=True)
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("color", socket_type="str", optional=True)
        self.set_property("description", UNRESOLVED)
        self.set_property("name", UNRESOLVED)
        self.set_property("color", UNRESOLVED)
        self.add_output("character", socket_type="character")
        
    async def run(self, state: GraphState):
        character:"Character" = self.get_input_value("character")
        color = self.get_input_value("color")
        base_attributes = self.get_input_value("base_attributes")
        details = self.get_input_value("details")
        description = self.get_input_value("description")
        name = self.get_input_value("name")
        
        if self.is_set(base_attributes):
            character.update(base_attributes=base_attributes)
        if self.is_set(details):
            character.update(details=details)
        if self.is_set(description):
            character.update(description=description)
        if self.is_set(name):
            character.rename(name)
        if self.is_set(color):
            character.color = color
            
        self.set_output_values({
            "character": character
        })
        
        
        

@register("scene/UnpackInteractionState")
class UnpackInteractionState(Node):
    """
    Will take an interaction state and unpack it into the individual fields
    
    Inputs
    - interaction_state `interaction_state`
    
    Outputs
    - act_as `str`
    - from_choice `str`
    - input `str`
    - reset_requested `bool`
    """
    
    def __init__(self, title="Unpack Interaction State", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("interaction_state", socket_type="interaction_state")
        self.add_output("act_as", socket_type="str")
        self.add_output("from_choice", socket_type="str")
        self.add_output("input", socket_type="str")
        self.add_output("reset_requested", socket_type="bool")
        
    async def run(self, state: GraphState):
        interaction_state:InteractionState = self.get_input_value("interaction_state")
        
        if not isinstance(interaction_state, InteractionState):
            raise InputValueError(self, "interaction_state", "Input is not an InteractionState instance")
        
        self.set_output_values({
            "act_as": interaction_state.act_as,
            "from_choice": interaction_state.from_choice,
            "input": interaction_state.input,
            "reset_requested": interaction_state.reset_requested
        })
        
        
@register("scene/message/CharacterMessage")
class CharacterMessage(Node):
    """
    Creates a character message from a character and a message
    
    Inputs:
    
    - character: The character object
    - message: The message to send
    - source: The source of the message - player or ai, so whether the message is result of user input or AI generated
    - from_choice: For player messages this indicates that the message was generated from a choice selection, for ai sourced messages this indicates the instruction that was followed
    
    Properties:
    
    - source: The source of the message
    
    Outputs:
    
    - message: The message object (this is a scene_message.CharacterMessage instance)
    """
    
    class Fields:
        source = PropertyField(
            name="source",
            description="The source of the message",
            type="str",
            default="player",
            choices=[
                "player",
                "ai",
            ]
        )
    
    def __init__(self, title="Character Message", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("character", socket_type="character")
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("from_choice", socket_type="str", optional=True)
        
        self.set_property("source", "player")
        
        self.add_output("message", socket_type="message_object")
        
    async def run(self, state: GraphState):
        character:"Character" = self.get_input_value("character")
        message = self.get_input_value("message")
        source = self.get_input_value("source")
        from_choice = self.get_input_value("from_choice")
        
        extra = {}
        
        if isinstance(from_choice, str):
            extra["from_choice"] = from_choice
        
        message = scene_message.CharacterMessage(
            f"{character.name}: {message}", source=source, **extra
        )
        
        self.set_output_values({
            "message": message
        })

@register("scene/message/NarratorMessage")
class NarratorMessage(Node):
    """
    Creates a narrator message
    
    Inputs:
    
    - message: The message to send
    - source: The source of the message - player or ai, so whether the message is result of user input or AI generated
    - meta: A dictionary of meta information to attach to the message. This will generally be arguments and function name that was called on the narrator agent to generate the message and will be used when regenerating the message.
    
    Properties:
    
    - source: The source of the message
    
    Outputs:
    
    - message: The message object (this is a scene_message.NarratorMessage instance)
    """
    
    class Fields:
        source = PropertyField(
            name="source",
            description="The source of the message",
            type="str",
            default="ai",
            choices=[
                "player",
                "ai",
            ]
        )
    
    def __init__(self, title="Narrator Message", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("meta", socket_type="dict", optional=True)
        
        self.set_property("source", "ai")
        
        self.add_output("message", socket_type="message_object")
        
    async def run(self, state: GraphState):
        message = self.get_input_value("message")
        source = self.get_input_value("source")
        meta = self.get_input_value("meta")
        
        extra = {}
        
        if meta and isinstance(meta, dict):
            extra["meta"] = meta
        
        message = scene_message.NarratorMessage(
            message, source=source, **extra
        )
        
        self.set_output_values({
            "message": message
        })

@register("scene/message/DirectorMessage")
class DirectorMessage(Node):
    """
    Creates a director message
    
    Inputs:
    
    - message: The message to send
    - source: The source of the message - player or ai, so whether the message is result of user input or AI generated
    - meta: A dictionary of meta information to attach to the message. Can hold the character name that the message is related to.
    - character: The character object that the message is related to
    
    Properties:
    
    - source: The source of the message
    - action: Describes the director action
    
    Outputs:
    
    - message: The message object (this is a scene_message.DirectorMessage instance)
    """
    
    class Fields:
        source = PropertyField(
            name="source",
            description="The source of the message",
            type="str",
            default="ai",
            choices=[
                "player",
                "ai",
            ]
        )
        
        action = PropertyField(
            name="action",
            description="Describes the director action",
            type="str",
            default="actor_instruction"
        )
    
    def __init__(self, title="Director Message", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("meta", socket_type="dict", optional=True)
        self.add_input("character", socket_type="character", optional=True)
        self.add_input("action", socket_type="str", optional=True)
        
        self.set_property("source", "ai")
        self.set_property("action", "actor_instruction")
        
        self.add_output("message", socket_type="message_object")
        
    async def run(self, state: GraphState):
        message = self.get_input_value("message")
        source = self.get_input_value("source")
        action = self.get_input_value("action")
        meta = self.get_input_value("meta")
        character:"Character" = self.get_input_value("character")
        
        extra = {}
        
        if meta and isinstance(meta, dict):
            extra["meta"] = meta
        
        message = scene_message.DirectorMessage(
            message, source=source, action=action, **extra
        )
        
        if character and character is not UNRESOLVED:
            message.set_meta(character=character.name)
        
        self.set_output_values({
            "message": message
        })

@register("scene/message/UnpackMeta")
class UnpackMessageMeta(Node):
    """
    Unpacks a message meta dictionary
    into arguments
    
    Inputs:
    
    - meta: The meta dictionary
    
    Outputs:
    
    - agent_name: The agent name
    - function_name: The function name
    - arguments: The arguments dictionary
    """
    
    def __init__(self, title="Unpack Message Meta", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("meta", socket_type="dict")
        self.add_output("agent_name", socket_type="str")
        self.add_output("function_name", socket_type="str")
        self.add_output("arguments", socket_type="dict")
        
    async def run(self, state: GraphState):
        meta = self.get_input_value("meta")
        
        self.set_output_values({
            "agent_name": meta["agent"],
            "function_name": meta["function"],
            "arguments": meta.get("arguments", {}).copy()
        })


@register("scene/message/ToggleMessageContextVisibility")
class ToggleMessageContextVisibility(Node):
    """
    Hide or show a message. Hidden messages are not displayed to the AI.
    
    Inputs:
    
    - message: The message object
    
    Properties:
    
    - hidden: Whether the message is hidden
    
    Outputs:
    
    - message: The message object
    """
    
    class Fields:
        hidden = PropertyField(
            name="hidden",
            description="Whether the message is hidden",
            type="bool",
            default=False
        )
    
    def __init__(self, title="Toggle Message Context Visibility", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("message", socket_type="message_object")
        
        self.set_property("hidden", False)
        
        self.add_output("message", socket_type="message_object")
        
    async def run(self, state: GraphState):
        message = self.require_input("message")
        hidden = self.get_property("hidden")
        
        if hidden:
            message.hide()
        else:
            message.show()
        
        self.set_output_values({
            "message": message
        })
    

@register("input/WaitForInput")
class WaitForInput(Node):
    """
    Get input from the user to interact with the scene.
    
    This node will wait for the user to input a message, and then return the message
    for processing.
    
    Inputs:
    
    - state: The current graph state
    - player_character: The player character
    - reason: The reason for the input
    - prefix: The prefix for the input message (similar to a cli prompt)
    - abort_condition: A condition to abort the input loop
    
    Properties
    
    - allow_commands: Allow commands to be executed, using the ! prefix
    
    Outputs:
    
    - input: The input message
    - interaction_state: The interaction state
    - character: The character object
    
    Abort Conditions:
    
    The chain of nodes connected to the abort_condition socket will be executed
    on each iteration of the input loop. If the chain resolves to a boolean value,
    the input loop will be aborted.
    
    You can use this to check for conditions that should abort the input loop.
    """
    
    class Fields:
        allow_commands = PropertyField(
            name="allow_commands",
            description="Allow commands to be executed, using the ! prefix",
            type="bool",
            default=True
        )
        prefix = PropertyField(
            name="prefix",
            description="The prefix for the input message (similar to a cli prompt)",
            type="str",
            default=""
        )
        reason = PropertyField(
            name="reason",
            description="The reason for the input",
            type="str",
            default="talk"
        )
    
    def __init__(self, title="Get Input", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("player_character", optional=True, socket_type="character")
        self.add_input("reason", optional=True, socket_type="str")
        self.add_input("prefix", optional=True, socket_type="str")
        self.add_input("abort_condition", optional=True, socket_type="any")
        
        self.set_property("reason", "talk")
        self.set_property("prefix", "")
        self.set_property("allow_commands", True)
        
        self.add_output("input", socket_type="str")
        self.add_output("interaction_state", socket_type="interaction_state")
        self.add_output("character", socket_type="character")
        
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        player_character:"Character" = self.get_input_value("player_character")
        allow_commands = self.get_property("allow_commands")
        
        async def _abort_condition() -> bool:
            """
            Logic that checks on whether the node connected to the abort_condition socket
            resolves. 
            
            Once it does resolve, the input loop will be aborted, and an AbortWaitForInput
            exception will be propagated to a LoopContinue exception.
            """
            
            socket = self.get_input_socket("abort_condition")
            
            # nothing connected, so return False
            if not socket.source:
                return False
            
            # run a new state of the graph to get the value of the connected node
            # this only runs the node connected to the abort_condition socket and any
            # ascending nodes it depends on
            inner_state:GraphState = await state.graph.execute_to_node(socket.source.node, state)
            
            # get the value of the connected node
            rv = inner_state.get_node_socket_value(socket.source.node, socket.source.name)
            
            # if the value is a boolean, return it as is
            if isinstance(rv, bool):
                return rv
            
            # if the value is not None and not UNRESOLVED, return True (abort)
            return (rv is not None and rv != UNRESOLVED)
        
        # prepare the kwargs for wait_for_input
        wait_for_input_kwargs = {
            "abort_condition": _abort_condition if self.get_input_socket("abort_condition").source else None,
        }
        
        # if the verbosity is verbose, set the sleep time to 1 so that the input loop
        # doesn't spam the console
        if state.verbosity == NodeVerbosity.VERBOSE:
            wait_for_input_kwargs["sleep_time"] = 1
        
        try:
            if player_character:
                await async_signals.get("player_turn_start").send(events.PlayerTurnStartEvent(
                    scene=scene,
                    event_type="player_turn_start",
                ))
            
            input = await wait_for_input(
                self.get_input_value("prefix"),
                character=player_character if player_character is not UNRESOLVED else None,
                data={"reason": self.get_property("reason")},
                return_struct=True,
                **wait_for_input_kwargs
            )
        except AbortWaitForInput:
            raise LoopContinue()
        
        text_message = input["message"]
        interaction_state = input["interaction"]

        state.shared["skip_to_player"] = False

        if not text_message:
            # input was empty, so continue the loop
            raise LoopContinue()
        
        if allow_commands and await scene.commands.execute(text_message):
            # command was executed, so break the loop to start the next iteration
            state.shared["signal_game_loop"] = False
            state.shared["skip_to_player"] = True
            raise LoopBreak()
        
        
        log.warning("Wait for input", text_message=text_message, interaction_state=interaction_state)
        
        self.set_output_values({
            "input": text_message,
            "interaction_state": interaction_state,
            "character": player_character,
        })

@register("scene/event/trigger/GameLoopActorIter")
class TriggerGameLoopActorIter(Trigger):

    """
    Trigger the game loop actor iteration event.
    
    In a most basic setup you will trigger this everytime an actor has had a turn.
    
    Inputs:
    
    - actor: The actor that has had a turn
    """

    class Fields:
        pass

    @property
    def signal_name(self) -> str:
        return "game_loop_actor_iter"

    def __init__(self, title="Game Loop Actor Iteration", **kwargs):
        super().__init__(title=title, **kwargs)
    
    def make_event_object(self, state:GraphState) -> events.GameLoopActorIterEvent:
        return events.GameLoopActorIterEvent(
            scene=active_scene.get(),
            event_type="game_loop_actor_iter",
            actor=self.get_input_value("actor"),
            game_loop=state.shared["game_loop"]
        )
        
    def setup_required_inputs(self):
        super().setup_required_inputs()
        self.add_input("actor", socket_type="actor")
    
    def setup_optional_inputs(self):
        return
    
    def setup_properties(self):
        return
    
    async def after(self, state:GraphState, event:events.GameLoopActorIterEvent):
        
        new_event = events.GameLoopCharacterIterEvent(
            scene=active_scene.get(),
            event_type="game_loop_player_character_iter",
            character=event.actor.character,
            game_loop=state.shared["game_loop"]
        )
        
        if event.actor.character.is_player:
            await self.signals.get("game_loop_player_character_iter").send(new_event)
        else:
            await self.signals.get("game_loop_ai_character_iter").send(new_event)

@register("scene/UnpackCharacter")
class UnpackCharacter(Node):
    """
    Unpack a character into its individual fields
    
    Inputs:
    
    - character: The character object
    
    Outputs:
    
    - name: The name of the character
    - is_player: Whether the character is the player character
    - description: The character description
    - base_attributes: The character base attributes dictionary
    - details: The character details dictionary
    - color: The character name color
    - actor: The actor instance tied to the character
    """
    
    def __init__(self, title="Unpack Character", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("character", socket_type="character")
        
        self.add_output("name", socket_type="str")
        self.add_output("is_player", socket_type="bool")
        self.add_output("description", socket_type="str")
        self.add_output("base_attributes", socket_type="dict")
        self.add_output("details", socket_type="dict")
        self.add_output("color", socket_type="str")
        self.add_output("actor", socket_type="actor")
        
    async def run(self, state: GraphState):
        character:"Character" = self.get_input_value("character")
        
        self.set_output_values({
            "name": character.name,
            "is_player": character.is_player,
            "actor": character.actor,
            "description": character.description,
            "base_attributes": character.base_attributes,
            "details": character.details,
            "color": character.color
        })

# get the current scene loop state
@register("scene/GetSceneLoopState")
class GetSceneLoopState(Node):
    
    """
    Returns the current scene loop states
    
    Outputs:
    
    - state: The current node state, this is the state of the graph currently being processed
    - parent: The parent node state, this is the state of the graph that contains the current graph
    - shared: The shared state, this is the state shared between all graphs
    """
    
    def __init__(self, title="Get Scene Loop State", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_output("state", socket_type="dict")
        self.add_output("parent", socket_type="dict")
        self.add_output("shared", socket_type="dict")
        
    async def run(self, state: GraphState):
        self.set_output_values({
            "state": state.data,
            "parent": state.outer.data if getattr(state, "outer", None) else {},
            "shared": state.shared
        })

@register("scene/Restore")
class RestoreScene(Node):
    """
    Restore the scene to its resore point
    
    Inputs:
    
    - state: The graph state
    
    Outputs:
    
    - state: The graph state
    """
    
    def __init__(self, title="Restore Scene", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_output("state")
        
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        await scene.restore()
        
        self.set_output_values({
            "state": state
        })

@register("scene/SceneLoop", as_base_type=True) 
class SceneLoop(Loop):
    
    """
    The main scene loop node
    
    It will loop through the scene graph until the loop is broken.
    
    Properties:
    
    - trigger_game_loop: Whether to trigger the game loop event
    """
    
    class Fields:
        trigger_game_loop = PropertyField(
            name="trigger_game_loop",
            description="Trigger the game loop event",
            type="bool",
            default=True
        )
    
    _export_definition: ClassVar[bool] = False
    
    @property
    def scene_loop_event(self) -> SceneLoopEvent:
        return SceneLoopEvent(
            scene=active_scene.get(),
            event_type="scene_loop"
        )
    
    def __init__(self, title="Scene Loop", **kwargs):
        super().__init__(title=title, **kwargs)
    
    def setup(self):
        self.set_property("trigger_game_loop", True)
    
    async def on_loop_start(self, state: GraphState):
        scene:"Scene" = state.outer.data["scene"]
        await scene.ensure_memory_db()
        await scene.load_active_pins()
        
        connect_listeners(self, state, disconnect=True)
        
        if not state.data.get("_scene_loop_init"):
            await async_signals.get("scene_loop_init").send(self.scene_loop_event)
            state.data["_scene_loop_init"] = True
        
        trigger_game_loop = self.get_property("trigger_game_loop")
        
        if state.verbosity >= NodeVerbosity.NORMAL:
            log.warning("TRIGGER GAME LOOP", id=self.id, trigger_game_loop=trigger_game_loop, signal_game_loop=state.shared.get("signal_game_loop"), skip_to_player=state.shared.get("skip_to_player"))  
        
        if trigger_game_loop:
            game_loop = events.GameLoopEvent(
                scene=self, event_type="game_loop", had_passive_narration=False
            )
            state.shared["game_loop"] = game_loop
        if state.shared.get("signal_game_loop", True) and trigger_game_loop:
            await scene.signals["game_loop"].send(game_loop)

        state.shared["signal_game_loop"] = True
        state.shared["scene_loop"] = {}
        state.shared["creative_mode"] = scene.environment == "creative"
        
        await async_signals.get("scene_loop_start_cycle").send(self.scene_loop_event)
        
    async def on_loop_end(self, state: GraphState):
        scene:"Scene" = state.outer.data["scene"]
        if scene.auto_save:
            await scene.save(auto=True)
            
        scene.emit_status()
        
        await async_signals.get("scene_loop_end_cycle").send(self.scene_loop_event)
    
    async def execute(self, outer_state: GraphState):
        """
        Execute the scene loop
        """
        try:
            outer_state.data["scene"] = active_scene.get()
            await super().execute(outer_state)
        finally:
            disconnect_listeners(self, outer_state)

    async def on_loop_error(self, state: GraphState, exc: Exception):
        scene:"Scene" = state.outer.data["scene"]
        if isinstance(exc, ActedAsCharacter):
            state.shared["signal_game_loop"] = False
            state.shared["acted_as_character"] = scene.get_character(exc.character_name)
            raise LoopBreak()
        
        elif isinstance(exc, GenerationCancelled):
            state.shared["skip_to_player"] = True
            state.shared["signal_game_loop"] = False
            raise LoopBreak()
        
        await async_signals.get("scene_loop_error").send(self.scene_loop_event)