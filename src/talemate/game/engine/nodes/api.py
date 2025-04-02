import structlog
import pydantic
from talemate.game.engine.nodes.core import (
    Node,
    register,
    GraphState,
    NodeStyle,
    PropertyField,
    UNRESOLVED,
    PASSTHROUGH_ERRORS,
)
from talemate.instance import get_agent
from talemate.context import active_scene
from talemate.game.engine.nodes.base_types import base_node_type

from talemate.game.engine import exec_restricted
from talemate.game.scope import OpenScopedContext, GameInstructionScope

log = structlog.get_logger("talemate.game.engine.nodes.core.api")

@register("core/functions/ScopedAPIFunction")
class ScopedAPIFunction(Node):
    """
    Executes python code inside the quarantined scoped environment.
    """
    
    class Fields:
        code = PropertyField(
            name="code",
            description="The code to execute",
            type="text",
            default=UNRESOLVED
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#306c51",
            icon="F10D6", #code-braces-box
        )
    

    def __init__(self, title="Scoped API Function", **kwargs):
        super().__init__(title=title, **kwargs)
        
    
    def setup(self):
        self.add_input("state")
        self.add_input("agent", socket_type="agent")
        self.add_input("arguments", socket_type="dict", optional=True)
        
        self.set_property("code", UNRESOLVED)
        
        self.add_output("result")
        
    async def run(self, state: GraphState):
        
        scene = active_scene.get()
        code = self.require_input("code")
        agent = self.require_input("agent")
        arguments = self.normalized_input_value("arguments")
        
        if arguments is None:
            arguments = {}
            
        result = {}
            
            
        def exec_scoped_api(scope):
            nonlocal result    
            exec_restricted(
                code, 
                f"<{self.title}>",
                arguments=arguments,
                result=result,
                TM=scope
            )
            
            return result.get("value")
            
        _module = GameInstructionScope(
            director=get_agent("director"),
            log=log,
            scene=scene,
            module_function=lambda s: exec_scoped_api(s)
        )
        
        with OpenScopedContext(scene, agent.client):
            _module()
            
        self.set_output_values({
            "result": result
        })