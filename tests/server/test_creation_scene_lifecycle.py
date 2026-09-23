"""A superseded load cannot publish success, start work or reset its successor."""

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import talemate.instance as instance
from talemate.server import websocket_server
from talemate.server.websocket_server import WebsocketHandler
from talemate.scene_agent_settings import SceneAgentSettings
from talemate.tale_mate import Scene


@pytest.fixture
def handler(monkeypatch):
    handler = object.__new__(WebsocketHandler)
    handler.scene = Scene()
    handler.queue_put = lambda frame: None
    handler.load_scene_failure = AsyncMock()

    def release():
        handler.scene.active = False
        handler.scene = Scene()
        return handler.scene

    handler.release_scene = release
    monkeypatch.setitem(
        instance.AGENTS,
        "summarizer",
        SimpleNamespace(check_perception_backlog=lambda scene: None),
    )
    return handler


@pytest.mark.parametrize("late_result", ["success", "failure", "none"])
async def test_superseded_load_cannot_finish_or_rebind(
    handler, monkeypatch, late_result
):
    first_entered = asyncio.Event()
    first_finish = asyncio.Event()
    second_started = asyncio.Event()
    finished = []
    scenes = []

    async def loader(scene, path, **kwargs):
        scenes.append(scene)
        if path == "first":
            first_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await first_finish.wait()
            if late_result == "failure":
                raise ValueError("late failed creation")
            if late_result == "none":
                return None
        return scene

    async def start(scene, **kwargs):
        second_started.set()
        await asyncio.Event().wait()

    async def callback():
        finished.append(handler.scene)

    monkeypatch.setattr(websocket_server, "load_scene", loader)
    monkeypatch.setattr(Scene, "start", start)
    first = asyncio.create_task(handler.load_scene("first", callback=callback))
    second = None
    try:
        await asyncio.wait_for(first_entered.wait(), 5)
        first.cancel()
        second = asyncio.create_task(handler.load_scene("second", callback=callback))
        await asyncio.wait_for(second_started.wait(), 5)
        first_finish.set()
        await asyncio.wait_for(first, 5)
        assert finished == [scenes[1]]
        assert handler.scene is scenes[1]
        assert handler.scene.active
        handler.load_scene_failure.assert_not_awaited()
    finally:
        for task in [first, second]:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)


async def test_failed_owned_load_releases_its_scene_and_reports_its_request(
    handler, monkeypatch
):
    failed_scene = None

    async def loader(scene, *args, **kwargs):
        nonlocal failed_scene
        failed_scene = scene
        raise ValueError("invalid card")

    monkeypatch.setattr(websocket_server, "load_scene", loader)
    await handler.load_scene("bad", request_id="creation-123")
    assert handler.scene is not failed_scene
    assert failed_scene.active is False
    assert handler.scene.agent_overrides is None
    handler.load_scene_failure.assert_awaited_once()
    assert handler.load_scene_failure.call_args.args[1] == "creation-123"


async def test_loading_callback_rejects_history_from_a_superseded_scene(
    handler, monkeypatch
):
    callbacks = []

    async def loader(scene, *args, before_memory, **kwargs):
        callbacks.append((scene, before_memory))
        return scene

    monkeypatch.setattr(websocket_server, "load_scene", loader)
    monkeypatch.setattr(Scene, "start", AsyncMock())
    await handler.load_scene("first")
    await handler.load_scene("second")
    scene, callback = callbacks[0]
    with pytest.raises(asyncio.CancelledError):
        await callback(scene)


async def test_cancelled_creation_discards_provisional_bindings_without_successor(
    handler, monkeypatch, tmp_path
):
    installed = asyncio.Event()
    owned = None

    async def loader(scene, *args, **kwargs):
        nonlocal owned
        owned = scene
        scene.agent_overrides = SceneAgentSettings(
            filepath=tmp_path / "creation.json", pending=True
        )
        installed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(websocket_server, "load_scene", loader)
    callback = AsyncMock()
    task = asyncio.create_task(handler.load_scene("card", callback=callback))
    await asyncio.wait_for(installed.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert handler.scene is not owned
    assert not owned.active
    assert handler.scene.agent_overrides is None
    assert not list(tmp_path.iterdir())
    callback.assert_not_awaited()
