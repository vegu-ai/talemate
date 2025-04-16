import os
import json
import pytest
import talemate.game.engine.nodes.load_definitions
import talemate.agents.director
from talemate.context import active_scene, ActiveScene
from talemate.tale_mate import Scene, Helper
import talemate.instance as instance
from talemate.game.engine.nodes.core import (
    Node, Graph, GraphState, GraphContext, 
    Socket, UNRESOLVED
)
from talemate.game.engine.nodes.layout import load_graph_from_file
from talemate.game.engine.nodes.registry import import_talemate_node_definitions
from talemate.agents.director import DirectorAgent
from talemate.client import ClientBase

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_GRAPH_DIR = os.path.join(BASE_DIR, "data", "graphs")
RESULTS_DIR = os.path.join(BASE_DIR, "data", "graphs", "results")
UPDATE_RESULTS = False

# This runs once for the entire test session
@pytest.fixture(scope="session", autouse=True)
def load_node_definitions():
    import_talemate_node_definitions()

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
def mock_agents(mock_scene):
    director = instance.get_agent("director", client=mock_client)
    conversation = instance.get_agent("conversation", client=mock_client)
    summarizer = instance.get_agent("summarizer", client=mock_client)
    editor = instance.get_agent("editor", client=mock_client)
    mock_scene.add_helper(Helper(director))
    mock_scene.add_helper(Helper(conversation))
    mock_scene.add_helper(Helper(summarizer))
    mock_scene.add_helper(Helper(editor))
    return {
        "director": director,
        "conversation": conversation,
        "summarizer": summarizer,
        "editor": editor
    }

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
    async def test_graph(mock_scene):
        assert_fn = make_assert_fn(name, write_results)
        
        with ActiveScene(mock_scene):
            graph = load_test_graph(name)
            assert graph is not None
            graph.callbacks.append(assert_fn)
            await graph.execute()

    return test_graph


@pytest.mark.asyncio
async def test_graph_core(mock_scene, mock_agents):
    fn = make_graph_test("test-harness-core", False)
    
    await fn(mock_scene)
    
@pytest.mark.asyncio
async def test_graph_data(mock_scene, mock_agents):
    fn = make_graph_test("test-harness-data", False)
    
    await fn(mock_scene)

@pytest.mark.asyncio
async def test_graph_scene(mock_scene, mock_agents):
    fn = make_graph_test("test-harness-scene", False)
    
    await fn(mock_scene)

