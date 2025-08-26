import pydantic
from typing import ClassVar
from . import Node
from talemate.game.engine.nodes.registry import base_node_type

@base_node_type("core/DynamicSocketNodeBase")
class DynamicSocketNodeBase(Node):
    """
    Base class for nodes that support dynamic sockets.
    Dynamic sockets are stored in the dynamic_inputs property and 
    automatically included in the inputs computed property.
    """
    dynamic_input_label: str = "input{i}"
    dynamic_inputs: list[dict] = pydantic.Field(default_factory=list)
    
    def setup(self):
        super().setup()
        
        self.add_static_inputs()
        for dynamic_input in self.dynamic_inputs:
            self.add_input(dynamic_input["name"], socket_type=dynamic_input["type"], optional=True)
            
    def add_static_inputs(self):
        pass