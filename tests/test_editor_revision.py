"""
Tests for ``talemate.agents.editor.revision`` (the RevisionMixin and helpers).

Targets:
- Pure helpers: ``_strip_character_prefix``, ``_reattach_character_prefix``,
  ``_format_length_ratio``, ``_revision_exceeds_max_length``.
- Schema/property behavior: ``Issues.log``, ``RevisionInformation``, the
  context managers (``RevisionDisabled``, ``RevisionContext``).
- RevisionMixin: action registration, config property helpers,
  ``revision_collect_repetition_range``, ``revision_detect_bad_prose`` (regex
  branch), ``revision_collect_issues`` for the fuzzy path,
  ``revision_dedupe`` (full happy-path and reduction-too-high path),
  ``revision_revise`` dispatch + GenerationCancelled handling, the
  non-SceneMessage signal hook ``revision_on_generation``, and the
  push_history-time hooks ``maybe_revise_inplace`` / ``revision_on_push``.
- Async LLM-driven paths (``revision_rewrite``, ``revision_unslop``) are not
  exhaustively driven through Prompt.request; they rely on too much template
  plumbing. Those are covered indirectly via the dispatch tests.
"""

import pytest

from talemate.agents.creator.assistant import (
    ContentGenerationContext,
    ContextualGenerateEmission,
)
from talemate.agents.editor.revision import (
    CONTEXTUAL_GENERATION_TYPES,
    Issues,
    RevisionContext,
    RevisionDisabled,
    RevisionInformation,
    _format_length_ratio,
    _reattach_character_prefix,
    _revision_exceeds_max_length,
    _strip_character_prefix,
    revision_context,
    revision_disabled_context,
)
from talemate.agents.summarize import SummarizeEmission
from talemate.character import Character
from talemate.events import HistoryEvent
from talemate.exceptions import GenerationCancelled
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    DirectorMessage,
    MessageVersion,
    NarratorMessage,
)
from talemate.world_state.templates.content import PhraseDetection, WritingStyle

from conftest import MockScene, bootstrap_scene


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alice():
    return Character(name="Alice", description="A test character.")


def _make_contextual_emission(editor, context_str: str) -> ContextualGenerateEmission:
    """Build a ContextualGenerateEmission with a real ContentGenerationContext.

    The ``context_type``/``context_name`` are computed properties that read
    from the inner ``ContentGenerationContext.context`` (in ``"type:name"``
    form), so we wire that up here rather than passing keyword args directly.
    """
    return ContextualGenerateEmission(
        agent=editor,
        response="some text",
        content_generation_context=ContentGenerationContext(context=context_str),
    )


class _SceneWithWritingStyle(MockScene):
    """MockScene that allows ``writing_style`` to be set as an attribute.

    The base ``Scene`` exposes ``writing_style`` as a read-only property
    that resolves through ``writing_style_template`` and the world-state
    template collection. For unit tests we want to plug in a
    ``WritingStyle`` directly without a template store, so override the
    property with a mutable attribute.
    """

    _writing_style: WritingStyle | None = None

    @property
    def writing_style(self):  # type: ignore[override]
        return self._writing_style

    @writing_style.setter
    def writing_style(self, value):
        self._writing_style = value


@pytest.fixture
def editor_scene():
    """A bootstrapped scene with the editor (RevisionMixin) wired up."""
    scene = _SceneWithWritingStyle()
    agents = bootstrap_scene(scene)
    editor = agents["editor"]
    # Enable the revision action so config helpers reflect the actual action.
    editor.actions["revision"].enabled = True
    return scene, editor


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestStripAndReattachCharacterPrefix:
    def test_strip_character_prefix_match(self, alice):
        text = "Alice: Hello there"
        body, had = _strip_character_prefix(text, alice)
        assert body == "Hello there"
        assert had is True

    def test_strip_character_prefix_no_match(self, alice):
        text = "Bob: Hello there"
        body, had = _strip_character_prefix(text, alice)
        assert body == text
        assert had is False

    def test_strip_character_prefix_no_character(self):
        text = "Alice: Hi"
        body, had = _strip_character_prefix(text, None)
        assert body == text
        assert had is False

    def test_reattach_character_prefix_when_missing(self, alice):
        result = _reattach_character_prefix("Hi there", alice, had_prefix=True)
        assert result == "Alice: Hi there"

    def test_reattach_character_prefix_idempotent(self, alice):
        # If model already included the prefix, do not double it up.
        result = _reattach_character_prefix("Alice: Hi there", alice, had_prefix=True)
        assert result == "Alice: Hi there"

    def test_reattach_character_prefix_skipped_when_no_prefix_originally(self, alice):
        result = _reattach_character_prefix("Hi", alice, had_prefix=False)
        assert result == "Hi"

    def test_reattach_character_prefix_no_character(self):
        # Without a character, return text unchanged even if had_prefix=True.
        result = _reattach_character_prefix("Hi", None, had_prefix=True)
        assert result == "Hi"


