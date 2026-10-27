import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import talemate.agents.visual.generation as generation_module
import talemate.instance as instance
from talemate.agents.summarize.context_history import (
    ContextHistoryMixin,
    ContextHistoryParams,
)
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.schema import (
    VIS_TYPE,
    AssetAttachmentContext,
    GenerationRequest,
)
from talemate.context import active_scene
from talemate.emit.base import Emission
from talemate.history import HistoryEntry, collect_source_entries
from talemate.load import _load_history
import talemate.regenerate as regenerate_module
from talemate.regenerate import regenerate_target_message
import talemate.scene_assets as scene_assets_module
from talemate.config import get_config
from talemate.scene_assets import Asset, AssetMeta, AssetSavedPayload, SceneAssets
from talemate.world_state.snapshot_revision import SnapshotProvenance
from talemate.scene_message import (
    NON_STORY_TYPES,
    NarratorMessage,
    SceneBackdropMessage,
)


@pytest.fixture
def active(scene, monkeypatch):
    monkeypatch.setattr(SceneAssets, "validate_asset_id", lambda self, asset_id: True)
    scene.active = True
    token = active_scene.set(scene)
    yield scene
    active_scene.reset(token)


def backdrops(scene) -> list[tuple]:
    return [
        (m.backdrop, m.previous_backdrop, m.pending)
        for m in scene.history
        if isinstance(m, SceneBackdropMessage)
    ]


async def test_a_changed_backdrop_is_recorded_in_the_history(active):
    await active.assets.set_scene_backdrop(asset_id="harbour-day")
    await active.assets.set_scene_backdrop(asset_id="harbour-day")
    active.history.append(NarratorMessage("Night falls over the harbour."))
    await active.assets.set_scene_backdrop(enabled=False)
    await active.assets.set_scene_backdrop(asset_id="harbour-night")
    active.history.append(NarratorMessage("The lanterns go out."))
    await active.assets.set_scene_backdrop(clear=True)

    assert backdrops(active) == [
        ("harbour-day", None, False),
        ("harbour-night", "harbour-day", False),
        (None, "harbour-night", False),
    ]


async def test_consecutive_changes_at_the_end_share_one_message(active):
    active.history.append(NarratorMessage("Night falls over the harbour."))
    await active.assets.set_scene_backdrop(asset_id="harbour-dusk")
    await active.assets.set_scene_backdrop(asset_id="harbour-night")
    await active.assets.set_scene_backdrop(asset_id="harbour-storm")

    assert backdrops(active) == [("harbour-storm", None, False)]
    assert active.history[-1].backdrop == "harbour-storm"


async def test_changing_back_at_the_end_removes_the_message(active):
    await active.assets.set_scene_backdrop(asset_id="harbour-day", record=False)
    active.history.append(NarratorMessage("Night falls over the harbour."))
    await active.assets.set_scene_backdrop(asset_id="harbour-night")
    await active.assets.set_scene_backdrop(asset_id="harbour-day")

    assert backdrops(active) == []
    assert active.assets.backdrop == "harbour-day"


async def test_a_change_after_a_pending_message_is_its_own_message(active):
    pending = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(pending)
    await active.assets.set_scene_backdrop(asset_id="harbour-day")

    assert backdrops(active) == [(None, None, True), ("harbour-day", None, False)]


async def test_an_unrecorded_backdrop_change_adds_no_message(active):
    await active.assets.set_scene_backdrop(asset_id="harbour-day", record=False)

    assert active.assets.backdrop == "harbour-day"
    assert backdrops(active) == []


async def test_a_generated_backdrop_fills_its_pending_message(active):
    await active.assets.set_scene_backdrop(asset_id="harbour-day")
    ctx = AssetAttachmentContext(scene_backdrop=True)

    await active.assets.begin_generated_backdrop(ctx)
    assert backdrops(active)[-1] == (None, "harbour-day", True)
    assert active.assets.backdrop == "harbour-day"

    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert backdrops(active) == [("harbour-night", None, False)]
    assert active.assets.backdrop == "harbour-night"


async def test_a_generated_backdrop_after_story_keeps_the_earlier_message(active):
    await active.assets.set_scene_backdrop(asset_id="harbour-day")
    active.history.append(NarratorMessage("Night falls over the harbour."))
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert backdrops(active) == [
        ("harbour-day", None, False),
        ("harbour-night", "harbour-day", False),
    ]


