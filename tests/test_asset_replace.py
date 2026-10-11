"""Regenerate (replace) and Edit (replace): the new image takes the old one's
place, and the old image is deleted only when nothing else shows it."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import talemate.agents.visual.generation as generation_module
import talemate.scene_assets as scene_assets_module
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.schema import (
    VIS_TYPE,
    AssetAttachmentContext,
    GenerationRequest,
)
from talemate.character import Character
from talemate.context import active_scene
from talemate.scene_assets import AssetMeta, BackdropEntryTarget, MessageTarget
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    SceneBackdropMessage,
)
from talemate.server.scene_assets import SceneAssetsPlugin
from talemate.tale_mate import Scene


@pytest.fixture
def active(scene, monkeypatch, tmp_path):
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    scene.active = True
    token = active_scene.set(scene)
    yield scene
    active_scene.reset(token)


@pytest.fixture
def statuses(monkeypatch):
    sent = []

    def record(typ, *args, **kwargs):
        if typ == "status":
            sent.append(kwargs.get("message"))

    monkeypatch.setattr(scene_assets_module, "emit", record)
    return sent


async def add_asset(scene, data: bytes, vis_type=VIS_TYPE.SCENE_BACKGROUND, **meta):
    asset = await scene.assets.add_asset(
        data, "png", "image/png", meta=AssetMeta(vis_type=vis_type, **meta)
    )
    return asset.id


async def change_backdrop(scene, asset_id) -> SceneBackdropMessage:
    scene.history.append(NarratorMessage(f"The scene turns to {asset_id}."))
    await scene.assets.set_scene_backdrop(asset_id=asset_id)
    return next(
        m for m in reversed(scene.history) if isinstance(m, SceneBackdropMessage)
    )


def entries(scene) -> list[str]:
    return [m.backdrop for m in scene.history if isinstance(m, SceneBackdropMessage)]


# Backdrop entries (A)


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
        return await active.assets.add_asset(
            b"regenerated",
            "png",
            "image/png",
            meta=AssetMeta(vis_type=VIS_TYPE.SCENE_BACKGROUND),
        )

    monkeypatch.setattr(agent, "finalize_prompt_request", no_finalize)
    monkeypatch.setattr(agent, "emit_status", no_status)
    monkeypatch.setattr(active.assets, "add_asset_from_generation_response", save)
    return agent


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


def replace_request(entry: SceneBackdropMessage) -> GenerationRequest:
    """What Regenerate (replace) on a Backdrop entry's image sends."""
    return GenerationRequest(
        vis_type=VIS_TYPE.SCENE_BACKGROUND,
        asset_attachment_context=AssetAttachmentContext(
            message_ids=[entry.id],
            allow_auto_attach=True,
            allow_override=True,
            delete_old=True,
        ),
    )


async def test_replacing_the_current_entry_swaps_its_image_and_deletes_the_old(
    visual, active
):
    dusk = await add_asset(active, b"dusk")
    day = await add_asset(active, b"day")
    await change_backdrop(active, dusk)
    latest = await change_backdrop(active, day)

    await visual.generate(replace_request(latest))
    visual.backend.release.set()
    await settle()

    new = latest.backdrop
    assert new not in (day, dusk)
    assert entries(active) == [dusk, new]
    assert active.assets.backdrop == new
    assert not active.assets.validate_asset_id(day)


async def test_replacing_an_older_entry_keeps_the_current_backdrop(visual, active):
    dusk = await add_asset(active, b"dusk")
    day = await add_asset(active, b"day")
    older = await change_backdrop(active, dusk)
    latest = await change_backdrop(active, day)

    await visual.generate(replace_request(older))
    visual.backend.release.set()
    await settle()

    new = older.backdrop
    assert entries(active) == [new, day]
    assert latest.previous_backdrop == new
    assert active.assets.backdrop == day
    assert not active.assets.validate_asset_id(dusk)


async def test_a_shared_background_moves_every_entry_to_the_new_image(visual, active):
    dawn = await add_asset(active, b"dawn")
    dusk = await add_asset(active, b"dusk")
    first = await change_backdrop(active, dawn)
    middle = await change_backdrop(active, dusk)
    revisit = await change_backdrop(active, dawn)

    await visual.generate(replace_request(first))
    visual.backend.release.set()
    await settle()

    new = first.backdrop
    assert entries(active) == [new, dusk, new]
    assert middle.previous_backdrop == new
    assert revisit.previous_backdrop == dusk
    assert active.assets.backdrop == new
    assert not active.assets.validate_asset_id(dawn)


