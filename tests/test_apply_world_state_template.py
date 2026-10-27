from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pydantic
import pytest

import test_perception_context as cases
from talemate.instance import get_agent
from talemate.server.world_state_manager import (
    ApplyWorldStateTemplatePayload,
    ApplyWorldStateTemplatesPayload,
    SetWorldEntryReinforcementPayload,
    WorldStateManagerPlugin,
)
from talemate.world_state import Reinforcement
from talemate.world_state.templates import StateReinforcement

setup = cases.setup
tracked_scene = cases.tracked_scene
pytestmark = pytest.mark.asyncio

QUESTION = "What is the current time of day?"
WORLD_TEMPLATE = StateReinforcement(
    name="Time of day",
    query=QUESTION,
    state_type="world",
    insert="all-context",
    uid="time_of_day",
)
CHARACTER_TEMPLATE = StateReinforcement(
    name="Mood",
    query="How does the character feel?",
    state_type="npc",
    insert="all-context",
    uid="mood",
)


def make_plugin(scene) -> WorldStateManagerPlugin:
    plugin = WorldStateManagerPlugin(
        SimpleNamespace(scene=scene, queue_put=Mock(), set_scene=Mock())
    )
    plugin.handle_get_world = AsyncMock()
    plugin.handle_get_templates = AsyncMock()
    plugin.signal_operation_done = AsyncMock()
    return plugin


async def tracked_world_state(scene, answer="Late evening."):
    world = scene.world_state
    await world.add_reinforcement(QUESTION, None, insert="all-context")
    await world.add_reinforcement(QUESTION, None, answer=answer, insert="all-context")
    return world


async def apply_with(plugin, route, template, character_name):
    if route == "apply_template":
        task = await plugin.handle_apply_template(
            {
                "template": template.model_dump(),
                "character_name": character_name,
            }
        )
    else:
        task = await plugin.handle_apply_templates(
            {
                "templates": [template.model_dump()],
                "character_name": character_name,
            }
        )
    await task


def states_for(world, question):
    return [state for state in world.reinforce if state.question == question]


@pytest.mark.parametrize("route", ["apply_template", "apply_templates"])
@pytest.mark.parametrize("character_name", [None, ""])
async def test_reapplying_a_world_template_keeps_the_state_and_its_entry(
    tracked_scene, route, character_name
):
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    world = await tracked_world_state(scene)
    entry = world.manual_context[QUESTION]
    plugin = make_plugin(scene)

    for _ in range(2):
        await apply_with(plugin, route, WORLD_TEMPLATE, character_name)

    states = states_for(world, QUESTION)
    assert [(state.character, state.answer) for state in states] == [
        (None, "Late evening.")
    ]
    assert world.manual_context[QUESTION] is entry
    assert entry.text == f"{QUESTION} Late evening."


@pytest.mark.parametrize("route", ["apply_template", "apply_templates"])
async def test_applying_a_world_template_for_the_first_time_stores_no_character(
    tracked_scene, route
):
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    plugin = make_plugin(scene)

    await apply_with(plugin, route, WORLD_TEMPLATE, "")

    assert [state.character for state in states_for(scene.world_state, QUESTION)] == [
        None
    ]


@pytest.mark.parametrize("route", ["apply_template", "apply_templates"])
async def test_reapplying_a_character_template_still_starts_blank(tracked_scene, route):
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    world = scene.world_state
    question = CHARACTER_TEMPLATE.query
    await world.add_reinforcement(
        question, "Bob", answer="Tired.", insert="all-context"
    )
    plugin = make_plugin(scene)

    await apply_with(plugin, route, CHARACTER_TEMPLATE, "Bob")

    states = states_for(world, question)
    assert [(state.character, state.answer) for state in states] == [("Bob", "")]


@pytest.mark.parametrize("route", ["apply_template", "apply_templates"])
async def test_reapplying_over_a_state_saved_with_an_empty_character_updates_it(
    tracked_scene, route
):
    # scenes saved by 0.39.0 hold a World state applied from a template as
    # character "" rather than None
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    world = scene.world_state
    saved = Reinforcement(
        question=QUESTION, character="", answer="Late evening.", insert="all-context"
    )
    world.reinforce.append(saved)
    plugin = make_plugin(scene)

    await apply_with(plugin, route, WORLD_TEMPLATE, None)

    assert states_for(world, QUESTION) == [saved]
    assert saved.answer == "Late evening."