class TestFormatLengthRatio:
    def test_zero_division_returns_inf(self):
        assert _format_length_ratio(10, 0) == "inf"

    def test_basic_ratio(self):
        assert _format_length_ratio(150, 100) == "1.50"

    def test_zero_new(self):
        assert _format_length_ratio(0, 100) == "0.00"


class TestRevisionExceedsMaxLength:
    def test_within_ratio_returns_false(self):
        # 100 -> 120 is within 1.25 ratio.
        assert (
            _revision_exceeds_max_length("test", "x" * 100, "y" * 120, ratio=1.25)
            is False
        )

    def test_at_ratio_returns_false(self):
        # Exactly at the ratio boundary -> not "exceeds".
        assert (
            _revision_exceeds_max_length("test", "x" * 100, "y" * 125, ratio=1.25)
            is False
        )

    def test_above_ratio_returns_true(self):
        assert (
            _revision_exceeds_max_length("test", "x" * 100, "y" * 200, ratio=1.25)
            is True
        )

    def test_empty_original_returns_true_when_revised_has_text(self):
        assert _revision_exceeds_max_length("test", "", "anything", ratio=1.25) is True


# ---------------------------------------------------------------------------
# Schema & context manager tests
# ---------------------------------------------------------------------------


class TestIssuesSchema:
    def test_log_combines_repetition_and_bad_prose(self):
        issues = Issues(
            repetition_log=["rep-a", "rep-b"],
            bad_prose_log=["bp-a"],
        )
        assert issues.log == ["rep-a", "rep-b", "bp-a"]

    def test_empty_log(self):
        assert Issues().log == []

    def test_repetition_matches_default_empty(self):
        assert Issues().repetition_matches == []


class TestRevisionInformationDefaults:
    def test_defaults(self):
        info = RevisionInformation()
        assert info.text is None
        assert info.character is None
        assert info.context_type is None
        assert info.summarization_history is None
        assert info.revision_method is None

    def test_loading_status_excluded_from_dump(self):
        info = RevisionInformation(text="hi")
        dumped = info.model_dump()
        assert "loading_status" not in dumped
        assert dumped["text"] == "hi"


class TestRevisionDisabledContext:
    def test_disabled_inside_context_manager(self):
        assert revision_disabled_context.get() is False
        with RevisionDisabled():
            assert revision_disabled_context.get() is True
        assert revision_disabled_context.get() is False


class TestRevisionContext:
    def test_message_id_set_inside_context_manager(self):
        # default state has message_id=None
        assert revision_context.get().message_id is None
        with RevisionContext(message_id=42):
            assert revision_context.get().message_id == 42
        assert revision_context.get().message_id is None

    def test_no_message_id_inside_context_manager(self):
        with RevisionContext(message_id=None):
            assert revision_context.get().message_id is None


# ---------------------------------------------------------------------------
# Action registration & config helpers
# ---------------------------------------------------------------------------


class TestRevisionActionRegistration:
    def test_action_present_with_expected_keys(self, editor_scene):
        _, editor = editor_scene
        action = editor.actions["revision"]
        assert action.label == "Revision"
        assert action.icon == "mdi-typewriter"
        for key in [
            "automatic_revision",
            "automatic_revision_targets",
            "revision_method",
            "split_on_comma",
            "min_issues",
            "detect_bad_prose",
            "detect_bad_prose_threshold",
            "repetition_detection_method",
            "repetition_threshold",
            "repetition_range",
            "repetition_min_length",
            "repetition_handling",
        ]:
            assert key in action.config

    def test_default_method_is_unslop(self, editor_scene):
        _, editor = editor_scene
        assert editor.revision_method == "unslop"

    def test_property_helpers_match_config(self, editor_scene):
        _, editor = editor_scene
        # Set a few config values and confirm property accessors mirror them.
        editor.actions["revision"].config["repetition_threshold"].value = 90
        editor.actions["revision"].config["repetition_range"].value = 5
        editor.actions["revision"].config["repetition_min_length"].value = 25
        editor.actions["revision"].config["min_issues"].value = 2
        editor.actions["revision"].config["split_on_comma"].value = False
        editor.actions["revision"].config["detect_bad_prose"].value = False
        editor.actions["revision"].config["detect_bad_prose_threshold"].value = 0.8
        editor.actions["revision"].config["automatic_revision"].value = False
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator"
        ]
        editor.actions["revision"].config["repetition_detection_method"].value = "fuzzy"
        editor.actions["revision"].config["repetition_handling"].value = "rewrite"

        assert editor.revision_repetition_threshold == 90
        assert editor.revision_repetition_range == 5
        assert editor.revision_repetition_min_length == 25
        assert editor.revision_min_issues == 2
        assert editor.revision_split_on_comma is False
        assert editor.revision_detect_bad_prose_enabled is False
        assert editor.revision_detect_bad_prose_threshold == 0.8
        assert editor.revision_automatic_enabled is False
        assert editor.revision_automatic_targets == ["narrator"]
        assert editor.revision_repetition_detection_method == "fuzzy"
        assert editor.revision_repetition_handling == "rewrite"
        assert editor.revision_enabled is True


