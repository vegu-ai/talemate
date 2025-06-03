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
    TYPE_CHOICES
)
import dataclasses
from .registry import register
from .event import connect_listeners, disconnect_listeners
import talemate.events as events
from talemate.emit import wait_for_input, emit
from talemate.exceptions import ActedAsCharacter, AbortWaitForInput
from talemate.context import active_scene, InteractionState
import talemate.scene_message as scene_message
import talemate.emit.async_signals as async_signals
from talemate.scene.schema import SceneIntent, ScenePhase, SceneType
from talemate.scene.intent import set_scene_phase

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

__all__ = [
    "GetSceneIntent",
    "SetSceneIntent",
    "SetScenePhase",
    "UnpackScenePhase",
    "MakeSceneType",
]

log = structlog.get_logger("talemate.game.engine.nodes.scene_intent")


TYPE_CHOICES.extend([
    "scene_intent/scene_intent",
    "scene_intent/scene_phase",
    "scene_intent/scene_type",
])

@register("scene/intention/GetSceneIntent")
class GetSceneIntent(Node):
    
    """
    Returns the intent state.
    
    Outputs:
    
    - intent (str) - the overall intent
    - phase (scene_intent/scene_phase) - the current phase
    - scene_type (scene_intent/scene_type) - the current scene type
    - start (int) - the message id where this intent started
    """

    def __init__(self, title="Get Scene Intent", **kwargs):
        super().__init__(title=title, **kwargs)
        
        
    def setup(self):
        
        self.add_output("intent", socket_type="str")
        self.add_output("phase", socket_type="scene_intent/scene_phase")
        self.add_output("scene_type", socket_type="scene_intent/scene_type")
        self.add_output("start", socket_type="int")
        
    async def run(self, state: GraphState):
        
        scene:"Scene" = active_scene.get()
        
        self.set_output_values({
            "intent": scene.intent_state.intent,  
        })
        
        phase:ScenePhase = scene.intent_state.phase
        
        if phase:
            self.set_output_values({
                "phase": phase,
                "scene_type": scene.intent_state.current_scene_type,
                "start": scene.intent_state.start,
            })
            
@register("scene/intention/SetSceneIntent")
class SetSceneIntent(Node):
    
    """
    Updates the overall intent.
    
    Inputs:
    
    - state - graph state
    - intent (str) - the overall intent
    
    Outputs:
    
    - state - graph state
    - intent (str) - the overall intent
    """

    class Fields:
        intent = PropertyField(
            name="intent",
            type="str",
            description="Overall story / experience intent",
            default="",
        )

    def __init__(self, title="Set Scene Intent", **kwargs):
        super().__init__(title=title, **kwargs)
        
        
    def setup(self):
        self.add_input("state")
        self.add_input("intent", socket_type="str", optional=True)
        
        self.set_property("intent", "")
        
        self.add_output("state")
        self.add_output("intent", socket_type="str")
        
        
    async def run(self, state: GraphState):
        
        scene:"Scene" = active_scene.get()
        
        intent = self.get_input_value("intent")
        
        scene.intent_state.intent = intent
        
        self.set_output_values({
            "state": scene.intent_state,
            "intent": intent,
        })
        
@register("scene/intention/SetScenePhase")
class SetScenePhase(Node):
    
    """
    Set a new scene phase.
    
    Inputs:
    
    - state - graph state
    - scene_type (str) - the type of scene (scene type id)
    - intent (str) - the phase intent
    
    Outputs:
    
    - state - graph state
    - phase (scene_intent/scene_phase) - the new phase
    - scene_type (scene_intent/scene_type) - the scene type of the new phase (object)
    """

    class Fields:
        scene_type = PropertyField(
            name="scene_type",
            type="str",
            description="Type of scene",
            default="roleplay",
        )
        intent = PropertyField(
            name="intent",
            type="str",
            description="Phase intent",
            default="",
        )

    def __init__(self, title="Set Scene Phase", **kwargs):
        super().__init__(title=title, **kwargs)
        
        
    def setup(self):
        self.add_input("state")
        self.add_input("scene_type", socket_type="str", optional=True)
        self.add_input("intent", socket_type="str", optional=True)
        
        self.set_property("scene_type", "")
        self.set_property("intent", "")
        
        self.add_output("state")
        self.add_output("phase", socket_type="scene_intent/scene_phase")
        self.add_output("scene_type", socket_type="scene_intent/scene_type")
        
    async def run(self, state: GraphState):
        
        scene:"Scene" = active_scene.get()
        
        scene_type = self.get_input_value("scene_type")
        intent = self.get_input_value("intent")
        
        phase = await set_scene_phase(scene, scene_type, intent)
        
        scene.emit_status()
        self.set_output_values({
            "state": scene.intent_state,
            "phase": phase,
            "scene_type": scene.intent_state.current_scene_type,
        })
        
