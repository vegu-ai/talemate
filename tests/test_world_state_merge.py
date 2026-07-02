"""
Tests for ``talemate.world_state.merge``.

These are pure-function tests over dicts of CharacterState / ObjectState /
PlaceState. They cover the delta-merge policy (add / patch / drop / silent
carry-forward) and the TimePassage boundary helper.
"""

from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    TimePassageMessage,
)
from talemate.world_state import CharacterState, ObjectState, PlaceState
from talemate.world_state.merge import (
    apply_bucket_patch,
    has_time_passage_boundary,
)


# ---------------------------------------------------------------------------
# apply_bucket_patch — add / patch / drop
# ---------------------------------------------------------------------------


class TestApplyBucketPatchAdd:
    def test_empty_prior_accepts_new_entity(self):
        merged = apply_bucket_patch(
            {},
            {"Door": {"snapshot": "wooden", "mentions": ["the door"]}},
            ObjectState,
        )
        assert "Door" in merged
        assert merged["Door"].snapshot == "wooden"
        assert merged["Door"].mentions == ["the door"]

    def test_new_key_added_alongside_existing(self):
        prior = {"Door": ObjectState(snapshot="wooden", mentions=["door"])}
        merged = apply_bucket_patch(
            prior,
            {"Window": {"snapshot": "broken", "mentions": ["the window"]}},
            ObjectState,
        )
        assert set(merged.keys()) == {"Door", "Window"}
        assert merged["Window"].snapshot == "broken"
        # Prior entry untouched.
        assert merged["Door"].snapshot == "wooden"


class TestApplyBucketPatchUpdate:
    def test_partial_dict_patches_only_named_fields(self):
        prior = {
            "Alice": CharacterState(
                snapshot="standing calm",
                emotion="calm",
                mentions=["Alice"],
            )
        }
        merged = apply_bucket_patch(
            prior,
            {"Alice": {"emotion": "anxious"}},
            CharacterState,
        )
        assert merged["Alice"].emotion == "anxious"
        # Omitted fields preserved.
        assert merged["Alice"].snapshot == "standing calm"
        assert merged["Alice"].mentions == ["Alice"]

    def test_snapshot_can_evolve(self):
        prior = {"Locker": ObjectState(snapshot="intact, capacitor humming")}
        merged = apply_bucket_patch(
            prior,
            {"Locker": {"snapshot": "wrenched open, capacitor exposed"}},
            ObjectState,
        )
        assert merged["Locker"].snapshot == "wrenched open, capacitor exposed"

    def test_mentions_replace_when_emitted(self):
        # mentions are focus-window-specific; the new pass's list wins
        # outright (no union semantic).
        prior = {"Locker": ObjectState(mentions=["the auxiliary maintenance locker"])}
        merged = apply_bucket_patch(
            prior,
            {"Locker": {"mentions": ["the locker"]}},
            ObjectState,
        )
        assert merged["Locker"].mentions == ["the locker"]

    def test_empty_mentions_list_explicitly_clears(self):
        # Distinguish "absent key → preserve prior" from "explicit empty
        # list → clear". This locks in the contract for the case where the
        # LLM intentionally drops all canonical phrasings.
        prior = {"Locker": ObjectState(mentions=["the locker"])}
        merged = apply_bucket_patch(
            prior,
            {"Locker": {"mentions": []}},
            ObjectState,
        )
        assert merged["Locker"].mentions == []

    def test_full_dict_replaces_all_fields(self):
        prior = {"Locker": ObjectState(snapshot="prior", mentions=["the prior phrase"])}
        merged = apply_bucket_patch(
            prior,
            {
                "Locker": {
                    "snapshot": "new",
                    "mentions": ["the new phrase"],
                }
            },
            ObjectState,
        )
        assert merged["Locker"].snapshot == "new"
        assert merged["Locker"].mentions == ["the new phrase"]


class TestApplyBucketPatchDrop:
    def test_none_value_drops_entity(self):
        prior = {
            "Door": ObjectState(snapshot="wooden"),
            "Window": ObjectState(snapshot="broken"),
        }
        merged = apply_bucket_patch(prior, {"Door": None}, ObjectState)
        assert "Door" not in merged
        assert "Window" in merged

    def test_none_for_unknown_key_is_noop(self):
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(prior, {"NeverExisted": None}, ObjectState)
        assert set(merged.keys()) == {"Door"}