@pytest.fixture
def saved_pair(tracked_scene):
    """A World state pair as 0.39.0 saved it: the template state first, then the
    twin that editing it in the World Editor appended."""
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    template_state = Reinforcement(
        question=QUESTION, character="", answer="Old.", insert="all-context"
    )
    shown = Reinforcement(
        question=QUESTION, character=None, answer="Edited.", insert="all-context"
    )
    scene.world_state.reinforce.extend([template_state, shown])
    assert scene.world_state.reinforcements_for_world()[QUESTION] is shown
    return scene, template_state, shown


async def test_a_lookup_prefers_the_exact_character_form_in_a_saved_pair(saved_pair):
    scene, template_state, shown = saved_pair
    world = scene.world_state

    assert await world.find_reinforcement(QUESTION, None) == (1, shown)
    assert await world.find_reinforcement(QUESTION, "") == (0, template_state)


async def test_saving_a_world_state_in_a_saved_pair_writes_the_shown_state(saved_pair):
    scene, template_state, shown = saved_pair
    plugin = make_plugin(scene)

    await plugin.handle_set_world_state_reinforcement(
        {"question": QUESTION, "answer": "New.", "insert": "all-context"}
    )

    assert (shown.answer, template_state.answer) == ("New.", "Old.")


async def test_refreshing_a_world_state_in_a_saved_pair_runs_the_shown_state(
    saved_pair, monkeypatch
):
    scene, template_state, shown = saved_pair
    monkeypatch.setattr(
        get_agent("world_state"),
        "generate_reinforcement",
        AsyncMock(return_value="Fresh."),
    )
    plugin = make_plugin(scene)

    task = await plugin.handle_run_world_state_reinforcement({"question": QUESTION})
    await task

    assert (shown.answer, template_state.answer) == ("Fresh.", "Old.")


async def test_deleting_a_world_state_in_a_saved_pair_removes_the_shown_state(
    saved_pair,
):
    scene, template_state, _ = saved_pair
    plugin = make_plugin(scene)

    await plugin.handle_delete_world_state_reinforcement({"question": QUESTION})

    assert states_for(scene.world_state, QUESTION) == [template_state]


@pytest.mark.parametrize("character", [None, ""])
async def test_a_global_lookup_finds_a_state_by_either_form(tracked_scene, character):
    scene, _, _ = tracked_scene
    world = scene.world_state
    saved = Reinforcement(question=QUESTION, character="", insert="all-context")
    other = Reinforcement(question=QUESTION, character="Bob", insert="all-context")
    world.reinforce.extend([other, saved])

    idx, found = await world.find_reinforcement(QUESTION, character)

    assert (idx, found) == (1, saved)


async def test_both_apply_payloads_read_an_empty_character_name_as_none():
    template = WORLD_TEMPLATE.model_dump()

    single = ApplyWorldStateTemplatePayload(template=template, character_name="")
    several = ApplyWorldStateTemplatesPayload(templates=[template], character_name="")

    assert single.character_name is None
    assert several.character_name is None
    assert (
        ApplyWorldStateTemplatePayload(
            template=template, character_name="Bob"
        ).character_name
        == "Bob"
    )


@pytest.mark.parametrize("character_name", [False, 0, [], {}])
async def test_apply_payloads_reject_a_character_name_that_is_not_a_string(
    character_name,
):
    template = WORLD_TEMPLATE.model_dump()

    with pytest.raises(pydantic.ValidationError):
        ApplyWorldStateTemplatePayload(template=template, character_name=character_name)
    with pytest.raises(pydantic.ValidationError):
        ApplyWorldStateTemplatesPayload(
            templates=[template], character_name=character_name
        )


async def test_a_world_state_save_without_an_answer_keeps_the_answer_by_default():
    assert SetWorldEntryReinforcementPayload(question=QUESTION).answer is None


async def test_a_world_state_save_without_an_answer_keeps_the_stored_answer(
    tracked_scene,
):
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    world = await tracked_world_state(scene)
    plugin = make_plugin(scene)

    await plugin.handle_set_world_state_reinforcement(
        {"question": QUESTION, "interval": 5, "insert": "all-context"}
    )

    [state] = states_for(world, QUESTION)
    assert state.answer == "Late evening." and state.interval == 5
    assert world.manual_context[QUESTION].text == f"{QUESTION} Late evening."


async def test_a_world_state_save_with_an_empty_answer_still_clears_it(tracked_scene):
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    world = await tracked_world_state(scene)
    plugin = make_plugin(scene)

    await plugin.handle_set_world_state_reinforcement(
        {"question": QUESTION, "answer": "", "insert": "all-context"}
    )

    [state] = states_for(world, QUESTION)
    assert state.answer == ""
    assert QUESTION not in world.manual_context
