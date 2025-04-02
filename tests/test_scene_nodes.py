import pytest
import talemate.game.engine.nodes.scene
from talemate.game.engine.nodes.core import Graph, Entry, Node
from talemate.game.engine.nodes.registry import get_node

@pytest.mark.asyncio
async def test_select_function():
    select_item:Node = get_node("core/SelectItem")()
    json_output:Node = get_node("data/JSON")()
    
    json_output.set_property("json", '["item1", "item2", "item3"]')
    
    graph = Graph()
    graph.add_node(select_item)
    graph.add_node(json_output)
    
    graph.connect(json_output.outputs[0], select_item.inputs[0])
    
    await graph.execute()
    
    assert select_item.outputs[0].value in ["item1", "item2", "item3"]