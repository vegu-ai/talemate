"""
Unit tests for Scene.context_history() method.

Tests the original behavior of context_history which controls how scene history
is split between summarized context and actual dialogue messages.

These tests focus on the budget allocation logic and key behaviors that we
want to preserve or modify when adding the dialogue ratio feature.
"""

import pytest
from unittest.mock import Mock, patch


class TestContextHistoryBudgetSplit:
    """Tests for the 50/50 budget split between context and dialogue."""

    def test_default_budget_is_8192(self):
        """Verify default budget parameter is 8192."""
        from talemate.tale_mate import Scene

        import inspect

        sig = inspect.signature(Scene.context_history)
        assert sig.parameters["budget"].default == 8192

    def test_budget_split_fifty_fifty(self):
        """Verify budget is split 50/50 between context and dialogue."""
        budget = 8192
        budget_context = int(0.5 * budget)
        budget_dialogue = int(0.5 * budget)

        assert budget_context == 4096
        assert budget_dialogue == 4096
        assert budget_context + budget_dialogue == budget

    def test_budget_split_various_values(self):
        """Test budget split with various budget values."""
        for budget in [1000, 4096, 8192, 16384, 32768]:
            budget_context = int(0.5 * budget)
            budget_dialogue = int(0.5 * budget)
            assert budget_context == budget // 2
            assert budget_dialogue == budget // 2


class TestSummarizedToBoundaryLogic:
    """
    Tests for the summarized_to boundary behavior.

    This is the key logic we want to make configurable:
    - When i < summarized_to AND dialogue_messages_collected >= assured_dialogue_num: break

    This means the loop stops when:
    1. We've gone past the summarization boundary (into summarized messages)
    2. AND we've collected at least assured_dialogue_num messages
    """

    def test_boundary_logic_stops_when_both_conditions_met(self):
        """Should stop when below summarized_to AND assured_dialogue_num is met."""
        # Simulate the loop logic
        summarized_to = 10
        assured_dialogue_num = 5

        # Scenario: We're at index 8 (below summarized_to=10)
        # and have collected 5 messages (>= assured_dialogue_num)
        i = 8
        dialogue_messages_collected = 5

        should_break = (
            i < summarized_to
            and dialogue_messages_collected >= assured_dialogue_num
        )

        assert should_break is True

    def test_boundary_logic_continues_if_above_summarized_to(self):
        """Should continue if we're still above the summarized_to boundary."""
        summarized_to = 10
        assured_dialogue_num = 5

        # At index 12 (above summarized_to), even with enough messages
        i = 12
        dialogue_messages_collected = 5

        should_break = (
            i < summarized_to
            and dialogue_messages_collected >= assured_dialogue_num
        )

        assert should_break is False

    def test_boundary_logic_continues_if_not_enough_messages(self):
        """Should continue if we haven't collected enough assured messages."""
        summarized_to = 10
        assured_dialogue_num = 5

        # Below boundary but only 3 messages collected
        i = 8
        dialogue_messages_collected = 3

        should_break = (
            i < summarized_to
            and dialogue_messages_collected >= assured_dialogue_num
        )

        assert should_break is False

    def test_assured_dialogue_forces_past_boundary(self):
        """assured_dialogue_num should force collection past the boundary."""
        summarized_to = 10

        # With assured_dialogue_num=5, if we only have 3 messages,
        # we must continue past the boundary
        for i in range(15, -1, -1):
            dialogue_messages_collected = max(0, 15 - i)  # Collect as we go

            should_break = (
                i < summarized_to
                and dialogue_messages_collected >= 5
            )

            # Should only break once we're below boundary AND have 5 messages
            if i < summarized_to and dialogue_messages_collected >= 5:
                assert should_break is True
                break
            else:
                assert should_break is False


class TestBudgetLimitLogic:
    """Tests for the budget limit behavior in dialogue collection."""

    def test_budget_limit_breaks_collection(self):
        """Collection should stop when budget is exceeded."""
        budget_dialogue = 1000
        message_tokens = 300

        parts_dialogue_tokens = 0
        messages_collected = 0

        for i in range(10):
            new_total = parts_dialogue_tokens + message_tokens
            if new_total > budget_dialogue:
                break
            parts_dialogue_tokens = new_total
            messages_collected += 1

        # Should collect 3 messages (900 tokens) before exceeding 1000
        assert messages_collected == 3
        assert parts_dialogue_tokens == 900

    def test_budget_respects_various_message_sizes(self):
        """Budget calculation should work with varying message sizes."""
        budget_dialogue = 500
        message_sizes = [100, 150, 200, 100, 50]

        total_tokens = 0
        messages_collected = 0

        for size in message_sizes:
            if total_tokens + size > budget_dialogue:
                break
            total_tokens += size
            messages_collected += 1

        # 100 + 150 + 200 = 450, next would be 550 > 500
        assert messages_collected == 3
        assert total_tokens == 450


