from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import test_perception_context as cases
from talemate.config.schema import SceneAppearance
from talemate.emit.base import Emission
from talemate.emit.signals import handlers
from talemate.instance import get_agent
from talemate.scene_message import NarratorMessage, ReinforcementMessage
from talemate.server.scene_message import SceneMessagePlugin
from talemate.server.websocket_server import WebsocketHandler
from talemate.world_state import Reinforcement
from talemate.world_state.manager import THEME_APPEARANCE_MAP
from talemate.world_state.templates.theme import Theme

setup = cases.setup
tracked_scene = cases.tracked_scene
FEED_FRAMES = ("reinforcement", "remove_message", "message_edited")


@pytest.fixture
def frames():
    captured = []

    def receive(emission):
        captured.append((emission.typ, emission.id, emission.message))

    for typ in FEED_FRAMES:
        handlers[typ].connect(receive, weak=False)
    yield captured
    for typ in FEED_FRAMES:
        handlers[typ].disconnect(receive)


async def track(scene, character="Bob", question="Condition"):
    state = Reinforcement(question=question, character=character, insert="sequential")
    scene.world_state.reinforce.append(state)
    return state


async def answer(state, text):
    world = get_agent("world_state")
    return await world._apply_reinforcement(
        state, world._prepare_reinforcement(state, False), text, False
    )


def reinforcement_frame(message: ReinforcementMessage) -> dict:
    handler = WebsocketHandler.__new__(WebsocketHandler)
    handler.queue_put = Mock()
    WebsocketHandler.handle_reinforcement(
        handler,
        Emission(
            typ="reinforcement",
            message=message.message,
            message_object=message,
            id=message.id,
        ),
    )
    return handler.queue_put.call_args.args[0]


@pytest.mark.parametrize("character", ["Bob", None])
def test_a_reinforcement_reaches_the_frontend(character):
    message = ReinforcementMessage(message="Asleep.")
    message.set_source(
        "world_state", "update_reinforcement", question="Condition", character=character
    )

    assert reinforcement_frame(message) == {
        "type": "reinforcement",
        "id": message.id,
        "message": "Asleep.",
        "question": "Condition",
        "character": character,
        "flags": 0,
    }


@pytest.mark.asyncio
async def test_a_sequential_answer_is_sent_to_the_feed(tracked_scene, frames):
    scene, _, _ = tracked_scene
    state = await track(scene)

    message = await answer(state, "Asleep.")

    assert scene.history == [message]
    assert frames == [("reinforcement", message.id, "Asleep.")]


@pytest.mark.asyncio
async def test_a_rerun_replaces_the_recent_row(tracked_scene, frames):
    scene, _, _ = tracked_scene
    state = await track(scene)
    first = await answer(state, "Asleep.")
    story = NarratorMessage(message="A bell chimes.")
    scene.history.append(story)

    second = await answer(state, "Awake.")

    assert scene.history == [story, second]
    assert frames[1:] == [
        ("remove_message", first.id, ""),
        ("reinforcement", second.id, "Awake."),
    ]


@pytest.mark.asyncio
async def test_an_older_row_stays_beside_the_rerun(tracked_scene, frames):
    scene, _, _ = tracked_scene
    state = await track(scene)
    first = await answer(state, "Asleep.")
    scene.history.extend(
        NarratorMessage(message=f"A bell chimes {index} times.") for index in range(10)
    )

    second = await answer(state, "Awake.")

    assert scene.history[0] is first and scene.history[-1] is second
    assert ("remove_message", first.id, "") not in frames


@pytest.mark.asyncio
async def test_every_popped_message_leaves_the_feed(frames):
    from talemate.tale_mate import Scene

    scene = Scene()
    kept = NarratorMessage(message="A bell chimes.")
    popped = []
    for text in ("Asleep.", "Awake."):
        message = ReinforcementMessage(message=text)
        message.set_source(
            "world_state", "update_reinforcement", question="Condition", character="Bob"
        )
        popped.append(message)
    scene.history = [popped[0], kept, popped[1]]

    scene.pop_history(typ="reinforcement", meta_hash=popped[0].meta_hash, all=True)

    assert scene.history == [kept]
    assert sorted(frames) == sorted(
        ("remove_message", message.id, "") for message in popped
    )