# ---------------------------------------------------------------------------
# revision_collect_repetition_range
# ---------------------------------------------------------------------------


class TestCollectRepetitionRange:
    async def test_collects_character_messages_without_name(self, editor_scene):
        scene, editor = editor_scene
        scene.history = [
            CharacterMessage(message="Alice: Hello there", source="ai"),
            CharacterMessage(message="Bob: Hi back", source="ai"),
            NarratorMessage(message="The wind blows.", source="ai"),
        ]
        editor.actions["revision"].config["repetition_range"].value = 10

        result = await editor.revision_collect_repetition_range()

        # CharacterMessage uses without_name (everything after the colon),
        # NarratorMessage falls into the else branch and uses .message.
        assert any("Hello there" in r for r in result)
        assert any("Hi back" in r for r in result)
        assert any("The wind blows." in r for r in result)
        # Verify CharacterMessage prefix is stripped.
        assert all("Alice:" not in r for r in result)
        assert all("Bob:" not in r for r in result)

    async def test_respects_repetition_range_limit(self, editor_scene):
        scene, editor = editor_scene
        scene.history = [
            CharacterMessage(message=f"Alice: m{i}", source="ai") for i in range(20)
        ]
        editor.actions["revision"].config["repetition_range"].value = 3

        result = await editor.revision_collect_repetition_range()
        assert len(result) == 3

    async def test_empty_history_returns_empty_list(self, editor_scene):
        scene, editor = editor_scene
        scene.history = []
        result = await editor.revision_collect_repetition_range()
        assert result == []

    async def test_includes_context_investigation_messages(self, editor_scene):
        """CIMs are part of the narrative surface and must contribute to
        the repetition corpus regardless of the auto-revision target flag."""
        scene, editor = editor_scene
        scene.history = [
            NarratorMessage(message="The wind blows.", source="ai"),
            ContextInvestigationMessage(message="a closer look at the lantern"),
            DirectorMessage(message="Direct the scene toward dusk."),
        ]
        editor.actions["revision"].config["repetition_range"].value = 10

        result = await editor.revision_collect_repetition_range()

        assert any("The wind blows." in r for r in result)
        assert any("closer look at the lantern" in r for r in result)
        assert all("Direct the scene" not in r for r in result)

    async def test_excludes_context_message_and_anything_after(self, editor_scene):
        """A ``RevisionContext`` excludes the message under revision (and
        anything after it) from the comparison range."""
        scene, editor = editor_scene
        target = NarratorMessage(message="the target message", source="ai")
        scene.history = [
            NarratorMessage(message="earlier one", source="ai"),
            target,
            NarratorMessage(message="later one", source="ai"),
        ]
        editor.actions["revision"].config["repetition_range"].value = 10

        with RevisionContext(message_id=target.id):
            result = await editor.revision_collect_repetition_range()

        assert any("earlier one" in r for r in result)
        assert all("the target message" not in r for r in result)
        assert all("later one" not in r for r in result)


# ---------------------------------------------------------------------------
# revision_detect_bad_prose (regex branch)
# ---------------------------------------------------------------------------


