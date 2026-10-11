"""Deleting an asset that other places point to: each place is either cleaned,
or left as it is because nothing breaks."""

import json
import os

import pytest

import talemate.instance as instance
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.nodes import SelectBackend
from talemate.agents.visual.schema import GEN_TYPE, GenerationRequest, VIS_TYPE
from talemate.character import Character
from talemate.context import active_scene
from talemate.scene_assets import AssetMeta
from talemate.scene_message import CharacterMessage, SceneBackdropMessage
from talemate.tale_mate import Scene

from _node_test_helpers import run_node


@pytest.fixture
def active(scene, monkeypatch, tmp_path):
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    token = active_scene.set(scene)
    yield scene
    active_scene.reset(token)


async def add_asset(scene, data: bytes, **meta) -> str:
    asset = await scene.assets.add_asset(
        data, "png", "image/png", meta=AssetMeta(**meta)
    )
    return asset.id


def stored_library(scene) -> dict:
    with open(os.path.join(scene.assets.asset_directory, "library.json")) as f:
        return json.load(f)["assets"]


async def test_other_assets_drop_the_deleted_reference(active):
    reference = await add_asset(active, b"ref")
    kept = await add_asset(active, b"kept")
    generated = await add_asset(active, b"gen", reference_assets=[reference, kept])

    active.assets.remove_asset(reference)

    assert active.assets.get_asset(generated).meta.reference_assets == [kept]
    assert stored_library(active)[generated]["meta"]["reference_assets"] == [kept]


async def test_a_marked_reference_leaves_the_reference_search(active):
    marked = await add_asset(
        active,
        b"portrait",
        vis_type=VIS_TYPE.CHARACTER_PORTRAIT,
        reference=[VIS_TYPE.CHARACTER_PORTRAIT],
    )

    active.assets.remove_asset(marked)

    assert (
        active.assets.search_assets(reference_vis_types=[VIS_TYPE.CHARACTER_PORTRAIT])
        == []
    )


async def test_a_message_image_is_cleared(active):
    image = await add_asset(active, b"img", vis_type=VIS_TYPE.SCENE_ILLUSTRATION)
    message = CharacterMessage(
        "Alice: hi", asset_id=image, asset_type="scene_illustration"
    )
    active.history = [message]

    active.assets.remove_asset(image)

    assert message.asset_id is None
    assert message.asset_type is None


@pytest.mark.parametrize(
    "field", ["avatar", "current_avatar", "cover_image"], ids=lambda f: f
)
async def test_a_character_image_is_cleared(active, field):
    image = await add_asset(active, b"img", vis_type=VIS_TYPE.CHARACTER_PORTRAIT)
    character = Character(name="Alice", **{field: image})
    active.character_data["Alice"] = character

    active.assets.remove_asset(image)

    assert getattr(character, field) is None


@pytest.mark.parametrize("field", ["cover_image", "backdrop"], ids=lambda f: f)
async def test_a_scene_image_is_cleared(active, field):
    image = await add_asset(active, b"img", vis_type=VIS_TYPE.SCENE_BACKGROUND)
    setattr(active.assets, field, image)

    active.assets.remove_asset(image)

    assert getattr(active.assets, field) is None


async def test_a_backdrop_entry_keeps_its_record_and_rollback_skips_it(active):
    day, night = [
        await add_asset(active, bytes([i]), vis_type=VIS_TYPE.SCENE_BACKGROUND)
        for i in range(2)
    ]
    first = SceneBackdropMessage(backdrop=day, previous_backdrop=None)
    second = SceneBackdropMessage(backdrop=night, previous_backdrop=day)
    active.history = [first, second]
    active.assets.backdrop = night

    active.assets.remove_asset(day)

    # the entry still records the change; the frontend reads it as "Image removed"
    assert first.backdrop == day
    assert second.previous_backdrop == day
    await active.assets.delete_backdrop_message(second)
    assert active.assets.backdrop is None


@pytest.fixture
def visual_agent(monkeypatch):
    agent = VisualAgent()
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda self: True))
    monkeypatch.setattr(VisualAgent, "can_edit_images", property(lambda self: True))
    return agent


async def test_a_request_drops_missing_references(active, visual_agent):
    kept = await add_asset(active, b"kept")
    request = GenerationRequest(
        gen_type=GEN_TYPE.IMAGE_EDIT, reference_assets=["deleted", kept]
    )

    visual_agent._drop_missing_references(request)

    assert request.reference_assets == [kept]
    assert request.gen_type == GEN_TYPE.IMAGE_EDIT


async def test_an_edit_without_any_remaining_reference_generates_from_text(
    active, visual_agent
):
    request = GenerationRequest(
        gen_type=GEN_TYPE.IMAGE_EDIT, reference_assets=["deleted"]
    )

    visual_agent._drop_missing_references(request)

    assert request.reference_assets == []
    assert request.gen_type == GEN_TYPE.TEXT_TO_IMAGE


async def test_backend_selection_ignores_missing_references(active, visual_agent):
    instance.AGENTS["visual"] = visual_agent
    try:
        outputs = await run_node(
            SelectBackend(),
            scene=active,
            inputs={
                "vis_type": VIS_TYPE.SCENE_ILLUSTRATION.value,
                "reference_assets": ["deleted"],
            },
        )
    finally:
        instance.AGENTS.pop("visual", None)

    assert outputs["gen_type"] == GEN_TYPE.TEXT_TO_IMAGE
    assert outputs["reference_assets"] == []


async def test_asset_uses_lists_every_place_that_shows_the_asset(active):
    image = await add_asset(active, b"img", vis_type=VIS_TYPE.SCENE_ILLUSTRATION)
    shown = CharacterMessage("Alice: hi", asset_id=image, asset_type="avatar")
    other = CharacterMessage("Alice: bye")
    entry = SceneBackdropMessage(backdrop=image)
    follower = SceneBackdropMessage(backdrop=None, previous_backdrop=image)
    active.history = [shown, other, entry, follower]
    active.character_data["Alice"] = Character(
        name="Alice", avatar=image, current_avatar=image, cover_image=image
    )
    active.assets.backdrop = image
    active.assets.cover_image = image

    uses = active.assets.asset_uses(image)

    assert uses.message_ids == [shown.id]
    assert uses.backdrop_entry_ids == [entry.id]
    assert uses.previous_backdrop_entry_ids == [follower.id]
    assert uses.scene_backdrop and uses.scene_cover
    assert uses.default_avatar_of == uses.current_avatar_of == ["Alice"]
    assert uses.cover_of == ["Alice"]
    assert uses.reasons(besides_message_id=shown.id) == [
        "Character's default avatar",
        "Character's current avatar",
        "Character's cover image",
        "Scene cover image",
        "Scene backdrop",
    ]
    assert active.assets.asset_uses("unused").reasons(besides_message_id=1) == []


async def test_asset_uses_lists_reference_roles(active):
    image = await add_asset(
        active,
        b"marked",
        vis_type=VIS_TYPE.CHARACTER_PORTRAIT,
        reference=[VIS_TYPE.CHARACTER_PORTRAIT],
    )
    derived = await add_asset(active, b"derived", reference_assets=[image])

    uses = active.assets.asset_uses(image)

    assert uses.marked_reference
    assert uses.reference_of == [derived]
    assert uses.reasons() == ["Marked as reference", "Reference for other images"]
    assert uses.reasons(besides_asset_id=derived) == ["Marked as reference"]