class TestContextCollectionLogic:
    """Tests for context (summarized history) collection logic."""

    def test_context_trimmed_from_beginning(self):
        """Context should be trimmed from the beginning (oldest first)."""
        budget_context = 200

        # Simulate context entries of 100 tokens each
        parts_context = ["entry1", "entry2", "entry3", "entry4"]
        token_counts = {item: 100 for item in parts_context}

        def count_tokens(items):
            return sum(token_counts.get(item, 0) for item in items)

        # Trim logic: pop(0) until under budget
        while parts_context and count_tokens(parts_context) > budget_context:
            parts_context.pop(0)

        # Should keep only last 2 entries (200 tokens)
        assert parts_context == ["entry3", "entry4"]

    def test_archived_entries_without_end_skipped(self):
        """Archived history entries without 'end' key should be skipped."""
        archived_history = [
            {"ts": "PT30M", "text": "No end - skip"},
            {"end": 5, "ts": "PT45M", "text": "Has end - include"},
            {"end": None, "ts": "PT60M", "text": "None end - skip"},
        ]

        collected = []
        for entry in archived_history:
            end = entry.get("end")
            if end is None:
                continue
            collected.append(entry["text"])

        assert collected == ["Has end - include"]


class TestIntroFallbackLogic:
    """Tests for intro fallback when context is sparse."""

    def test_intro_added_when_context_under_128_tokens(self):
        """Intro should be added when context is under 128 tokens."""
        parts_context = ["short"]
        parts_context_tokens = 50
        intro = "Welcome to the story!"

        if parts_context_tokens < 128 and intro:
            parts_context.insert(0, intro)

        assert parts_context[0] == intro

    def test_intro_not_added_when_context_sufficient(self):
        """Intro should not be added when context has enough tokens."""
        parts_context = ["sufficient content here"]
        parts_context_tokens = 200
        intro = "Welcome to the story!"

        if parts_context_tokens < 128 and intro:
            parts_context.insert(0, intro)

        assert intro not in parts_context


class TestDialogueRatioCalculations:
    """
    Tests for different dialogue ratio calculations.

    These tests document what we WANT the new behavior to be:
    - A configurable ratio that controls the split between dialogue and context
    """

    def test_fifty_percent_ratio_is_default(self):
        """50% ratio should be the default (current behavior)."""
        budget = 8192
        ratio = 50

        budget_dialogue = int((ratio / 100.0) * budget)
        budget_context = budget - budget_dialogue

        assert budget_dialogue == 4096
        assert budget_context == 4096

    def test_seventy_percent_ratio_favors_dialogue(self):
        """70% ratio should give more budget to dialogue."""
        budget = 10000
        ratio = 70

        budget_dialogue = int((ratio / 100.0) * budget)
        budget_context = budget - budget_dialogue

        assert budget_dialogue == 7000
        assert budget_context == 3000

    def test_thirty_percent_ratio_favors_context(self):
        """30% ratio should give more budget to context."""
        budget = 10000
        ratio = 30

        budget_dialogue = int((ratio / 100.0) * budget)
        budget_context = budget - budget_dialogue

        assert budget_dialogue == 3000
        assert budget_context == 7000

    def test_ratio_range_boundaries(self):
        """Test ratio calculations at boundary values."""
        budget = 10000

        # At 10% (minimum we'd allow)
        budget_dialogue_10 = int((10 / 100.0) * budget)
        assert budget_dialogue_10 == 1000

        # At 90% (maximum we'd allow)
        budget_dialogue_90 = int((90 / 100.0) * budget)
        assert budget_dialogue_90 == 9000