class TestRevisionDetectBadProseRegex:
    async def test_returns_empty_when_no_writing_style(self, editor_scene):
        _, editor = editor_scene
        editor.scene.writing_style = None
        result = await editor.revision_detect_bad_prose("anything")
        assert result == []

    async def test_returns_empty_when_writing_style_has_no_phrases(self, editor_scene):
        _, editor = editor_scene
        editor.scene.writing_style = WritingStyle(
            name="empty", description="x", phrases=[]
        )
        assert await editor.revision_detect_bad_prose("anything") == []

    async def test_regex_match_returns_identified_phrase(self, editor_scene):
        _, editor = editor_scene
        # Use regex method to keep this offline (no embedding needed).
        # The split_on_comma flag transforms sentences into bare strings
        # before the regex helper runs.
        editor.actions["revision"].config["split_on_comma"].value = True
        editor.scene.writing_style = WritingStyle(
            name="ws",
            description="d",
            phrases=[
                PhraseDetection(
                    phrase="purple prose",
                    instructions="Avoid this exact wording.",
                    classification="unwanted",
                    match_method="regex",
                    active=True,
                )
            ],
        )
        # The bad-prose helper unconditionally calls the memory agent's
        # semantic-similarity path even when no semantic-similarity phrases
        # are configured. Stub it out to keep this regex test self-contained.
        from talemate.instance import get_agent

        async def empty_compare(a, b, similarity_threshold=None):
            return {"similarity_matches": []}

        get_agent("memory").compare_string_lists = empty_compare

        result = await editor.revision_detect_bad_prose(
            "She wrote some purple prose for fun."
        )
        assert len(result) == 1
        assert result[0]["matched"] == "purple prose"
        assert result[0]["method"] == "regex"
        assert result[0]["instructions"] == "Avoid this exact wording."

    async def test_inactive_phrases_skipped(self, editor_scene):
        _, editor = editor_scene
        editor.scene.writing_style = WritingStyle(
            name="ws",
            description="d",
            phrases=[
                PhraseDetection(
                    phrase="purple prose",
                    instructions="x",
                    classification="unwanted",
                    match_method="regex",
                    active=False,
                )
            ],
        )
        from talemate.instance import get_agent

        async def empty_compare(a, b, similarity_threshold=None):
            return {"similarity_matches": []}

        get_agent("memory").compare_string_lists = empty_compare

        assert await editor.revision_detect_bad_prose("purple prose abound") == []


# ---------------------------------------------------------------------------
# revision_collect_issues — fuzzy path (no embeddings required)
# ---------------------------------------------------------------------------


class TestRevisionCollectIssuesFuzzy:
    async def test_no_repetition_returns_empty_issues(self, editor_scene, alice):
        scene, editor = editor_scene
        scene.history = []
        editor.actions["revision"].config["repetition_detection_method"].value = "fuzzy"
        editor.scene.writing_style = None
        issues = await editor.revision_collect_issues(
            "Brand new sentence that has nothing matched.", alice
        )
        assert issues.repetition == []
        assert issues.repetition_matches == []
        assert issues.repetition_log == []
        assert issues.bad_prose_log == []
        assert issues.bad_prose == []

    async def test_repetition_detected_via_fuzzy(self, editor_scene, alice):
        scene, editor = editor_scene
        # Build a duplicate sentence in scene history -> the same sentence in
        # incoming text should fuzzy-match against it.
        repeated = "She walked into the dim garden and breathed deeply."
        scene.history = [CharacterMessage(message=f"Alice: {repeated}", source="ai")]
        editor.actions["revision"].config["repetition_detection_method"].value = "fuzzy"
        editor.actions["revision"].config["repetition_threshold"].value = 80
        editor.actions["revision"].config["repetition_range"].value = 5
        editor.actions["revision"].config["repetition_min_length"].value = 5
        editor.scene.writing_style = None

        issues = await editor.revision_collect_issues(repeated, alice)
        assert issues.repetition_matches, "expected at least one fuzzy match"
        assert any("Repetition" in line for line in issues.repetition_log)


# ---------------------------------------------------------------------------
# revision_dedupe
# ---------------------------------------------------------------------------


class TestRevisionDedupe:
    async def test_no_repetition_returns_original(self, editor_scene, alice):
        scene, editor = editor_scene
        editor.actions["revision"].config["repetition_detection_method"].value = "fuzzy"
        editor.scene.writing_style = None
        scene.history = []

        info = RevisionInformation(
            text="Alice: A unique line that has not been said before.",
            character=alice,
        )
        result = await editor.revision_dedupe(info)
        assert result == info.text

    async def test_repetition_dedupes_and_preserves_prefix(self, editor_scene, alice):
        scene, editor = editor_scene
        editor.actions["revision"].config["repetition_detection_method"].value = "fuzzy"
        editor.actions["revision"].config["repetition_threshold"].value = 90
        editor.actions["revision"].config["repetition_range"].value = 10
        editor.actions["revision"].config["repetition_min_length"].value = 5
        editor.scene.writing_style = None

        repeated = "She walked into the dim garden and breathed deeply."
        unique = "Then she pulled out a tiny brass key."
        scene.history = [
            CharacterMessage(message=f"Alice: {repeated}", source="ai"),
        ]
        info = RevisionInformation(
            text=f"Alice: {repeated} {unique}",
            character=alice,
        )
        result = await editor.revision_dedupe(info)
        # Prefix preserved.
        assert result.startswith("Alice: ")
        # Repeated sentence removed; unique sentence preserved.
        assert unique in result
        # Method marker set.
        assert info.revision_method == "dedupe"


