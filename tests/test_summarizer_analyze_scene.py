"""
Tests for ``talemate.agents.summarize.analyze_scene`` (the
SceneAnalyzationMixin) and helpers.

Targets:
- Action registration & config helper properties (analyze_scene,
  analysis_length, cache_analysis, deep_analysis,
  analyze_scene_for_conversation, analyze_scene_for_narration).
- ``SceneAnalysisDisabled`` context manager.
- ``analyze_scene_sub_type`` dispatch (narration sub-type computed from
  active_agent state; conversation has no sub-type function and falls back
  to "").
- ``analyze_scene_narration_sub_type`` covers all branches.
- ``analyze_scene_rag_build_sub_instruction`` covers all branches.
- ``get_cached_analysis`` / ``set_cached_analysis`` round-trip through
  scene state, including fingerprint mismatch.
- ``on_inject_instructions`` filter behavior (disabled action, disabled
  per-type, cache hit path, cache miss falls back to LLM, disabled
  context manager).
- ``on_editor_revision_analysis_before`` injects scene analysis state.
- ``on_rag_build_sub_instruction`` populates emission only when truthy.

The deep-analysis branch of ``analyze_scene_for_next_action`` and the
templated Prompt.request flow are exercised via patched ``Prompt.request``
to avoid the templating pipeline.
"""

from unittest.mock import AsyncMock, patch

import pytest

from talemate.agents.base import (
    AgentTemplateEmission,
    RagBuildSubInstructionEmission,
)
from talemate.agents.context import ActiveAgent
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.narrator import NarratorAgentEmission
from talemate.agents.summarize.analyze_scene import (
    SceneAnalysisDisabled,
    scene_analysis_disabled_context,
)
from talemate.character import Character
from talemate.context import ActiveScene

from conftest import MockScene, bootstrap_scene


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alice():
    return Character(name="Alice", description="A test character.")


@pytest.fixture
def summarizer_scene():
    """Bootstrapped MockScene + summarizer with analyze_scene enabled."""
    scene = MockScene()
    agents = bootstrap_scene(scene)
    summarizer = agents["summarizer"]
    # Ensure the analyze_scene action is enabled by default for these tests.
    summarizer.actions["analyze_scene"].enabled = True

    with ActiveScene(scene):
        yield scene, summarizer


@pytest.fixture
def summarizer_with_active_agent(summarizer_scene):
    """``summarizer_scene`` plus an ActiveAgent context so that
    ``set_context_states`` / ``context_fingerprint`` work correctly.
    """
    scene, summarizer = summarizer_scene

    def dummy_fn():
        pass

    with ActiveAgent(summarizer, dummy_fn) as ctx:
        yield scene, summarizer, ctx


# ---------------------------------------------------------------------------
# Action registration & config helpers
# ---------------------------------------------------------------------------


class TestAnalyzeSceneActionRegistration:
    def test_action_present_with_expected_keys(self, summarizer_scene):
        _, summarizer = summarizer_scene
        action = summarizer.actions["analyze_scene"]
        assert action.label == "Scene Analysis"
        assert action.icon == "mdi-lightbulb"
        for key in [
            "analysis_length",
            "for_conversation",
            "for_narration",
            "deep_analysis",
            "cache_analysis",
        ]:
            assert key in action.config

    def test_property_helpers(self, summarizer_scene):
        _, summarizer = summarizer_scene
        assert summarizer.analyze_scene is True
        assert summarizer.analysis_length == 1024
        assert summarizer.cache_analysis is True
        assert summarizer.deep_analysis is False
        assert summarizer.analyze_scene_for_conversation is True
        assert summarizer.analyze_scene_for_narration is True

        # Mutate a config value and verify the property reflects it.
        summarizer.actions["analyze_scene"].config["analysis_length"].value = "256"
        assert summarizer.analysis_length == 256

        summarizer.actions["analyze_scene"].config["for_narration"].value = False
        assert summarizer.analyze_scene_for_narration is False


# ---------------------------------------------------------------------------
# SceneAnalysisDisabled context manager
# ---------------------------------------------------------------------------


class TestSceneAnalysisDisabledContext:
    def test_default_state_false(self):
        assert scene_analysis_disabled_context.get() is False

    def test_inside_block_state_true(self):
        with SceneAnalysisDisabled():
            assert scene_analysis_disabled_context.get() is True
        assert scene_analysis_disabled_context.get() is False


# ---------------------------------------------------------------------------
# Sub-type dispatch
# ---------------------------------------------------------------------------


