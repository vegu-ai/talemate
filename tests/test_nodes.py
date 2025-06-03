from talemate.game.engine.nodes.core import Node, Graph, Socket, GraphState, Loop, Entry, Router, GraphContext
import networkx as nx
import structlog
import pytest
from talemate.util.async_tools import cleanup_pending_tasks

log = structlog.get_logger()

class Counter(Node):
    def __init__(self, title="Counter", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_output("value")
        self.set_property("counter", 0)
    
    async def run(self, state: GraphState):
        counter = self.get_property("counter")
        self.set_output_values({
            "value": counter
        })
        self.set_property("counter", counter + 1, state)

@pytest.mark.asyncio
async def test_simple_graph():
    # Create nodes
    node_a = Node(title="A")
    node_b = Node(title="B")
    node_c = Node(title="C")
    node_d = Node(title="D")
    
    # Add sockets to nodes
    out_a1 = node_a.add_output("out1")
    out_a2 = node_a.add_output("out2")
    
    in_b = node_b.add_input("in")
    out_b = node_b.add_output("out")
    
    in_c = node_c.add_input("in")
    out_c = node_c.add_output("out")
    
    in_d1 = node_d.add_input("in1")
    in_d2 = node_d.add_input("in2")
    
    # Create graph
    graph = Graph()
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_node(node_c)
    graph.add_node(node_d)
    
    # Connect nodes via sockets
    graph.connect(out_a1, in_b)    # A -> B
    graph.connect(out_a2, in_c)    # A -> C
    graph.connect(out_b, in_d1)    # B -> D
    graph.connect(out_c, in_d2)    # C -> D
    
    nxgraph = graph.build()
    
    # Print paths
    print([graph.node(n).title for n in nx.shortest_path(nxgraph, node_a.id, node_d.id)])
    print([graph.node(n).title for n in nx.topological_sort(nxgraph)])
    
    # Add assertions for expected behavior
    shortest_path = [graph.node(n).title for n in nx.shortest_path(nxgraph, node_a.id, node_d.id)]
    topo_sort = [graph.node(n).title for n in nx.topological_sort(nxgraph)]
    
    assert len(shortest_path) == 3, "Shortest path should have 3 nodes"
    assert shortest_path[0] == "A", "Path should start with A"
    assert shortest_path[-1] == "D", "Path should end with D"
    assert len(topo_sort) == 4, "Should have all 4 nodes in topological sort"
    assert topo_sort[0] == "A", "Topological sort should start with A"
    assert topo_sort[-1] == "D", "Topological sort should end with D"
    
    await cleanup_pending_tasks()

@pytest.mark.asyncio
async def test_data_flow():
    # Create nodes with specific behaviors
    class NodeA(Node):
        def __init__(self):
            super().__init__(title="A")
            self.add_output("out1")
            self.add_output("out2")
        
        async def run(self, state: GraphState):
            # Output constant values for testing
            self.set_output_values({
                "out1": 5,
                "out2": 10
            })

    class NodeB(Node):
        def __init__(self):
            super().__init__(title="B")
            self.add_input("in")
            self.add_output("out")
        
        async def run(self, state: GraphState):
            inputs = self.get_input_values()
            # Double the input value
            self.set_output_values({
                "out": inputs["in"] * 2
            })

    class NodeC(Node):
        def __init__(self):
            super().__init__(title="C")
            self.add_input("in")
            self.add_output("out")
        
        async def run(self, state: GraphState):
            inputs = self.get_input_values()
            # Add 1 to the input value
            self.set_output_values({
                "out": inputs["in"] + 1
            })

    class NodeD(Node):
        result: int = 0
        
        def __init__(self):
            super().__init__(title="D")
            self.add_input("in1")
            self.add_input("in2")
        
        async def run(self, state: GraphState):
            inputs = self.get_input_values()
            # Store sum for testing
            self.result = inputs["in1"] + inputs["in2"]

    # Create nodes
    node_a = NodeA()
    node_b = NodeB()
    node_c = NodeC()
    node_d = NodeD()
    
    # Create graph
    graph = Graph()
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_node(node_c)
    graph.add_node(node_d)
    
    # Connect nodes via sockets
    graph.connect(node_a.outputs[0], node_b.inputs[0])    # A.out1 -> B.in
    graph.connect(node_a.outputs[1], node_c.inputs[0])    # A.out2 -> C.in
    graph.connect(node_b.outputs[0], node_d.inputs[0])    # B.out -> D.in1
    graph.connect(node_c.outputs[0], node_d.inputs[1])    # C.out -> D.in2
    
    async def assert_state(state: GraphState):
        print(state.data)
        # Test data flow
        # NodeA outputs: out1=5, out2=10
        assert node_a.outputs[0].value == 5, "NodeA out1 should be 5"
        assert node_a.outputs[1].value == 10, "NodeA out2 should be 10"
        
        # NodeB doubles input: 5 * 2 = 10
        assert node_b.outputs[0].value == 10, "NodeB should double input value"
        
        # NodeC adds 1: 10 + 1 = 11
        assert node_c.outputs[0].value == 11, "NodeC should add 1 to input value"
        
        # NodeD sums inputs: 10 + 11 = 21
        assert node_d.result == 21, "NodeD should sum its inputs"
    
    # Execute graph
    graph.callbacks.append(assert_state)
    await graph.execute()
    await cleanup_pending_tasks()


@pytest.mark.asyncio
async def test_property_flow():
    # Create nodes with property-driven behaviors
    class NumberSource(Node):
        def __init__(self):
            super().__init__(title="Source")
            self.add_output("value")
            # Set default property
            self.set_property("value", 5)
        
        async def run(self, state: GraphState):
            # Output property value
            self.set_output_values({
                "value": self.get_property("value")
            })

    class Multiplier(Node):
        def __init__(self):
            super().__init__(title="Multiplier")
            self.add_input("value")
            self.add_output("result")
            # Set default multiplier
            self.set_property("multiplier", 2)
        
        async def run(self, state: GraphState):
            inputs = self.get_input_values()
            multiplier = self.get_input_value("multiplier")  # Will fall back to property
            
            print("Multiplier input:", inputs["value"], "Multiplier:", multiplier)
            self.set_output_values({
                "result": (inputs["value"] or 0) * multiplier
            })

    class Adder(Node):
        def __init__(self):
            super().__init__(title="Adder")
            self.add_input("value")
            self.add_output("result")
            # Set default addend
            self.set_property("addend", 1)
        
        async def run(self, state: GraphState):
            inputs = self.get_input_values()
            addend = self.get_input_value("addend")  # Will fall back to property
            self.set_output_values({
                "result": inputs["value"] + addend
            })

    class Collector(Node):
        result: float = 0
        
        def __init__(self):
            super().__init__(title="Collector")
            self.add_input("value1")
            self.add_input("value2")
            # Set default values
            self.set_property("value1", 0)
            self.set_property("value2", 0)
        
        async def run(self, state: GraphState):
            inputs = self.get_input_values()
            self.result = inputs["value1"] + inputs["value2"]

    # Create nodes and graph setup...
    source = NumberSource()
    mult = Multiplier()
    add = Adder()
    collect = Collector()
    
    # Create graph
    graph = Graph()
    graph.add_node(source)
    graph.add_node(mult)
    graph.add_node(add)
    graph.add_node(collect)
    
    # Connect nodes
    graph.connect(source.outputs[0], mult.inputs[0])     # Source -> Multiplier
    graph.connect(source.outputs[0], add.inputs[0])      # Source -> Adder
    graph.connect(mult.outputs[0], collect.inputs[0])    # Multiplier -> Collector.value1
    graph.connect(add.outputs[0], collect.inputs[1])     # Adder -> Collector.value2
    
       
    async def assert_state(state:GraphState): 
        # Run assertions...
        assert source.outputs[0].value == 5, "Source should output property value"
        assert mult.outputs[0].value == 10, "Multiplier should use property multiplier"
        assert add.outputs[0].value == 6, "Adder should use property addend"
        assert collect.result == 16, "Collector should sum multiplier and adder outputs"
    
    # Test property defaults
    graph.callbacks.append(assert_state)
    await graph.execute()
    await cleanup_pending_tasks()


@pytest.mark.asyncio
async def test_simple_loop():
    entry_loop = Entry()
    counter = Counter()
    
    loop = Loop(exit_condition=lambda state: counter.get_property("counter") > 10)
    loop.add_node(entry_loop)
    loop.add_node(counter)
    loop.connect(entry_loop.outputs[0], counter.inputs[0])
    
    entry = Entry()
    graph = Graph()
    
    graph.add_node(entry)
    graph.add_node(loop)
    
    graph.connect(entry.outputs[0], loop.inputs[0])    
    
    async def assert_state(state: GraphState):
        assert counter.outputs[0].value == 10, "Counter should count to 10"
    
    loop.callbacks.append(assert_state)
    await graph.execute()
    


@pytest.mark.asyncio
async def test_simple_fork():
    entry = Entry(title="Entry")
    entry_loop = Entry(title="Entry Loop")
    
    counter_main = Counter("CNT Main")
    counter_a = Counter("CNT A")
    counter_b = Counter("CNT B")
    router = Router(2, selector=lambda state: 0 if counter_main.get_property("counter") % 2 == 0 else 1)
    
    loop = Loop(title="Loop", exit_condition=lambda state: counter_main.get_property("counter") > 10)
    
    loop.add_node(entry_loop)
    loop.add_node(counter_main)
    loop.add_node(counter_a)
    loop.add_node(counter_b)
    loop.add_node(router)
    
    loop.connect(entry_loop.outputs[0], counter_main.inputs[0])
    loop.connect(counter_main.outputs[0], router.inputs[0])
    loop.connect(router.outputs[0], counter_a.inputs[0])
    loop.connect(router.outputs[1], counter_b.inputs[0])
    
    graph = Graph()
    graph.add_node(entry)
    graph.add_node(loop)
    
    graph.connect(entry.outputs[0], loop.inputs[0])
    
    async def assert_state_loop(state: GraphState): 
        assert counter_main.get_property("counter") == 11, "Main counter should count to 11"
        assert counter_a.get_property("counter") == 5, "Counter A should count to 5"
        assert counter_b.get_property("counter") == 5, "Counter B should count to 5"
    
    loop.callbacks.append(assert_state_loop)

    await graph.execute()
    await cleanup_pending_tasks()
    

    

@pytest.mark.asyncio
async def test_visited_paths():
    """Test that nodes can be visited through multiple paths"""
    # Create a simple graph where node A connects to B both directly and through C
    # A -> B
    # A -> C -> B
    # Only one path gets deactivated, other should still work
    
    graph = Graph()
    
    # Create nodes
    node_a = Node(title="Node A")
    node_b = Node(title="Node B")
    node_c = Node(title="Node C")
    
    # Add nodes to graph
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_node(node_c)
    
    # Create sockets
    a_out1 = node_a.add_output("out1")
    a_out2 = node_a.add_output("out2")
    b_in1 = node_b.add_input("in1")
    b_in2 = node_b.add_input("in2")
    c_in = node_c.add_input("in")
    c_out = node_c.add_output("out")
    
    # Connect nodes
    # A -> B (direct path)
    graph.connect(a_out1, b_in1)
    # A -> C -> B (indirect path)
    graph.connect(a_out2, c_in)
    graph.connect(c_out, b_in2)
    
    with GraphContext() as state:
        # Deactivate the direct path
        a_out1.deactivated = True
        
        # Node A should still be available because the path through C is still active
        assert node_a.check_is_available(state), "Node A should be available through path via C"
        
        # Now deactivate the indirect path too
        a_out2.deactivated = True
        
        # Now Node A should be unavailable as all paths are deactivated
        assert not node_a.check_is_available(state), "Node A should be unavailable when all paths are deactivated"
        
    await cleanup_pending_tasks()
    