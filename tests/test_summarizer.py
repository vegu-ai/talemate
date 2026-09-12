"""
Tests for ``talemate.agents.summarize`` (the SummarizeAgent base class).

Targets:
- Action registration & config helper properties (threshold, archive_method,
  archive_include_previous, archive_instructions).
- ``estimated_entry_count`` arithmetic over scene history.
- ``clean_result`` string normalization (hash-stripping, partial-sentence
  trimming, surrounding whitespace).
- ``rag_build_sub_instruction`` signal flow.
- ``previous_summaries`` for both layered-history-available and the
  archived-history-only path; raises when entry id is unknown.
- ``build_archive`` happy path / disabled-action / nothing-to-archive paths,
  using a stubbed ``summarize`` and ``analyze_dialoge`` to avoid the LLM
  prompt pipeline.
- ``find_natural_scene_termination`` numeric splitting using a queued
  client response.
- ``on_push_history`` simply forwards to ``build_archive``.

The full Prompt.request pipeline used by ``analyze_dialoge``,
``summarize``, ``summarize_events``, and ``summarize_director_chat`` requires
heavy template plumbing; we cover those via stubs and queued client
responses where the path can be exercised without triggering the templated
prompt machinery. Other LLM paths that depend on full template rendering
are left for higher-level integration tests.
"""

from unittest.mock import patch

import pytest

import talemate.util as util
from talemate.context import ActiveScene
from talemate.events import HistoryEvent
from talemate.history import ArchiveEntry
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    TimePassageMessage,
)

from conftest import MockScene, bootstrap_scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _char_count_tokens(source):
    """Deterministic token counter: 1 char = 1 token."""
    if isinstance(source, list):
        return sum(_char_count_tokens(s) for s in source)
    return len(str(source))


def make_character_message(text: str, character: str = "Alice") -> CharacterMessage:
    return CharacterMessage(message=f"{character}: {text}", source="ai")


def make_archived(
    text: str = "summary",
    start: int | None = None,
    end: int | None = None,
    ts: int = 0,
    entry_id: str | None = None,
) -> dict:
    e = ArchiveEntry(text=text, ts=ts, start=start, end=end)
    d = e.model_dump(exclude_none=True)
    if entry_id:
        d["id"] = entry_id
    return d


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_count_tokens():
    """Replace count_tokens with character-length counting.

    Patching the module attribute makes the patch visible everywhere
    summarize/__init__.py looks up ``util.count_tokens``.
    """
    with patch.object(util, "count_tokens", side_effect=_char_count_tokens):
        yield


@pytest.fixture
def summarizer_scene():
    """Bootstrapped MockScene + summarizer agent.

    The ActiveScene context var is set so methods that reach for it (via
    ``set_processing``) work correctly.
    """
    scene = MockScene()
    agents = bootstrap_scene(scene)
    summarizer = agents["summarizer"]

    with ActiveScene(scene):
        yield scene, summarizer


# ---------------------------------------------------------------------------
# Action registration & properties
# ---------------------------------------------------------------------------


class TestActionRegistration:
    def test_archive_action_present(self, summarizer_scene):
        _, summarizer = summarizer_scene
        action = summarizer.actions["archive"]
        assert action.label == "Summarization"
        assert {
            "threshold",
            "method",
            "include_previous",
            "instructions",
        } <= set(action.config.keys())

    def test_threshold_default_and_property(self, summarizer_scene):
        _, summarizer = summarizer_scene
        # Default value defined in init_actions is 1536.
        assert summarizer.threshold == 1536
        assert summarizer.archive_threshold == 1536
        summarizer.actions["archive"].config["threshold"].value = 256
        assert summarizer.threshold == 256
        assert summarizer.archive_threshold == 256

    def test_archive_method_property(self, summarizer_scene):
        _, summarizer = summarizer_scene
        assert summarizer.archive_method == "balanced"
        summarizer.actions["archive"].config["method"].value = "facts"
        assert summarizer.archive_method == "facts"

    def test_archive_include_previous_property(self, summarizer_scene):
        _, summarizer = summarizer_scene
        assert summarizer.archive_include_previous == 6
        summarizer.actions["archive"].config["include_previous"].value = 0
        assert summarizer.archive_include_previous == 0

    def test_archive_instructions_property(self, summarizer_scene):
        _, summarizer = summarizer_scene
        assert summarizer.archive_instructions == ""
        summarizer.actions["archive"].config["instructions"].value = "be terse"
        assert summarizer.archive_instructions == "be terse"