async def test_a_failed_generation_keeps_the_message_before_it(active):
    active.history.append(NarratorMessage("Night falls over the harbour."))
    await active.assets.set_scene_backdrop(asset_id="harbour-day")
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    active.assets.abandon_generated_backdrop(ctx)

    assert backdrops(active) == [("harbour-day", None, False)]


async def test_a_generated_backdrop_whose_message_was_removed_is_not_applied(
    active,
):
    await active.assets.set_scene_backdrop(asset_id="harbour-day")
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)

    active.delete_message(ctx.backdrop_message_id)
    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert active.assets.backdrop == "harbour-day"
    assert backdrops(active) == [("harbour-day", None, False)]


async def test_an_abandoned_generation_removes_only_a_pending_message(active):
    pending = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(pending)
    filled = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(filled)
    await active.assets.finish_generated_backdrop(filled, "harbour-night")

    active.assets.abandon_generated_backdrop(pending)
    active.assets.abandon_generated_backdrop(filled)
    active.assets.abandon_generated_backdrop(AssetAttachmentContext())

    assert backdrops(active) == [("harbour-night", None, False)]


class GatedBackend:
    name = "gated"

    def __init__(self):
        self.release = asyncio.Event()
        self.error: BaseException | None = None

    async def generate(self, request, response):
        await self.release.wait()
        if self.error:
            raise self.error
        response.generated = b"image"
        return response

    async def cancel_request(self):
        pass


@pytest.fixture
def visual(active, monkeypatch):
    monkeypatch.setattr(generation_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: True))
    monkeypatch.setattr(VisualAgent, "backend", None, raising=False)
    agent = VisualAgent()
    agent.backend = GatedBackend()

    async def no_finalize(request):
        pass

    async def no_status(*args, **kwargs):
        pass

    async def save(response):
        return SimpleNamespace(id="generated")

    monkeypatch.setattr(agent, "finalize_prompt_request", no_finalize)
    monkeypatch.setattr(agent, "emit_status", no_status)
    monkeypatch.setattr(active.assets, "add_asset_from_generation_response", save)
    return agent


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


def backdrop_request() -> GenerationRequest:
    return GenerationRequest(
        asset_attachment_context=AssetAttachmentContext(scene_backdrop=True)
    )


async def test_a_backdrop_generation_shows_a_pending_message_until_saved(
    visual, active
):
    await visual.generate(backdrop_request())
    assert backdrops(active) == [(None, None, True)]

    visual.backend.release.set()
    await settle()

    assert backdrops(active) == [("generated", None, False)]
    assert active.assets.backdrop == "generated"


@pytest.mark.parametrize("outcome", ["error", "cancel"])
async def test_a_failed_backdrop_generation_removes_its_pending_message(
    visual, active, outcome
):
    await visual.generate(backdrop_request())
    assert backdrops(active) == [(None, None, True)]

    if outcome == "error":
        visual.backend.error = ValueError("backend refused")
        visual.backend.release.set()
    else:
        await visual.cancel_generation()
    await settle()

    assert backdrops(active) == []
    assert active.assets.backdrop is None


async def test_a_backdrop_generation_that_cannot_start_leaves_no_message(
    visual, active, monkeypatch
):
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: False))

    with pytest.raises(Exception):
        await visual.generate(backdrop_request())

    assert backdrops(active) == []


def test_backdrop_messages_are_not_story():
    assert "scene_backdrop" in NON_STORY_TYPES
    params = ContextHistoryParams()
    assert not ContextHistoryMixin._is_dialogue_qualifying(
        SceneBackdropMessage(backdrop="harbour-night"), params
    )
    assert SceneBackdropMessage().as_format("movie_script") == ""
    assert not SceneBackdropMessage().supports_perceptions


async def test_summary_sources_and_recent_history_skip_backdrop_messages(active):
    story = NarratorMessage("The harbour lights go out.")
    active.history = [story, SceneBackdropMessage(backdrop="harbour-night")]

    sources = collect_source_entries(
        active, HistoryEntry(text="", ts=0, index=0, layer=0, start=0, end=1)
    )

    assert [source.id for source in sources] == [story.id]
    assert active.snapshot(lines=3, return_as_list=True) == [story]


