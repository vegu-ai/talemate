"""Tests for world_state handling in changelog reconstruction (issue #296).

Covers:
- pins / reinforce / character_name_mappings are tracked in deltas and
  reconstruct at their true per-revision values
- the derived subtrees (characters / items / location) stay excluded from
  deltas and are overlaid from the latest snapshot during reconstruction
- chains written before the long-lived subtrees were tracked do not
  false-positive chain divergence
- fork carries rev-N long-lived world state + current derived world state
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest

from _changelog_test_helpers import make_changelog_scene
from talemate.changelog import (
    _get_latest_changelog_file,
    _latest_path,
    append_scene_delta,
    check_chain_divergence,
    fork_scene_at_revision,
    reconstruct_scene_data,
    save_changelog,
)


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _serialize(
    *,
    pins=None,
    reinforce=None,
    name_mappings=None,
    characters=None,
    items=None,
    location=None,
    intro="intro",
):
    return {
        "history": [],
        "intro": intro,
        "world_state": {
            "pins": pins if pins is not None else {},
            "reinforce": reinforce if reinforce is not None else [],
            "character_name_mappings": (
                name_mappings if name_mappings is not None else {}
            ),
            "characters": characters if characters is not None else {},
            "items": items if items is not None else {},
            "location": location,
        },
    }


def _delta_paths(delta: dict) -> list[str]:
    paths = []
    for delta_type in (
        "values_changed",
        "iterable_item_added",
        "iterable_item_removed",
        "dictionary_item_added",
        "dictionary_item_removed",
        "type_changes",
    ):
        if delta_type in delta:
            paths.extend(str(p) for p in delta[delta_type].keys())
    return paths


@pytest.mark.asyncio
async def test_long_lived_world_state_tracked_in_deltas(temp_dir):
    """pins / reinforce / character_name_mappings changes are recorded."""
    scene = make_changelog_scene(temp_dir, initial_serialize=_serialize())
    await save_changelog(scene)

    scene.serialize = _serialize(
        pins={"pin-1": {"text": "remember this", "active": True}},
        reinforce=[{"id": 1, "question": "q", "answer": "a"}],
        name_mappings={"alice": ["al"]},
    )
    rev = await append_scene_delta(scene, {"action": "ws_change"})
    assert rev == 1

    _, log_path = _get_latest_changelog_file(scene)
    with open(log_path) as f:
        delta = json.load(f)["deltas"][0]["delta"]

    paths = _delta_paths(delta)
    assert any("world_state']['pins']" in p for p in paths)
    assert any("world_state']['reinforce']" in p for p in paths)
    assert any("world_state']['character_name_mappings']" in p for p in paths)


@pytest.mark.asyncio
async def test_long_lived_world_state_reconstructs_per_revision(temp_dir):
    """Reconstruction at rev N returns rev-N values for the tracked subtrees."""
    scene = make_changelog_scene(temp_dir, initial_serialize=_serialize())
    await save_changelog(scene)

    scene.serialize = _serialize(pins={"pin-1": {"text": "v1", "active": True}})
    assert await append_scene_delta(scene) == 1

    scene.serialize = _serialize(
        pins={"pin-1": {"text": "v2", "active": True}},
        reinforce=[{"id": 1, "question": "q", "answer": "a"}],
    )
    assert await append_scene_delta(scene) == 2

    rev2 = await reconstruct_scene_data(scene, to_rev=2)
    assert rev2["world_state"]["pins"] == {"pin-1": {"text": "v2", "active": True}}
    assert rev2["world_state"]["reinforce"] == [
        {"id": 1, "question": "q", "answer": "a"}
    ]

    rev1 = await reconstruct_scene_data(scene, to_rev=1)
    assert rev1["world_state"]["pins"] == {"pin-1": {"text": "v1", "active": True}}
    assert rev1["world_state"]["reinforce"] == []

    rev0 = await reconstruct_scene_data(scene, to_rev=0)
    assert rev0["world_state"]["pins"] == {}


@pytest.mark.asyncio
async def test_derived_world_state_overlaid_from_latest_snapshot(temp_dir):
    """characters / items / location reconstruct from the latest snapshot."""
    scene = make_changelog_scene(
        temp_dir,
        initial_serialize=_serialize(
            characters={"Alice": {"snapshot": "s0"}},
            items={"Lamp": {"snapshot": "i0"}},
            location="loc0",
        ),
    )
    await save_changelog(scene)

    # derived subtrees change alongside a tracked change; the delta records
    # only the tracked one
    scene.serialize = _serialize(
        characters={"Alice": {"snapshot": "s1"}, "Bob": {"snapshot": "b1"}},
        items={},
        location="loc1",
        intro="intro v1",
    )
    assert await append_scene_delta(scene) == 1

    _, log_path = _get_latest_changelog_file(scene)
    with open(log_path) as f:
        delta = json.load(f)["deltas"][0]["delta"]
    paths = _delta_paths(delta)
    assert not any("world_state']['characters']" in p for p in paths)
    assert not any("world_state']['location']" in p for p in paths)

    for rev in (0, 1):
        reconstructed = await reconstruct_scene_data(scene, to_rev=rev)
        world_state = reconstructed["world_state"]
        assert world_state["characters"] == {
            "Alice": {"snapshot": "s1"},
            "Bob": {"snapshot": "b1"},
        }
        assert world_state["items"] == {}
        assert world_state["location"] == "loc1"


@pytest.mark.asyncio
async def test_overlay_noop_without_latest_snapshot(temp_dir):
    """Without a readable latest snapshot the base values stand."""
    scene = make_changelog_scene(
        temp_dir,
        initial_serialize=_serialize(
            characters={"Alice": {"snapshot": "s0"}}, location="loc0"
        ),
    )
    await save_changelog(scene)
    os.remove(_latest_path(scene))

    reconstructed = await reconstruct_scene_data(scene, to_rev=0)
    assert reconstructed["world_state"]["characters"] == {"Alice": {"snapshot": "s0"}}
    assert reconstructed["world_state"]["location"] == "loc0"


@pytest.mark.asyncio
async def test_legacy_chain_does_not_report_divergence(temp_dir):
    """A chain whose long-lived world state was never recorded stays healthy.

    Simulates a pre-tracking chain by hand-writing base / delta / latest
    artifacts where the latest snapshot's pins changed without a delta ever
    recording it.
    """
    scene = make_changelog_scene(temp_dir, initial_serialize=_serialize())
    await save_changelog(scene)

    # rev 1 records a tracked change only (as a pre-tracking chain would)
    scene.serialize = _serialize(intro="intro v1")
    assert await append_scene_delta(scene) == 1

    # pins change without entering the chain: rewrite the latest snapshot
    with open(_latest_path(scene)) as f:
        latest = json.load(f)
    latest["world_state"]["pins"] = {"pin-1": {"text": "v1", "active": True}}
    with open(_latest_path(scene), "w") as f:
        json.dump(latest, f)

    assert await check_chain_divergence(scene) == []

    # sanity: an actual unrecorded difference outside the masked paths is
    # still reported
    latest["intro"] = "tampered"
    with open(_latest_path(scene), "w") as f:
        json.dump(latest, f)
    divergent = await check_chain_divergence(scene)
    assert divergent
    assert any("intro" in p for p in divergent)


@pytest.mark.asyncio
async def test_mixed_legacy_chain_reconstructs_full_subtrees(temp_dir):
    """Legacy drift + a post-tracking save must reconstruct completely.

    A chain created before the long-lived subtrees were tracked carries
    their drift only in the latest snapshot. The first post-tracking delta
    must therefore record the full subtree, not an increment against the
    unreconstructable base — otherwise reconstruction at the new revision
    silently drops the pre-existing values.
    """
    scene = make_changelog_scene(temp_dir, initial_serialize=_serialize())
    await save_changelog(scene)

    # pre-tracking drift: pin "old" exists in the latest snapshot but was
    # never recorded in a delta
    with open(_latest_path(scene)) as f:
        latest = json.load(f)
    latest["world_state"]["pins"] = {"old": {"text": "legacy", "active": True}}
    with open(_latest_path(scene), "w") as f:
        json.dump(latest, f)

    # post-tracking save adds pin "new"
    scene.serialize = _serialize(
        pins={
            "old": {"text": "legacy", "active": True},
            "new": {"text": "fresh", "active": True},
        }
    )
    assert await append_scene_delta(scene) == 1

    # the delta carries the full subtree, not just the increment
    _, log_path = _get_latest_changelog_file(scene)
    with open(log_path) as f:
        delta = json.load(f)["deltas"][0]["delta"]
    full_op = delta.get("values_changed", {}).get("root['world_state']['pins']")
    assert full_op is not None
    assert set(full_op["new_value"]) == {"old", "new"}
    assert not any(
        "pins']['new']" in p or "pins']['old']" in p for p in _delta_paths(delta)
    )

    # reconstruction at the new revision contains both pins
    reconstructed = await reconstruct_scene_data(scene, to_rev=1)
    assert set(reconstructed["world_state"]["pins"]) == {"old", "new"}

    # and the chain verifies clean without any masking
    assert await check_chain_divergence(scene) == []


@pytest.mark.asyncio
async def test_partially_upgraded_legacy_chain_records_all_subtrees(temp_dir):
    """A post-tracking save touching one subtree records all three.

    Legacy drift in ``reinforce``/``character_name_mappings`` with a
    post-tracking save that only touches ``pins``: the delta must carry
    full-subtree ops for all three, so the chain becomes self-sufficient
    at once and the divergence check's all-or-nothing unmask cannot
    false-positive on the subtrees the save did not touch.
    """
    scene = make_changelog_scene(temp_dir, initial_serialize=_serialize())
    await save_changelog(scene)

    # pre-tracking drift in reinforce and character_name_mappings only
    with open(_latest_path(scene)) as f:
        latest = json.load(f)
    latest["world_state"]["reinforce"] = [
        {"id": 1, "question": "legacy q", "answer": "legacy a"}
    ]
    latest["world_state"]["character_name_mappings"] = {"alice": ["al"]}
    with open(_latest_path(scene), "w") as f:
        json.dump(latest, f)

    # post-tracking save touches only pins
    scene.serialize = _serialize(
        pins={"pin-1": {"text": "v1", "active": True}},
        reinforce=[{"id": 1, "question": "legacy q", "answer": "legacy a"}],
        name_mappings={"alice": ["al"]},
    )
    assert await append_scene_delta(scene) == 1

    _, log_path = _get_latest_changelog_file(scene)
    with open(log_path) as f:
        delta = json.load(f)["deltas"][0]["delta"]
    values_changed = delta.get("values_changed", {})
    assert set(
        values_changed.get("root['world_state']['pins']", {}).get("new_value", {})
    ) == {"pin-1"}
    assert values_changed.get("root['world_state']['reinforce']", {}).get(
        "new_value"
    ) == [{"id": 1, "question": "legacy q", "answer": "legacy a"}]
    assert values_changed.get("root['world_state']['character_name_mappings']", {}).get(
        "new_value"
    ) == {"alice": ["al"]}

    # the healthy chain does not report divergence on the untouched subtrees
    assert await check_chain_divergence(scene) == []

    # and reconstruction (e.g. a fork) at the new revision carries the
    # drifted values, not the base's
    reconstructed = await reconstruct_scene_data(scene, to_rev=1)
    assert reconstructed["world_state"]["reinforce"] == [
        {"id": 1, "question": "legacy q", "answer": "legacy a"}
    ]
    assert reconstructed["world_state"]["character_name_mappings"] == {"alice": ["al"]}


@pytest.mark.asyncio
async def test_divergence_detected_once_chain_records_world_state(temp_dir):
    """Once a delta records the long-lived subtrees, the divergence check
    no longer masks them — post-write drift is reported."""
    scene = make_changelog_scene(temp_dir, initial_serialize=_serialize())
    await save_changelog(scene)

    scene.serialize = _serialize(pins={"pin-1": {"text": "v1", "active": True}})
    assert await append_scene_delta(scene) == 1
    assert await check_chain_divergence(scene) == []

    with open(_latest_path(scene)) as f:
        latest = json.load(f)
    latest["world_state"]["pins"] = {}
    with open(_latest_path(scene), "w") as f:
        json.dump(latest, f)

    divergent = await check_chain_divergence(scene)
    assert divergent
    assert any("world_state']['pins']" in p for p in divergent)


def test_overlay_paths_match_world_state_exclusions():
    """OVERLAY_FROM_LATEST covers exactly the world_state delta exclusions."""
    from talemate.changelog import EXCLUDE_FROM_DELTAS, OVERLAY_FROM_LATEST

    assert {f"root['world_state']['{k}']" for k in OVERLAY_FROM_LATEST} == {
        p for p in EXCLUDE_FROM_DELTAS if p.startswith("root['world_state']")
    }


@pytest.mark.asyncio
async def test_fork_carries_rev_n_long_lived_and_current_derived_state(temp_dir):
    scene = make_changelog_scene(
        temp_dir,
        initial_serialize=_serialize(characters={"Alice": {"snapshot": "s0"}}),
    )
    await save_changelog(scene)

    scene.serialize = _serialize(
        characters={"Alice": {"snapshot": "s0"}},
        pins={"pin-1": {"text": "v1", "active": True}},
    )
    assert await append_scene_delta(scene) == 1

    scene.serialize = _serialize(
        characters={"Alice": {"snapshot": "s2"}},
        pins={"pin-1": {"text": "v2", "active": True}},
    )
    assert await append_scene_delta(scene) == 2

    fork_path = await fork_scene_at_revision(scene, 1, "fork-scene")
    with open(fork_path) as f:
        fork = json.load(f)

    # rev-1 long-lived state
    assert fork["world_state"]["pins"] == {"pin-1": {"text": "v1", "active": True}}
    # current derived state, not rev-0's
    assert fork["world_state"]["characters"] == {"Alice": {"snapshot": "s2"}}
