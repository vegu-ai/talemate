import pytest
import talemate.game.engine.nodes.scene
import talemate.game.engine.nodes.data
from talemate.game.engine.nodes.core import Graph, Entry, Node, Socket, GraphContext, GraphState
from talemate.game.engine.nodes.registry import get_node

@pytest.mark.asyncio
async def test_select_function():
    # Create a simple test for SelectItem node
    select_item = get_node("data/SelectItem")()
    
    # Create test items
    test_items = ["item1", "item2", "item3"]
    
    # Create a GraphState manually
    with GraphContext() as state:
        # Set the items input directly in the state
        state.set_node_socket_value(select_item, "items", test_items)
        
        # Run the node manually
        await select_item.run(state)
        
        # Verify the output is one of the items
        output_value = select_item.outputs[0].value
        assert output_value in test_items, f"Expected one of {test_items}, got {output_value}"