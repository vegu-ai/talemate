from unittest.mock import AsyncMock

import pytest

from _world_state_helpers import make_actor
from _world_state_helpers import scene as scene_fixture

from talemate.game.focal.schema import Call
from talemate.instance import get_agent
from talemate.world_state import Suggestion, WorldState

scene = scene_fixture


@pytest.fixture
def progression(scene):
    characters = [make_actor(scene, name) for name in ("Nora", "Sterling")]
    return get_agent("world_state"), characters


def change(uid, result="happy"):
    return Call(
        uid=uid,
        name="update_attribute",
        arguments={"name": "mood"},
        result=result,
        called=True,
    )


@pytest.mark.asyncio
async def test_no_change_check_does_not_create_group_or_erase_pending(
    scene, progression, monkeypatch
):
    agent, (nora, sterling) = progression
    determine = AsyncMock(side_effect=[[change("n1")], [], [], []])
    monkeypatch.setattr(agent, "determine_character_development", determine)
    monkeypatch.setattr(
        type(agent.client),
        "supports_concurrent_inference",
        property(lambda self: False),
    )

    await agent.character_progression_track([nora, sterling])
    await agent.character_progression_track([nora, sterling])

    saved = WorldState.model_validate_json(scene.world_state.model_dump_json())
    assert [(s.name, [p.uid for p in s.proposals]) for s in saved.suggestions] == [
        ("Nora", ["n1"])
    ]
    assert determine.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("selected", ["Nora", "Sterling"])
async def test_removing_one_character_keeps_other_pending_changes(
    scene, progression, selected, bulk
):
    agent, characters = progression
    for character in characters:
        await agent.character_progression_process_calls(
            character, [change(character.name)], as_suggestions=True
        )

    manager = scene.world_state_manager
    if bulk:
        await manager.remove_suggestion(f"character-{selected}")
    else:
        await manager.remove_suggestion_proposal(f"character-{selected}", selected)

    other = next(
        character.name for character in characters if character.name != selected
    )
    assert [
        (s.name, [p.uid for p in s.proposals]) for s in scene.world_state.suggestions
    ] == [(other, [other])]


@pytest.mark.asyncio
async def test_pending_calls_and_attribute_removal_are_not_empty_groups(scene):
    manager = scene.world_state_manager
    calls = [
        Call(uid="pending", name="update_description", called=False),
        Call(
            uid="remove",
            name="remove_attribute",
            arguments={"name": "mood"},
            called=True,
        ),
    ]
    await manager.add_suggestion(
        Suggestion(id="character-Nora", name="Nora", type="character", proposals=calls)
    )
    assert scene.world_state.suggestions[0].proposals == calls
