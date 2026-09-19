from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import test_perception_context as cases
from talemate.agents.summarize.perceptions import tracked_character_states
from talemate.instance import get_agent
from talemate.server.world_state_manager import WorldStateManagerPlugin
from talemate.world_state import Reinforcement

setup = cases.setup
tracked_scene = cases.tracked_scene
MODES = ["sequential", "all-context", "conversation-context", "never"]
pytestmark = pytest.mark.asyncio


async def record(scene, insert):
    scene.ts = 0
    state = Reinforcement(question="Condition", character="Bob", insert=insert)
    scene.world_state.reinforce.append(state)
    world = get_agent("world_state")
    await world._apply_reinforcement(
        state, world._prepare_reinforcement(state, False), "Asleep.", False
    )
    scene.ts = 21600
    return state


@pytest.mark.parametrize("insert", MODES)
@pytest.mark.parametrize("route", ["answer-save", "refresh"])
@pytest.mark.parametrize("answer", ["Asleep.", "Awake."])
async def test_answer_save_and_refresh_use_last_confirmation(
    tracked_scene, insert, route, answer
):
    scene, _, _ = tracked_scene
    state = await record(scene, insert)
    if route == "answer-save":
        await scene.world_state.add_reinforcement(
            "Condition", "Bob", answer=answer, insert=insert
        )
    else:
        world = get_agent("world_state")
        await world._apply_reinforcement(
            state, world._prepare_reinforcement(state, False), answer, False
        )
    scene.ts += 300
    assert tracked_character_states(scene, "Bob") == {
        "Condition": f"(5 Minutes ago) {answer}"
    }
    assert Reinforcement.model_validate(state.model_dump()).updated_ts == 21600


@pytest.mark.parametrize("original", ["sequential", "never"])
@pytest.mark.parametrize("missing_timestamp", [False, True])
async def test_configuration_mode_switch_preserves_known_age(
    tracked_scene, original, missing_timestamp
):
    scene, _, _ = tracked_scene
    state = await record(scene, original)
    if missing_timestamp:
        state.updated_ts = None
    assert state.source_for(scene).knowledge.acquired.ts == 0
    await scene.world_state.add_reinforcement(
        "Condition",
        "Bob",
        answer="Asleep.",
        insert="never" if original == "sequential" else "sequential",
        answer_confirmed=False,
    )
    assert state.updated_ts == 0
    assert tracked_character_states(scene, "Bob") == {
        "Condition": "(6 Hours ago) Asleep."
    }
    assert Reinforcement.model_validate(state.model_dump()).updated_ts == 0


@pytest.mark.parametrize("character", ["Bob", None])
@pytest.mark.parametrize("confirmed", [False, True])
async def test_websocket_save_preserves_confirmation_intent(
    tracked_scene, character, confirmed
):
    scene, _, _ = tracked_scene
    state = Reinforcement(
        question="Condition",
        character=character,
        answer="Asleep.",
        updated_ts=0,
        insert="never",
    )
    scene.world_state.reinforce.append(state)
    scene.ts = 21600
    plugin = WorldStateManagerPlugin(SimpleNamespace(scene=scene, queue_put=Mock()))
    plugin.handle_get_character_details = AsyncMock()
    plugin.handle_get_world = AsyncMock()
    plugin.signal_operation_done = AsyncMock()
    payload = {
        "name": character,
        "question": "Condition",
        "answer": "Asleep.",
        "insert": "never",
        "interval": 20,
        "answer_confirmed": confirmed,
    }
    handler = (
        plugin.handle_set_character_detail_reinforcement
        if character
        else plugin.handle_set_world_state_reinforcement
    )
    await handler(payload)
    assert state.updated_ts == (21600 if confirmed else 0)
