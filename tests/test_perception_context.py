import pytest

import test_perception_lifecycle
from talemate.agents.summarize.perceptions import perception_context
from talemate.instance import get_agent
from talemate.history import shift_scene_timeline
from talemate.knowledge.revision_refresh import _phase_identity
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage, TimePassageMessage
from talemate.tale_mate import Actor
from talemate.world_state import Reinforcement

setup = test_perception_lifecycle.setup
result = test_perception_lifecycle.result


@pytest.fixture
def tracked_scene(setup):
    scene, _, _ = setup
    for character in scene.character_data.values():
        actor = Actor(character, get_agent("conversation"))
        actor.scene = scene
        scene.actors.append(actor)
    return setup


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "insert", ["sequential", "all-context", "conversation-context", "never"]
)
async def test_tracked_state_outlives_passage_window_and_is_removed(
    tracked_scene, insert
):
    scene, _, request = tracked_scene
    scene.ts = 3600
    state = Reinforcement(question="Condition", character="Bob", insert=insert)
    scene.world_state.reinforce.append(state)
    world = get_agent("world_state")
    await world._apply_reinforcement(
        state, world._prepare_reinforcement(state, False), "Bob is blindfolded.", False
    )
    source = state.source_for(scene)
    assert source.knowledge.acquired.ts == 3600
    assert request.await_count == 1
    scene.history.extend(
        NarratorMessage(message=f"A bell chimes {index} times.") for index in range(13)
    )
    scene.history.append(TimePassageMessage(message="Six hours later.", ts=21600))
    scene.ts += 21600
    message = CharacterMessage(message="Alice: Look over here.")

    context = perception_context(scene, message)

    assert source.id not in {entry["id"] for entry in context["prior_physical_context"]}
    assert context["cast"][1]["tracked_states"] == {
        "Condition": "(6 Hours ago) Bob is blindfolded."
    }
    assert "Condition" not in context["cast"][1]["authored_details"]
    assert context["cast"][0]["tracked_states"] == {}
    assert request.await_count == 1

    await scene.world_state.remove_reinforcement(0)

    assert perception_context(scene, message)["cast"][1]["tracked_states"] == {}


def test_undated_states_are_included_without_inventing_an_age(setup):
    scene, _, _ = setup
    scene.world_state.reinforce.extend(
        [
            Reinforcement(question="Condition", character="Bob", answer="Asleep."),
            Reinforcement(question="Unanswered", character="Bob"),
            Reinforcement(question="Weather", answer="Rain."),
        ]
    )
    context = perception_context(scene, CharacterMessage(message="Alice: Hello."))
    assert context["cast"][1]["tracked_states"] == {
        "Condition": "(Time unknown) Asleep."
    }


@pytest.mark.asyncio
async def test_current_state_value_and_future_record_age(tracked_scene):
    scene, _, _ = tracked_scene
    scene.ts = 3600
    state = await scene.world_state.add_reinforcement(
        "Condition", "Bob", answer="Asleep.", insert="never"
    )
    scene.ts = 0
    message = CharacterMessage(message="Alice: Hello.")
    assert perception_context(scene, message)["cast"][1]["tracked_states"] == {
        "Condition": "(Recently) Asleep."
    }
    scene.ts = 7200
    world = get_agent("world_state")
    await world._apply_reinforcement(
        state, world._prepare_reinforcement(state, False), "Awake.", False
    )
    scene.ts += 3600
    assert perception_context(scene, message)["cast"][1]["tracked_states"] == {
        "Condition": "(1 Hour ago) Awake."
    }


def test_intention_precedes_task_and_scene_description_is_absent(setup):
    scene, _, _ = setup
    scene.description = "DESCRIPTION_SENTINEL"
    scene.intent_state.intent = "STORY_INTENTION_SENTINEL"
    scene.intent_state.phase.intent = "PHASE_INTENTION_SENTINEL"
    message = CharacterMessage(message="Alice: Hello.")
    context = perception_context(scene, message)
    assert "shared_scene_description" not in context
    assert "shared_story_intention" not in context
    rendered = Prompt.get(
        "summarizer.perceptions",
        vars={"scene": scene, "context": context, "validation_error": ""},
    ).render()
    assert "DESCRIPTION_SENTINEL" not in rendered
    task = rendered.index("Analyze the finalized passage")
    for intention in ("STORY_INTENTION_SENTINEL", "PHASE_INTENTION_SENTINEL"):
        assert rendered.count(intention) == 1
        assert rendered.index(intention) < task