async def test_the_world_state_moment_skips_backdrop_messages(active):
    story = NarratorMessage("The harbour lights go out.")
    active.history = [story, SceneBackdropMessage(backdrop="harbour-night")]

    moment = instance.get_agent("world_state").current_moment()

    assert [message.id for message in moment.messages] == [story.id]


async def test_regenerate_targets_the_story_message_before_a_backdrop(active):
    story = NarratorMessage("The harbour lights go out.")
    active.history = [story, SceneBackdropMessage(backdrop="harbour-night")]

    assert regenerate_target_message(active) is story


def test_a_backdrop_message_survives_a_save_and_load():
    message = SceneBackdropMessage(backdrop="harbour-night", previous_backdrop="day")

    (loaded,) = _load_history([message.to_dict()])

    assert isinstance(loaded, SceneBackdropMessage)
    assert (loaded.id, loaded.backdrop, loaded.previous_backdrop, loaded.pending) == (
        message.id,
        "harbour-night",
        "day",
        False,
    )


def test_a_pending_backdrop_message_is_dropped_on_load():
    story = NarratorMessage("The harbour lights go out.")

    loaded = _load_history(
        [story.to_dict(), SceneBackdropMessage(pending=True).to_dict()]
    )

    assert [message.id for message in loaded] == [story.id]


def test_a_backdrop_message_reaches_the_frontend():
    from talemate.server.websocket_server import WebsocketHandler

    message = SceneBackdropMessage(backdrop="harbour-night", previous_backdrop="day")
    handler = WebsocketHandler.__new__(WebsocketHandler)
    handler.queue_put = Mock()

    WebsocketHandler.handle_scene_backdrop(
        handler,
        Emission(
            typ="scene_backdrop", message="", message_object=message, id=message.id
        ),
    )

    assert handler.queue_put.call_args.args[0] == {
        "type": "scene_backdrop",
        "id": message.id,
        "backdrop": "harbour-night",
        "previous_backdrop": "day",
        "pending": False,
        "flags": 0,
    }


async def test_a_late_image_does_not_override_a_later_backdrop_change(active):
    await active.assets.set_scene_backdrop(asset_id="harbour-day", record=False)
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    await active.assets.set_scene_backdrop(asset_id="harbour-dusk")

    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert backdrops(active) == [("harbour-dusk", "harbour-day", False)]
    assert active.assets.backdrop == "harbour-dusk"


async def test_a_filled_backdrop_marks_the_scene_unsaved(active, monkeypatch):
    save = AsyncMock()
    monkeypatch.setattr(active, "attempt_auto_save", save)
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    active.saved = True

    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert active.saved is False
    save.assert_not_awaited()


async def test_a_late_image_leaves_a_released_scene_alone(active):
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    active.active = False
    active.saved = True

    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert backdrops(active) == [(None, None, True)]
    assert active.assets.backdrop is None
    assert active.saved is True
    assert active.assets.pending_backdrops == {}


async def test_a_reset_history_is_not_filled(active):
    from talemate.scene_signals import scene_reset

    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    active.history = []
    scene_reset.send(active)

    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert active.history == []
    assert active.assets.backdrop is None
    assert active.assets.pending_backdrops == {}


async def test_the_backdrop_is_applied_before_the_generation_stops_running(
    visual, active, monkeypatch
):
    seen = []
    finish = active.assets.finish_generated_backdrop

    async def recording_finish(ctx, asset_id):
        seen.append(len(visual.running_generations))
        await finish(ctx, asset_id)

    monkeypatch.setattr(active.assets, "finish_generated_backdrop", recording_finish)
    await visual.generate(backdrop_request())
    visual.backend.release.set()
    await settle()

    assert seen == [1]
    assert len(visual.running_generations) == 0
    assert active.assets.backdrop == "generated"