@pytest.mark.asyncio
async def test_saving_the_answer_updates_the_row(tracked_scene, frames):
    scene, _, _ = tracked_scene
    state = await track(scene)
    message = await answer(state, "Asleep.")

    await scene.world_state.add_reinforcement(
        "Condition", "Bob", answer="Awake.", insert="sequential"
    )

    assert message.message == "Awake."
    assert frames[-1] == ("message_edited", message.id, "Awake.")


def edit(scene, message, text):
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=Mock()))
    return plugin.handle_edit({"id": message.id, "text": text})


@pytest.mark.asyncio
@pytest.mark.parametrize("character", ["Bob", None])
async def test_editing_the_newest_row_changes_the_tracked_answer(
    tracked_scene, character
):
    scene, _, _ = tracked_scene
    state = await track(scene, character=character)
    message = await answer(state, "Asleep.")

    await edit(scene, message, "Awake and alert.")

    assert message.message == "Awake and alert."
    assert state.answer == "Awake and alert."


@pytest.mark.asyncio
@pytest.mark.parametrize("character", ["Bob", None])
async def test_editing_the_newest_row_without_perspectives_rewrites_the_entry(
    tracked_scene, character
):
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    state = await track(scene, character=character, question="Weather")
    message = await answer(state, "Rain.")

    await edit(scene, message, "Sun.")

    assert state.answer == "Sun."
    if character:
        assert scene.get_character(character).details["Weather"] == "Sun."
    else:
        assert scene.world_state.manual_context["Weather"].text == "Weather: Sun."


@pytest.mark.asyncio
@pytest.mark.parametrize("insert", ["sequential", "all-context"])
async def test_an_empty_world_answer_leaves_no_question_only_entry(
    tracked_scene, insert
):
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    world = scene.world_state

    # a configuration-only save of a World state that was never answered
    await world.add_reinforcement("Weather", None, answer="", insert=insert)
    await world.add_reinforcement("Weather", None, interval=5, answer="", insert=insert)
    assert "Weather" not in world.manual_context

    # clearing the answer of an answered World state removes its entry
    await world.add_reinforcement("Weather", None, answer="Rain.", insert=insert)
    assert world.manual_context["Weather"].text == "Weather: Rain."
    await world.add_reinforcement("Weather", None, answer="", insert=insert)
    assert "Weather" not in world.manual_context


@pytest.mark.asyncio
async def test_an_update_without_an_answer_keeps_the_world_answer_and_its_entry(
    tracked_scene,
):
    # applying a state template or the StateReinforcement node passes no answer
    scene, _, _ = tracked_scene
    scene.knowledge_eligibility = "legacy"
    world = scene.world_state
    await world.add_reinforcement("Weather", None, insert="all-context")
    await world.add_reinforcement("Weather", None, answer="Rain.", insert="all-context")
    entry = world.manual_context["Weather"]
    entry.shared = True

    state = await world.add_reinforcement(
        "Weather", None, "Check the sky.", 5, insert="all-context"
    )

    assert state.answer == "Rain."
    assert state.instructions == "Check the sky." and state.interval == 5
    assert world.manual_context["Weather"] is entry
    assert entry.text == "Weather: Rain." and entry.shared


@pytest.mark.asyncio
async def test_editing_an_older_row_keeps_the_tracked_answer(tracked_scene):
    scene, _, _ = tracked_scene
    state = await track(scene)
    first = await answer(state, "Asleep.")
    scene.history.extend(
        NarratorMessage(message=f"A bell chimes {index} times.") for index in range(10)
    )
    await answer(state, "Awake.")

    await edit(scene, first, "Dreaming.")

    assert first.message == "Dreaming."
    assert state.answer == "Awake."


def test_reinforcement_rows_have_an_appearance_style_shown_by_default():
    style = SceneAppearance().reinforcement_messages
    assert style.show is True
    assert THEME_APPEARANCE_MAP["reinforcement"] == "reinforcement_messages"
    theme = Theme(name="t", uid="t", group="g")
    assert theme.appearance.reinforcement.show is True
    assert theme.colors.messages.reinforcement
