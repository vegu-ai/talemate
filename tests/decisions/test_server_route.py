import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from talemate.decisions import decision_service
from talemate.decisions.events import (
    ActionRecord,
    DecisionLog,
    Failure,
    InvocationRecord,
    RequestRecord,
)
from talemate.decisions.provider import FailureCode
from talemate.server import websocket_server
from talemate.server.decisions import DecisionsPlugin
from talemate.server.websocket_server import WebsocketHandler
from talemate.tale_mate import Scene


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(decision_service, "log", DecisionLog(max_finished=1))
    frames = []
    handler = SimpleNamespace(scene=None, queue_put=frames.append)
    plugin = DecisionsPlugin(handler)
    return SimpleNamespace(plugin=plugin, frames=frames, log=decision_service.log)


def record(invocation_id="invocation"):
    return RequestRecord(
        invocation_id=invocation_id,
        template_uid="editor.policy",
        source_group="user",
        label="editor-repetition",
        provider="fake",
        model="model",
    )


def test_log_events_reach_the_socket_until_the_connection_ends(route):
    entry = record()
    route.log.start_invocation(
        InvocationRecord(id=entry.invocation_id, template_uid="editor.policy")
    )
    route.log.add(entry)
    assert [frame["event"] for frame in route.frames] == [
        "invocation",
        "invocation",
        "request",
    ]
    assert route.frames[-1]["type"] == "decisions"
    assert route.frames[-1]["entry"]["id"] == entry.id
    assert route.frames[-1]["entry"]["label"] == "editor-repetition"

    route.plugin.disconnect()
    route.log.update(entry)
    assert route.log.listeners == []
    assert [frame["event"] for frame in route.frames] == [
        "invocation",
        "invocation",
        "request",
    ]


def test_action_events_are_not_forwarded_because_the_entries_carry_them(route):
    entry = record()
    action = ActionRecord(action="editor.revision_rewrite")
    entry.actions.append(action)
    route.log.add(entry)
    route.log.emit(
        "action",
        invocation_id=entry.invocation_id,
        action={"id": action.id},
        request_ids=[entry.id],
    )
    assert [frame["event"] for frame in route.frames] == ["request"]
    assert route.frames[0]["entry"]["actions"][0]["action"] == "editor.revision_rewrite"


async def test_snapshot_answers_with_requests_and_invocations(route):
    entry = record()
    route.log.start_invocation(
        InvocationRecord(id=entry.invocation_id, template_uid="editor.policy")
    )
    route.log.add(entry)
    route.frames.clear()

    await route.plugin.handle({"action": "snapshot"})

    [frame] = route.frames
    assert frame["type"] == "decisions"
    assert frame["event"] == "snapshot"
    assert [request["id"] for request in frame["requests"]] == [entry.id]
    assert [record["id"] for record in frame["invocations"]] == [entry.invocation_id]


async def test_a_failed_entry_survives_the_json_encoding_of_its_failure_code(route):
    entry = record()
    entry.status = "failed"
    entry.failure = Failure.from_code(FailureCode.TIMEOUT)
    route.log.add(entry)

    await route.plugin.handle({"action": "snapshot"})

    encoded = json.loads(json.dumps(route.frames[-1]))
    assert encoded["requests"][0]["failure"] == {
        "code": "timeout",
        "message": "Decision policy unavailable: timeout",
    }


async def test_clear_removes_finished_entries_and_announces_them(route):
    pending = record("pending")
    finished = record("finished")
    finished.status = "completed"
    route.log.add(pending)
    route.log.add(finished)
    route.frames.clear()

    await route.plugin.handle({"action": "clear"})

    assert [frame["event"] for frame in route.frames] == ["removed"]
    assert route.frames[0]["request_ids"] == [finished.id]
    assert list(route.log.records) == [pending.id]


@pytest.fixture
def loading_handler(monkeypatch):
    handler = object.__new__(WebsocketHandler)
    handler.scene = Scene()
    handler.queue_put = lambda frame: None
    handler.load_scene_failure = AsyncMock()

    def release():
        handler.scene.active = False
        handler.scene = Scene()
        return handler.scene

    handler.release_scene = release
    monkeypatch.setattr(
        websocket_server,
        "load_scene",
        AsyncMock(side_effect=lambda scene, *_, **__: scene),
    )
    monkeypatch.setattr(Scene, "start", AsyncMock())
    return handler


async def test_a_scene_load_clears_the_log_through_the_backend(route, loading_handler):
    pending = record("pending")
    finished = record("finished")
    finished.status = "completed"
    route.log.add(pending)
    route.log.add(finished)
    route.frames.clear()

    await loading_handler.load_scene("scene.json")

    assert [frame["event"] for frame in route.frames] == ["removed"]
    assert route.frames[0]["request_ids"] == [finished.id]
    assert list(route.log.records) == [pending.id]
