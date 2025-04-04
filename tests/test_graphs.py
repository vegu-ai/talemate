import os
import json
import pytest
import talemate.game.engine.nodes.load_definitions
import talemate.agents.director
from talemate.context import active_scene, ActiveScene
from talemate.tale_mate import Scene
import talemate.instance as instance
from talemate.game.engine.nodes.core import (
    Node, Graph, GraphState, GraphContext, 
    Socket, UNRESOLVED
)
from talemate.game.engine.nodes.layout import load_graph_from_file
from talemate.agents.director import DirectorAgent
from talemate.client import ClientBase

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_GRAPH_DIR = os.path.join(BASE_DIR, "data", "graphs")
RESULTS_DIR = os.path.join(BASE_DIR, "data", "graphs", "results")
UPDATE_RESULTS = False

def load_test_graph(name) -> Graph:
    path = os.path.join(TEST_GRAPH_DIR, f"{name}.json")
    graph, _ = load_graph_from_file(path)
    return graph

class MockClient(ClientBase):
    def __init__(self, name: str):
        self.name = name
        self.enabled = True
        self.current_status = "idle"

@pytest.fixture
def mock_scene():
    scene = Scene()
    return scene

@pytest.fixture
def mock_client():
    client = MockClient("test_client")
    return client

@pytest.fixture
def mock_director_agent(mock_client, mock_scene):
    director = instance.get_agent("director", client=mock_client)
    director.scene = mock_scene
    return director

@pytest.mark.asyncio
async def test_graph_core(mock_scene, mock_director_agent):
    
    async def assert_state(state: GraphState):
        if UPDATE_RESULTS or not os.path.exists(os.path.join(RESULTS_DIR, "test-harness-core.json")):
            with open(os.path.join(RESULTS_DIR, "test-harness-core.json"), "w") as f:
                json.dump(state.shared, f, indent=4)
                
        else:
            with open(os.path.join(RESULTS_DIR, "test-harness-core.json"), "r") as f:
                expected = json.load(f)
                
            assert state.shared == expected
        
    with ActiveScene(mock_scene):
        graph = load_test_graph("test-harness-core")
        assert graph is not None
        graph.callbacks.append(assert_state)
        await graph.execute()
