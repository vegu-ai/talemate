import pydantic
from . import NodeBase, Socket
from talemate.game.engine.nodes.registry import base_node_type

@base_node_type("core/DynamicSocketNodeBase")
class DynamicSocketNodeBase(NodeBase):
    """
    Base class for nodes that support dynamic sockets.
    Dynamic sockets are stored in the dynamic_inputs property and 
    automatically included in the inputs computed property.
    """
    
    dynamic_inputs: list[dict] = pydantic.Field(default_factory=list)
    static_inputs: list[Socket] = pydantic.Field(default_factory=list, exclude=True)
    static_outputs: list[Socket] = pydantic.Field(default_factory=list, exclude=True)
    
    def add_input(self, name: str, **kwargs) -> Socket:
        """Override add_input to store in static_inputs"""
        socket = Socket(name=name, node=self, **kwargs)
        self.static_inputs.append(socket)
        return socket
    
    def add_output(self, name: str, **kwargs) -> Socket:
        """Override add_output to store in static_outputs"""
        socket = Socket(name=name, node=self, **kwargs)
        self.static_outputs.append(socket)
        return socket
    
    @pydantic.computed_field(description="Inputs")  
    @property
    def inputs(self) -> list[Socket]:
        # Combine static inputs + dynamic inputs
        all_inputs = self.static_inputs.copy()
        
        # Add dynamic inputs
        for dynamic_input in self.dynamic_inputs:
            socket = Socket(
                name=dynamic_input["name"],
                socket_type=dynamic_input["type"],
                node=self,
                optional=True,
            )
            all_inputs.append(socket)
        
        return all_inputs
    
    @pydantic.computed_field(description="Outputs")
    @property
    def outputs(self) -> list[Socket]:
        # For now, just return static outputs (no dynamic outputs needed yet)
        return self.static_outputs.copy()