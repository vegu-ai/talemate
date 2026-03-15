import os
import json
import pytest
import enum
import pydantic
import talemate.game.engine.nodes.load_definitions  # noqa: F401
import talemate.agents.director  # noqa: F401
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import (
    Graph,
    GraphState,
)
import structlog
from talemate.game.engine.nodes.layout import load_graph_from_file
from talemate.game.engine.nodes.registry import import_talemate_node_definitions

from conftest import MockClientContext, MockScene, bootstrap_scene

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_GRAPH_DIR = os.path.join(BASE_DIR, "data", "graphs")
RESULTS_DIR = os.path.join(BASE_DIR, "data", "graphs", "results")
UPDATE_RESULTS = False

log = structlog.get_logger("talemate.test_graphs")


# This runs once for the entire test session
@pytest.fixture(scope="session", autouse=True)
def load_node_definitions():
    import_talemate_node_definitions()


def load_test_graph(name) -> Graph:
    path = os.path.join(TEST_GRAPH_DIR, f"{name}.json")
    graph, _ = load_graph_from_file(path)
    return graph


@pytest.fixture
def mock_scene():
    scene = MockScene()
    bootstrap_scene(scene)
    return scene


@pytest.fixture
def mock_scene_with_assets():
    scene = MockScene()
    bootstrap_scene(scene)

    # Load test assets from the test scene file
    test_scene_path = os.path.join(
        BASE_DIR, "data", "scenes", "talemate-laboratory", "talemate-lab.json"
    )
    with open(test_scene_path, "r") as f:
        test_scene_data = json.load(f)

    # Override scenes_dir to point to test data directory
    test_scenes_dir = os.path.join(BASE_DIR, "data", "scenes")
    scene.scenes_dir = lambda: test_scenes_dir
    scene.project_name = "talemate-laboratory"

    # Create library.json file with assets from the scene file
    if "assets" in test_scene_data and "assets" in test_scene_data["assets"]:
        assets_dict = test_scene_data["assets"]["assets"]
        # Ensure assets directory exists
        assets_dir = os.path.join(test_scenes_dir, "talemate-laboratory", "assets")
        os.makedirs(assets_dir, exist_ok=True)

        # Create library.json file
        library_path = os.path.join(assets_dir, "library.json")
        with open(library_path, "w") as f:
            json.dump({"assets": assets_dict}, f, indent=2)

    return scene


def serialize_state(obj):
    """Custom JSON serializer for Pydantic models"""
    if isinstance(obj, pydantic.BaseModel):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def normalize_state(data):
    """Convert Pydantic models to dicts for comparison"""
    if isinstance(data, pydantic.BaseModel):
        return data.model_dump()
    elif isinstance(data, enum.Enum):
        return data.value
    elif isinstance(data, dict):
        return {k: normalize_state(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_state(item) for item in data]
    return data


def make_assert_fn(name: str, write_results: bool = False):
    async def assert_fn(state: GraphState):
        if write_results or not os.path.exists(
            os.path.join(RESULTS_DIR, f"{name}.json")
        ):
            with open(os.path.join(RESULTS_DIR, f"{name}.json"), "w") as f:
                json.dump(state.shared, f, indent=4, default=serialize_state)
        else:
            with open(os.path.join(RESULTS_DIR, f"{name}.json"), "r") as f:
                expected = json.load(f)

            # Normalize state.shared to convert Pydantic models to dicts for comparison
            normalized_shared = normalize_state(state.shared)
            assert normalized_shared == expected

    return assert_fn


def make_graph_test(name: str, write_results: bool = False):
    async def test_graph(scene):
        assert_fn = make_assert_fn(name, write_results)

        def error_handler(state, error: Exception):
            raise error

        with ActiveScene(scene):
            graph = load_test_graph(name)
            assert graph is not None
            graph.callbacks.append(assert_fn)
            graph.error_handlers.append(error_handler)
            await graph.execute()

    return test_graph


@pytest.mark.asyncio
async def test_graph_core(mock_scene):
    fn = make_graph_test("test-harness-core", False)
    await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_data(mock_scene):
    fn = make_graph_test("test-harness-data", False)
    await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_scene(mock_scene):
    fn = make_graph_test("test-harness-scene", False)
    await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_functions(mock_scene):
    fn = make_graph_test("test-harness-functions", False)
    await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_agents(mock_scene):
    fn = make_graph_test("test-harness-agents", False)
    await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_prompt(mock_scene):
    fn = make_graph_test("test-harness-prompt", False)

    async with MockClientContext() as client_reponses:
        client_reponses.append("The sum of 1 and 5 is 6.")
        client_reponses.append('```json\n{\n  "result": 6\n}\n```')
        await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_collectors(mock_scene):
    fn = make_graph_test("test-harness-collectors", False)
    await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_context_ids(mock_scene):
    fn = make_graph_test("test-harness-context-ids", False)
    await fn(mock_scene)


@pytest.mark.asyncio
async def test_graph_assets(mock_scene_with_assets):
    fn = make_graph_test("test-harness-assets", False)
    await fn(mock_scene_with_assets)
