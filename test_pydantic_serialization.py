#!/usr/bin/env python3
"""
Standalone test to reproduce Pydantic serialization issue
"""

import pydantic
from typing import Any, Annotated
import uuid
import json

# Base class similar to NodeBase
class NodeBase(pydantic.BaseModel):
    title: str = "Node"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    properties: dict[str, Any] = pydantic.Field(default_factory=dict)
    x: int = 0
    y: int = 0

# Extended class similar to DynamicSocketNodeBase  
class DynamicSocketNodeBase(NodeBase):
    is_this_here: bool = True
    dynamic_inputs: list[dict] = pydantic.Field(default_factory=list)
    supports_dynamic_sockets: bool = True

# Final class similar to DictCollector
class DictCollector(DynamicSocketNodeBase):
    dynamic_socket_type: str = "tuple"

# Validator function similar to validate_node
def validate_node(
    v: Any,
    handler: pydantic.ValidatorFunctionWrapHandler,
    info: pydantic.ValidationInfo,
) -> NodeBase:
    print(f"validate_node called with type: {type(v)}")
    
    # If it's already a Node instance, return it
    if isinstance(v, NodeBase):
        print(f"  -> Already a NodeBase instance, returning as-is")
        return v

    # If it's a dict, instantiate appropriate class
    if isinstance(v, dict):
        print(f"  -> Dict received with keys: {list(v.keys())}")
        print(f"  -> Creating DictCollector from dict")
        return DictCollector(**v)

    raise ValueError(f"Could not validate node: {v}")

# Annotated type similar to RegistryNode
RegistryNode = Annotated[NodeBase, pydantic.WrapValidator(validate_node)]

# Graph class similar to Graph
class Graph(pydantic.BaseModel):
    title: str = "Graph"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    nodes: dict[str, RegistryNode] = pydantic.Field(default_factory=dict)

    def add_node(self, node: NodeBase):
        self.nodes[node.id] = node

# Graph class with custom serializer workaround
class GraphWithSerializerWorkaround(pydantic.BaseModel):
    title: str = "Graph"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    nodes: dict[str, RegistryNode] = pydantic.Field(default_factory=dict)

    def add_node(self, node: NodeBase):
        self.nodes[node.id] = node
    
    @pydantic.field_serializer('nodes')
    def serialize_nodes(self, nodes_dict):
        """Custom serializer that calls model_dump on each node directly"""
        return {
            node_id: node.model_dump() 
            for node_id, node in nodes_dict.items()
        }

# Graph class with model_dump override workaround
class GraphWithModelDumpWorkaround(pydantic.BaseModel):
    title: str = "Graph"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    nodes: dict[str, RegistryNode] = pydantic.Field(default_factory=dict)

    def add_node(self, node: NodeBase):
        self.nodes[node.id] = node
    
    def model_dump(self, **kwargs):
        """Override model_dump to manually serialize nodes"""
        data = super().model_dump(exclude={'nodes'}, **kwargs)
        data['nodes'] = {
            node_id: node.model_dump(**kwargs) 
            for node_id, node in self.nodes.items()
        }
        return data

# Graph class without validator annotation
class GraphNoValidator(pydantic.BaseModel):
    title: str = "Graph"
    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    nodes: dict[str, Any] = pydantic.Field(default_factory=dict)  # No RegistryNode annotation

    def add_node(self, node: NodeBase):
        self.nodes[node.id] = node

def test_workarounds():
    print("=== Creating test node ===")
    node = DictCollector(title="Test Dict Collector")
    node.dynamic_inputs = [{"name": "entry_0", "type": "tuple"}]
    
    # Expected fields
    expected_fields = set(node.model_dump().keys())
    print(f"Expected fields: {sorted(expected_fields)}")
    
    print("\n=== Testing field_serializer workaround ===")
    graph1 = GraphWithSerializerWorkaround(title="Graph with field_serializer")
    graph1.add_node(node)
    
    dump1 = graph1.model_dump()
    node_data1 = dump1["nodes"][node.id]
    fields1 = set(node_data1.keys())
    
    print(f"Fields with field_serializer: {sorted(fields1)}")
    print(f"Missing fields: {sorted(expected_fields - fields1)}")
    print(f"SUCCESS: {fields1 == expected_fields}")
    
    print("\n=== Testing model_dump override workaround ===")
    graph2 = GraphWithModelDumpWorkaround(title="Graph with model_dump override")
    graph2.add_node(node)
    
    dump2 = graph2.model_dump()
    node_data2 = dump2["nodes"][node.id]
    fields2 = set(node_data2.keys())
    
    print(f"Fields with model_dump override: {sorted(fields2)}")
    print(f"Missing fields: {sorted(expected_fields - fields2)}")
    print(f"SUCCESS: {fields2 == expected_fields}")
    
    print("\n=== Testing no validator annotation workaround ===")
    graph3 = GraphNoValidator(title="Graph without validator")
    graph3.add_node(node)
    
    dump3 = graph3.model_dump()
    node_data3 = dump3["nodes"][node.id]
    fields3 = set(node_data3.keys())
    
    print(f"Fields without validator: {sorted(fields3)}")
    print(f"Missing fields: {sorted(expected_fields - fields3)}")
    print(f"SUCCESS: {fields3 == expected_fields}")

def test_original_issue():
    print("=== Testing original issue ===")
    node = DictCollector(title="Test Dict Collector")
    node.dynamic_inputs = [{"name": "entry_0", "type": "tuple"}]
    
    graph = Graph(title="Original Graph")
    graph.add_node(node)
    
    dump = graph.model_dump()
    node_data = dump["nodes"][node.id]
    expected_fields = set(node.model_dump().keys())
    actual_fields = set(node_data.keys())
    
    print(f"Expected: {sorted(expected_fields)}")
    print(f"Actual: {sorted(actual_fields)}")
    print(f"Missing: {sorted(expected_fields - actual_fields)}")

if __name__ == "__main__":
    test_original_issue()
    print("\n" + "="*60 + "\n")
    test_workarounds()