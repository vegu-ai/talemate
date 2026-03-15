"""
Tests for the summarizer LayeredHistoryMixin.

Covers summarize_to_layered_history() and compile_layered_history() using
a real Scene and real SummarizeAgent, with only the AI boundary
(summarize_events) mocked.
"""

import pytest
from unittest.mock import patch

import talemate.util as util
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.history import ArchiveEntry
from talemate.agents.summarize.layered_history import SummaryLongerThanOriginalError

from conftest import MockScene, bootstrap_scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _char_count_tokens(source):
    """Deterministic token counter: 1 char = 1 token."""
    if isinstance(source, list):
        return sum(_char_count_tokens(s) for s in source)
    return len(str(source))


def _pad(label: str, total_chars: int) -> str:
    """Create a string of exact character length with a readable label prefix."""
    if len(label) >= total_chars:
        return label[:total_chars]
    return label + "." * (total_chars - len(label))


def make_archived_entries(count: int, chars_per_entry: int = 50) -> list[dict]:
    """Create *count* summarized archived history entry dicts with exact char sizes."""
    entries = []
    for i in range(count):
        text = _pad(f"AH{i}", chars_per_entry)
        entry = ArchiveEntry(
            text=text,
            ts=f"PT{i}M",
            start=i * 10,
            end=i * 10 + 9,
        ).model_dump(exclude_none=True)
        entries.append(entry)
    return entries


def make_archived_entries_range(
    start: int, end: int, chars_per_entry: int = 50
) -> list[dict]:
    """Create summarized archived entries for index range [start, end)."""
    entries = []
    for i in range(start, end):
        text = _pad(f"AH{i}", chars_per_entry)
        entry = ArchiveEntry(
            text=text,
            ts=f"PT{i}M",
            start=i * 10,
            end=i * 10 + 9,
        ).model_dump(exclude_none=True)
        entries.append(entry)
    return entries


def make_static_entries(count: int, chars_per_entry: int = 50) -> list[dict]:
    """Create *count* static archived history entries (no start/end)."""
    entries = []
    for i in range(count):
        text = _pad(f"SH{i}", chars_per_entry)
        entry = ArchiveEntry(
            text=text,
            ts=f"PT{i}M",
        ).model_dump(exclude_none=True)
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_count_tokens():
    """Replace count_tokens with character-length counting."""
    with patch.object(util, "count_tokens", side_effect=_char_count_tokens):
        yield


@pytest.fixture(autouse=True)
def suppress_emit():
    """Suppress emit() calls inside layered_history module."""
    with patch("talemate.agents.summarize.layered_history.emit"):
        yield