class TestApplyBucketPatchSilent:
    def test_omitted_keys_unchanged(self):
        # An entry not mentioned in the patch is carried forward verbatim.
        prior = {
            "Door": ObjectState(snapshot="wooden", mentions=["the door"]),
            "Window": ObjectState(snapshot="broken", mentions=["window"]),
        }
        merged = apply_bucket_patch(
            prior,
            {"Window": {"snapshot": "fixed"}},
            ObjectState,
        )
        assert merged["Door"].snapshot == "wooden"
        assert merged["Door"].mentions == ["the door"]
        assert merged["Window"].snapshot == "fixed"

    def test_empty_patch_is_full_carry_forward(self):
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(prior, {}, ObjectState)
        assert merged["Door"].snapshot == "wooden"


# ---------------------------------------------------------------------------
# apply_bucket_patch — auto-eviction (the `misses` counter)
# ---------------------------------------------------------------------------


class TestApplyBucketPatchEviction:
    def test_disabled_by_default_no_aging(self):
        # Default threshold (0) → counters never move, nothing ages out.
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(prior, {}, ObjectState)
        assert merged["Door"].snapshot == "wooden"
        assert merged["Door"].misses == 0

    def test_untouched_entry_increments_misses(self):
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(prior, {}, ObjectState, eviction_threshold=3)
        assert merged["Door"].misses == 1
        assert "Door" in merged

    def test_touched_entry_resets_misses(self):
        prior = {"Door": ObjectState(snapshot="wooden", misses=2)}
        merged = apply_bucket_patch(
            prior,
            {"Door": {"snapshot": "varnished"}},
            ObjectState,
            eviction_threshold=3,
        )
        assert merged["Door"].misses == 0
        assert merged["Door"].snapshot == "varnished"

    def test_evicts_on_reaching_threshold(self):
        # Two prior misses + one more untouched pass == threshold → dropped.
        prior = {"Door": ObjectState(snapshot="wooden", misses=2)}
        merged = apply_bucket_patch(prior, {}, ObjectState, eviction_threshold=3)
        assert "Door" not in merged

    def test_aging_walks_to_eviction_over_passes(self):
        bucket = {"Door": ObjectState(snapshot="wooden")}
        bucket = apply_bucket_patch(bucket, {}, ObjectState, eviction_threshold=2)
        assert bucket["Door"].misses == 1  # survives the first untouched pass
        bucket = apply_bucket_patch(bucket, {}, ObjectState, eviction_threshold=2)
        assert "Door" not in bucket  # evicted on the second

    def test_touching_resets_the_aging_clock(self):
        bucket = {"Door": ObjectState(snapshot="wooden")}
        bucket = apply_bucket_patch(bucket, {}, ObjectState, eviction_threshold=2)
        assert bucket["Door"].misses == 1
        bucket = apply_bucket_patch(
            bucket, {"Door": {"snapshot": "wooden"}}, ObjectState, eviction_threshold=2
        )
        assert bucket["Door"].misses == 0
        # Reset means it survives a fresh untouched pass again.
        bucket = apply_bucket_patch(bucket, {}, ObjectState, eviction_threshold=2)
        assert "Door" in bucket and bucket["Door"].misses == 1

    def test_newly_added_entry_not_aged_same_pass(self):
        # An entry added this pass counts as touched, so even threshold=1 keeps it.
        merged = apply_bucket_patch(
            {}, {"Door": {"snapshot": "new"}}, ObjectState, eviction_threshold=1
        )
        assert merged["Door"].misses == 0

    def test_patch_supplied_misses_is_ignored(self):
        # The model can't drive its own staleness counter.
        merged = apply_bucket_patch(
            {},
            {"Door": {"snapshot": "new", "misses": 99}},
            ObjectState,
            eviction_threshold=3,
        )
        assert merged["Door"].misses == 0

    def test_explicit_drop_still_honored_with_eviction_on(self):
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(
            prior, {"Door": None}, ObjectState, eviction_threshold=3
        )
        assert "Door" not in merged

    def test_mix_touched_and_aged(self):
        prior = {
            "Door": ObjectState(snapshot="wooden", misses=2),
            "Window": ObjectState(snapshot="broken"),
        }
        # Window touched (reset), Door untouched (hits threshold → dropped).
        merged = apply_bucket_patch(
            prior, {"Window": {"snapshot": "fixed"}}, ObjectState, eviction_threshold=3
        )
        assert "Door" not in merged
        assert merged["Window"].snapshot == "fixed"
        assert merged["Window"].misses == 0


