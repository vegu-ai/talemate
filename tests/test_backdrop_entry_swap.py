"""Swapping the image of a backdrop entry for another scene background."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.agents.visual.schema import VIS_TYPE
from talemate.context import active_scene
from talemate.emit.async_signals import get as get_signal
from talemate.scene_assets import AssetMeta, AssetTargetNotFound, BackdropEntryTarget
from talemate.scene_message import NarratorMessage, SceneBackdropMessage
from talemate.server.scene_assets import SceneAssetsPlugin
from talemate.server.scene_message import SceneMessagePlugin


@pytest.fixture
def active(scene, monkeypatch):
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    scene.active = True
    token = active_scene.set(scene)
    yield scene
    active_scene.reset(token)


@pytest.fixture
def changes():
    received = []

    async def listener(payload):
        received.append(payload.backdrop)

    signal = get_signal("scene.backdrop_changed")
    signal.connect(listener)
    yield received
    signal.disconnect(listener)


async def add_asset(scene, data: bytes, vis_type=VIS_TYPE.SCENE_BACKGROUND) -> str:
    asset = await scene.assets.add_asset(
        data, "png", "image/png", meta=AssetMeta(vis_type=vis_type)
    )
    return asset.id


async def change_backdrop(scene, asset_id):
    scene.history.append(NarratorMessage(f"The scene turns to {asset_id}."))
    await scene.assets.set_scene_backdrop(asset_id=asset_id)
    return next(
        m for m in reversed(scene.history) if isinstance(m, SceneBackdropMessage)
    )


async def swap(scene, message_id, asset_id):
    return await scene.assets.set_asset(
        BackdropEntryTarget(message_id=message_id), asset_id
    )


def entries(scene) -> list[SceneBackdropMessage]:
    return [m for m in scene.history if isinstance(m, SceneBackdropMessage)]


async def test_swapping_the_latest_entry_sets_the_scene_backdrop(active, changes):
    day, night, dusk = [await add_asset(active, bytes([i])) for i in range(3)]
    await change_backdrop(active, day)
    latest = await change_backdrop(active, night)
    changes.clear()

    await swap(active, latest.id, dusk)

    assert [m.backdrop for m in entries(active)] == [day, dusk]
    assert active.assets.backdrop == dusk
    assert changes == [dusk]


async def test_swapping_does_not_write_a_new_entry(active):
    day, night = [await add_asset(active, bytes([i])) for i in range(2)]
    latest = await change_backdrop(active, day)
    count = len(active.history)

    await swap(active, latest.id, night)

    assert len(active.history) == count
    assert len(entries(active)) == 1


async def test_swapping_an_older_entry_keeps_the_current_backdrop(active, changes):
    day, night, dusk = [await add_asset(active, bytes([i])) for i in range(3)]
    older = await change_backdrop(active, day)
    latest = await change_backdrop(active, night)
    changes.clear()

    await swap(active, older.id, dusk)

    assert older.backdrop == dusk
    assert active.assets.backdrop == night
    assert changes == []
    assert latest.previous_backdrop == dusk


async def test_swapping_keeps_the_enabled_state(active):
    day, night = [await add_asset(active, bytes([i])) for i in range(2)]
    latest = await change_backdrop(active, day)
    await active.assets.set_scene_backdrop(enabled=False)

    await swap(active, latest.id, night)

    assert active.assets.backdrop == night
    assert active.assets.backdrop_enabled is False


async def test_the_swap_marks_the_scene_unsaved(active):
    day, night = [await add_asset(active, bytes([i])) for i in range(2)]
    latest = await change_backdrop(active, day)
    active.saved = True

    await swap(active, latest.id, night)

    assert active.saved is False


async def test_an_unknown_message_is_not_found(active):
    day = await add_asset(active, b"a")

    with pytest.raises(AssetTargetNotFound):
        await swap(active, 99999, day)


async def test_a_message_without_a_finished_backdrop_is_refused(active):
    day = await add_asset(active, b"a")
    story = NarratorMessage("Nothing changes.")
    pending = SceneBackdropMessage(pending=True)
    active.history.extend([story, pending])

    with pytest.raises(ValueError, match="not a backdrop entry"):
        await swap(active, story.id, day)
    with pytest.raises(ValueError, match="not a backdrop entry"):
        await swap(active, pending.id, day)


async def test_only_a_scene_background_can_be_chosen(active):
    day = await add_asset(active, b"a")
    illustration = await add_asset(active, b"b", VIS_TYPE.SCENE_ILLUSTRATION)
    latest = await change_backdrop(active, day)

    with pytest.raises(ValueError, match="not a scene background"):
        await swap(active, latest.id, illustration)
    with pytest.raises(ValueError, match="Invalid asset_id"):
        await swap(active, latest.id, "ghost")

    assert latest.backdrop == day
    assert active.assets.backdrop == day


async def test_the_websocket_action_swaps_the_image(active):
    day, night = [await add_asset(active, bytes([i])) for i in range(2)]
    latest = await change_backdrop(active, day)
    handler = SimpleNamespace(
        scene=active, queue_put=Mock(), request_scene_assets=Mock()
    )
    plugin = SceneAssetsPlugin(handler)

    await plugin.handle_set_asset(
        {
            "asset_id": night,
            "targets": [{"kind": "backdrop_entry", "message_id": latest.id}],
        }
    )

    assert latest.backdrop == night
    assert active.assets.backdrop == night
    handler.request_scene_assets.assert_called_once_with([night])
    active.attempt_auto_save.assert_awaited_once()


async def test_the_websocket_action_reports_a_refused_swap(active):
    illustration = await add_asset(active, b"b", VIS_TYPE.SCENE_ILLUSTRATION)
    day = await add_asset(active, b"a")
    latest = await change_backdrop(active, day)
    handler = SimpleNamespace(
        scene=active, queue_put=Mock(), request_scene_assets=Mock()
    )
    plugin = SceneAssetsPlugin(handler)

    await plugin.handle_set_asset(
        {
            "asset_id": illustration,
            "targets": [{"kind": "backdrop_entry", "message_id": latest.id}],
        }
    )

    assert latest.backdrop == day
    handler.request_scene_assets.assert_not_called()
    sent = [call.args[0] for call in handler.queue_put.call_args_list]
    assert any(
        "not a scene background" in frame.get("error", {}).get("message", "")
        for frame in sent
    )


async def delete(scene, message):
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=Mock()))
    await plugin.handle_delete({"id": message.id})


async def test_deleting_a_swapped_latest_entry_restores_the_entry_before(active):
    day, night, dusk = [await add_asset(active, bytes([i])) for i in range(3)]
    await change_backdrop(active, day)
    latest = await change_backdrop(active, night)
    await swap(active, latest.id, dusk)

    await delete(active, latest)

    assert [m.backdrop for m in entries(active)] == [day]
    assert active.assets.backdrop == day


async def test_deleting_the_latest_entry_after_swapping_an_older_one_keeps_the_swap(
    active,
):
    day, night, dusk = [await add_asset(active, bytes([i])) for i in range(3)]
    older = await change_backdrop(active, day)
    latest = await change_backdrop(active, night)
    await swap(active, older.id, dusk)

    await delete(active, latest)

    assert [m.backdrop for m in entries(active)] == [dusk]
    assert active.assets.backdrop == dusk