async def test_a_background_also_shown_elsewhere_is_kept(visual, active, statuses):
    dawn = await add_asset(active, b"dawn")
    entry = await change_backdrop(active, dawn)
    active.assets.cover_image = dawn

    await visual.generate(replace_request(entry))
    visual.backend.release.set()
    await settle()

    assert entry.backdrop != dawn
    assert active.assets.backdrop == entry.backdrop
    assert active.assets.validate_asset_id(dawn)
    assert active.assets.cover_image == dawn
    assert statuses == ["Kept the original image: Scene cover image"]


@pytest.mark.parametrize("outcome", ["error", "cancel"])
async def test_a_failed_or_cancelled_replace_keeps_the_old_image(
    visual, active, outcome
):
    day = await add_asset(active, b"day")
    latest = await change_backdrop(active, day)

    await visual.generate(replace_request(latest))
    if outcome == "error":
        visual.backend.error = ValueError("backend refused")
        visual.backend.release.set()
    else:
        await visual.cancel_generation()
    await settle()

    assert entries(active) == [day]
    assert active.assets.backdrop == day
    assert active.assets.validate_asset_id(day)


async def test_a_replace_whose_entry_was_removed_fills_its_own_entry(visual, active):
    day = await add_asset(active, b"day")
    latest = await change_backdrop(active, day)

    await visual.generate(replace_request(latest))
    active.delete_message(latest.id)
    visual.backend.release.set()
    await settle()

    assert len(entries(active)) == 1
    assert entries(active)[0] != day
    assert active.assets.validate_asset_id(day)


# Message images: portraits (B) and illustrations


async def portrait(scene, data: bytes) -> str:
    return await add_asset(
        scene, data, VIS_TYPE.CHARACTER_PORTRAIT, character_name="Edwin"
    )


@pytest.fixture
def edwin(active):
    character = Character(name="Edwin")
    active.character_data["Edwin"] = character
    return character


async def test_replacing_a_single_use_portrait_deletes_it(active, edwin):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert message.asset_id == new
    assert result.deleted_asset_id == old
    assert not active.assets.validate_asset_id(old)


async def test_replacing_a_portrait_another_message_shows_keeps_it(
    active, edwin, statuses
):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    other = CharacterMessage("Edwin: bye", asset_id=old, asset_type="avatar")
    active.history = [message, other]

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert message.asset_id == new
    assert other.asset_id == old
    assert result.kept_reason == "Used by other messages"
    assert active.assets.validate_asset_id(old)
    assert statuses == ["Kept the original image: Used by other messages"]


@pytest.mark.parametrize(
    "field, reason",
    [
        ("avatar", "Character's default avatar"),
        ("current_avatar", "Character's current avatar"),
        ("cover_image", "Character's cover image"),
    ],
)
async def test_replacing_a_portrait_the_character_uses_keeps_it(
    active, edwin, field, reason
):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    setattr(edwin, field, old)
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert result.kept_reason == reason
    assert getattr(edwin, field) == old
    assert active.assets.validate_asset_id(old)


async def test_smart_attach_with_delete_old_replaces_through_the_same_check(
    active, edwin
):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    edwin.current_avatar = old
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]

    await active.assets.smart_attach_asset(
        new, allow_override=True, delete_old=True, message_ids=[message.id]
    )

    assert message.asset_id == new
    assert edwin.current_avatar == old
    assert active.assets.validate_asset_id(old)


async def test_replacing_a_shared_illustration_keeps_it(active):
    old = await add_asset(active, b"old", VIS_TYPE.SCENE_ILLUSTRATION)
    new = await add_asset(active, b"new", VIS_TYPE.SCENE_ILLUSTRATION)
    message = NarratorMessage(
        "A harbour.", asset_id=old, asset_type="scene_illustration"
    )
    other = NarratorMessage(
        "The harbour.", asset_id=old, asset_type="scene_illustration"
    )
    active.history = [message, other]

    await active.assets.smart_attach_asset(
        new, allow_override=True, delete_old=True, message_ids=[message.id]
    )

    assert other.asset_id == old
    assert active.assets.validate_asset_id(old)


async def test_without_replace_the_old_image_stays(active):
    dusk = await add_asset(active, b"dusk")
    day = await add_asset(active, b"day")
    entry = await change_backdrop(active, dusk)

    result = await active.assets.set_asset(
        BackdropEntryTarget(message_id=entry.id), day
    )

    assert result.deleted_asset_id is None and result.kept_reason is None
    assert active.assets.validate_asset_id(dusk)


async def test_the_uses_action_names_why_a_portrait_cannot_be_replaced(active, edwin):
    old = await portrait(active, b"old")
    edwin.current_avatar = old
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    handler = SimpleNamespace(scene=active, queue_put=Mock())

    await SceneAssetsPlugin(handler).handle_asset_uses(
        {"asset_id": old, "message_id": message.id}
    )

    handler.queue_put.assert_called_once_with(
        {
            "type": "asset_uses",
            "asset_id": old,
            "message_id": message.id,
            "reasons": ["Character's current avatar"],
        }
    )