# ---------------------------------------------------------------------------
# apply_bucket_patch — edge cases / robustness
# ---------------------------------------------------------------------------


class TestApplyBucketPatchRobustness:
    def test_non_dict_patch_returns_prior_unchanged(self):
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(prior, "garbage", ObjectState)
        assert merged == prior

    def test_non_dict_entity_value_is_skipped(self):
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(
            prior,
            {"Door": "not a dict", "Window": {"snapshot": "broken"}},
            ObjectState,
        )
        # Bad entry skipped; good entry still applies.
        assert merged["Door"].snapshot == "wooden"
        assert merged["Window"].snapshot == "broken"

    def test_does_not_mutate_inputs(self):
        prior = {"Door": ObjectState(snapshot="wooden")}
        apply_bucket_patch(prior, {"Door": {"snapshot": "new"}}, ObjectState)
        # Original prior entity is unchanged.
        assert prior["Door"].snapshot == "wooden"

    def test_drop_branch_does_not_mutate_inputs(self):
        # The drop branch removes the key from the returned dict but must
        # not pop it from the caller's `prior`.
        prior = {"Door": ObjectState(snapshot="wooden")}
        merged = apply_bucket_patch(prior, {"Door": None}, ObjectState)
        assert "Door" not in merged
        assert "Door" in prior

    def test_constructor_failure_skips_bad_entry(self):
        # Pass an explicitly invalid type for a typed field; the bad entry
        # is dropped from the result while other entries still apply.
        prior = {}
        merged = apply_bucket_patch(
            prior,
            {
                "Bad": {"mentions": "should-be-a-list-not-a-string"},
                "Good": {"snapshot": "ok"},
            },
            ObjectState,
        )
        assert "Good" in merged
        assert "Bad" not in merged


# ---------------------------------------------------------------------------
# apply_bucket_patch — all bucket types
# ---------------------------------------------------------------------------


class TestApplyBucketPatchTypes:
    def test_character_bucket(self):
        prior = {
            "Alice": CharacterState(snapshot="calm", emotion="calm", mentions=["Alice"])
        }
        merged = apply_bucket_patch(
            prior, {"Alice": {"emotion": "anxious"}}, CharacterState
        )
        assert merged["Alice"].emotion == "anxious"
        assert merged["Alice"].snapshot == "calm"

    def test_place_bucket(self):
        prior = {"Med Bay": PlaceState(snapshot="sterile glow")}
        merged = apply_bucket_patch(
            prior,
            {"Med Bay": {"snapshot": "flickering, abandoned"}},
            PlaceState,
        )
        assert merged["Med Bay"].snapshot == "flickering, abandoned"


# ---------------------------------------------------------------------------
# has_time_passage_boundary
# ---------------------------------------------------------------------------


class TestHasTimePassageBoundary:
    def test_no_prior_anchors_returns_false(self):
        history = [TimePassageMessage(ts="PT1H", message="an hour later")]
        assert not has_time_passage_boundary(history, [])

    def test_no_time_passage_in_history_returns_false(self):
        m1 = NarratorMessage(message="x")
        m2 = CharacterMessage(message="y")
        assert not has_time_passage_boundary([m1, m2], [m1.id, m2.id])

    def test_time_passage_after_max_anchor_returns_true(self):
        anchored = NarratorMessage(message="anchor")
        cut = TimePassageMessage(ts="PT1H", message="hour later")
        assert has_time_passage_boundary([anchored, cut], [anchored.id])

    def test_time_passage_before_anchor_returns_false(self):
        cut = TimePassageMessage(ts="PT1H", message="hour earlier")
        anchored = NarratorMessage(message="anchor")
        assert not has_time_passage_boundary([cut, anchored], [anchored.id])
