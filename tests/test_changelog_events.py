import json
from pathlib import Path

import pytest

from talemate.changelog import (
    SceneRevisionEvent,
    delete_scene_revisions,
    fork_scene_at_revision,
    scene_ref_from_path,
)
from talemate.emit import async_signals
from talemate.storage.changelog import SnapshotStore


@pytest.fixture
def revision_events():
    events = []
    names = [
        "scene.revision_saved",
        "scene.revision_forked",
        "scene.revisions_deleted",
        "scene.revision_failed",
    ]

    async def receive(event):
        assert isinstance(event, SceneRevisionEvent)
        events.append(event)

    for name in names:
        async_signals.get(name).connect(receive)
    yield events
    for name in names:
        async_signals.get(name).disconnect(receive)


async def test_persistence_events_report_durable_state_and_origin(
    persistence_scene_factory, revision_events
):
    scene = persistence_scene_factory()
    scene.name, scene.filename = "Events", "source.json"
    observed = []

    async def after_save(event):
        assert not scene._save_lock.locked()
        saved = json.loads(Path(event.project_path, event.filename).read_text())
        assert saved == await SnapshotStore(event.project_path).assemble(
            event.filename, event.revision
        )
        observed.append(event.revision)

    signal = async_signals.get("scene.revision_saved")
    signal.connect(after_save)
    try:
        await scene.save(force=True)
    finally:
        signal.disconnect(after_save)
    assert observed == [0]
    assert revision_events[0].operation == "save"
    assert revision_events[0].revision_id
    path = await fork_scene_at_revision(scene, 0, "fork")
    fork = revision_events[-1]
    assert fork.operation == "fork"
    assert fork.source_filename == "source.json"
    assert fork.filename == "fork.json"
    assert fork.revision_id == revision_events[0].revision_id
    Path(path).unlink()
    await delete_scene_revisions(scene_ref_from_path(path))
    assert revision_events[-1].operation == "delete"
    assert revision_events[-1].filename == "fork.json"
    assert revision_events[-1].removed_revisions == 0
    assert revision_events[-1].removed_blobs == 0


async def test_failed_save_emits_failure_without_saved_event(
    persistence_scene_factory, revision_events, monkeypatch
):
    scene = persistence_scene_factory()
    scene.name, scene.filename = "Events", "source.json"

    async def refuse(*args, **kwargs):
        raise OSError("database full")

    monkeypatch.setattr(SnapshotStore, "append", refuse)
    with pytest.raises(OSError, match="database full"):
        await scene.save(force=True)
    assert len(revision_events) == 1
    assert revision_events[0].operation == "save"
    assert revision_events[0].error == "database full"
    assert revision_events[0].revision_id is None
    assert not Path(scene.full_path).exists()


async def test_validation_failure_does_not_emit_revision_failure(
    persistence_scene_factory, revision_events
):
    from talemate.exceptions import TalemateError

    scene = persistence_scene_factory()
    scene.name = ""
    with pytest.raises(TalemateError, match="Scene has no name"):
        await scene.save()
    assert revision_events == []


async def test_file_failure_after_commit_emits_saved_with_error(
    persistence_scene_factory, revision_events, monkeypatch
):
    import builtins

    scene = persistence_scene_factory()
    scene.name, scene.filename = "Events", "source.json"
    original_open = builtins.open

    def fail_json_write(file, mode="r", *args, **kwargs):
        if Path(file) == Path(scene.full_path) and mode == "w":
            raise OSError("JSON file is unwritable")
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_json_write)
    with pytest.raises(OSError, match="JSON file is unwritable"):
        await scene.save(force=True)
    assert len(revision_events) == 1
    event = revision_events[0]
    head = await SnapshotStore(scene.save_dir).head(scene.filename)
    assert event.operation == "save"
    assert event.revision_id == head.id
    assert event.error == "JSON file is unwritable"


async def test_save_as_emits_committed_link_then_revision(
    persistence_scene_factory, revision_events
):
    scene = persistence_scene_factory()
    scene.name, scene.filename = "Events", "source.json"
    await scene.save(force=True)
    source_id = revision_events[-1].revision_id
    revision_events.clear()
    await scene.save(save_as=True, copy_name="copy.json")
    assert [event.operation for event in revision_events] == ["fork", "save"]
    assert revision_events[0].revision_id == source_id
    assert revision_events[0].source_filename == "source.json"
    assert revision_events[0].filename == "copy.json"
    assert revision_events[1].parent_id == source_id