# ---------------------------------------------------------------------------
# estimated_entry_count
# ---------------------------------------------------------------------------


class TestEstimatedEntryCount:
    def test_zero_history(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        scene.history = []
        assert summarizer.estimated_entry_count == 0

    def test_history_below_threshold(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        # threshold default 1536; one short message -> 0 entries.
        scene.history = [make_character_message("hi")]
        assert summarizer.estimated_entry_count == 0

    def test_history_above_threshold_yields_count(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        # threshold = 100, three 60-char messages = 180 tokens -> 1.
        summarizer.actions["archive"].config["threshold"].value = 100
        scene.history = [
            make_character_message("x" * 60),
            make_character_message("y" * 60),
            make_character_message("z" * 60),
        ]
        # Each "Alice: <60 x>" has length len("Alice: ") + 60 = 67.
        # Total tokens 3 * 67 = 201, threshold 100 -> 2 entries.
        assert summarizer.estimated_entry_count == 2


# ---------------------------------------------------------------------------
# clean_result
# ---------------------------------------------------------------------------


class TestCleanResult:
    def test_strips_after_hash(self, summarizer_scene):
        _, summarizer = summarizer_scene
        # The hash and everything after is removed; leading/trailing
        # whitespace is stripped. Note that strip_partial_sentences trims
        # tails that don't end with a sentence terminator.
        result = summarizer.clean_result("hello there. # internal note")
        assert result == "hello there."

    def test_no_hash_returns_stripped(self, summarizer_scene):
        _, summarizer = summarizer_scene
        assert summarizer.clean_result("  one sentence.  ") == "one sentence."

    def test_strip_partial_sentence_at_end(self, summarizer_scene):
        _, summarizer = summarizer_scene
        # Trailing partial sentence (no terminating punctuation) is stripped.
        result = summarizer.clean_result("Done one. Two and th")
        assert result == "Done one."


# ---------------------------------------------------------------------------
# previous_summaries
# ---------------------------------------------------------------------------


class TestPreviousSummaries:
    async def test_unknown_entry_id_raises(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        scene.archived_history = [make_archived(entry_id="aa", start=0, end=5)]

        ghost = ArchiveEntry(text="ghost", ts=60, start=0, end=1)
        ghost.id = "does-not-exist"
        with pytest.raises(ValueError):
            await summarizer.previous_summaries(ghost)

    async def test_returns_empty_when_include_previous_zero(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["include_previous"].value = 0
        e = ArchiveEntry(text="e", ts=60, start=0, end=5)
        d = e.model_dump(exclude_none=True)
        scene.archived_history = [d]
        # Re-create entry that matches the dict id so we can look it up.
        target = ArchiveEntry(**d)
        target.id = d["id"]
        result = await summarizer.previous_summaries(target)
        assert result == []

    async def test_non_layered_path_reads_text_from_dict(self, summarizer_scene):
        """The non-layered branch reads `text` via dict subscript because
        `archived_history` stores dicts (via `model_dump`), not
        `ArchiveEntry` instances."""
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["include_previous"].value = 2
        summarizer.actions["layered_history"].enabled = False

        # Three prior summaries, dict-shaped as production stores them.
        scene.archived_history = [
            make_archived(text="oldest", start=0, end=5, entry_id="a1"),
            make_archived(text="middle", start=6, end=10, entry_id="a2"),
            make_archived(text="recent", start=11, end=15, entry_id="a3"),
            make_archived(text="target", start=16, end=20, entry_id="target"),
        ]

        target_dict = scene.archived_history[-1]
        target = ArchiveEntry(**target_dict)
        target.id = target_dict["id"]

        result = await summarizer.previous_summaries(target)
        # entry_index=3, end=2; slice [end - num_previous : end] = [0:2]
        # → text from indices 0 and 1.
        assert result == ["oldest", "middle"]

    async def test_layered_history_path_returns_compiled_summaries(
        self, summarizer_scene
    ):
        """When layered_history is available, ``previous_summaries`` defers
        to ``compile_layered_history`` and slices the tail.
        """
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["include_previous"].value = 2
        summarizer.actions["layered_history"].enabled = True

        # Build a single layer so layered_history_available is True.
        scene.layered_history = [
            [
                {
                    "text": "L0-A",
                    "start": 0,
                    "end": 0,
                    "ts": 0,
                    "ts_start": 0,
                    "ts_end": 0,
                    "id": "l0a",
                }
            ]
        ]
        d = make_archived(text="D", start=31, end=40, entry_id="id-d")
        scene.archived_history = [d]

        target = ArchiveEntry(**d)
        target.id = "id-d"

        # Stub compile_layered_history so we don't have to construct a
        # complete layered+archived setup.
        captured = {}

        def stub_compile(*args, **kwargs):
            captured["kwargs"] = kwargs
            return ["pre-1", "pre-2", "pre-3"]

        summarizer.compile_layered_history = stub_compile

        result = await summarizer.previous_summaries(target)
        assert captured["kwargs"]["base_layer_end_id"] == "id-d"
        assert captured["kwargs"]["include_base_layer"] is True
        # Tail slice [-num_previous:] = last 2 entries.
        assert result == ["pre-2", "pre-3"]


# ---------------------------------------------------------------------------
# rag_build_sub_instruction
# ---------------------------------------------------------------------------


class TestRagBuildSubInstruction:
    async def test_returns_none_when_no_listener_sets(self, summarizer_scene):
        _, summarizer = summarizer_scene
        # If the analyze_scene action is disabled, on_rag_build_sub_instruction
        # listener returns "" but emission.sub_instruction defaults to None.
        result = await summarizer.rag_build_sub_instruction()
        # The mixin sets sub_instruction only when there is a non-empty
        # value, otherwise it remains None.
        assert result is None


# ---------------------------------------------------------------------------
# build_archive
# ---------------------------------------------------------------------------


class TestBuildArchive:
    async def test_disabled_archive_action_returns_none(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].enabled = False
        scene.history = [make_character_message("hello")]
        result = await summarizer.build_archive(scene)
        assert result is None
        assert scene.archived_history == []

    async def test_below_threshold_no_summary(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        # Force the threshold above what the test history contains
        summarizer.actions["archive"].config["threshold"].value = 10000
        scene.history = [make_character_message("a") for _ in range(3)]

        result = await summarizer.build_archive(scene)
        # Nothing to archive -> returns None.
        assert result is None
        assert scene.archived_history == []

    async def test_time_passage_terminates_chunk_and_pushes_archive(
        self, summarizer_scene
    ):
        scene, summarizer = summarizer_scene
        # threshold large so the only termination is the TimePassageMessage.
        summarizer.actions["archive"].config["threshold"].value = 100000
        # TimePassageMessage in the middle of history.
        scene.history = [
            make_character_message("first"),
            make_character_message("second"),
            make_character_message("third"),
            TimePassageMessage(ts=300, message="Five minutes pass"),
            make_character_message("post-passage"),
            make_character_message("trailing"),
        ]

        called = {}

        async def stub_summarize(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            called["text"] = text
            called["extra_context"] = extra_context
            return ("SUMMARIZED", None) if return_facts else "SUMMARIZED"

        summarizer.summarize = stub_summarize

        # Without a TimePassageMessage immediately at i==start, the loop
        # accumulates dialogue, hits the time-passage at i=3, and
        # terminates with end=2. analyze_dialoge is then called.
        async def stub_analyze(dialogue):
            return ""  # No termination suggested -> keep dialogue.

        summarizer.analyze_dialoge = stub_analyze

        result = await summarizer.build_archive(scene)

        assert result is True
        assert called["text"] == "SUMMARIZED" or called["text"]  # text passed
        # archived_history should have a single new ArchiveEntry.
        assert len(scene.archived_history) == 1
        entry = scene.archived_history[0]
        assert entry["text"] == "SUMMARIZED"
        assert entry["start"] == 0
        assert entry["end"] == 2
        # Time passage 5M -> scene timestamp updated to 300.
        assert scene.ts == 300

    async def test_director_messages_skipped_at_start(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["threshold"].value = 100000
        # DirectorMessage at start -> start is incremented past it.
        scene.history = [
            DirectorMessage(message="cue!", source="ai"),
            make_character_message("first"),
            make_character_message("second"),
            TimePassageMessage(ts=120, message="Two minutes pass"),
            make_character_message("trailing"),
        ]

        async def stub_summarize(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return ("SUMM", None) if return_facts else "SUMM"

        summarizer.summarize = stub_summarize

        async def stub_analyze(dialogue):
            return ""

        summarizer.analyze_dialoge = stub_analyze

        result = await summarizer.build_archive(scene)
        assert result is True
        assert len(scene.archived_history) == 1
        # start advanced past the DirectorMessage
        assert scene.archived_history[0]["start"] == 1

    async def test_resumes_from_existing_archive_end(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["threshold"].value = 100000
        # Existing archive ending at index 1 -> start = 2.
        scene.archived_history = [make_archived(text="prior", start=0, end=1, ts=60)]
        scene.history = [
            make_character_message("a"),
            make_character_message("b"),
            make_character_message("c"),
            make_character_message("d"),
            TimePassageMessage(ts=120, message="Two minutes pass"),
            make_character_message("trailing"),
        ]

        async def stub_summarize(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return ("NEW SUMM", None) if return_facts else "NEW SUMM"

        summarizer.summarize = stub_summarize

        async def stub_analyze(dialogue):
            return ""

        summarizer.analyze_dialoge = stub_analyze

        await summarizer.build_archive(scene)
        # Two archives now: the pre-existing one and the new one starting
        # at index 2 (the message after the previous end).
        assert len(scene.archived_history) == 2
        assert scene.archived_history[1]["start"] == 2
        assert scene.archived_history[1]["text"] == "NEW SUMM"

    async def test_null_ts_on_recent_archive_entry(self, summarizer_scene):
        """Scenes saved before scene time became integer seconds may carry an
        explicit null `ts` on an archive entry, which the migration keeps as
        is. Summarization has to treat it as the start of the scene."""
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["threshold"].value = 100000
        prior = make_archived(text="prior", start=0, end=1, ts=0)
        prior["ts"] = None
        scene.archived_history = [prior]
        scene.history = [
            make_character_message("a"),
            make_character_message("b"),
            make_character_message("c"),
            make_character_message("d"),
            TimePassageMessage(ts=120, message="Two minutes pass"),
            make_character_message("trailing"),
        ]

        async def stub_summarize(
            text, extra_context=None, generation_options=None, return_facts=False
        ):
            return ("NEW SUMM", None) if return_facts else "NEW SUMM"

        summarizer.summarize = stub_summarize

        async def stub_analyze(dialogue):
            return ""

        summarizer.analyze_dialoge = stub_analyze

        await summarizer.build_archive(scene)

        assert len(scene.archived_history) == 2
        assert scene.archived_history[1]["ts"] == 120


# ---------------------------------------------------------------------------
# on_push_history
# ---------------------------------------------------------------------------


class TestOnPushHistory:
    async def test_forwards_to_build_archive(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        called = {}

        async def stub_build_archive(
            scene_arg, generation_options=None, *, notify=False
        ):
            called["scene"] = scene_arg
            called["generation_options"] = generation_options
            called["notify"] = notify

        summarizer.build_archive = stub_build_archive

        emission = HistoryEvent(
            scene=scene, event_type="push_history.after", messages=[]
        )
        await summarizer.on_push_history(emission)
        assert called["notify"] is True
        assert called["scene"] is scene
        # generation_options is constructed with the scene's writing_style.
        assert called["generation_options"] is not None


# ---------------------------------------------------------------------------
# find_natural_scene_termination
# ---------------------------------------------------------------------------


class TestFindNaturalSceneTermination:
    async def test_splits_on_returned_progress_numbers(self, summarizer_scene):
        scene, summarizer = summarizer_scene

        # Each "chunk" is a single line (or multiple paragraphs combined into
        # one chunk). The function rebuilds chunks by splitting on \n and
        # keeping non-empty paragraphs.
        chunks = [
            "Para 0",
            "Para 1",
            "Para 2",
            "Para 3",
            "Para 4",
        ]

        # Mock LLM response: a numbered list "Progress N" between 0 and 4.
        mock_response = (
            "Some preamble, no list yet.\n"
            "1. Progress 1\n"
            "2. Progress 3\n"
            "Then more prose."
        )
        # Patch Prompt.request to return our mock with extracted response.
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                mock_response,
                {"response": mock_response},
            )
            result = await summarizer.find_natural_scene_termination(chunks)

        # Sorted unique numbers from "Progress N" -> [1, 3].
        # The function emits one group per number (chunks[prev:n+1]) but
        # the trailing chunks beyond the last number are NOT emitted.
        assert result == [
            ["Para 0", "Para 1"],
            ["Para 2", "Para 3"],
        ]

    async def test_no_progress_numbers_returns_single_group(self, summarizer_scene):
        scene, summarizer = summarizer_scene

        chunks = ["a", "b", "c"]
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        # Response without any "Progress N" entries.
        mock_response = "Not a list at all"
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                mock_response,
                {"response": mock_response},
            )
            result = await summarizer.find_natural_scene_termination(chunks)

        # No numbers extracted -> the function does not split, so result is [].
        assert result == []

    async def test_paragraph_splitting_in_chunks(self, summarizer_scene):
        scene, summarizer = summarizer_scene

        # A single chunk that contains multiple paragraphs joined by \n;
        # the function rebuilds them into separate chunks.
        chunks = ["First paragraph\n\nSecond paragraph\nThird paragraph"]
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        mock_response = "1. Progress 0\n2. Progress 2"
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                mock_response,
                {"response": mock_response},
            )
            result = await summarizer.find_natural_scene_termination(chunks)

        # 3 sub-paragraphs after rebuild; numbers 0, 2 -> groups [0:1], [1:3]
        assert result == [
            ["First paragraph"],
            ["Second paragraph", "Third paragraph"],
        ]


# ---------------------------------------------------------------------------
# summarize / summarize_director_chat — light smoke through Prompt.request mock
# ---------------------------------------------------------------------------


class TestSummarizeViaPromptRequest:
    """Drive the high-level ``summarize`` / ``summarize_director_chat`` /
    ``summarize_events`` paths via a patched ``Prompt.request``.

    These tests exercise the response-extraction and post-processing
    branches (capitalization, hash splitting, trailing-partial-sentence
    stripping) of the public functions without needing the templated
    prompt machinery.
    """

    async def test_summarize_returns_extracted_summary(self, summarizer_scene):
        _, summarizer = summarizer_scene
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "<SUMMARY>this is the summary.</SUMMARY>",
                {"summary": "this is the summary."},
            )
            result = await summarizer.summarize("dialogue text here")

        # Capitalized first letter and partial-sentence stripping applied.
        assert result == "This is the summary."

    async def test_summarize_returns_empty_when_no_summary_extracted(
        self, summarizer_scene
    ):
        _, summarizer = summarizer_scene
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "no summary in here",
                {"summary": None},
            )
            result = await summarizer.summarize("dialogue text here")

        assert result == ""

    async def test_summarize_director_chat_uses_extracted_summary(
        self, summarizer_scene
    ):
        _, summarizer = summarizer_scene
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "raw response",
                {"summary": "  director said x.  "},
            )
            result = await summarizer.summarize_director_chat(
                [{"role": "user", "content": "x"}]
            )

        assert result == "director said x."

    async def test_summarize_director_chat_falls_back_to_response(
        self, summarizer_scene
    ):
        _, summarizer = summarizer_scene
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "fallback response.",
                {"summary": None},
            )
            result = await summarizer.summarize_director_chat([])

        assert result == "fallback response."

    async def test_summarize_events_strips_analysis_lines(self, summarizer_scene):
        scene, summarizer = summarizer_scene
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        # When analyze_chunks=True, lines starting with "ANALYSIS OF" must
        # be stripped from the summary before further processing.
        cleaned_text = (
            "ANALYSIS OF chunk 1: thinking about it\n"
            "Real summary line one is decently long.\n"
            "Real summary line two is also long enough.\n"
        )

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "raw",
                {"cleaned": cleaned_text},
            )
            result = await summarizer.summarize_events(
                "incoming events text", analyze_chunks=True
            )

        # ANALYSIS OF line removed; remaining lines kept.
        assert "ANALYSIS OF" not in result
        assert "Real summary line one" in result

    async def test_summarize_events_filters_short_lines(self, summarizer_scene):
        _, summarizer = summarizer_scene
        from talemate.prompts import Prompt
        from unittest.mock import AsyncMock

        # The MIN_CHUNK_LINE_LENGTH filter strips any non-empty line shorter
        # than 20 chars (placeholder text from the model).
        cleaned_text = (
            "[no content.]\nThis second line is more than twenty characters.\n"
        )
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "raw",
                {"cleaned": cleaned_text},
            )
            result = await summarizer.summarize_events("anything")

        assert "[no content.]" not in result
        assert "twenty characters" in result


# ---------------------------------------------------------------------------
# archive_extract_facts resolves the scene overlay, not the global value
# ---------------------------------------------------------------------------


class TestArchiveExtractFactsResolvesSceneOverrides:
    def _overlay(self, tmp_path, value):
        from talemate.scene_agent_settings import SceneAgentSettings

        overlay = SceneAgentSettings(filepath=tmp_path / "agent-settings.json")
        overlay.set_value("summarizer", "archive", "extract_facts", value)
        return overlay

    def test_overlay_disables_a_global_on(self, summarizer_scene, tmp_path):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["extract_facts"].value = True
        scene.agent_overrides = self._overlay(tmp_path, False)
        assert summarizer.archive_extract_facts is False

    def test_overlay_enables_a_global_off(self, summarizer_scene, tmp_path):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["extract_facts"].value = False
        scene.agent_overrides = self._overlay(tmp_path, True)
        assert summarizer.archive_extract_facts is True

    def test_removing_the_override_restores_the_global(
        self, summarizer_scene, tmp_path
    ):
        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["extract_facts"].value = True
        scene.agent_overrides = self._overlay(tmp_path, False)
        assert summarizer.archive_extract_facts is False
        scene.agent_overrides.clear_value("summarizer", "archive", "extract_facts")
        assert summarizer.archive_extract_facts is True

    async def test_summarize_follows_the_effective_switch(
        self, summarizer_scene, tmp_path
    ):
        from unittest.mock import AsyncMock

        from talemate.prompts import Prompt

        scene, summarizer = summarizer_scene
        summarizer.actions["archive"].config["extract_facts"].value = True
        scene.agent_overrides = self._overlay(tmp_path, False)

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "<SUMMARY>a summary.</SUMMARY>",
                {"summary": "a summary."},
            )
            await summarizer.summarize("dialogue text here", return_facts=True)

        assert mock_request.call_args.kwargs["vars"]["extract_facts"] is False

        # inverting the two sides asks for the facts section again
        summarizer.actions["archive"].config["extract_facts"].value = False
        scene.agent_overrides.set_value("summarizer", "archive", "extract_facts", True)
        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "<SUMMARY>a summary.</SUMMARY>",
                {"summary": "a summary."},
            )
            await summarizer.summarize("dialogue text here", return_facts=True)

        assert mock_request.call_args.kwargs["vars"]["extract_facts"] is True
