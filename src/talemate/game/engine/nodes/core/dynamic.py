import pydantic
from . import Node, Socket
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
            self.add_input(
                dynamic_input["name"], socket_type=dynamic_input["type"], optional=True
            )

    def add_static_inputs(self):
        pass

    # Shared helper for dynamic key inference
    def best_key_name_for_socket(self, socket: Socket):
        """
        Determine a best-effort key name for a connected input socket.

        Priority (when source socket name is 'value'):
            1. source node 'name' input/property
            2. source node 'key' input/property
            3. source node 'attribute' input/property
            4. fallback to source socket name

        Otherwise, fallback to the source socket name.
        """
        source = getattr(socket, "source", None)
        if not source:
            return getattr(socket, "name", "value")

        source_node = source.node
        if source.name == "value":
            _name = source_node.normalized_input_value("name")
            _key = source_node.normalized_input_value("key")
            _attribute = source_node.normalized_input_value("attribute")
            if _name:
                return _name
            elif _key:
                return _key
            elif _attribute:
                return _attribute
            else:
                return source.name
        else:
            return source.name