@pytest.mark.parametrize("outcome", ["finish", "abandon"])
async def test_a_backdrop_generation_ending_during_regenerate(
    active, monkeypatch, outcome
):
    story = NarratorMessage("Night falls over the harbour.")
    active.history = [story]
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    pending = active.history[-1]
    removed = []
    monkeypatch.setattr(
        regenerate_module,
        "emit",
        lambda typ, message=None, **kw: removed.append(kw.get("id"))
        if typ == "remove_message"
        else None,
    )
    monkeypatch.setattr(regenerate_module, "can_regenerate", lambda scene: True)

    async def fake_regenerate(scene):
        assert pending not in scene.history
        if outcome == "finish":
            await scene.assets.finish_generated_backdrop(ctx, "harbour-night")
        else:
            scene.assets.abandon_generated_backdrop(ctx)
        return []

    save = AsyncMock()
    monkeypatch.setattr(active, "attempt_auto_save", save)
    monkeypatch.setattr(regenerate_module, "_regenerate", fake_regenerate)
    await regenerate_module.regenerate(active)

    save.assert_not_awaited()
    if outcome == "finish":
        assert backdrops(active) == [("harbour-night", None, False)]
        assert active.assets.backdrop == "harbour-night"
    else:
        assert backdrops(active) == []
        assert removed == [pending.id]
        assert active.assets.backdrop is None


async def test_a_deleted_pending_message_is_not_filled(active):
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    active.delete_message(ctx.backdrop_message_id)

    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert backdrops(active) == []
    assert active.assets.backdrop is None
    assert active.assets.pending_backdrops == {}


def test_the_newest_story_message_ignores_entries_after_it(active):
    story = NarratorMessage("Night falls over the harbour.")
    active.history = [
        NarratorMessage("Dusk."),
        story,
        SceneBackdropMessage(backdrop="harbour-night"),
    ]

    assert active.last_story_message_index() == 1
    active.history = [SceneBackdropMessage(backdrop="harbour-night")]
    assert active.last_story_message_index() == -1


async def test_deleting_the_newest_reply_before_a_backdrop_entry_is_final(active):
    from talemate.server.scene_message import SceneMessagePlugin

    story = NarratorMessage("Night falls over the harbour.")
    earlier = NarratorMessage("Dusk.")
    active.history = [earlier, story, SceneBackdropMessage(backdrop="harbour-night")]
    plugin = SceneMessagePlugin.__new__(SceneMessagePlugin)
    plugin.websocket_handler = Mock(scene=active)

    for message, final in ((story, True), (earlier, False)):
        await plugin.handle_get_history_position({"id": message.id, "request_id": "r"})
        assert plugin.websocket_handler.queue_put.call_args.args[0]["final"] is final