# ---------------------------------------------------------------------------
# revision_revise — dispatch & error handling
# ---------------------------------------------------------------------------


class TestRevisionReviseDispatch:
    async def test_dispatch_dedupe(self, editor_scene, alice):
        _, editor = editor_scene
        editor.actions["revision"].config["revision_method"].value = "dedupe"
        called = {}

        async def fake_dedupe(info):
            called["dedupe"] = info
            return "DEDUPED"

        editor.revision_dedupe = fake_dedupe

        info = RevisionInformation(text="some text", character=alice)
        result = await editor.revision_revise(info)
        assert result == "DEDUPED"
        assert called["dedupe"] is info

    async def test_dispatch_rewrite(self, editor_scene, alice):
        _, editor = editor_scene
        editor.actions["revision"].config["revision_method"].value = "rewrite"

        async def fake_rewrite(info):
            return "REWRITTEN"

        editor.revision_rewrite = fake_rewrite
        info = RevisionInformation(text="orig", character=alice)
        assert await editor.revision_revise(info) == "REWRITTEN"

    async def test_dispatch_unslop(self, editor_scene, alice):
        _, editor = editor_scene
        editor.actions["revision"].config["revision_method"].value = "unslop"

        async def fake_unslop(info):
            return "UNSLOPPED"

        editor.revision_unslop = fake_unslop
        info = RevisionInformation(text="orig", character=alice)
        assert await editor.revision_revise(info) == "UNSLOPPED"

    async def test_generation_cancelled_returns_original_text(
        self, editor_scene, alice
    ):
        _, editor = editor_scene
        editor.actions["revision"].config["revision_method"].value = "dedupe"

        async def cancelling(info):
            raise GenerationCancelled("cancelled")

        editor.revision_dedupe = cancelling
        info = RevisionInformation(text="ORIGINAL", character=alice)
        result = await editor.revision_revise(info)
        assert result == "ORIGINAL"

    async def test_other_exception_returns_original_text(self, editor_scene, alice):
        _, editor = editor_scene
        editor.actions["revision"].config["revision_method"].value = "dedupe"

        async def failing(info):
            raise RuntimeError("oops")

        editor.revision_dedupe = failing
        info = RevisionInformation(text="ORIGINAL", character=alice)
        result = await editor.revision_revise(info)
        assert result == "ORIGINAL"


# ---------------------------------------------------------------------------
# revision_on_generation — filter logic (non-SceneMessage emissions)
# ---------------------------------------------------------------------------