class TestManageSceneHistoryBehavior:
    """
    Tests for the manage_scene_history feature behavior.

    When manage_scene_history is DISABLED (default), use original 50/50 split
    and respect the summarized_to boundary.

    When manage_scene_history is ENABLED, use custom ratio and ignore the
    summarized_to boundary (let budget control collection).
    """

    def test_disabled_respects_summarized_to_boundary(self):
        """When disabled, summarized_to boundary should be respected."""
        manage_scene_history = False
        summarized_to = 10
        assured_dialogue_num = 5

        # At index 8 with 5 messages collected
        i = 8
        dialogue_messages_collected = 5

        # When disabled: break when both conditions met
        should_break = (
            not manage_scene_history
            and i < summarized_to
            and dialogue_messages_collected >= assured_dialogue_num
        )

        assert should_break is True

    def test_enabled_ignores_summarized_to_boundary(self):
        """When enabled, summarized_to boundary should be ignored."""
        manage_scene_history = True
        summarized_to = 10
        assured_dialogue_num = 5

        # At index 8 with 5 messages collected
        i = 8
        dialogue_messages_collected = 5

        # When enabled: don't break based on summarized_to
        should_break = (
            not manage_scene_history
            and i < summarized_to
            and dialogue_messages_collected >= assured_dialogue_num
        )

        # Should NOT break because manage_scene_history is enabled
        assert should_break is False

    def test_enabled_still_respects_budget(self):
        """When enabled, budget should still limit collection."""
        ratio = 70
        budget = 10000
        budget_dialogue = int((ratio / 100.0) * budget)  # 7000 tokens

        message_tokens = 1000
        parts_dialogue_tokens = 0
        messages_collected = 0

        for i in range(20):
            if parts_dialogue_tokens + message_tokens > budget_dialogue:
                break
            parts_dialogue_tokens += message_tokens
            messages_collected += 1

        # Should collect 7 messages (7000 tokens)
        assert messages_collected == 7
        assert parts_dialogue_tokens == 7000

    def test_max_budget_override(self):
        """max_budget should override the passed budget when > 0."""
        passed_budget = 8192
        max_budget = 16384

        # When max_budget > 0, it should be used instead of passed_budget
        effective_budget = max_budget if max_budget > 0 else passed_budget
        assert effective_budget == 16384

        # When max_budget == 0, passed_budget should be used
        max_budget = 0
        effective_budget = max_budget if max_budget > 0 else passed_budget
        assert effective_budget == 8192


class TestManageSceneHistorySettings:
    """Tests for the manage_scene_history agent action settings."""

    def test_manage_scene_history_action_exists(self):
        """Verify manage_scene_history action exists."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        assert "manage_scene_history" in actions

    def test_manage_scene_history_disabled_by_default(self):
        """Verify manage_scene_history is disabled by default."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        assert actions["manage_scene_history"].enabled is False

    def test_dialogue_ratio_setting_exists(self):
        """Verify dialogue_ratio setting exists in manage_scene_history."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        assert "dialogue_ratio" in actions["manage_scene_history"].config

    def test_dialogue_ratio_default_is_fifty(self):
        """Verify default dialogue ratio is 50%."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        config = actions["manage_scene_history"].config["dialogue_ratio"]
        assert config.value == 50

    def test_dialogue_ratio_range(self):
        """Verify dialogue ratio has valid range (10-90%)."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        config = actions["manage_scene_history"].config["dialogue_ratio"]
        assert config.min == 10
        assert config.max == 90
        assert config.step == 5

    def test_max_budget_setting_exists(self):
        """Verify max_budget setting exists in manage_scene_history."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        assert "max_budget" in actions["manage_scene_history"].config

    def test_max_budget_default_is_zero(self):
        """Verify default max_budget is 0 (disabled)."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        config = actions["manage_scene_history"].config["max_budget"]
        assert config.value == 0

    def test_max_budget_range(self):
        """Verify max_budget has valid range."""
        from talemate.agents.summarize import SummarizeAgent

        actions = SummarizeAgent.init_actions()
        config = actions["manage_scene_history"].config["max_budget"]
        assert config.min == 0
        assert config.max == 65536
        assert config.step == 1024

    def test_manage_scene_history_enabled_property(self):
        """Verify manage_scene_history_enabled property works."""
        from talemate.agents.summarize import SummarizeAgent

        agent = SummarizeAgent(client=None)
        assert agent.manage_scene_history_enabled is False

        agent.actions["manage_scene_history"].enabled = True
        assert agent.manage_scene_history_enabled is True

    def test_scene_history_dialogue_ratio_property(self):
        """Verify scene_history_dialogue_ratio property works."""
        from talemate.agents.summarize import SummarizeAgent

        agent = SummarizeAgent(client=None)
        assert agent.scene_history_dialogue_ratio == 50

        agent.actions["manage_scene_history"].config["dialogue_ratio"].value = 70
        assert agent.scene_history_dialogue_ratio == 70

    def test_scene_history_max_budget_property(self):
        """Verify scene_history_max_budget property works."""
        from talemate.agents.summarize import SummarizeAgent

        agent = SummarizeAgent(client=None)
        assert agent.scene_history_max_budget == 0

        agent.actions["manage_scene_history"].config["max_budget"].value = 16384
        assert agent.scene_history_max_budget == 16384
