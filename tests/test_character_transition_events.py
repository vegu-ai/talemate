"""
character.deactivated, the transition field of character.activated, and the
Unpack Character Transition / Set Arrival Note nodes.
"""

import pytest

import talemate.emit.async_signals as async_signals
from _node_test_helpers import run_node
from talemate.character import activate_character, deactivate_character
from talemate.context import SceneIsLoading
from talemate.events import CharacterActivatedEvent, CharacterDeactivatedEvent
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.nodes.history import (
    SetArrivalNote,
    UnpackCharacterTransition,
)
from talemate.scene_message import CharacterTransitionMessage, NarratorMessage

import test_character_transitions

returning_scene = test_character_transitions.returning_scene
leave_and_return = test_character_transitions.leave_and_return


@pytest.fixture
def transitions():
    received = []

    async def handler(event):
        received.append(event)

    for name in ("character.activated", "character.deactivated"):
        async_signals.get(name).connect(handler)
    yield received
    for name in ("character.activated", "character.deactivated"):
        async_signals.get(name).disconnect(handler)


@pytest.mark.asyncio
async def test_departure_and_return_carry_their_history_entries(
    returning_scene, transitions
):
    scene = returning_scene
    arrival = await leave_and_return(scene, lines=1)
    deactivated, activated = transitions
    assert isinstance(deactivated, CharacterDeactivatedEvent)
    assert deactivated.event_type == "character.deactivated"
    assert deactivated.character.name == "Nora"
    assert isinstance(deactivated.transition, CharacterTransitionMessage)
    assert deactivated.transition.kind == "deactivated"
    assert deactivated.transition in scene.history

    assert isinstance(activated, CharacterActivatedEvent)
    assert activated.transition is arrival
    assert activated.transition.returning is True
    assert activated.transition.departure_message_id == deactivated.transition.id


@pytest.mark.asyncio
async def test_no_transition_while_loading(returning_scene, transitions):
    scene = returning_scene
    with SceneIsLoading(scene):
        await deactivate_character(scene, "Nora")
        await activate_character(scene, "Nora")
    deactivated, activated = transitions
    assert deactivated.transition is None
    assert activated.transition is None


@pytest.mark.asyncio
async def test_unrecorded_departure_still_sends_the_event(returning_scene, transitions):
    scene = returning_scene
    await deactivate_character(scene, "Nora", record_transition=False)
    [event] = transitions
    assert event.character.name == "Nora"
    assert event.transition is None


@pytest.mark.asyncio
async def test_inactive_character_sends_nothing(returning_scene, transitions):
    scene = returning_scene
    await deactivate_character(scene, "Nora")
    transitions.clear()
    assert await deactivate_character(scene, "Nora") is False
    assert transitions == []


class TestUnpackCharacterTransition:
    @pytest.mark.asyncio
    async def test_arrival(self, returning_scene):
        scene = returning_scene
        arrival = await leave_and_return(scene, lines=1, seconds=172800)
        arrival.arrival_note = "Her boots are wet."
        out = await run_node(
            UnpackCharacterTransition(), scene=scene, inputs={"message": arrival}
        )
        assert out["character_name"] == "Nora"
        assert out["kind"] == "activated"
        assert out["returning"] is True
        assert out["arrival_note"] == "Her boots are wet."
        assert out["departure_message_id"] == arrival.departure_message_id
        assert out["absence_seconds"] == 172800
        assert "Mara" in out["participants"]

    @pytest.mark.asyncio
    async def test_other_messages_are_refused(self, returning_scene):
        with pytest.raises(InputValueError):
            await run_node(
                UnpackCharacterTransition(),
                scene=returning_scene,
                inputs={"message": NarratorMessage("Rain.")},
            )


class TestSetArrivalNote:
    @pytest.mark.asyncio
    async def test_sets_the_note(self, returning_scene, monkeypatch):
        scene = returning_scene
        emitted = []
        monkeypatch.setattr(scene, "emit_history_message", emitted.append)
        arrival = await leave_and_return(scene, lines=1)
        emitted.clear()
        scene.saved = True
        await run_node(
            SetArrivalNote(),
            scene=scene,
            inputs={"message": arrival, "text": "  She found the key.  "},
        )
        assert arrival.arrival_note == "She found the key."
        assert scene.saved is False
        assert emitted == [arrival]

    @pytest.mark.asyncio
    async def test_departure_is_refused(self, returning_scene, transitions):
        scene = returning_scene
        await deactivate_character(scene, "Nora")
        [event] = transitions
        with pytest.raises(InputValueError, match="Activation entry not found"):
            await run_node(
                SetArrivalNote(),
                scene=scene,
                inputs={"message": event.transition, "text": "x"},
            )

    @pytest.mark.asyncio
    async def test_removed_arrival_is_refused(self, returning_scene):
        scene = returning_scene
        arrival = await leave_and_return(scene, lines=1)
        scene.history.remove(arrival)
        with pytest.raises(InputValueError, match="no longer available"):
            await run_node(
                SetArrivalNote(),
                scene=scene,
                inputs={"message": arrival, "text": "x"},
            )