class TestRevisionOnGeneration:
    """Verify filter / branching logic of revision_on_generation.

    Character / narrator emissions are NOT handled here anymore — those run
    at push_history time via ``maybe_revise_inplace`` / ``revision_on_push``.
    These tests focus on the remaining emission types: contextual generation
    and summarization.
    """

    @pytest.fixture
    def stub_revise(self, editor_scene):
        scene, editor = editor_scene
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["automatic_revision"].value = True

        calls = []

        async def fake_revise(info):
            calls.append(info)
            return "REVISED"

        editor.revision_revise = fake_revise
        return scene, editor, calls

    async def test_skipped_when_disabled(self, editor_scene):
        _, editor = editor_scene
        editor.actions["revision"].enabled = False
        called = []

        async def revise_spy(info):
            called.append(info)
            return "X"

        editor.revision_revise = revise_spy

        emission = SummarizeEmission(
            agent=editor,
            response="hi",
            summarization_type="dialogue",
        )
        await editor.revision_on_generation(emission)
        assert called == []
        # The original response is left untouched.
        assert emission.response == "hi"

    async def test_skipped_when_automatic_off(self, editor_scene):
        _, editor = editor_scene
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["automatic_revision"].value = False
        called = []

        async def spy(info):
            called.append(info)
            return "X"

        editor.revision_revise = spy
        emission = SummarizeEmission(
            agent=editor,
            response="hi",
            summarization_type="dialogue",
        )
        await editor.revision_on_generation(emission)
        assert called == []

    async def test_filter_contextual_generation_target_disabled(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "character"
        ]
        emission = _make_contextual_emission(editor, "character attribute:age")
        await editor.revision_on_generation(emission)
        assert calls == []

    async def test_contextual_generation_unknown_type_skipped(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "contextual_generation"
        ]
        emission = _make_contextual_emission(editor, "not-a-real-type:x")
        await editor.revision_on_generation(emission)
        assert calls == []

    async def test_contextual_generation_known_type_runs(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "contextual_generation"
        ]
        emission = _make_contextual_emission(
            editor, f"{CONTEXTUAL_GENERATION_TYPES[0]}:x"
        )
        await editor.revision_on_generation(emission)
        assert len(calls) == 1

    async def test_summarize_dialogue_filtered_when_summarization_target_off(
        self, stub_revise
    ):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "character"
        ]
        emission = SummarizeEmission(
            agent=editor,
            response="summary",
            summarization_type="dialogue",
            summarization_history=["prev1"],
        )
        await editor.revision_on_generation(emission)
        assert calls == []

    async def test_summarize_dialogue_runs_when_summarization_target_on(
        self, stub_revise
    ):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "summarization"
        ]
        emission = SummarizeEmission(
            agent=editor,
            response="summary",
            summarization_type="dialogue",
            summarization_history=["prev1"],
        )
        await editor.revision_on_generation(emission)
        assert len(calls) == 1
        assert calls[0].summarization_history == ["prev1"]

    async def test_summarize_events_always_skipped(self, stub_revise):
        """Event summarization is hard-coded as skipped regardless of target."""
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "summarization"
        ]
        emission = SummarizeEmission(
            agent=editor,
            response="summary",
            summarization_type="events",
        )
        await editor.revision_on_generation(emission)
        assert calls == []

    async def test_disabled_through_context_manager(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "summarization"
        ]
        emission = SummarizeEmission(
            agent=editor,
            response="orig",
            summarization_type="dialogue",
        )
        with RevisionDisabled():
            await editor.revision_on_generation(emission)
        assert calls == []
        assert emission.response == "orig"


# ---------------------------------------------------------------------------
# maybe_revise_inplace — character / narrator messages at push_history time
# ---------------------------------------------------------------------------


