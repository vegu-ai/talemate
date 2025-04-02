import pytest
from talemate.game.engine.nodes.core import (
    Node, Graph, GraphState, GraphContext, 
    Socket, UNRESOLVED
)
from talemate.game.engine.nodes.run import (
    FunctionArgument, FunctionReturn, AsFunction, FunctionWrapper
)

@pytest.mark.asyncio
async def test_as_function():
    # Create a graph
    graph = Graph()
    
    # Create function argument nodes
    arg_a = FunctionArgument(title="Arg A")
    arg_a.set_property("name", "a")
    arg_a.set_property("type", "int")
    
    arg_b = FunctionArgument(title="Arg B")
    arg_b.set_property("name", "b")
    arg_b.set_property("type", "int")
    
    # Create a node that adds the arguments
    class Adder(Node):
        def __init__(self):
            super().__init__(title="Adder")
            self.add_input("a")
            self.add_input("b")
            self.add_output("sum")
        
        async def run(self, state: GraphState):
            a = self.get_input_value("a") or 0
            b = self.get_input_value("b") or 0
            print(f"Adding {a} + {b}")
            self.set_output_values({"sum": a + b})
    
    adder = Adder()
    
    # Create a return node
    ret = FunctionReturn(title="Return")
    
    # Create an AsFunction node
    as_fn = AsFunction(title="As Function")
    as_fn.set_property("name", "add")
    
    # Add all nodes to the graph
    graph.add_node(arg_a)
    graph.add_node(arg_b)
    graph.add_node(adder)
    graph.add_node(ret)
    graph.add_node(as_fn)
    
    # Connect nodes to build the function flow:
    # arg_a.value -> adder.a
    # arg_b.value -> adder.b
    # adder.sum -> ret.value
    graph.connect(arg_a.outputs[0], adder.inputs[0])
    graph.connect(arg_b.outputs[0], adder.inputs[1])
    graph.connect(adder.outputs[0], ret.inputs[0])
    
    # For AsFunction, we connect to the return node
    # This makes ret the target endpoint for the function
    graph.connect(adder.outputs[0], as_fn.inputs[0])
    
    # Execute the graph to get the function
    fn_wrapper = None
    
    async def capture_function(state: GraphState):
        nonlocal fn_wrapper
        fn_wrapper = as_fn.outputs[0].value
        print(f"Captured function: {fn_wrapper}")
    
    graph.callbacks.append(capture_function)
    with GraphContext() as state:
        await graph.execute()
    
        # Verify the function was created
        assert fn_wrapper is not None, "Function wrapper should be created"
        assert fn_wrapper is not UNRESOLVED, "Function wrapper should not be unresolved"
        
        print("ASSERT")
        # Call the function with arguments
        result = await fn_wrapper(a=5, b=3)
    
        # Verify the result
        assert result == 8, "Function should add numbers correctly"
    
    # Also test by directly creating a FunctionWrapper around the return node
    with GraphContext() as state:
        direct_wrapper = FunctionWrapper(ret, graph, state)
        direct_result = await direct_wrapper(a=10, b=20)
        assert direct_result == 30, "Direct function wrapper should also work"