class TestAnalyzeSceneSubType:
    async def test_unknown_type_returns_empty_string(self, summarizer_scene):
        _, summarizer = summarizer_scene
        # The conversation type has no analyze_scene_<typ>_sub_type method,
        # so the dispatch returns an empty string.
        assert await summarizer.analyze_scene_sub_type("conversation") == ""

    async def test_narration_dispatches_to_narration_sub_type(
        self, summarizer_with_active_agent
    ):
        _, summarizer, ctx = summarizer_with_active_agent
        # No state set -> "progress" default.
        assert await summarizer.analyze_scene_sub_type("narration") == "progress"


class TestAnalyzeSceneNarrationSubType:
    async def test_progress_default_with_no_active_context(self, summarizer_scene):
        _, summarizer = summarizer_scene
        # Without an ActiveAgent context, the function returns "progress"
        # via the early-return branch.
        assert await summarizer.analyze_scene_narration_sub_type() == "progress"

    async def test_query_branch(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__query_narration"] = True
        assert await summarizer.analyze_scene_narration_sub_type() == "query"

    async def test_sensory_branch(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__sensory_narration"] = True
        assert await summarizer.analyze_scene_narration_sub_type() == "sensory"

    async def test_visual_branch(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__visual_narration"] = True
        assert await summarizer.analyze_scene_narration_sub_type() == "visual"

    async def test_visual_character_branch(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__visual_narration"] = True
        ctx.state["narrator__character"] = "Alice"
        assert await summarizer.analyze_scene_narration_sub_type() == "visual-character"

    async def test_progress_character_entry(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__fn_narrate_character_entry"] = True
        assert (
            await summarizer.analyze_scene_narration_sub_type()
            == "progress-character-entry"
        )

    async def test_progress_character_exit(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__fn_narrate_character_exit"] = True
        assert (
            await summarizer.analyze_scene_narration_sub_type()
            == "progress-character-exit"
        )


# ---------------------------------------------------------------------------
# RAG sub-instruction
# ---------------------------------------------------------------------------


class TestAnalyzeSceneRagBuildSubInstruction:
    async def test_no_active_context_returns_empty(self, summarizer_scene):
        _, summarizer = summarizer_scene
        assert await summarizer.analyze_scene_rag_build_sub_instruction() == ""

    async def test_query_with_question_mark(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__query_narration"] = True
        ctx.state["narrator__query"] = "What is happening?"
        assert (
            await summarizer.analyze_scene_rag_build_sub_instruction()
            == "Answer the following question: What is happening?"
        )

    async def test_query_without_question_mark(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__query_narration"] = True
        ctx.state["narrator__query"] = "Describe the scene"
        assert (
            await summarizer.analyze_scene_rag_build_sub_instruction()
            == "Describe the scene"
        )

    async def test_sensory_with_direction(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__sensory_narration"] = True
        ctx.state["narrator__narrative_direction"] = "the smell of pine"
        result = await summarizer.analyze_scene_rag_build_sub_instruction()
        assert "sensory" in result.lower()
        assert "the smell of pine" in result

    async def test_visual_with_direction(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__visual_narration"] = True
        ctx.state["narrator__narrative_direction"] = "moonlit clearing"
        result = await summarizer.analyze_scene_rag_build_sub_instruction()
        assert "visual" in result.lower()
        assert "moonlit clearing" in result

    async def test_character_entry_with_direction(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__fn_narrate_character_entry"] = True
        ctx.state["narrator__narrative_direction"] = "Alice arrives"
        result = await summarizer.analyze_scene_rag_build_sub_instruction()
        assert "character entry" in result
        assert "Alice arrives" in result

    async def test_character_exit_with_direction(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__fn_narrate_character_exit"] = True
        ctx.state["narrator__narrative_direction"] = "Bob leaves"
        result = await summarizer.analyze_scene_rag_build_sub_instruction()
        assert "character exit" in result
        assert "Bob leaves" in result

    async def test_progress_with_direction(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__fn_narrate_progress"] = True
        ctx.state["narrator__narrative_direction"] = "tension rises"
        result = await summarizer.analyze_scene_rag_build_sub_instruction()
        assert "progressing the story" in result
        assert "tension rises" in result

    async def test_no_match_returns_empty(self, summarizer_with_active_agent):
        _, summarizer, ctx = summarizer_with_active_agent
        # No relevant state -> empty string.
        ctx.state["unrelated_state"] = True
        assert await summarizer.analyze_scene_rag_build_sub_instruction() == ""


# ---------------------------------------------------------------------------
# get_cached_analysis / set_cached_analysis
# ---------------------------------------------------------------------------


class TestCachedAnalysis:
    async def test_returns_none_when_no_cache(self, summarizer_with_active_agent):
        _, summarizer, _ = summarizer_with_active_agent
        result = await summarizer.get_cached_analysis("conversation")
        assert result is None

    async def test_round_trip_when_fingerprint_matches(
        self, summarizer_with_active_agent
    ):
        _, summarizer, _ = summarizer_with_active_agent
        await summarizer.set_cached_analysis("conversation", "the analysis text")
        result = await summarizer.get_cached_analysis("conversation")
        assert result == "the analysis text"

    async def test_returns_none_when_fingerprint_mismatches(
        self, summarizer_with_active_agent
    ):
        scene, summarizer, _ = summarizer_with_active_agent
        await summarizer.set_cached_analysis("conversation", "old analysis")

        # Tamper with the stored fingerprint to simulate a mismatch.
        cached = scene.agent_state["summarizer"]["cached_analysis_conversation"]
        cached["fp"] = "bogus-fingerprint"

        result = await summarizer.get_cached_analysis("conversation")
        assert result is None


# ---------------------------------------------------------------------------
# on_inject_instructions
# ---------------------------------------------------------------------------


class TestOnInjectInstructions:
    async def test_invalid_emission_raises(self, summarizer_scene):
        _, summarizer = summarizer_scene
        # Anything that's not Conversation/Narrator emission triggers ValueError.
        bogus = AgentTemplateEmission(agent=summarizer)
        with pytest.raises(ValueError):
            await summarizer.on_inject_instructions(bogus)

    async def test_skipped_when_action_disabled(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        summarizer.actions["analyze_scene"].enabled = False
        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )
        await summarizer.on_inject_instructions(emission)
        assert emission.dynamic_instructions == []

    async def test_skipped_when_per_type_disabled(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        summarizer.actions["analyze_scene"].enabled = True
        summarizer.actions["analyze_scene"].config["for_conversation"].value = False
        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )
        await summarizer.on_inject_instructions(emission)
        assert emission.dynamic_instructions == []

    async def test_disabled_via_context_manager(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        # Enabled, but the context manager short-circuits the function.
        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )
        with SceneAnalysisDisabled():
            await summarizer.on_inject_instructions(emission)
        assert emission.dynamic_instructions == []

    async def test_uses_cached_analysis_when_available(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        # Pre-populate cache.
        await summarizer.set_cached_analysis("conversation", "cached analysis", alice)

        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )
        # Stub analyze_scene_for_next_action to ensure we don't call it
        # when the cache is warm.
        called = []

        async def stub_analyze(*args, **kwargs):
            called.append((args, kwargs))
            return "FROM_LLM"

        summarizer.analyze_scene_for_next_action = stub_analyze

        await summarizer.on_inject_instructions(emission)
        assert called == []
        assert len(emission.dynamic_instructions) == 1
        assert emission.dynamic_instructions[0].content == "cached analysis"
        assert emission.dynamic_instructions[0].title == "Scene Analysis"

    async def test_falls_through_to_analyze_when_no_cache(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )

        captured = {}

        async def stub_analyze(typ, character, length):
            captured["typ"] = typ
            captured["character"] = character
            captured["length"] = length
            return "FRESH ANALYSIS"

        summarizer.analyze_scene_for_next_action = stub_analyze

        await summarizer.on_inject_instructions(emission)
        assert captured == {
            "typ": "conversation",
            "character": alice,
            "length": summarizer.analysis_length,
        }
        assert any(
            di.content == "FRESH ANALYSIS" for di in emission.dynamic_instructions
        )

    async def test_narrator_emission_works(self, summarizer_with_active_agent):
        _, summarizer, _ = summarizer_with_active_agent
        emission = NarratorAgentEmission(agent=summarizer, response="")

        async def stub_analyze(typ, character, length):
            return "narrator analysis"

        summarizer.analyze_scene_for_next_action = stub_analyze
        await summarizer.on_inject_instructions(emission)
        assert any(
            di.content == "narrator analysis" for di in emission.dynamic_instructions
        )

    async def test_empty_analysis_means_no_instructions_appended(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )

        async def stub_analyze(typ, character, length):
            return ""

        summarizer.analyze_scene_for_next_action = stub_analyze
        await summarizer.on_inject_instructions(emission)
        assert emission.dynamic_instructions == []


# ---------------------------------------------------------------------------
# _inject_deep_analysis_context / on_inject_deep_analysis_context
# ---------------------------------------------------------------------------


class TestInjectDeepAnalysisContext:
    async def test_does_nothing_when_deep_analysis_disabled(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        summarizer.actions["analyze_scene"].config["deep_analysis"].value = False
        # Even with state set, the function returns early.
        summarizer.set_scene_states(deep_analysis_context="ctx")

        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )
        await summarizer.on_inject_deep_analysis_context(emission)
        assert emission.dynamic_instructions == []

    async def test_injects_when_deep_analysis_enabled_and_state_set(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
        summarizer.set_scene_states(deep_analysis_context="background facts")

        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )
        await summarizer.on_inject_deep_analysis_context(emission)
        assert any(
            di.title == "Deep Analysis Context" and di.content == "background facts"
            for di in emission.dynamic_instructions
        )

    async def test_no_injection_when_deep_analysis_state_missing(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
        # No deep_analysis_context state set.
        emission = ConversationAgentEmission(
            agent=summarizer, response="", actor=None, character=alice
        )
        await summarizer.on_inject_deep_analysis_context(emission)
        assert emission.dynamic_instructions == []


# ---------------------------------------------------------------------------
# on_editor_revision_analysis_before
# ---------------------------------------------------------------------------


class TestOnEditorRevisionAnalysisBefore:
    async def test_no_state_means_no_instruction_added(
        self, summarizer_with_active_agent
    ):
        _, summarizer, _ = summarizer_with_active_agent
        emission = AgentTemplateEmission(agent=summarizer)
        await summarizer.on_editor_revision_analysis_before(emission)
        assert emission.dynamic_instructions == []

    async def test_state_appends_instruction(self, summarizer_with_active_agent):
        _, summarizer, _ = summarizer_with_active_agent
        summarizer.set_scene_states(scene_analysis="prior analysis")
        emission = AgentTemplateEmission(agent=summarizer)
        await summarizer.on_editor_revision_analysis_before(emission)
        assert len(emission.dynamic_instructions) == 1
        assert emission.dynamic_instructions[0].title == "Scene Analysis"
        assert emission.dynamic_instructions[0].content == "prior analysis"


# ---------------------------------------------------------------------------
# on_rag_build_sub_instruction
# ---------------------------------------------------------------------------


class TestOnRagBuildSubInstruction:
    async def test_no_active_context_leaves_emission_unchanged(self, summarizer_scene):
        _, summarizer = summarizer_scene
        emission = RagBuildSubInstructionEmission(agent=summarizer)
        await summarizer.on_rag_build_sub_instruction(emission)
        assert emission.sub_instruction is None

    async def test_progress_state_sets_sub_instruction(
        self, summarizer_with_active_agent
    ):
        _, summarizer, ctx = summarizer_with_active_agent
        ctx.state["narrator__fn_narrate_progress"] = True
        ctx.state["narrator__narrative_direction"] = "the storm grows"
        emission = RagBuildSubInstructionEmission(agent=summarizer)
        await summarizer.on_rag_build_sub_instruction(emission)
        assert emission.sub_instruction is not None
        assert "the storm grows" in emission.sub_instruction


# ---------------------------------------------------------------------------
# analyze_scene_for_next_action — patched Prompt.request
# ---------------------------------------------------------------------------


class TestAnalyzeSceneForNextAction:
    async def test_returns_extracted_analysis(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        from talemate.prompts import Prompt

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "raw response",
                {"analysis": "extracted analysis", "investigate": ""},
            )
            result = await summarizer.analyze_scene_for_next_action(
                "conversation", alice, length=512
            )

        assert result == "extracted analysis"
        # Scene state should have been updated with the analysis.
        assert summarizer.get_scene_state("scene_analysis") == "extracted analysis"

    async def test_returns_response_when_no_extracted_analysis(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        from talemate.prompts import Prompt

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "the raw response",
                {"analysis": None, "investigate": None},
            )
            result = await summarizer.analyze_scene_for_next_action(
                "conversation", alice, length=512
            )

        assert result == "the raw response"

    async def test_empty_result_does_not_set_scene_state(
        self, summarizer_with_active_agent, alice
    ):
        _, summarizer, _ = summarizer_with_active_agent
        from talemate.prompts import Prompt

        with patch.object(Prompt, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                "  ",  # whitespace-only -> "" after strip
                {"analysis": "  ", "investigate": ""},
            )
            result = await summarizer.analyze_scene_for_next_action(
                "conversation", alice, length=256
            )

        # Function returns the raw whitespace string but bails before setting state.
        assert result.strip() == ""
        assert summarizer.get_scene_state("scene_analysis") is None
