"""
Delta merge for world-state snapshots.

The world-state agent's response is interpreted as a Python-style dict
merge applied on top of the current world state: include only entities or
fields that should change, set an entity's value to ``None`` to drop it,
and omit anything that should remain unchanged.

Semantics
---------
For each bucket (characters, items, places):

- ``patch[key] is None`` → drop the entity.
- ``patch[key]`` is a dict → if the key is already in current state,
  shallow-merge the fields into the existing entity (omitted fields
  preserved); otherwise construct a fresh entity from the patch.
- Key omitted from the patch → entity is untouched.

Auto-eviction
-------------
The model can't be trusted to reliably drop entities it has stopped
caring about, so omitted keys also age out automatically. Each entity
carries a ``misses`` counter: touching it (a dict value in the patch)
resets the counter to 0; leaving it out of the patch increments it. Once
an entity has been untouched for ``eviction_threshold`` consecutive
passes it is dropped. This is invisible to the model — it never sees the
counter and is never asked to manage it. ``eviction_threshold <= 0``
disables aging (counters stay at 0), which is the default for callers
that don't opt in.

A ``TimePassageMessage`` pushed since the last snapshot's anchors is a
hard scene-cut — callers should wipe the state before showing it to the
LLM so the patch is applied against an empty baseline.

The ``location`` field (a bare string) is patched inline by the caller
in ``WorldStateSnapshotMixin.apply_snapshot_update`` — it has no bucket of
its own, so it does not flow through ``apply_bucket_patch``.
"""

import structlog
from typing import Any, Callable, TypeVar

from talemate.scene_message import SceneMessage, TimePassageMessage
from talemate.world_state.schema import CharacterState, ObjectState, PlaceState

StateT = TypeVar("StateT", CharacterState, ObjectState, PlaceState)

log = structlog.get_logger("talemate.world_state.merge")


def apply_bucket_patch(
    prior: dict[str, StateT],
    patch_data: Any,
    factory: Callable[..., StateT],
    eviction_threshold: int = 0,
) -> dict[str, StateT]:
    """
    Apply a delta dict against a prior bucket. Returns a new bucket dict;
    inputs are not mutated.

    Malformed entries (non-dict, non-None values; constructor failures)
    are logged and skipped — the rest of the patch still applies.

    When ``eviction_threshold > 0``, entities left untouched by the patch
    have their ``misses`` counter incremented and are dropped once it
    reaches the threshold; touched entities reset to 0. The ``misses``
    field is controlled entirely here — any value supplied in the patch is
    ignored. An entry whose patch raised a constructor error counts as
    untouched (it wasn't actually updated), so it ages this pass.
    """
    result: dict[str, StateT] = dict(prior)
    if not isinstance(patch_data, dict):
        patch_data = {}
    touched: set[str] = set()
    for key, value in patch_data.items():
        if value is None:
            result.pop(key, None)
            continue
        if not isinstance(value, dict):
            log.warning(
                "apply_bucket_patch: skipping non-dict entity payload",
                key=key,
                value_type=type(value).__name__,
            )
            continue
        try:
            if key in result:
                merged_fields = {**result[key].model_dump(), **value}
            else:
                merged_fields = dict(value)
            # ``misses`` is ours to manage — a touched entity is fresh.
            merged_fields["misses"] = 0
            result[key] = factory(**merged_fields)
            touched.add(key)
        except Exception as e:
            log.error(
                "apply_bucket_patch: failed to apply entry",
                key=key,
                factory=factory.__name__,
                value=value,
                error=str(e),
            )
    if eviction_threshold > 0:
        for key in list(result.keys()):
            if key in touched:
                continue
            misses = result[key].misses + 1
            if misses >= eviction_threshold:
                result.pop(key)
            else:
                result[key] = result[key].model_copy(update={"misses": misses})
    return result


def cap_bucket(bucket: dict[str, StateT], max_items: int) -> dict[str, StateT]:
    """
    Cap a bucket to at most ``max_items`` entries, dropping the stalest
    entries first — those with the highest ``misses`` count (untouched
    longest). Ties are broken by insertion order, so among equally-stale
    entries the earliest-added is dropped first. Returns a new bucket dict
    preserving the original insertion order of the kept entries.

    ``max_items <= 0`` disables the cap and returns the bucket unchanged.
    """
    if max_items <= 0 or len(bucket) <= max_items:
        return bucket
    # Ascending by misses keeps the freshest entries; the stable sort
    # preserves insertion order among ties so we keep the earliest-added.
    kept = set(sorted(bucket, key=lambda k: bucket[k].misses)[:max_items])
    return {key: value for key, value in bucket.items() if key in kept}


def has_time_passage_boundary(
    scene_history: list[SceneMessage], prior_anchor_ids: list[int]
) -> bool:
    """
    Return True when a TimePassageMessage was pushed to ``scene_history``
    after the highest of ``prior_anchor_ids``. Crossing a TimePassage is a
    hard scene-cut and invalidates the entire prior snapshot.
    """
    if not prior_anchor_ids:
        return False
    max_prior = max(prior_anchor_ids)
    for message in scene_history:
        if isinstance(message, TimePassageMessage) and message.id > max_prior:
            return True
    return False
