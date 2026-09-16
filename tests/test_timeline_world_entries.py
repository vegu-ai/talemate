"""A timeline shift moves the scene time a world entry records (#651)."""

from unittest.mock import AsyncMock

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.history import (
    HistoryEntry,
    add_history_entry,
    delete_history_entry,
    shift_scene_timeline,
)
from talemate.instance import get_agent
from talemate.server.world_state_manager.shared_context import SharedContextMixin
from talemate.world_state import ManualContext


@pytest.fixture()
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.world_state.manual_context = {
        "promise": ManualContext(
            id="promise",
            text="Alice promised to return",
            meta={"ts": 1800, "pin_only": True, "typ": "world_state"},
        ),
        "lore": ManualContext(
            id="lore", text="The lighthouse is old", meta={"typ": "world_state"}
        ),
    }
    return scene


def _metas(scene):
    return {
        entry.id: dict(entry.meta)
        for entry in scene.world_state.manual_context.values()
    }


@pytest.fixture()
def memory_calls(monkeypatch):
    add_many = AsyncMock()
    monkeypatch.setattr(get_agent("memory"), "add_many", add_many)
    return add_many


def _committed_ids(add_many):
    return [[item["id"] for item in call.args[0]] for call in add_many.await_args_list]


@pytest.mark.parametrize("shift, expected", [(3600, 5400), (-600, 1200), (-9000, 0)])
def test_shift_moves_only_the_recorded_time(scene, shift, expected):
    shift_scene_timeline(scene, shift)

    assert _metas(scene) == {
        "promise": {"ts": expected, "pin_only": True, "typ": "world_state"},
        "lore": {"typ": "world_state"},
    }


@pytest.mark.asyncio
async def test_adding_an_older_static_entry_refreshes_the_pin(
    scene, memory_calls, monkeypatch
):
    load_active_pins = AsyncMock()
    monkeypatch.setattr(scene, "load_active_pins", load_active_pins)
    scene.ts = scene.start_ts = 3600

    await add_history_entry(scene, "the war ended", offset=7200)

    assert scene.world_state.manual_context["promise"].meta["ts"] == 5400
    assert ["promise"] in _committed_ids(memory_calls)
    load_active_pins.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_a_static_entry_inside_the_timeline_moves_nothing(
    scene, memory_calls, monkeypatch
):
    load_active_pins = AsyncMock()
    monkeypatch.setattr(scene, "load_active_pins", load_active_pins)
    scene.ts = scene.start_ts = 3600

    await add_history_entry(scene, "an hour ago", offset=600)

    assert scene.world_state.manual_context["promise"].meta["ts"] == 1800
    assert ["promise"] not in _committed_ids(memory_calls)
    load_active_pins.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleting_the_oldest_static_entry_refreshes_the_pin(
    scene, memory_calls, monkeypatch
):
    load_active_pins = AsyncMock()
    monkeypatch.setattr(scene, "load_active_pins", load_active_pins)
    scene.archived_history = [
        {"id": "m1", "text": "oldest", "ts": 0},
        {"id": "m2", "text": "next", "ts": 900},
    ]
    scene.ts = scene.start_ts = 3600

    await delete_history_entry(
        scene, HistoryEntry(text="oldest", ts=0, index=0, layer=0, id="m1")
    )

    assert scene.world_state.manual_context["promise"].meta["ts"] == 900
    assert ["promise"] in _committed_ids(memory_calls)
    load_active_pins.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_linking_a_shared_context_that_moves_the_start_refreshes_the_pin(
    scene, memory_calls, monkeypatch
):
    load_active_pins = AsyncMock()
    monkeypatch.setattr(scene, "load_active_pins", load_active_pins)
    scene.ts = scene.start_ts = 3600

    class Shared:
        async def update_to_scene(self, scene):
            shift_scene_timeline(scene, 7200)

        update_from_scene = AsyncMock()

    class Handler(SharedContextMixin):
        pass

    handler = Handler()
    handler.scene = scene

    await handler._apply_shared_context(Shared())

    assert scene.world_state.manual_context["promise"].meta["ts"] == 9000
    assert ["promise"] in _committed_ids(memory_calls)
    load_active_pins.assert_awaited_once_with()