@register("scene/intention/UnpackScenePhase")
class UnpackScenePhase(Node):

    """
    Inputs:
    
    - phhase (scene_intent/scene_phase)
    
    Outputs
    
    - intent
    - scene_type
    - scene_type_instructions
    - scene_type_description
    - scene_type_name
    - scene_type_id
    """
    
    def __init__(self, title="Unpack Scene Phase", **kwargs):
        super().__init__(title=title, **kwargs)
        
        
    def setup(self):
        self.add_input("phase", socket_type="scene_intent/scene_phase")
        
        self.add_output("intent", socket_type="str")
        self.add_output("scene_type", socket_type="str")
        self.add_output("scene_type_instructions", socket_type="str")
        self.add_output("scene_type_description", socket_type="str")
        self.add_output("scene_type_name", socket_type="str")
        self.add_output("scene_type_id", socket_type="str")
        
    async def run(self, state: GraphState):
        
        scene:"Scene" = active_scene.get()
        phase:ScenePhase = self.get_input_value("phase")
        
        scene_type:SceneType = scene.intent_state.scene_types[phase.scene_type]
        
        self.set_output_values({
            "intent": phase.intent,
            "scene_type": phase.scene_type,
            "scene_type_instructions": scene_type.instructions,
            "scene_type_description": scene_type.description,
            "scene_type_name": scene_type.name,
            "scene_type_id": scene_type.id,
        })
    
@register("scene/intention/MakeSceneType")
class MakeSceneType(Node):
    
    """
    Create a new scene type object.
    
    Inputs:
    
    - id (str) - scene type ID
    - name (str) - scene type name
    - description (text) - scene type description
    - instructions (text) - scene type instructions
    
    Outputs:
    
    - scene_type (scene_intent/scene_type) - the new scene type object
    """

    class Fields:
        scene_type_id = PropertyField(
            name="scene_type_id",
            type="str",
            description="Scene type ID",
            default=UNRESOLVED,
        )
        name = PropertyField(
            name="name",
            type="str",
            description="Scene type name",
            default="",
        )
        description = PropertyField(
            name="description",
            type="text",
            description="Scene type description",
            default="",
        )
        instructions = PropertyField(
            name="instructions",
            type="text",
            description="Scene type instructions",
            default="",
        )
        auto_append = PropertyField(
            name="auto_append",
            type="bool",
            description="Automatically append this scene type to scene_types dict",
            default=True,
        )

    def __init__(self, title="Make Scene Type", **kwargs):
        super().__init__(title=title, **kwargs)
        
        
    def setup(self):
        
        self.add_input("scene_type_id", socket_type="str", optional=True)
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("description", socket_type="text", optional=True)
        self.add_input("instructions", socket_type="text", optional=True)
        
        self.set_property("scene_type_id", UNRESOLVED)
        self.set_property("name", "")
        self.set_property("description", "")
        self.set_property("instructions", "")
        self.set_property("auto_append", True)
        
        
        self.add_output("scene_type", socket_type="scene_intent/scene_type")
        
    async def run(self, state: GraphState):
        
        auto_append = self.normalized_input_value("auto_append")
        scene:"Scene" = active_scene.get()
        
        scene_type = SceneType(
            id=self.require_input("scene_type_id"),
            name=self.require_input("name"),
            description=self.normalized_input_value("description"),
            instructions=self.normalized_input_value("instructions"),
        )
        
        if auto_append:
            scene.intent_state.scene_types[scene_type.id] = scene_type
        
        self.set_output_values({
            "scene_type": scene_type,
        })
        
@register("scene/intention/GetSceneType")
class GetSceneType(Node):
    
    """
    Get a scene type object.
    
    Inputs:
    
    - id (str) - scene type ID
    
    Outputs:
    
    - scene_type (scene_intent/scene_type) - the scene type object
    """
    
    def __init__(self, title="Get Scene Type", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("scene_type_id", socket_type="str")
        self.add_output("scene_type", socket_type="scene_intent/scene_type")
        
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        scene_type_id = self.require_input("scene_type_id")
        
        try:
            scene_type = scene.intent_state.scene_types[scene_type_id]
            self.set_output_values({"scene_type": scene_type})
        except KeyError:
            raise InputValueError(self, "scene_type_id", f"Scene type not found: {scene_type_id}")
        
@register("scene/intention/UnpackSceneType")
class UnpackSceneType(Node):
    
    """
    Unpack a scene type object.
    
    Inputs:
    
    - scene_type (scene_intent/scene_type) - the scene type object
    
    Outputs:
    
    - id (str) - scene type ID
    - name (str) - scene type name
    - description (text) - scene type description
    - instructions (text) - scene type instructions
    """
    
    def __init__(self, title="Unpack Scene Type", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("scene_type", socket_type="scene_intent/scene_type")
        
        self.add_output("scene_type_id", socket_type="str")
        self.add_output("name", socket_type="str")
        self.add_output("description", socket_type="str")
        self.add_output("instructions", socket_type="str")
        
    async def run(self, state: GraphState):
        scene_type:SceneType = self.get_input_value("scene_type")
        
        self.set_output_values({
            "scene_type_id": scene_type.id,
            "name": scene_type.name,
            "description": scene_type.description,
            "instructions": scene_type.instructions,
        })
        
@register("scene/intention/RemoveSceneType")
class RemoveSceneType(Node):
    
    """
    Remove a scene type object.
    
    Inputs:
    
    - state - graph state
    - id (str) - scene type ID
    
    Outputs:
    
    - state - graph state
    """
    
    def __init__(self, title="Remove Scene Type", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("scene_type_id", socket_type="str")
        
        self.add_output("state")
        
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        
        scene_type_id = self.require_input("scene_type_id")
        
        scene.intent_state.scene_types.pop(scene_type_id, None)
        
        self.set_output_values({
            "state": scene.intent_state,
        })
        
        
        
    