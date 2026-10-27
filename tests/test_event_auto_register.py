"""On Message Set Background registers itself instead of being placed in the
scene loop; the released agent event modules stay in the loop's Events group.
Every scene loop runs each of them once per event."""

import pytest

import talemate.agents  # noqa: F401
import talemate.emit.async_signals as async_signals
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphState
from talemate.game.engine.nodes.event import (
    collect_auto_register_listeners,
    collect_listeners,
    connect_auto_register_listeners,
    connect_listeners,
    disconnect_auto_register_listeners,
    disconnect_listeners,
)
from talemate.game.engine.nodes.layout import load_graph_from_file
from talemate.game.engine.nodes.registry import get_node
from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
from talemate.tale_mate import Scene

BACKGROUND = "agents/world_state/onMessageSetBackground"

PLACED_MODULES = {
    "agents/director/events/onPersistCharacterGenerateVisual": "agent.director.character_management.after_persist_character",
    "agents/summarizer/onMessageSetAvatar": "agent.conversation.finalized",
    "agents/narrator/autoNarration": "game_loop_actor_iter",
}

EVENT_MODULES = {**PLACED_MODULES, BACKGROUND: "game_loop_new_message"}

SCENE_LOOPS = [
    "src/talemate/game/engine/nodes/modules/scene/scene-loop.json",
    "scenes/simulation-suite-v2/nodes/scene-loop.json",
    "scenes/infinity-quest-dynamic-story-v2/nodes/scene-loop.json",
    "scenes/model-testing-harness/nodes/scene-loop.json",
]


@pytest.fixture(autouse=True)
def registry():
    ensure_registry_loaded()


def auto_registered() -> list:
    with ActiveScene(Scene()):
        return collect_auto_register_listeners()


def test_on_message_set_background_registers_itself():
    module = get_node(BACKGROUND)()
    assert module.get_property("auto_register") is True
    assert module.get_property("event_name") == "game_loop_new_message"
    assert [listener.registry for listener in auto_registered()].count(BACKGROUND) == 1


@pytest.mark.parametrize("registry_name", PLACED_MODULES)
def test_released_event_modules_stay_placed(registry_name):
    assert get_node(registry_name)().get_property("auto_register") is False
    assert registry_name not in [listener.registry for listener in auto_registered()]


@pytest.mark.parametrize("path", SCENE_LOOPS)
def test_scene_loop_places_the_released_modules_only(path):
    graph, _ = load_graph_from_file(path)
    placed = [
        listener.registry
        for listeners in collect_listeners(graph).values()
        for listener in listeners
    ]
    assert BACKGROUND not in placed
    for registry_name in PLACED_MODULES:
        assert placed.count(registry_name) == 1, registry_name


@pytest.mark.parametrize("path", SCENE_LOOPS)
def test_each_event_module_receives_its_event_once(path):
    graph, _ = load_graph_from_file(path)
    state = GraphState()
    auto_listeners = auto_registered()
    connect_listeners(graph, state)
    connect_auto_register_listeners(auto_listeners, state)
    try:
        for registry_name, event_name in EVENT_MODULES.items():
            receivers = [
                receiver
                for receiver in async_signals.get(event_name).receivers
                if getattr(getattr(receiver, "__self__", None), "registry", None)
                == registry_name
            ]
            assert len(receivers) == 1, registry_name
    finally:
        disconnect_listeners(graph, state)
        disconnect_auto_register_listeners(auto_listeners, state)