@pytest.mark.parametrize("part", ["story", "phase", "scene_type"])
@pytest.mark.asyncio
async def test_intention_changes_discard_inflight_response_and_change_receipt(
    setup, part
):
    scene, summarizer, request = setup
    message = CharacterMessage(message="Alice: Hello.")
    scene.history.append(message)
    summarizer._register_perception_sources(scene, [message])
    before = _phase_identity(scene, message, "perceptions")

    async def analyze(*args, **kwargs):
        if request.await_count == 1:
            if part == "story":
                scene.intent_state.intent = "A changing story."
            elif part == "phase":
                scene.intent_state.phase.intent = "A changing phase."
            else:
                scene.intent_state.current_scene_type.description = "A changed type."
            return result(test_perception_lifecycle.answer("Stale.", "Stale."))
        return result()

    request.side_effect = analyze
    await summarizer.ensure_perceptions(scene)

    assert request.await_count == 2
    assert all(view.text != "Stale." for view in message.knowledge.views)
    assert _phase_identity(scene, message, "perceptions") != before


@pytest.mark.asyncio
async def test_scene_description_edit_does_not_repeat_analysis(setup):
    scene, _, request = setup

    async def analyze(*args, **kwargs):
        scene.description = "A changed unused description."
        return result()

    request.side_effect = analyze
    await scene.push_history(CharacterMessage(message="Alice: Hello."))
    assert request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "insert", ["sequential", "all-context", "conversation-context", "never"]
)
async def test_editing_tracked_state_uses_last_update_time(tracked_scene, insert):
    scene, _, _ = tracked_scene
    scene.ts = 0
    state = Reinforcement(question="Condition", character="Bob", insert=insert)
    scene.world_state.reinforce.append(state)
    world = get_agent("world_state")
    await world._apply_reinforcement(
        state, world._prepare_reinforcement(state, False), "Blindfolded.", False
    )
    source = state.source_for(scene)
    scene.history.append(TimePassageMessage(message="Six hours later.", ts=21600))
    scene.ts = 21600

    await scene.world_state.add_reinforcement(
        "Condition", "Bob", answer="Awake and alert.", insert=insert
    )

    message = CharacterMessage(message="Alice: Hello.")
    assert perception_context(scene, message)["cast"][1]["tracked_states"] == {
        "Condition": "(Recently) Awake and alert."
    }
    assert state.updated_ts == 21600
    assert Reinforcement.model_validate(state.model_dump()).updated_ts == 21600
    if insert == "sequential":
        assert state.source_for(scene) is source
        assert source.knowledge.acquired.ts == 0

    scene.ts += 3600
    await scene.world_state.add_reinforcement(
        "Condition",
        "Bob",
        answer="Awake and alert.",
        insert=insert,
        interval=20,
        answer_confirmed=False,
    )
    assert state.updated_ts == 21600
    assert perception_context(scene, message)["cast"][1]["tracked_states"] == {
        "Condition": "(1 Hour ago) Awake and alert."
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "insert", ["sequential", "all-context", "conversation-context", "never"]
)
async def test_refreshing_same_tracked_state_refreshes_its_age(tracked_scene, insert):
    scene, _, _ = tracked_scene
    state = Reinforcement(question="Condition", character="Bob", insert=insert)
    scene.world_state.reinforce.append(state)
    world = get_agent("world_state")
    for timestamp in (0, 21600):
        scene.ts = timestamp
        await world._apply_reinforcement(
            state, world._prepare_reinforcement(state, False), "Awake.", False
        )
    assert perception_context(scene, CharacterMessage(message="Alice: Hello."))["cast"][
        1
    ]["tracked_states"] == {"Condition": "(Recently) Awake."}


@pytest.mark.parametrize(
    "shift, expected",
    [(1800, "1 Hour ago"), (-1800, "1 Hour ago"), (-5400, "30 Minutes ago")],
)
def test_tracked_state_update_age_follows_scene_timeline_shift(setup, shift, expected):
    scene, _, _ = setup
    scene.ts = 7200
    scene.world_state.reinforce.extend(
        [
            Reinforcement(
                question="Condition", character="Bob", answer="Awake.", updated_ts=3600
            ),
            Reinforcement(question="Location", character="Bob", answer="At home."),
        ]
    )

    shift_scene_timeline(scene, shift)

    assert perception_context(scene, CharacterMessage(message="Alice: Hello."))["cast"][
        1
    ]["tracked_states"] == {
        "Condition": f"({expected}) Awake.",
        "Location": "(Time unknown) At home.",
    }
