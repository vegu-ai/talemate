"""Tests for kind -> preset/token resolution in talemate.client.presets."""

import pytest

from talemate.client.presets import (
    max_tokens_for_kind,
    preset_name_for_kind,
)


class TestPresetNameForKind:
    def test_exact_match_wins(self):
        assert preset_name_for_kind("create") == "creative_instruction"
        assert preset_name_for_kind("conversation") == "conversation"

    def test_substring_fallback(self):
        assert preset_name_for_kind("narrate_512") == "creative"
        assert preset_name_for_kind("create_256") == "creative"

    def test_unknown_kind_returns_none(self):
        assert preset_name_for_kind("totally_unknown") is None

    @pytest.mark.parametrize("length", [128, 256, 512])
    def test_creative_instruction_parametric_kind_keeps_preset(self, length):
        # A parametric creative_instruction kind must resolve to the
        # creative_instruction preset, not be captured by the broader
        # "create"/"creative" substring entries.
        assert (
            preset_name_for_kind(f"creative_instruction_{length}")
            == "creative_instruction"
        )

    def test_create_parametric_kind_unaffected(self):
        # The narrower creative_instruction entry must not change how plain
        # create_/creative_ parametric kinds resolve.
        assert preset_name_for_kind("create_256") == "creative"
        assert preset_name_for_kind("creative_256") == "creative"


class TestMaxTokensForKind:
    def test_trailing_digit_is_used(self):
        assert max_tokens_for_kind("creative_instruction_256", 8192) == 256
        assert max_tokens_for_kind("create_128", 8192) == 128

    def test_callable_budget_mapping(self):
        # "create" caps at min(1024, budget * 0.35)
        assert max_tokens_for_kind("create", 1000) == 350
        assert max_tokens_for_kind("create", 100000) == 1024
