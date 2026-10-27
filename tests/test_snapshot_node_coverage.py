"""
Add Snapshot Entity, Get Snapshot and agent.world_state.snapshot.entity_added.
"""

import pytest

import talemate.emit.async_signals as async_signals
import talemate.instance as instance_module
from _node_test_helpers import run_node
from _world_state_helpers import scene  # noqa: F401 - pytest fixture
from talemate.agents.world_state.nodes import AddSnapshotEntity, GetSnapshot
from talemate.agents.world_state.snapshot import SnapshotEntityAddedEmission
from talemate.game.engine.nodes.core import InputValueError
from talemate.scene_message import NarratorMessage
from talemate.world_state.schema import ObjectState

from test_world_state_agent import _stub_entity_response

LOCKER = {
    "resolved": True,
    "kind": "item",
    "name": "dented locker",
    "snapshot": "Its door is welded shut.",
    "mentions": ["A dented locker"],
}


@pytest.fixture
def added():
    received = []

    async def handler(emission):
        received.append(emission)

    signal = async_signals.get("agent.world_state.snapshot.entity_added")
    signal.connect(handler)
    yield received
    signal.disconnect(handler)


def seed(scene, text="A dented locker sits against the wall."):  # noqa: F811
    message = NarratorMessage(message=text)
    scene.history.append(message)
    return message


@pytest.mark.asyncio
async def test_node_adds_the_entity_and_the_event_follows(
    scene,  # noqa: F811
    monkeypatch,
    added,
):
    message = seed(scene)
    _stub_entity_response(monkeypatch, LOCKER)
    out = await run_node(
        AddSnapshotEntity(),
        scene=scene,
        inputs={"message": message, "text": "dented locker"},
    )
    assert out["resolved"] is True
    assert out["kind"] == "item"
    assert out["name"]
    assert out["waiting_for_regeneration"] is False
    assert "Dented Locker" in scene.world_state.items

    [emission] = added
    assert isinstance(emission, SnapshotEntityAddedEmission)
    assert emission.agent is instance_module.get_agent("world_state")
    assert emission.message_id == message.id
    assert emission.selection == "dented locker"
    assert emission.kind == "item"
    assert emission.name == out["name"]
    assert emission.mentions == out["mentions"]


@pytest.mark.asyncio
async def test_refusal_sends_nothing(scene, monkeypatch, added):  # noqa: F811
    message = seed(scene, "And then she said nothing at all.")
    _stub_entity_response(monkeypatch, {"resolved": False})
    out = await run_node(
        AddSnapshotEntity(),
        scene=scene,
        inputs={"message_id": message.id, "text": "and then she said"},
    )
    assert out["resolved"] is False
    assert out["name"] is None and out["kind"] is None
    assert added == []


@pytest.mark.asyncio
async def test_needs_a_message(scene):  # noqa: F811
    with pytest.raises(InputValueError) as exc:
        await run_node(AddSnapshotEntity(), scene=scene, inputs={"text": "locker"})
    assert exc.value.input_name == "message_id"


@pytest.mark.asyncio
async def test_disabled_world_state_updates_are_refused(
    scene,  # noqa: F811
    monkeypatch,
):
    agent = instance_module.get_agent("world_state")
    monkeypatch.setattr(
        type(agent), "can_add_snapshot_entity", property(lambda _: False)
    )
    message = seed(scene)
    with pytest.raises(InputValueError, match="cannot update the world snapshot"):
        await run_node(
            AddSnapshotEntity(),
            scene=scene,
            inputs={"message": message, "text": "locker"},
        )


@pytest.mark.asyncio
async def test_get_snapshot(scene):  # noqa: F811
    scene.world_state.items["Dented Locker"] = ObjectState(
        snapshot="Sealed.", mentions=["the locker"]
    )
    scene.world_state.location = "A cold hangar."
    out = await run_node(GetSnapshot(), scene=scene)
    assert out["items"]["Dented Locker"]["snapshot"] == "Sealed."
    assert out["items"]["Dented Locker"]["mentions"] == ["the locker"]
    assert out["characters"] == {}
    assert out["places"] == {}
    assert out["location"] == "A cold hangar."


@pytest.mark.asyncio
async def test_the_add_takes_the_snapshot_slot_from_a_running_refresh(
    scene,  # noqa: F811
    monkeypatch,
):
    import asyncio

    from talemate.agents.world_state.snapshot import SNAPSHOT_TASK

    agent = instance_module.get_agent("world_state")
    refresh = asyncio.create_task(asyncio.Event().wait())
    agent._tracked_tasks = {SNAPSHOT_TASK: refresh}
    message = seed(scene)
    _stub_entity_response(monkeypatch, LOCKER)
    out = await run_node(
        AddSnapshotEntity(),
        scene=scene,
        inputs={"message": message, "text": "dented locker"},
    )
    await asyncio.sleep(0)
    assert out["resolved"] is True
    assert refresh.cancelled()


