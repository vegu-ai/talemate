"""Deleting the backdrop entry that set the current backdrop winds the
backdrop back to the one the remaining history ends with."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.agents.visual.schema import AssetAttachmentContext
from talemate.context import active_scene
from talemate.emit.async_signals import get as get_signal
from talemate.scene_assets import SceneAssets
from talemate.scene_message import NarratorMessage, SceneBackdropMessage
from talemate.server.scene_message import SceneMessagePlugin


@pytest.fixture
def library():
    return {"harbour-day", "harbour-dusk", "harbour-night"}


@pytest.fixture
def active(scene, monkeypatch, library):
    monkeypatch.setattr(
        SceneAssets, "validate_asset_id", lambda self, asset_id: asset_id in library
    )
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


async def change_backdrop(scene, asset_id):
    scene.history.append(NarratorMessage(f"The scene turns to {asset_id}."))
    if asset_id is None:
        await scene.assets.set_scene_backdrop(clear=True)
    else:
        await scene.assets.set_scene_backdrop(asset_id=asset_id)
    return scene.history[-1]


async def delete(scene, message):
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=Mock()))
    await plugin.handle_delete({"id": message.id})


def backdrop_entries(scene) -> list[str | None]:
    return [m.backdrop for m in scene.history if isinstance(m, SceneBackdropMessage)]


async def test_deleting_the_latest_entry_restores_the_previous_backdrop(
    active, changes
):
    await change_backdrop(active, "harbour-day")
    latest = await change_backdrop(active, "harbour-night")
    changes.clear()

    await delete(active, latest)

    assert backdrop_entries(active) == ["harbour-day"]
    assert active.assets.backdrop == "harbour-day"
    assert changes == ["harbour-day"]
    active.attempt_auto_save.assert_awaited_once()


async def test_deleting_an_older_entry_keeps_the_current_backdrop(active, changes):
    older = await change_backdrop(active, "harbour-day")
    await change_backdrop(active, "harbour-night")
    changes.clear()

    await delete(active, older)

    assert backdrop_entries(active) == ["harbour-night"]
    assert active.assets.backdrop == "harbour-night"
    assert changes == []


async def test_deleting_the_only_entry_clears_the_backdrop(active, changes):
    only = await change_backdrop(active, "harbour-day")
    changes.clear()

    await delete(active, only)

    assert backdrop_entries(active) == []
    assert active.assets.backdrop is None
    assert changes == [None]


async def test_deleting_the_only_entry_restores_the_backdrop_from_before_it(active):
    await active.assets.set_scene_backdrop(asset_id="harbour-day", record=False)
    only = await change_backdrop(active, "harbour-night")
    assert only.previous_backdrop == "harbour-day"

    await delete(active, only)

    assert active.assets.backdrop == "harbour-day"


async def test_a_deleted_previous_image_falls_back_to_an_earlier_one(active, library):
    await change_backdrop(active, "harbour-day")
    await change_backdrop(active, "harbour-dusk")
    latest = await change_backdrop(active, "harbour-night")
    library.discard("harbour-dusk")

    await delete(active, latest)

    assert active.assets.backdrop == "harbour-day"


async def test_no_remaining_image_clears_the_backdrop(active, library):
    await change_backdrop(active, "harbour-day")
    latest = await change_backdrop(active, "harbour-night")
    library.discard("harbour-day")

    await delete(active, latest)

    assert active.assets.backdrop is None


async def test_deleting_the_entry_after_a_cleared_one_keeps_it_cleared(active):
    await change_backdrop(active, "harbour-day")
    await change_backdrop(active, None)
    latest = await change_backdrop(active, "harbour-night")

    await delete(active, latest)

    assert active.assets.backdrop is None


async def test_deleting_a_cleared_entry_restores_the_backdrop_before_it(active):
    await change_backdrop(active, "harbour-day")
    cleared = await change_backdrop(active, None)

    await delete(active, cleared)

    assert active.assets.backdrop == "harbour-day"


async def test_deleting_a_pending_entry_keeps_the_backdrop(active, changes):
    await change_backdrop(active, "harbour-day")
    active.history.append(NarratorMessage("Night falls over the harbour."))
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    pending = active.history[-1]
    changes.clear()

    await delete(active, pending)

    assert backdrop_entries(active) == ["harbour-day"]
    assert active.assets.backdrop == "harbour-day"
    assert active.assets.pending_backdrops == {}
    assert changes == []


async def test_the_latest_entry_before_a_pending_one_still_rolls_back(active):
    await change_backdrop(active, "harbour-day")
    latest = await change_backdrop(active, "harbour-night")
    active.history.append(NarratorMessage("The lanterns go out."))
    await active.assets.begin_generated_backdrop(
        AssetAttachmentContext(scene_backdrop=True)
    )

    await delete(active, latest)

    assert active.assets.backdrop == "harbour-day"


async def test_the_restore_adds_no_backdrop_entry(active):
    await change_backdrop(active, "harbour-day")
    latest = await change_backdrop(active, "harbour-night")
    length = len(active.history)

    await delete(active, latest)

    assert len(active.history) == length - 1
    assert backdrop_entries(active) == ["harbour-day"]


async def test_changing_back_at_the_end_does_not_roll_back_further(active):
    await change_backdrop(active, "harbour-day")
    await change_backdrop(active, "harbour-night")
    await active.assets.set_scene_backdrop(asset_id="harbour-day")

    assert backdrop_entries(active) == ["harbour-day"]
    assert active.assets.backdrop == "harbour-day"


async def test_other_messages_are_deleted_as_before(active):
    await change_backdrop(active, "harbour-day")
    story = NarratorMessage("The lanterns go out.")
    active.history.append(story)

    await delete(active, story)

    assert story not in active.history
    assert active.assets.backdrop == "harbour-day"