async def test_failed_save_as_emits_no_committed_link(
    persistence_scene_factory, revision_events, monkeypatch
):
    from unittest.mock import AsyncMock

    scene = persistence_scene_factory()
    scene.name, scene.filename = "Events", "source.json"
    await scene.save(force=True)
    revision_events.clear()
    monkeypatch.setattr(
        SnapshotStore, "append", AsyncMock(side_effect=OSError("disk full"))
    )
    with pytest.raises(OSError, match="disk full"):
        await scene.save(save_as=True, copy_name="copy.json")
    assert len(revision_events) == 1
    event = revision_events[0]
    assert event.operation == "save"
    assert event.filename == "copy.json"
    assert event.revision_id is None and event.error == "disk full"
    assert await SnapshotStore(scene.save_dir).head("copy.json") is None


async def test_revision_listener_writes_game_state_after_saved_snapshot(
    persistence_scene_factory,
):
    import asyncio

    from _node_test_helpers import make_capture, make_constant
    from talemate.context import ActiveScene
    from talemate.game.engine.nodes.core import GraphContext, Listen
    from talemate.game.engine.nodes.data import Get
    from talemate.game.engine.nodes.event import State as EventState
    from talemate.game.engine.nodes.state import SetStatePath

    scene = persistence_scene_factory()
    scene.name, scene.filename = "Event graph", "source.json"
    token = {"activation": "saved"}
    captured, changes = {}, []
    changed = asyncio.Event()
    listener = Listen()
    listener.set_property("event_name", "scene.revision_saved")
    event, read = EventState(), Get()
    read.set_property("attribute", "revision_id")
    activation = make_constant(state=token)
    writer = SetStatePath()
    writer.set_property("scope", "game")
    writer.set_property("name", "last_saved_revision")
    capture = make_capture(captured, "state", "value")
    for node in (event, read, activation, writer, capture):
        listener.add_node(node)
    listener.connect(event.get_output_socket("event"), read.get_input_socket("object"))
    listener.connect(read.get_output_socket("value"), writer.get_input_socket("value"))
    listener.connect(
        activation.get_output_socket("state"), writer.get_input_socket("state")
    )
    listener.connect(
        writer.get_output_socket("state"), capture.get_input_socket("state")
    )
    listener.connect(
        writer.get_output_socket("value"), capture.get_input_socket("value")
    )
    assert not writer.get_input_socket("state").optional

    async def receive_change(event):
        changes.append(event)
        changed.set()

    saved_signal = async_signals.get("scene.revision_saved")
    changed_signal = async_signals.get("game_state.changed")
    saved_signal.connect(listener.execute_from_event)
    changed_signal.connect(receive_change)
    try:
        with ActiveScene(scene), GraphContext():
            await scene.save(force=True)
            await asyncio.wait_for(changed.wait(), timeout=5)
    finally:
        saved_signal.disconnect(listener.execute_from_event)
        changed_signal.disconnect(receive_change)

    head = await SnapshotStore(scene.save_dir).head(scene.filename)
    assert captured == {"state": token, "value": head.id}
    assert captured["state"] is token
    assert token == {"activation": "saved"}
    assert [(e.path, e.value, e.previous_value) for e in changes] == [
        ("last_saved_revision", head.id, None)
    ]
    assert scene.game_state.variables["last_saved_revision"] == head.id
    saved = json.loads(Path(scene.full_path).read_text())
    assert "last_saved_revision" not in saved["game_state"]["variables"]
    assert saved == await SnapshotStore(scene.save_dir).assemble(scene.filename)
    await scene.save(force=True)
    assert (
        json.loads(Path(scene.full_path).read_text())["game_state"]["variables"][
            "last_saved_revision"
        ]
        == head.id
    )


@pytest.mark.parametrize("node_name", ["SetStatePath", "UpdateGameState"])
def test_revision_listener_writers_require_activation(node_name):
    from talemate.game.engine.nodes import state as state_nodes
    from talemate.game.engine.nodes.core import Graph, GraphContext

    node = getattr(state_nodes, node_name)()
    graph = Graph()
    graph.add_node(node)
    node.set_property("scope", "game")
    node.set_property("name", "saved_revision")
    node.set_property("value", "revision-id")
    node.set_property("updates", {"saved_revision": "revision-id"})
    assert not node.get_input_socket("state").optional
    assert node.get_output_socket("state") is not None
    with GraphContext() as state:
        assert node.check_is_available(state) is False
        node.set_property("state", "activation")
        for socket in node.outputs:
            socket.deactivated = False
        assert node.check_is_available(state) is True
