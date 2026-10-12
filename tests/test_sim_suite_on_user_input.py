"""Sim Suite On User Input treats the player's line as a computer instruction
whether the player typed it or a Director dynamic action generated it."""

from pathlib import Path

import pytest

from talemate.character import Character
from talemate.context import ActiveScene
from talemate.events import GameLoopCharacterIterEvent, GameLoopEvent
from talemate.game.engine.nodes.core import Graph, GraphContext, GraphState
from talemate.game.engine.nodes.layout import load_graph_from_file
from talemate.game.engine.nodes.registry import get_node
from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
from talemate.game.engine.nodes.tools.loader import register_scene_modules
from talemate.scene_message import CharacterMessage, NarratorMessage
from talemate.tale_mate import Player, Scene

ON_USER_INPUT = "scenes/simulation-suite-v2/nodes/sim-suite-on-user-input.json"


@pytest.fixture
def on_user_input() -> Graph:
    ensure_registry_loaded()
    register_scene_modules(Path(ON_USER_INPUT).parent)
    graph, _ = load_graph_from_file(ON_USER_INPUT)
    return graph


@pytest.fixture
def main_calls(on_user_input, monkeypatch) -> list[GraphState]:
    calls = []

    async def record(self, state: GraphState):
        calls.append(state)
        self.set_output_values({"state": self.get_input_value("state")})

    # Sim Suite Main sends the instruction to the computer prompt; record the
    # hand-off instead
    monkeypatch.setattr(get_node("sim-suite/simSuiteMain"), "run", record)
    return calls


def player_scene(message: CharacterMessage) -> tuple[Scene, Character]:
    scene = Scene()
    character = Character(name="User", is_player=True)
    scene.actors.append(Player(character=character, agent=None))
    scene.character_data[character.name] = character
    scene.active_characters.append(character.name)
    scene.history.append(
        NarratorMessage("The control panel waits for a simulation prompt.")
    )
    scene.history.append(message)
    return scene, character


@pytest.mark.parametrize(
    "message",
    [
        CharacterMessage(
            "User: Start a simulation on a derelict station.", source="player"
        ),
        CharacterMessage(
            'User: "Show me an alien planet during an eclipse."',
            from_choice="Describe an uncharted alien planet during an eclipse.",
        ),
    ],
    ids=["typed", "director_action"],
)
async def test_player_line_starts_the_simulation(on_user_input, main_calls, message):
    scene, character = player_scene(message)
    event = GameLoopCharacterIterEvent(
        scene=scene,
        event_type="game_loop_player_character_iter",
        character=character,
        game_loop=GameLoopEvent(scene=scene, event_type="game_loop"),
    )

    with ActiveScene(scene), GraphContext() as state:
        state.shared["scene_loop"] = {}
        await on_user_input.execute_from_event(event)

    assert len(main_calls) == 1
    assert state.shared["scene_loop"]["user_message"] is message
    assert scene.game_state.get_var("player_message_is_instruction") is True
    assert state.shared["skip_to_player"] is True