@pytest.fixture
def scene_with_summarizer():
    """
    Real MockScene + real SummarizeAgent with:
      - layered_history action enabled
      - deterministic thresholds (threshold=100, max_process_tokens=200, max_layers=3)
      - summarize_events mocked at instance level (returns ~60% of input)
      - active_scene context var set
    """
    scene = MockScene()
    agents_dict = bootstrap_scene(scene)
    summarizer = agents_dict["summarizer"]

    # Enable and configure layered history
    summarizer.actions["layered_history"].enabled = True
    summarizer.actions["layered_history"].config["threshold"].value = 100
    summarizer.actions["layered_history"].config["max_layers"].value = 3
    summarizer.actions["layered_history"].config["max_process_tokens"].value = 200

    # Mock summarize_events at instance level — shadows the @set_processing
    # decorated class method so we don't need the full prompt pipeline.
    call_log = []

    async def mock_summarize_events(text, **kwargs):
        call_log.append({"text": text, "kwargs": kwargs})
        # Return ~60% of the input length to pass validation
        # but remain large enough to trigger higher-layer summarization.
        target_len = max(10, len(text) * 6 // 10)
        return "S" * target_len

    summarizer.summarize_events = mock_summarize_events
    summarizer._test_call_log = call_log

    with ActiveScene(scene):
        yield scene, summarizer


# ---------------------------------------------------------------------------
# A. Base Layer Construction
# ---------------------------------------------------------------------------


class TestBaseLayerConstruction:
    """Tests for archived_history -> layer 0."""

    async def test_empty_archived_history_no_layers(self, scene_with_summarizer):
        scene, summarizer = scene_with_summarizer
        scene.archived_history = []

        await summarizer.summarize_to_layered_history()

        assert scene.layered_history == []

    async def test_under_threshold_deferred(self, scene_with_summarizer):
        """Two entries totaling < threshold -> no layer-0 entries (deferred)."""
        scene, summarizer = scene_with_summarizer
        # 2 entries * 40 chars = 80 < threshold=100 -> deferred
        scene.archived_history = make_archived_entries(2, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()

        assert len(scene.layered_history) >= 1
        layer0 = scene.layered_history[0]
        assert len(layer0) == 0

    async def test_premature_first_layer_prevented(self, scene_with_summarizer):
        """
        Reproduces the premature first-layer generation bug.

        With default-like threshold=1536 and a small number of archived_history
        entries well below that threshold, no layer-0 entry should be generated.
        Previously, the final chunk was committed as soon as it had >= 2 entries,
        regardless of token count, causing premature summarization.
        """
        scene, summarizer = scene_with_summarizer
        summarizer.actions["layered_history"].config["threshold"].value = 1536

        # Simulate the reported scenario: a few archived entries totaling
        # well under the threshold (e.g., ~327 tokens each, ~654 total << 1536)
        scene.archived_history = make_archived_entries(2, chars_per_entry=327)

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        assert len(layer0) == 0, (
            f"Expected no layer-0 entries with {327 * 2} tokens "
            f"(threshold=1536), but got {len(layer0)}"
        )

        # Even with 3 entries (~981 tokens), still under threshold
        scene.archived_history = make_archived_entries(3, chars_per_entry=327)
        scene.layered_history = [[]]

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        assert len(layer0) == 0, (
            f"Expected no layer-0 entries with {327 * 3} tokens "
            f"(threshold=1536), but got {len(layer0)}"
        )

    async def test_static_entries_ignored(self, scene_with_summarizer):
        """Static entries (no start/end) are completely ignored by layered history."""
        scene, summarizer = scene_with_summarizer
        # 3 static entries of 55c each = 165 tokens, above threshold=100,
        # but they should all be skipped.
        scene.archived_history = make_static_entries(3, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        assert len(layer0) == 0

    async def test_static_entries_mixed_with_summarized(self, scene_with_summarizer):
        """Static entries intermixed with summarized entries are skipped;
        only summarized entries contribute to chunks and token counts."""
        scene, summarizer = scene_with_summarizer
        # 2 static at front + 6 summarized of 55c -> 3 layer-0 entries
        static = make_static_entries(2, chars_per_entry=55)
        summarized = make_archived_entries(6, chars_per_entry=55)
        scene.archived_history = static + summarized

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        # The 6 summarized entries produce 3 chunks of 2, same as without statics
        assert len(layer0) == 3
        # Range covers positions in archived_history (static entries within
        # the range are simply skipped, not summarized)
        assert layer0[0]["start"] == 0
        assert layer0[0]["end"] == 3

    async def test_static_entries_dont_inflate_token_count(self, scene_with_summarizer):
        """Static entries should not contribute to token counts that trigger commits."""
        scene, summarizer = scene_with_summarizer
        # 2 summarized entries of 40c = 80 < threshold=100 (would be deferred)
        # + 2 static entries of 100c each (would push over threshold if counted)
        static = make_static_entries(2, chars_per_entry=100)
        summarized = make_archived_entries(2, chars_per_entry=40)
        scene.archived_history = static + summarized

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        # Should still be deferred — static tokens don't count
        assert len(layer0) == 0

    async def test_exceeding_threshold_multiple_entries(self, scene_with_summarizer):
        """
        6 entries of 55c each, threshold=100.
        In-loop: i=1 (110>100, len=1 skip), i=2 (165>100, len=2 commit [0,1]).
        Same pattern for [2,3] and final chunk [4,5] (110>=100).
        """
        scene, summarizer = scene_with_summarizer
        scene.archived_history = make_archived_entries(6, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        assert len(layer0) == 3
        assert layer0[0]["start"] == 0
        assert layer0[0]["end"] == 1
        assert layer0[1]["start"] == 2
        assert layer0[1]["end"] == 3
        assert layer0[2]["start"] == 4
        assert layer0[2]["end"] == 5

    async def test_end_inclusive_mid_chunk(self, scene_with_summarizer):
        """Mid-chunk end should be i - 1 (last entry in the chunk)."""
        scene, summarizer = scene_with_summarizer
        # 4 entries of 40c: chunk triggers at i=2 (0+40+40=80, then 80+40=120>100)
        scene.archived_history = make_archived_entries(4, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        # First mid-chunk: entries 0,1 -> end = 2-1 = 1
        assert layer0[0]["end"] == 1

    async def test_end_inclusive_final_chunk(self, scene_with_summarizer):
        """Final chunk end should be len(source_layer) - 1."""
        scene, summarizer = scene_with_summarizer
        # 6 entries of 55c: chunks [0,1], [2,3], final [4,5] (110>=100)
        scene.archived_history = make_archived_entries(6, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        last_entry = layer0[-1]
        assert last_entry["end"] == 5  # len(6) - 1

    async def test_timestamps_extracted(self, scene_with_summarizer):
        """Verify ts, ts_start, ts_end are set from chunk entries."""
        scene, summarizer = scene_with_summarizer
        # 2 entries of 55c each = 110 >= threshold=100
        scene.archived_history = make_archived_entries(2, chars_per_entry=55)
        # Entries have ts="PT0M" and ts="PT1M"

        await summarizer.summarize_to_layered_history()

        entry = scene.layered_history[0][0]
        assert "ts" in entry
        assert "ts_start" in entry
        assert "ts_end" in entry
        # ts_start comes from first entry, ts_end from last entry
        assert entry["ts_start"] == "PT0M"
        assert entry["ts_end"] == "PT1M"


# ---------------------------------------------------------------------------
# B. Multi-Layer Construction
# ---------------------------------------------------------------------------


class TestMultiLayerConstruction:
    """Tests for layer 0 -> layer 1 -> layer 2."""

    async def test_layer1_created_from_layer0(self, scene_with_summarizer):
        """Enough layer-0 data triggers layer 1 creation."""
        scene, summarizer = scene_with_summarizer
        # 6 entries * 55c -> 3 layer-0 entries (each covers 2 source entries).
        # Each layer-0 summary is ~60% of 110c = 66c.
        # 3 * 66c = 198 > threshold=100 -> triggers layer 1.
        scene.archived_history = make_archived_entries(6, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        assert len(scene.layered_history) >= 2
        layer1 = scene.layered_history[1]
        assert len(layer1) >= 1
        # Layer 1 entries reference layer 0 indices
        for entry in layer1:
            assert entry["start"] >= 0
            assert entry["end"] < len(scene.layered_history[0])

    async def test_index_space_mapping(self, scene_with_summarizer):
        """Layer 0 end = archived index, layer 1 end = layer 0 index."""
        scene, summarizer = scene_with_summarizer
        scene.archived_history = make_archived_entries(6, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        # Layer 0 indices reference archived_history positions
        for entry in scene.layered_history[0]:
            assert entry["end"] < len(scene.archived_history)

        # Layer 1 indices reference layer 0 positions
        if len(scene.layered_history) >= 2:
            for entry in scene.layered_history[1]:
                assert entry["end"] < len(scene.layered_history[0])

    async def test_three_layers_deep(self, scene_with_summarizer):
        """With enough data, 3 layers should be created."""
        scene, summarizer = scene_with_summarizer
        summarizer.actions["layered_history"].config["max_layers"].value = 5
        # 30 entries * 40c -> many layer-0 entries -> enough to cascade layers
        scene.archived_history = make_archived_entries(30, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()

        assert len(scene.layered_history) >= 3, (
            f"Expected at least 3 layers, got {len(scene.layered_history)}"
        )

        # Verify each layer's entries reference the previous layer's index space
        for layer_idx in range(1, len(scene.layered_history)):
            prev_layer = scene.layered_history[layer_idx - 1]
            for entry in scene.layered_history[layer_idx]:
                assert entry["end"] < len(prev_layer), (
                    f"Layer {layer_idx} entry end={entry['end']} "
                    f">= prev layer len={len(prev_layer)}"
                )

    async def test_max_layers_limit(self, scene_with_summarizer):
        """max_layers=1 caps at layers 0 and 1."""
        scene, summarizer = scene_with_summarizer
        summarizer.actions["layered_history"].config["max_layers"].value = 1
        # Enough data that without limit, 3+ layers would be created
        scene.archived_history = make_archived_entries(30, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()

        # max_layers=1: update_layers allows index 0 -> creates layer 1,
        # but blocks index 1 -> no layer 2
        assert len(scene.layered_history) <= 2


# ---------------------------------------------------------------------------
# C. Incremental Updates
# ---------------------------------------------------------------------------


class TestIncrementalUpdates:
    """Tests for resumption from existing state."""

    async def test_resumes_from_end_plus_one(self, scene_with_summarizer):
        """Second run only processes new entries."""
        scene, summarizer = scene_with_summarizer
        scene.archived_history = make_archived_entries(4, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()

        layer0_entries_before = [e.copy() for e in scene.layered_history[0]]
        call_log = summarizer._test_call_log
        calls_before = len(call_log)

        # Add more entries
        scene.archived_history.extend(
            make_archived_entries_range(4, 8, chars_per_entry=40)
        )

        await summarizer.summarize_to_layered_history()

        # Old entries should be unchanged
        for i, old_entry in enumerate(layer0_entries_before):
            assert scene.layered_history[0][i]["start"] == old_entry["start"]
            assert scene.layered_history[0][i]["end"] == old_entry["end"]
            assert scene.layered_history[0][i]["text"] == old_entry["text"]

        # New summarize_events calls should have been made
        assert len(call_log) > calls_before

    async def test_new_entries_appended(self, scene_with_summarizer):
        """New entries are appended to existing layer 0."""
        scene, summarizer = scene_with_summarizer
        scene.archived_history = make_archived_entries(4, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()
        count_before = len(scene.layered_history[0])

        scene.archived_history.extend(
            make_archived_entries_range(4, 8, chars_per_entry=40)
        )

        await summarizer.summarize_to_layered_history()
        count_after = len(scene.layered_history[0])

        assert count_after > count_before

    async def test_final_chunk_with_multiple_entries_processed(
        self, scene_with_summarizer
    ):
        """Final chunk with >= 2 entries AND >= threshold tokens is committed."""
        scene, summarizer = scene_with_summarizer
        # 4 entries of 55c: in-loop commit [0,1] at i=2 (110>100),
        # then final chunk [2,3] (110>=100) also committed.
        scene.archived_history = make_archived_entries(4, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        assert len(layer0) == 2
        # Final chunk should cover entries 2-3
        assert layer0[1]["start"] == 2
        assert layer0[1]["end"] == 3

    async def test_single_entry_final_chunk_deferred(self, scene_with_summarizer):
        """A single remaining entry is deferred until more data arrives."""
        scene, summarizer = scene_with_summarizer
        # 3 entries of 55c: in-loop commit [0,1] at i=2 (110>100), entry 2 alone
        scene.archived_history = make_archived_entries(3, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        # Only the in-loop entry should exist; entry 2 is deferred
        assert len(layer0) == 1
        assert layer0[0]["start"] == 0
        assert layer0[0]["end"] == 1

        # Adding another entry: [2,3] = 110 >= threshold=100, committed
        scene.archived_history.extend(
            make_archived_entries_range(3, 4, chars_per_entry=55)
        )
        await summarizer.summarize_to_layered_history()

        layer0 = scene.layered_history[0]
        assert len(layer0) == 2
        assert layer0[1]["start"] == 2
        assert layer0[1]["end"] == 3

    async def test_incremental_single_entry_should_not_cascade(
        self, scene_with_summarizer
    ):
        """
        Reproduces the single-entry cascade bug.

        When entries are added one-at-a-time to the source layer, the final
        chunk processing should NOT create degenerate 1-item summaries that
        cascade through all higher layers.

        Scenario: Build initial layers with a batch, then add entries one at
        a time via repeated summarize_to_layered_history calls. After several
        incremental additions, higher layers should NOT have entries that each
        cover only 1 source entry.
        """
        scene, summarizer = scene_with_summarizer
        # Use a threshold that requires ~2-3 entries to trigger (each entry ~48c
        # after 60% summarization, threshold=100)
        summarizer.actions["layered_history"].config["threshold"].value = 100
        summarizer.actions["layered_history"].config["max_layers"].value = 3

        # Start with a batch to establish the base layers
        scene.archived_history = make_archived_entries(6, chars_per_entry=40)
        await summarizer.summarize_to_layered_history()

        initial_layer0_count = len(scene.layered_history[0])
        assert initial_layer0_count >= 2, "Need multiple layer-0 entries to start"

        # Now add entries one at a time, simulating incremental updates
        for i in range(6, 12):
            scene.archived_history.extend(
                make_archived_entries_range(i, i + 1, chars_per_entry=40)
            )
            await summarizer.summarize_to_layered_history()

        # Check all layers for degenerate single-item entries.
        # Every entry in layer N should cover >= 2 entries from layer N-1,
        # UNLESS it's the very last entry in that layer (which may be a
        # legitimate partial chunk waiting for more data).
        for layer_idx in range(1, len(scene.layered_history)):
            layer = scene.layered_history[layer_idx]
            if len(layer) < 2:
                continue
            # Check all entries except the last (which may be partial)
            for entry_idx, entry in enumerate(layer[:-1]):
                coverage = entry["end"] - entry["start"] + 1
                assert coverage >= 2, (
                    f"Layer {layer_idx} entry {entry_idx} covers only "
                    f"{coverage} source entry (start={entry['start']}, "
                    f"end={entry['end']}). Single-item summaries should "
                    f"not be created in higher layers."
                )

    async def test_already_fully_processed_is_noop(self, scene_with_summarizer):
        """When all archived entries are already covered, second call is a no-op."""
        scene, summarizer = scene_with_summarizer
        scene.archived_history = make_archived_entries(4, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()

        layer0_snapshot = [e.copy() for e in scene.layered_history[0]]

        # Call again without adding new entries
        await summarizer.summarize_to_layered_history()

        # Layer 0 should be completely unchanged
        layer0_after = scene.layered_history[0]
        assert len(layer0_after) == len(layer0_snapshot)
        for i, snap in enumerate(layer0_snapshot):
            assert layer0_after[i]["start"] == snap["start"]
            assert layer0_after[i]["end"] == snap["end"]
            assert layer0_after[i]["text"] == snap["text"]


# ---------------------------------------------------------------------------
# D. Chunk Splitting
# ---------------------------------------------------------------------------


class TestChunkSplitting:
    """Tests for _lh_split_and_summarize_chunks behavior."""

    async def test_split_by_max_process_tokens(self, scene_with_summarizer):
        """Low max_process_tokens causes multiple summarize_events calls per chunk."""
        scene, summarizer = scene_with_summarizer
        # High threshold so everything goes in one chunk,
        # but low max_process_tokens to force splitting within that chunk
        summarizer.actions["layered_history"].config["threshold"].value = 500
        summarizer.actions["layered_history"].config["max_process_tokens"].value = 50

        # 14 entries of 40c = 560c total. In-loop commit at i=12 (480+40>500)
        # produces a 12-entry chunk (480c), which is then split by max_process_tokens.
        scene.archived_history = make_archived_entries(14, chars_per_entry=40)

        call_log = summarizer._test_call_log
        call_log.clear()

        await summarizer.summarize_to_layered_history()

        # With max_process_tokens=50 and a 12-entry chunk,
        # the split should produce multiple summarize_events calls
        assert len(call_log) > 1, (
            f"Expected multiple summarize_events calls, got {len(call_log)}"
        )

    async def test_summaries_joined(self, scene_with_summarizer):
        """Multiple partial summaries are joined with double newline in order."""
        scene, summarizer = scene_with_summarizer
        summarizer.actions["layered_history"].config["threshold"].value = 500
        summarizer.actions["layered_history"].config["max_process_tokens"].value = 50

        call_count = 0

        async def labeled_mock(text, **kwargs):
            nonlocal call_count
            call_count += 1
            return f"Part{call_count}"

        summarizer.summarize_events = labeled_mock

        # 14 entries of 40c = 560c. In-loop commit at i=12 (480+40>500)
        # produces a 12-entry chunk, split by max_process_tokens=50.
        scene.archived_history = make_archived_entries(14, chars_per_entry=40)

        await summarizer.summarize_to_layered_history()

        assert call_count > 1, "Expected multiple summarize_events calls"

        entry_text = scene.layered_history[0][0]["text"]
        assert "\n\n" in entry_text

        # Verify ordering: Part1 should appear before Part2
        parts = entry_text.split("\n\n")
        assert parts[0] == "Part1"
        assert parts[1] == "Part2"


# ---------------------------------------------------------------------------
# E. Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for error handling."""

    async def test_summary_longer_than_original(self, scene_with_summarizer):
        """Bloated summary triggers SummaryLongerThanOriginalError, caught internally."""
        scene, summarizer = scene_with_summarizer

        async def bloating_mock(text, **kwargs):
            return text + " EXTRA PADDING " * 20

        summarizer.summarize_events = bloating_mock

        scene.archived_history = make_archived_entries(4, chars_per_entry=40)

        # Should not raise — SummaryLongerThanOriginalError is caught internally
        await summarizer.summarize_to_layered_history()

        # Layer 0 was created (the list is appended before summarization runs)
        # but no entries should have been committed since the first chunk fails
        assert len(scene.layered_history) == 1
        assert len(scene.layered_history[0]) == 0

    async def test_summary_longer_than_original_raises_directly(
        self, scene_with_summarizer
    ):
        """_lh_validate_summary_length raises SummaryLongerThanOriginalError."""
        _, summarizer = scene_with_summarizer

        with pytest.raises(SummaryLongerThanOriginalError):
            summarizer._lh_validate_summary_length(["x" * 200], original_length=50)

    async def test_summary_shorter_than_original_passes(self, scene_with_summarizer):
        """_lh_validate_summary_length does not raise when summary is shorter."""
        _, summarizer = scene_with_summarizer

        # Should not raise
        summarizer._lh_validate_summary_length(["short"], original_length=100)

    async def test_generation_cancelled(self, scene_with_summarizer):
        """GenerationCancelled is caught and handled gracefully."""
        scene, summarizer = scene_with_summarizer

        async def cancel_mock(text, **kwargs):
            raise GenerationCancelled("cancelled")

        summarizer.summarize_events = cancel_mock

        scene.archived_history = make_archived_entries(4, chars_per_entry=40)

        # Should not raise
        await summarizer.summarize_to_layered_history()

        # Layer 0 was created but no entries committed
        assert len(scene.layered_history) == 1
        assert len(scene.layered_history[0]) == 0

    async def test_generation_cancelled_during_higher_layers(
        self, scene_with_summarizer
    ):
        """GenerationCancelled during update_layers is caught without losing layer 0."""
        scene, summarizer = scene_with_summarizer

        call_count = 0

        async def cancel_on_second_layer(text, **kwargs):
            nonlocal call_count
            call_count += 1
            # Let base layer succeed, then cancel during higher layers.
            # Base layer processes 6 entries of 55c -> 3 chunks -> 3 calls.
            # Higher layer starts on call 4+.
            if call_count > 3:
                raise GenerationCancelled("cancelled")
            target_len = max(10, len(text) * 6 // 10)
            return "S" * target_len

        summarizer.summarize_events = cancel_on_second_layer
        scene.archived_history = make_archived_entries(6, chars_per_entry=55)

        await summarizer.summarize_to_layered_history()

        # Layer 0 should have been fully built before the cancellation
        assert len(scene.layered_history) >= 1
        assert len(scene.layered_history[0]) > 0


# ---------------------------------------------------------------------------
# F. Compile Layered History
# ---------------------------------------------------------------------------


class TestCompileLayeredHistory:
    """Tests for compile_layered_history (synchronous, reads scene data)."""

    def test_single_layer(self, scene_with_summarizer):
        """Single layer returns all entries as text."""
        scene, summarizer = scene_with_summarizer
        scene.layered_history = [
            [
                {
                    "text": "Summary A",
                    "start": 0,
                    "end": 2,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "a1",
                },
                {
                    "text": "Summary B",
                    "start": 3,
                    "end": 5,
                    "ts": "PT2M",
                    "ts_start": "PT2M",
                    "ts_end": "PT3M",
                    "id": "b1",
                },
            ]
        ]

        result = summarizer.compile_layered_history()
        assert result == ["Summary A", "Summary B"]

    def test_multi_layer_boundary_tracking(self, scene_with_summarizer):
        """Layer 1 covers early entries, layer 0 fills remainder from end + 1."""
        scene, summarizer = scene_with_summarizer
        scene.layered_history = [
            [  # Layer 0
                {
                    "text": "L0-A",
                    "start": 0,
                    "end": 2,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l0a",
                },
                {
                    "text": "L0-B",
                    "start": 3,
                    "end": 5,
                    "ts": "PT2M",
                    "ts_start": "PT2M",
                    "ts_end": "PT3M",
                    "id": "l0b",
                },
                {
                    "text": "L0-C",
                    "start": 6,
                    "end": 8,
                    "ts": "PT4M",
                    "ts_start": "PT4M",
                    "ts_end": "PT5M",
                    "id": "l0c",
                },
            ],
            [  # Layer 1 covers layer-0 entries 0-1
                {
                    "text": "L1-X",
                    "start": 0,
                    "end": 1,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT3M",
                    "id": "l1x",
                },
            ],
        ]

        result = summarizer.compile_layered_history()

        # Layer 1: L1-X (covers layer-0 indices 0-1, so next_layer_start=2)
        # Layer 0: starts from index 2 -> L0-C
        assert result == ["L1-X", "L0-C"]

    def test_for_layer_index(self, scene_with_summarizer):
        """for_layer_index limits compilation to specific layer and above."""
        scene, summarizer = scene_with_summarizer
        scene.layered_history = [
            [
                {
                    "text": "L0-A",
                    "start": 0,
                    "end": 2,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l0a",
                },
                {
                    "text": "L0-B",
                    "start": 3,
                    "end": 5,
                    "ts": "PT2M",
                    "ts_start": "PT2M",
                    "ts_end": "PT3M",
                    "id": "l0b",
                },
            ],
            [
                {
                    "text": "L1-X",
                    "start": 0,
                    "end": 0,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l1x",
                },
            ],
        ]

        # for_layer_index=1 should only return layer 1 entries
        result = summarizer.compile_layered_history(for_layer_index=1)
        assert result == ["L1-X"]

    def test_as_objects(self, scene_with_summarizer):
        """as_objects returns dicts with metadata."""
        scene, summarizer = scene_with_summarizer
        scene.layered_history = [
            [
                {
                    "text": "L0-A",
                    "start": 0,
                    "end": 2,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l0a",
                },
            ]
        ]

        result = summarizer.compile_layered_history(as_objects=True)

        assert len(result) == 1
        obj = result[0]
        assert obj["text"] == "L0-A"
        assert obj["layer"] == 0
        assert obj["start"] == 0
        assert obj["end"] == 2
        assert "layer_r" in obj
        assert "index" in obj
        assert "ts_start" in obj

    def test_include_base_layer(self, scene_with_summarizer):
        """include_base_layer appends archived_history entries past layer 0."""
        scene, summarizer = scene_with_summarizer
        scene.archived_history = [
            {"text": "AH0", "start": 0, "end": 9, "ts": "PT0S", "id": "ah0"},
            {"text": "AH1", "start": 10, "end": 19, "ts": "PT1M", "id": "ah1"},
            {"text": "AH2", "start": 20, "end": 29, "ts": "PT2M", "id": "ah2"},
        ]
        scene.layered_history = [
            [
                {
                    "text": "L0-A",
                    "start": 0,
                    "end": 1,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l0a",
                },
            ]
        ]

        result = summarizer.compile_layered_history(include_base_layer=True)

        # L0-A covers archived indices 0-1, so base layer starts at end+1=2
        assert "L0-A" in result
        assert "AH2" in result

    def test_empty_layers(self, scene_with_summarizer):
        """Empty layers produce empty result."""
        scene, summarizer = scene_with_summarizer
        scene.layered_history = [[], []]

        result = summarizer.compile_layered_history()
        assert result == []

    def test_empty_intermediate_layer(self, scene_with_summarizer):
        """An empty layer between populated layers is skipped gracefully."""
        scene, summarizer = scene_with_summarizer
        scene.layered_history = [
            [  # Layer 0
                {
                    "text": "L0-A",
                    "start": 0,
                    "end": 2,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l0a",
                },
                {
                    "text": "L0-B",
                    "start": 3,
                    "end": 5,
                    "ts": "PT2M",
                    "ts_start": "PT2M",
                    "ts_end": "PT3M",
                    "id": "l0b",
                },
            ],
            [],  # Layer 1 empty
            [  # Layer 2
                {
                    "text": "L2-X",
                    "start": 0,
                    "end": 0,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l2x",
                },
            ],
        ]

        result = summarizer.compile_layered_history()

        # Layer 2 should be included; empty layer 1 skipped;
        # layer 0 fills from L2-X's end+1 = 1
        assert "L2-X" in result
        assert "L0-B" in result
        # L0-A (index 0) is covered by L2-X (end=0), so it should not appear
        assert "L0-A" not in result

    def test_max_parameter(self, scene_with_summarizer):
        """max parameter stops at specified end index."""
        scene, summarizer = scene_with_summarizer
        scene.layered_history = [
            [
                {
                    "text": "L0-A",
                    "start": 0,
                    "end": 2,
                    "ts": "PT0S",
                    "ts_start": "PT0S",
                    "ts_end": "PT1M",
                    "id": "l0a",
                },
                {
                    "text": "L0-B",
                    "start": 3,
                    "end": 5,
                    "ts": "PT2M",
                    "ts_start": "PT2M",
                    "ts_end": "PT3M",
                    "id": "l0b",
                },
                {
                    "text": "L0-C",
                    "start": 6,
                    "end": 8,
                    "ts": "PT4M",
                    "ts_start": "PT4M",
                    "ts_end": "PT5M",
                    "id": "l0c",
                },
            ]
        ]

        # max=5: the check is `max <= entry["end"]`, so L0-A (end=2) passes,
        # L0-B (end=5) triggers 5<=5 -> break
        result = summarizer.compile_layered_history(for_layer_index=0, max=5)

        assert "L0-A" in result
        assert "L0-B" not in result
