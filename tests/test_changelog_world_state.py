import copy

import pytest

from _changelog_test_helpers import make_changelog_scene, persist_test_mutation
from talemate.changelog import reconstruct_scene_data, save_changelog


@pytest.mark.parametrize(
    "section",
    [
        "characters",
        "items",
        "location",
        "places",
        "location_perspectives",
        "anchor_message_ids",
        "snapshot_provenance",
        "previous_snapshot",
        "pins",
        "reinforcements",
        "character_name_mappings",
    ],
)
async def test_every_world_state_section_belongs_to_its_own_revision(tmp_path, section):
    original = {
        "history": [],
        "character_data": {},
        "world_state": {section: {"value": "old"}},
    }
    scene = make_changelog_scene(
        str(tmp_path), initial_serialize=copy.deepcopy(original)
    )
    await save_changelog(scene)
    scene.serialize["world_state"][section] = {"value": "new"}
    await persist_test_mutation(scene)
    assert (await reconstruct_scene_data(scene, 0))["world_state"] == original[
        "world_state"
    ]
    assert (await reconstruct_scene_data(scene, 1))["world_state"] == scene.serialize[
        "world_state"
    ]