async def test_replacing_a_background_on_a_story_message_adds_an_entry_at_the_end(
    visual, active
):
    dawn = await add_asset(active, b"dawn")
    day = await add_asset(active, b"day")
    story = NarratorMessage(
        "The harbour at dawn.", asset_id=dawn, asset_type="scene_illustration"
    )
    active.history.append(story)
    latest = await change_backdrop(active, day)
    active.history.append(NarratorMessage("Noon passes."))
    request = replace_request(latest)
    request.asset_attachment_context.message_ids = [story.id]

    await visual.generate(request)
    visual.backend.release.set()
    await settle()

    assert active.history[0] is story and story.asset_id == dawn
    new = active.history[-1].backdrop
    assert entries(active) == [day, new]
    assert active.history[-1].previous_backdrop == day
    assert latest.previous_backdrop is None
    assert active.assets.backdrop == new
    assert active.assets.validate_asset_id(dawn) and active.assets.validate_asset_id(
        day
    )


# Uses besides the scene's history and characters


async def test_an_image_shown_in_director_chat_is_still_replaced(active, edwin):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    # the chat is a log: a deleted image there reads Image removed
    active.agent_state["director"] = {
        "chats": {"c1": {"messages": [{"type": "asset_view", "asset_id": old}]}}
    }

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert result.deleted_asset_id == old
    assert not active.assets.validate_asset_id(old)


async def test_a_marked_reference_is_kept(active, edwin):
    old = await add_asset(
        active,
        b"old",
        VIS_TYPE.CHARACTER_PORTRAIT,
        character_name="Edwin",
        reference=[VIS_TYPE.CHARACTER_PORTRAIT],
    )
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert result.kept_reason == "Marked as reference"
    assert active.assets.search_assets(
        reference_vis_types=[VIS_TYPE.CHARACTER_PORTRAIT]
    ) == [old]


async def test_a_reference_of_another_image_is_kept(active, edwin):
    old = await portrait(active, b"old")
    derived = await add_asset(
        active,
        b"derived",
        VIS_TYPE.CHARACTER_PORTRAIT,
        character_name="Edwin",
        reference_assets=[old],
    )
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert result.kept_reason == "Reference for other images"
    assert active.assets.get_asset(derived).meta.reference_assets == [old]


async def test_an_edit_made_from_the_image_does_not_keep_it(active, edwin):
    old = await portrait(active, b"old")
    edited = await add_asset(
        active,
        b"edited",
        VIS_TYPE.CHARACTER_PORTRAIT,
        character_name="Edwin",
        reference_assets=[old],
    )
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), edited, replace=True
    )

    assert result.deleted_asset_id == old
    assert active.assets.get_asset(edited).meta.reference_assets == []


@pytest.fixture
def project(active, tmp_path):
    active.project_name = "vester"
    active.filename = "vester.json"
    return tmp_path / "vester"


async def test_an_image_another_save_of_the_project_uses_is_kept(
    active, edwin, project
):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    (project / "vester.json").write_text(f'{{"asset_id": "{old}"}}')
    (project / "vester-fork.json").write_text(f'{{"asset_id": "{old}"}}')

    uses = active.assets.asset_uses(old)
    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert uses.other_saves == ["vester-fork.json"]
    assert result.kept_reason == "Used by another save of this scene"
    assert active.assets.validate_asset_id(old)


async def test_the_scene_s_own_save_does_not_keep_an_image(active, edwin, project):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    (project / "vester.json").write_text(f'{{"asset_id": "{old}"}}')

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert result.deleted_asset_id == old


async def test_a_locked_scene_s_own_save_keeps_an_image(active, edwin, project):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    active.immutable_save = True
    (project / "vester.json").write_text(f'{{"asset_id": "{old}"}}')

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert result.kept_reason == "Used by another save of this scene"
    assert active.assets.validate_asset_id(old)


async def test_a_save_that_cannot_be_read_keeps_an_image(active, edwin, project):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    (project / "vester-checkpoint.json").write_bytes(b"\xff\xfe not utf-8")

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert active.assets.asset_uses(old).other_saves == ["vester-checkpoint.json"]
    assert result.kept_reason == "Used by another save of this scene"
    assert active.assets.validate_asset_id(old)