async def test_a_late_image_during_regenerate_keeps_a_later_manual_change(
    active, monkeypatch
):
    story = NarratorMessage("Night falls over the harbour.")
    active.history = [story]
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    await active.assets.set_scene_backdrop(asset_id="harbour-dusk")
    monkeypatch.setattr(regenerate_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(regenerate_module, "can_regenerate", lambda scene: True)

    async def fake_regenerate(scene):
        await scene.assets.finish_generated_backdrop(ctx, "harbour-night")
        return []

    monkeypatch.setattr(regenerate_module, "_regenerate", fake_regenerate)
    await regenerate_module.regenerate(active)

    assert backdrops(active) == [("harbour-dusk", None, False)]
    assert active.assets.backdrop == "harbour-dusk"
    assert active.history[0] is story


async def test_nested_lifts_apply_held_images_once_the_outermost_ends(active):
    first = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(first)

    async with active.assets.backdrops_lifted():
        await active.assets.finish_generated_backdrop(first, "harbour-night")
        async with active.assets.backdrops_lifted():
            pass
        assert backdrops(active) == [(None, None, True)]

    assert backdrops(active) == [("harbour-night", None, False)]
    assert active.assets.backdrop == "harbour-night"


def story_background_request(**ctx) -> GenerationRequest:
    return GenerationRequest(
        vis_type=VIS_TYPE.SCENE_BACKGROUND,
        asset_attachment_context=AssetAttachmentContext(
            allow_auto_attach=True, allow_override=True, **ctx
        ),
    )


async def test_a_story_background_generation_becomes_a_backdrop_entry(visual, active):
    request = story_background_request()

    await visual.generate(request)
    assert backdrops(active) == [(None, None, True)]
    assert request.asset_attachment_context.scene_backdrop is True
    assert request.asset_attachment_context.allow_auto_attach is False

    visual.backend.release.set()
    await settle()

    assert backdrops(active) == [("generated", None, False)]
    assert active.assets.backdrop == "generated"


@pytest.mark.parametrize(
    "request_",
    [
        GenerationRequest(
            vis_type=VIS_TYPE.SCENE_BACKGROUND,
            asset_attachment_context=AssetAttachmentContext(),
        ),
        GenerationRequest(
            vis_type=VIS_TYPE.SCENE_ILLUSTRATION,
            asset_attachment_context=AssetAttachmentContext(allow_auto_attach=True),
        ),
    ],
    ids=["library background", "story illustration"],
)
async def test_other_generations_record_no_backdrop_entry(visual, active, request_):
    await visual.generate(request_)
    visual.backend.release.set()
    await settle()

    assert backdrops(active) == []
    assert request_.asset_attachment_context.scene_backdrop is False


async def test_a_background_for_an_older_message_goes_right_after_it(active):
    harbour, tavern, street = (
        NarratorMessage("The harbour lies quiet."),
        NarratorMessage("The tavern door swings open."),
        NarratorMessage("Rain runs down the street."),
    )
    active.history = [harbour, tavern, street]
    active.archived_history = [{"text": "Arrival", "start": 0, "end": 1, "ts": 0}]
    await active.assets.set_scene_backdrop(asset_id="harbour-day", record=False)
    ctx = AssetAttachmentContext(scene_backdrop=True, message_ids=[harbour.id])

    await active.assets.begin_generated_backdrop(ctx)

    assert active.history[1].id == ctx.backdrop_message_id
    assert backdrops(active) == [(None, "harbour-day", True)]
    assert active.archived_history[0]["end"] == 2

    await active.assets.finish_generated_backdrop(ctx, "harbour-dusk")

    assert active.history[1].id == ctx.backdrop_message_id
    assert backdrops(active) == [("harbour-dusk", "harbour-day", False)]
    assert active.assets.backdrop == "harbour-dusk"


async def test_a_background_for_the_latest_message_is_appended(active):
    story = NarratorMessage("The harbour lies quiet.")
    active.history = [story]
    ctx = AssetAttachmentContext(scene_backdrop=True, message_ids=[story.id])

    await active.assets.begin_generated_backdrop(ctx)

    assert active.history[-1].id == ctx.backdrop_message_id


async def test_a_background_for_an_older_message_replaces_the_entry_after_it(
    active,
):
    harbour, tavern = (
        NarratorMessage("The harbour lies quiet."),
        NarratorMessage("The tavern door swings open."),
    )
    active.history = [
        harbour,
        SceneBackdropMessage(backdrop="harbour-day", previous_backdrop="dawn"),
        tavern,
    ]
    ctx = AssetAttachmentContext(scene_backdrop=True, message_ids=[harbour.id])

    await active.assets.begin_generated_backdrop(ctx)
    assert active.history[2].id == ctx.backdrop_message_id

    await active.assets.finish_generated_backdrop(ctx, "harbour-dusk")

    assert backdrops(active) == [("harbour-dusk", "dawn", False)]
    assert active.history[1].id == ctx.backdrop_message_id


async def test_an_earlier_background_is_kept_but_not_live_before_a_later_change(
    active,
):
    harbour, tavern = (
        NarratorMessage("The harbour lies quiet."),
        NarratorMessage("The tavern door swings open."),
    )
    later = SceneBackdropMessage(backdrop="tavern", previous_backdrop="harbour-day")
    active.history = [harbour, tavern, later]
    await active.assets.set_scene_backdrop(asset_id="tavern", record=False)
    ctx = AssetAttachmentContext(scene_backdrop=True, message_ids=[harbour.id])

    await active.assets.begin_generated_backdrop(ctx)
    assert backdrops(active)[0] == (None, "harbour-day", True)

    await active.assets.finish_generated_backdrop(ctx, "harbour-dusk")

    assert backdrops(active) == [
        ("harbour-dusk", "harbour-day", False),
        ("tavern", "harbour-dusk", False),
    ]
    assert active.assets.backdrop == "tavern"


async def test_a_late_image_is_kept_when_the_story_moved_on_before_a_later_change(
    active,
):
    await active.assets.set_scene_backdrop(asset_id="harbour-day", record=False)
    ctx = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(ctx)
    active.history.append(NarratorMessage("The tavern door swings open."))
    await active.assets.set_scene_backdrop(asset_id="tavern")

    await active.assets.finish_generated_backdrop(ctx, "harbour-night")

    assert backdrops(active) == [
        ("harbour-night", "harbour-day", False),
        ("tavern", "harbour-night", False),
    ]
    assert active.assets.backdrop == "tavern"


@pytest.mark.parametrize(
    "vis_type, becomes_backdrop",
    [(VIS_TYPE.SCENE_ILLUSTRATION, True), (VIS_TYPE.SCENE_BACKGROUND, False)],
)
async def test_auto_backdrop_promotes_only_scene_illustrations(
    active, monkeypatch, vis_type, becomes_backdrop
):
    config = get_config().model_copy(deep=True)
    for kind in ("scene_illustration", "scene_background"):
        config.appearance.scene.message_assets[kind].auto_backdrop = True
    config.appearance.scene.auto_attach_assets = False
    monkeypatch.setattr(scene_assets_module, "get_config", lambda: config)
    asset = Asset(
        id="library-image",
        file_type="png",
        media_type="image/png",
        meta=AssetMeta(vis_type=vis_type),
    )

    await scene_assets_module._handle_asset_saved(
        AssetSavedPayload(asset=asset, new_asset=True)
    )

    assert (active.assets.backdrop == "library-image") is becomes_backdrop


async def test_a_story_background_with_auto_attach_off_only_goes_to_the_library(
    visual, active, monkeypatch
):
    config = get_config().model_copy(deep=True)
    config.appearance.scene.auto_attach_assets = False
    monkeypatch.setattr(generation_module, "get_config", lambda: config)
    request = story_background_request()

    await visual.generate(request)
    visual.backend.release.set()
    await settle()

    assert backdrops(active) == []
    assert active.assets.backdrop is None
    assert request.asset_attachment_context.scene_backdrop is False


@pytest.mark.parametrize("first", ["earlier", "later"])
async def test_a_filled_entry_takes_the_backdrop_before_it_whichever_fills_first(
    active, first
):
    harbour, tavern = (
        NarratorMessage("The harbour lies quiet."),
        NarratorMessage("The tavern door swings open."),
    )
    active.history = [harbour, tavern]
    await active.assets.set_scene_backdrop(asset_id="dawn", record=False)
    later = AssetAttachmentContext(scene_backdrop=True)
    await active.assets.begin_generated_backdrop(later)
    earlier = AssetAttachmentContext(scene_backdrop=True, message_ids=[harbour.id])
    await active.assets.begin_generated_backdrop(earlier)

    fills = [(earlier, "harbour-dusk"), (later, "tavern")]
    for ctx, asset_id in fills if first == "earlier" else reversed(fills):
        await active.assets.finish_generated_backdrop(ctx, asset_id)

    assert backdrops(active) == [
        ("harbour-dusk", "dawn", False),
        ("tavern", "harbour-dusk", False),
    ]
    assert active.assets.backdrop == "tavern"

    await active.assets.set_scene_backdrop(asset_id="dawn")
    assert backdrops(active) == [
        ("harbour-dusk", "dawn", False),
        ("dawn", "harbour-dusk", False),
    ]


async def test_a_generated_backdrop_does_not_also_auto_promote(active, monkeypatch):
    config = get_config().model_copy(deep=True)
    config.appearance.scene.message_assets["scene_illustration"].auto_backdrop = True
    config.appearance.scene.auto_attach_assets = False
    monkeypatch.setattr(scene_assets_module, "get_config", lambda: config)
    asset = Asset(
        id="illustration",
        file_type="png",
        media_type="image/png",
        meta=AssetMeta(vis_type=VIS_TYPE.SCENE_ILLUSTRATION),
    )

    await scene_assets_module._handle_asset_saved(
        AssetSavedPayload(
            asset=asset,
            new_asset=True,
            asset_attachment_context=AssetAttachmentContext(scene_backdrop=True),
        )
    )

    assert active.assets.backdrop is None


async def test_a_backdrop_entry_leaves_the_world_snapshot_inputs_unchanged(active):
    harbour, tavern = (
        NarratorMessage("The harbour lies quiet."),
        NarratorMessage("The tavern door swings open."),
    )
    active.history = [harbour, tavern]
    provenance = SnapshotProvenance.capture(active)

    await active.assets.begin_generated_backdrop(
        AssetAttachmentContext(scene_backdrop=True, message_ids=[harbour.id])
    )
    await active.assets.set_scene_backdrop(asset_id="tavern")

    assert [m.typ for m in active.history].count("scene_backdrop") == 2
    assert provenance.matches(active)
    assert SnapshotProvenance.capture(active).source_message_id == tavern.id