class TestMaybeReviseInplace:
    """Verify the push-time auto-revision hook for SceneMessages.

    Character/narrator revision happens here (not in revision_on_generation)
    so the SceneMessage object is in hand and the revised text can be
    appended to ``message.versions`` as a new active entry.
    """

    @pytest.fixture
    def stub_revise(self, editor_scene):
        scene, editor = editor_scene
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["automatic_revision"].value = True

        calls = []

        async def fake_revise(info):
            calls.append(info)
            return "REVISED"

        editor.revision_revise = fake_revise
        return scene, editor, calls

    async def test_skipped_when_disabled(self, editor_scene):
        _, editor = editor_scene
        editor.actions["revision"].enabled = False

        called = []

        async def spy(info):
            called.append(info)
            return "X"

        editor.revision_revise = spy
        msg = NarratorMessage(message="orig narrator", source="ai")
        assert await editor.maybe_revise_inplace(msg) is False
        assert called == []
        assert msg.message == "orig narrator"

    async def test_skipped_when_automatic_off(self, editor_scene):
        _, editor = editor_scene
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["automatic_revision"].value = False

        called = []

        async def spy(info):
            called.append(info)
            return "X"

        editor.revision_revise = spy
        msg = NarratorMessage(message="orig narrator", source="ai")
        assert await editor.maybe_revise_inplace(msg) is False
        assert called == []

    async def test_returns_false_for_unsupported_message_type(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "character",
            "narrator",
            "context_investigation",
        ]
        msg = DirectorMessage(message="dir")
        assert await editor.maybe_revise_inplace(msg) is False
        assert calls == []

    async def test_character_target_disabled_skips_message(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator"
        ]
        msg = CharacterMessage(message="Alice: hi")
        assert await editor.maybe_revise_inplace(msg) is False
        assert calls == []

    async def test_narrator_target_disabled_skips_message(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "character"
        ]
        msg = NarratorMessage(message="The wind blows.")
        assert await editor.maybe_revise_inplace(msg) is False
        assert calls == []

    async def test_narrator_target_enabled_appends_revised_version(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator"
        ]
        msg = NarratorMessage(message="orig narrator")
        assert await editor.maybe_revise_inplace(msg) is True
        assert msg.message == "REVISED"
        # Original stays on the stack as the seeded "original" entry;
        # the revision is appended and becomes active.
        assert msg.versions == [
            MessageVersion(message="orig narrator", source="original"),
            MessageVersion(message="REVISED", source="revision"),
        ]
        assert msg.active_version == 1
        assert len(calls) == 1
        assert calls[0].text == "orig narrator"
        # Narrator messages have no character context.
        assert calls[0].character is None

    async def test_character_target_enabled_resolves_character_and_appends(
        self, stub_revise, alice, monkeypatch
    ):
        scene, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "character"
        ]
        # Patch get_character — building a full Actor on the scene needs
        # more wiring than this test cares about.
        monkeypatch.setattr(
            scene, "get_character", lambda name: alice if name == "Alice" else None
        )

        msg = CharacterMessage(message="Alice: orig")
        assert await editor.maybe_revise_inplace(msg) is True
        assert msg.message == "REVISED"
        assert msg.versions == [
            MessageVersion(message="Alice: orig", source="original"),
            MessageVersion(message="REVISED", source="revision"),
        ]
        assert msg.active_version == 1
        assert len(calls) == 1
        assert calls[0].text == "Alice: orig"
        assert calls[0].character is alice

    async def test_player_authored_character_message_is_skipped(self, stub_revise):
        """Player input must not be auto-revised."""
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "character"
        ]
        msg = CharacterMessage(message="Alice: hi", source="player")
        assert await editor.maybe_revise_inplace(msg) is False
        assert calls == []
        assert msg.message == "Alice: hi"

    async def test_player_authored_narrator_message_is_skipped(self, stub_revise):
        """Player-authored narration must not be auto-revised either."""
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator"
        ]
        msg = NarratorMessage(message="The wind blows.", source="player")
        assert await editor.maybe_revise_inplace(msg) is False
        assert calls == []
        assert msg.message == "The wind blows."

    async def test_context_investigation_target_disabled_skips_message(
        self, stub_revise
    ):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "character",
            "narrator",
        ]
        msg = ContextInvestigationMessage(message="ctx")
        assert await editor.maybe_revise_inplace(msg) is False
        assert calls == []

    async def test_context_investigation_target_enabled_appends_revised_version(
        self, stub_revise
    ):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "context_investigation"
        ]
        msg = ContextInvestigationMessage(message="orig ctx")
        assert await editor.maybe_revise_inplace(msg) is True
        assert msg.message == "REVISED"
        assert msg.versions == [
            MessageVersion(message="orig ctx", source="original"),
            MessageVersion(message="REVISED", source="revision"),
        ]
        assert msg.active_version == 1
        assert len(calls) == 1
        assert calls[0].text == "orig ctx"
        assert calls[0].character is None

    async def test_returns_false_when_revision_is_noop(self, editor_scene):
        _, editor = editor_scene
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["automatic_revision"].value = True
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator"
        ]

        async def identity(info):
            return info.text

        editor.revision_revise = identity
        msg = NarratorMessage(message="unchanged")
        assert await editor.maybe_revise_inplace(msg) is False
        assert msg.message == "unchanged"
        # No new version appended — only the seeded original remains.
        assert msg.versions == [MessageVersion(message="unchanged", source="original")]

    async def test_disabled_through_context_manager(self, stub_revise):
        _, editor, calls = stub_revise
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator"
        ]
        msg = NarratorMessage(message="orig")
        with RevisionDisabled():
            assert await editor.maybe_revise_inplace(msg) is False
        assert calls == []
        assert msg.message == "orig"


# ---------------------------------------------------------------------------
# revision_on_push — push_history signal handler
# ---------------------------------------------------------------------------