async def test_a_save_that_raises_on_open_keeps_an_image(active, edwin, project):
    old = await portrait(active, b"old")
    new = await portrait(active, b"new")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    # a dangling link: opening it raises FileNotFoundError, an OSError
    (project / "vester-gone.json").symlink_to(project / "missing.json")

    result = await active.assets.set_asset(
        MessageTarget(message_id=message.id), new, replace=True
    )

    assert result.kept_reason == "Used by another save of this scene"
    assert active.assets.validate_asset_id(old)


async def test_the_uses_action_names_another_save_of_the_scene(active, edwin, project):
    old = await portrait(active, b"old")
    message = CharacterMessage("Edwin: hi", asset_id=old, asset_type="avatar")
    active.history = [message]
    (project / "vester-fork.json").write_text(f'{{"asset_id": "{old}"}}')
    handler = SimpleNamespace(scene=active, queue_put=Mock())

    await SceneAssetsPlugin(handler).handle_asset_uses(
        {"asset_id": old, "message_id": message.id}
    )

    handler.queue_put.assert_called_once_with(
        {
            "type": "asset_uses",
            "asset_id": old,
            "message_id": message.id,
            "reasons": ["Used by another save of this scene"],
        }
    )


async def test_other_saves_are_not_read_when_the_scene_already_keeps_it(
    active, edwin, project, monkeypatch
):
    old = await portrait(active, b"old")
    edwin.current_avatar = old

    def unexpected(asset_id):
        raise AssertionError("read the project's saves")

    monkeypatch.setattr(active.assets, "_other_saves_using", unexpected)

    assert active.assets.replace_blockers(old) == ["Character's current avatar"]


# A history edit that holds a message out of the history


@pytest.mark.parametrize("shared", [True, False])
async def test_the_delete_check_waits_for_a_history_edit(active, shared):
    old = await add_asset(active, b"old", VIS_TYPE.SCENE_ILLUSTRATION)
    new = await add_asset(active, b"new", VIS_TYPE.SCENE_ILLUSTRATION)
    first = NarratorMessage("A harbour.", asset_id=old, asset_type="scene_illustration")
    last = NarratorMessage(
        "The harbour.",
        asset_id=old if shared else None,
        asset_type="scene_illustration" if shared else None,
    )
    active.history = [first, last]

    async with active.assets.backdrops_lifted():
        active.history.pop()
        result = await active.assets.set_asset(
            MessageTarget(message_id=first.id), new, replace=True
        )
        assert first.asset_id == new
        assert active.assets.validate_asset_id(old)
        active.history.append(last)

    assert active.assets.validate_asset_id(old) == shared
    assert result.kept_reason == ("Used by other messages" if shared else None)
    assert result.deleted_asset_id == (None if shared else old)


async def test_held_replaces_of_one_image_delete_it_once_and_run_the_rest(active):
    old = await add_asset(active, b"old", VIS_TYPE.SCENE_ILLUSTRATION)
    other = await add_asset(active, b"other", VIS_TYPE.SCENE_ILLUSTRATION)
    first, second, third = [
        await add_asset(active, bytes([i]), VIS_TYPE.SCENE_ILLUSTRATION)
        for i in range(3)
    ]
    a = NarratorMessage("A.", asset_id=old, asset_type="scene_illustration")
    b = NarratorMessage("B.", asset_id=old, asset_type="scene_illustration")
    c = NarratorMessage("C.", asset_id=other, asset_type="scene_illustration")
    active.history = [a, b, c]

    async with active.assets.backdrops_lifted():
        results = [
            await active.assets.set_asset(
                MessageTarget(message_id=message.id), new, replace=True
            )
            for message, new in [(a, first), (b, second), (c, third)]
        ]

    assert [m.asset_id for m in (a, b, c)] == [first, second, third]
    assert [r.deleted_asset_id for r in results] == [old, None, other]
    assert not active.assets.validate_asset_id(old)
    assert not active.assets.validate_asset_id(other)


async def test_a_held_backdrop_replace_whose_original_is_gone_still_moves_history(
    active,
):
    dawn = await add_asset(active, b"dawn")
    dusk = await add_asset(active, b"dusk")
    new = await add_asset(active, b"new")
    first = await change_backdrop(active, dawn)
    middle = await change_backdrop(active, dusk)
    revisit = await change_backdrop(active, dawn)

    async with active.assets.backdrops_lifted():
        result = await active.assets.set_asset(
            BackdropEntryTarget(message_id=first.id), new, replace=True
        )
        active.assets.remove_asset(dawn)

    assert entries(active) == [new, dusk, new]
    assert middle.previous_backdrop == new
    assert revisit.previous_backdrop == dusk
    # the delete itself cleared the live backdrop that showed dawn
    assert active.assets.backdrop is None
    assert result.deleted_asset_id is None and result.kept_reason is None