@pytest.mark.asyncio
async def test_request_world_state_outputs_the_snapshot_after_the_update(
    scene,  # noqa: F811
    monkeypatch,
):
    from talemate.agents.world_state.nodes import RequestWorldState

    async def request_update(self, *args, **kwargs):
        self.location = "The lamp room."
        self.items["Brass Key"] = ObjectState(snapshot="On the hook.")

    monkeypatch.setattr(type(scene.world_state), "request_update", request_update)
    out = await run_node(RequestWorldState(), scene=scene, inputs={"state": True})
    assert out["world_state"]["location"] == "The lamp room."
    assert out["world_state"]["items"]["Brass Key"]["snapshot"] == "On the hook."
    assert out["world_state"]["characters"] == {}


@pytest.mark.asyncio
async def test_a_listener_can_add_another_entity(
    scene,  # noqa: F811
    monkeypatch,
):
    import asyncio

    from talemate.prompts import Prompt

    message = seed(scene, "A dented locker stands beside a rusty drum.")
    answers = iter(
        [
            LOCKER,
            {
                "resolved": True,
                "kind": "item",
                "name": "rusty drum",
                "snapshot": "Half full of rain.",
                "mentions": ["a rusty drum"],
            },
        ]
    )

    async def respond(*args, vars, **kwargs):
        vars["snapshot_request"].context_history(budget=0)
        return "", {"entity": next(answers)}

    monkeypatch.setattr(Prompt, "request", respond)
    nested = []

    async def listener(emission):
        if emission.selection == "dented locker":
            nested.append(
                await run_node(
                    AddSnapshotEntity(),
                    scene=scene,
                    inputs={"message": message, "text": "rusty drum"},
                )
            )

    signal = async_signals.get("agent.world_state.snapshot.entity_added")
    signal.connect(listener)
    try:
        out = await asyncio.wait_for(
            run_node(
                AddSnapshotEntity(),
                scene=scene,
                inputs={"message": message, "text": "dented locker"},
            ),
            timeout=10,
        )
    finally:
        signal.disconnect(listener)
    assert out["resolved"] is True
    assert [result["resolved"] for result in nested] == [True]
    assert {"Dented Locker", "Rusty Drum"} <= set(scene.world_state.items)


@pytest.mark.asyncio
async def test_a_refused_selection_is_not_a_failed_snapshot_task(
    scene,  # noqa: F811
):
    from structlog.testing import capture_logs

    message = seed(scene)
    with capture_logs() as logs:
        with pytest.raises(InputValueError):
            await run_node(
                AddSnapshotEntity(),
                scene=scene,
                inputs={"message": message, "text": "   "},
            )
    assert not [e for e in logs if e["event"] == "tracked task error"]


@pytest.mark.asyncio
async def test_a_listener_child_task_can_add_another_entity(
    scene,  # noqa: F811
    monkeypatch,
):
    import asyncio

    from talemate.prompts import Prompt

    message = seed(scene, "A dented locker stands beside a rusty drum.")
    answers = iter(
        [
            LOCKER,
            {
                "resolved": True,
                "kind": "item",
                "name": "rusty drum",
                "snapshot": "Half full of rain.",
                "mentions": ["a rusty drum"],
            },
        ]
    )

    async def respond(*args, vars, **kwargs):
        vars["snapshot_request"].context_history(budget=0)
        return "", {"entity": next(answers)}

    monkeypatch.setattr(Prompt, "request", respond)
    nested = []

    async def listener(emission):
        # a graph's RunModule runs the module in an awaited child task
        if emission.selection == "dented locker":
            child = asyncio.create_task(
                run_node(
                    AddSnapshotEntity(),
                    scene=scene,
                    inputs={"message": message, "text": "rusty drum"},
                )
            )
            nested.append(await child)

    signal = async_signals.get("agent.world_state.snapshot.entity_added")
    signal.connect(listener)
    try:
        out = await asyncio.wait_for(
            run_node(
                AddSnapshotEntity(),
                scene=scene,
                inputs={"message": message, "text": "dented locker"},
            ),
            timeout=10,
        )
    finally:
        signal.disconnect(listener)
    assert out["resolved"] is True
    assert [result["resolved"] for result in nested] == [True]
    assert {"Dented Locker", "Rusty Drum"} <= set(scene.world_state.items)