class TestRevisionOnPush:
    """Verify revision_on_push appends the revised text as a new version."""

    @pytest.fixture
    def stub_revise_narrator(self, editor_scene):
        scene, editor = editor_scene
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["automatic_revision"].value = True
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator",
            "character",
        ]

        async def fake_revise(info):
            return f"REVISED({info.text})"

        editor.revision_revise = fake_revise
        return scene, editor

    async def test_narrator_message_revised_and_version_appended(
        self, stub_revise_narrator
    ):
        scene, editor = stub_revise_narrator
        msg = NarratorMessage(message="orig narrator")
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[msg])

        await editor.revision_on_push(event)

        assert msg.message == "REVISED(orig narrator)"
        # Original stays on the stack as the seeded entry; revised is
        # appended and becomes the active canonical.
        assert msg.versions == [
            MessageVersion(message="orig narrator", source="original"),
            MessageVersion(message="REVISED(orig narrator)", source="revision"),
        ]
        assert msg.active_version == 1

    async def test_character_message_revised_and_version_appended(
        self, stub_revise_narrator, alice, monkeypatch
    ):
        scene, editor = stub_revise_narrator
        monkeypatch.setattr(
            scene, "get_character", lambda name: alice if name == "Alice" else None
        )

        msg = CharacterMessage(message="Alice: hello")
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[msg])

        await editor.revision_on_push(event)

        assert msg.message == "REVISED(Alice: hello)"
        assert msg.versions == [
            MessageVersion(message="Alice: hello", source="original"),
            MessageVersion(message="REVISED(Alice: hello)", source="revision"),
        ]
        assert msg.active_version == 1

    async def test_no_new_version_when_revision_noop(self, editor_scene):
        scene, editor = editor_scene
        editor.actions["revision"].enabled = True
        editor.actions["revision"].config["automatic_revision"].value = True
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "narrator"
        ]

        async def identity(info):
            return info.text

        editor.revision_revise = identity
        msg = NarratorMessage(message="unchanged")
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[msg])

        await editor.revision_on_push(event)

        assert msg.message == "unchanged"
        # Only the seeded "original" entry remains.
        assert msg.versions == [MessageVersion(message="unchanged", source="original")]
        assert msg.active_version == 0

    async def test_non_target_message_is_ignored(self, stub_revise_narrator):
        scene, editor = stub_revise_narrator
        msg = DirectorMessage(message="dir")
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[msg])

        await editor.revision_on_push(event)

        assert msg.message == "dir"

    async def test_context_investigation_target_off_skips_cim(
        self, stub_revise_narrator
    ):
        scene, editor = stub_revise_narrator
        msg = ContextInvestigationMessage(message="ctx")
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[msg])

        await editor.revision_on_push(event)

        assert msg.message == "ctx"
        assert msg.versions == [MessageVersion(message="ctx", source="original")]

    async def test_context_investigation_target_on_revises_cim(
        self, stub_revise_narrator
    ):
        scene, editor = stub_revise_narrator
        editor.actions["revision"].config["automatic_revision_targets"].value = [
            "context_investigation"
        ]
        msg = ContextInvestigationMessage(message="orig ctx")
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[msg])

        await editor.revision_on_push(event)

        assert msg.message == "REVISED(orig ctx)"
        assert msg.versions == [
            MessageVersion(message="orig ctx", source="original"),
            MessageVersion(message="REVISED(orig ctx)", source="revision"),
        ]
        assert msg.active_version == 1

    async def test_only_first_matching_message_is_revised(self, stub_revise_narrator):
        """``push_history`` rarely batches narrator/character messages,
        but if it does, only the first one is processed (matches the
        single-target nature of revision)."""
        scene, editor = stub_revise_narrator

        m1 = NarratorMessage(message="first")
        m2 = NarratorMessage(message="second")
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[m1, m2])

        await editor.revision_on_push(event)

        assert m1.message == "REVISED(first)"
        assert m1.versions == [
            MessageVersion(message="first", source="original"),
            MessageVersion(message="REVISED(first)", source="revision"),
        ]
        # Second was left alone — still has just the seed.
        assert m2.message == "second"
        assert m2.versions == [MessageVersion(message="second", source="original")]

    async def test_revision_context_scoped_to_pushed_message(
        self, stub_revise_narrator
    ):
        """``revision_on_push`` scopes a ``RevisionContext`` to the pushed
        message so the repetition range can exclude it."""
        scene, editor = stub_revise_narrator

        seen_message_id = None

        async def capture_context(info):
            nonlocal seen_message_id
            seen_message_id = revision_context.get().message_id
            return info.text

        editor.revision_revise = capture_context

        msg = NarratorMessage(message="pushed narration")
        scene.history = [msg]
        event = HistoryEvent(scene=scene, event_type="push_history", messages=[msg])

        await editor.revision_on_push(event)

        assert seen_message_id == msg.id


# ---------------------------------------------------------------------------
# inject_prompt_paramters
# ---------------------------------------------------------------------------


class TestInjectPromptParameters:
    def test_revision_revise_initializes_extra_stopping_strings(self, editor_scene):
        _, editor = editor_scene
        params = {}
        editor.inject_prompt_paramters(params, "edit_512", "revision_revise")
        assert "extra_stopping_strings" in params
        # </FIX> is no longer injected — see commit 04a85847.
        assert "</FIX>" not in params["extra_stopping_strings"]

    def test_other_function_does_not_inject_fix_stop_string(self, editor_scene):
        _, editor = editor_scene
        params = {"extra_stopping_strings": ["BASE"]}
        editor.inject_prompt_paramters(params, "edit_512", "some_other_function")
        # Should not add </FIX> for non-matching functions.
        assert "</FIX>" not in params.get("extra_stopping_strings", [])
