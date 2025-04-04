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

def make_assert_fn(name:str, write_results:bool=False):
    async def assert_fn(state: GraphState):
        if write_results or not os.path.exists(os.path.join(RESULTS_DIR, f"{name}.json")):
            with open(os.path.join(RESULTS_DIR, f"{name}.json"), "w") as f:
                json.dump(state.shared, f, indent=4)
        else:
            with open(os.path.join(RESULTS_DIR, f"{name}.json"), "r") as f:
                expected = json.load(f)
                
            assert state.shared == expected
    
    return assert_fn

def make_graph_test(name:str, write_results:bool=False):
    async def test_graph(mock_scene, mock_director_agent):
        assert_fn = make_assert_fn(name, write_results)
        
        with ActiveScene(mock_scene):
            graph = load_test_graph(name)
            assert graph is not None
            graph.callbacks.append(assert_fn)
            await graph.execute()

    return test_graph


@pytest.mark.asyncio
async def test_graph_core(mock_scene, mock_director_agent):
    fn = make_graph_test("test-harness-core", False)
    
    await fn(mock_scene, mock_director_agent)
    
@pytest.mark.asyncio
async def test_graph_data(mock_scene, mock_director_agent):
    fn = make_graph_test("test-harness-data", True)
    
    await fn(mock_scene, mock_director_agent)
