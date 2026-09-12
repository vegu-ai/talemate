"""Unit tests for talemate.agents.director.plan.mixin.PlanMixin.

Covers:
- Config property helpers (plan_dialogue_ratio, plan_expand_chunk_size,
  plan_outline_critique, plan_expand_critique).
- _plan_revise_narrator_content: signal-driven revision pass.
- _plan_push_and_emit_block: dispatch by block type, narrator vs character,
  empty content skip.
- plan_critique_expanded_blocks: replaces or falls back to original blocks
  based on Prompt.request output.
- plan_expand_beats: full pipeline orchestration. Prompt.request is stubbed
  with deterministic responses keyed per-template (`narrator.arc-expand`
  and `narrator.arc-expand-critique`). Verifies chunking, retry-on-leaked-tags,
  failure-after-3-attempts, beat completion, and plan emission.
"""

from __future__ import annotations

from typing import Any

import pytest

from conftest import MockScene, bootstrap_scene

import talemate.emit.async_signals as async_signals
import talemate.instance as instance
from talemate.agents.director.plan.schema import (
    Beat,
    Plan,
    PlanStatus,
)
from talemate.agents.director.plan.util import get_plan, save_plan

from _director_test_helpers import patch_prompt_request_in


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    return s


@pytest.fixture
def director(scene):
    return instance.get_agent("director")


@pytest.fixture
def narrator(scene):
    return instance.get_agent("narrator")


def _make_beats(tensions: list[float]) -> list[Beat]:
    return [
        Beat(
            description=f"beat {i + 1}",
            order=i + 1,
            tension=t,
            type="narration",
        )
        for i, t in enumerate(tensions)
    ]


@pytest.fixture
def stub_prompt(monkeypatch):
    """Replace the real ``Prompt.request`` classmethod with a queued response source.

    Patches the canonical ``talemate.prompts.base.Prompt`` class with
    ``raising=True`` so a rename or removal of ``Prompt.request`` fails
    the test instead of being papered over by a fake.
    """
    from talemate.agents.director.plan import mixin as mixin_mod

    return patch_prompt_request_in(monkeypatch, mixin_mod)


# ---------------------------------------------------------------------------
# Config property helpers
# ---------------------------------------------------------------------------


class TestPlanConfigProperties:
    def test_dialogue_ratio_returns_float(self, director):
        assert isinstance(director.plan_dialogue_ratio, float)
        assert director.plan_dialogue_ratio == 0.4

    def test_expand_chunk_size_returns_int(self, director):
        assert isinstance(director.plan_expand_chunk_size, int)
        assert director.plan_expand_chunk_size == 5

    def test_outline_critique_returns_bool(self, director):
        assert director.plan_outline_critique is True

    def test_expand_critique_returns_bool(self, director):
        assert director.plan_expand_critique is True

    def test_property_reflects_config_change(self, director):
        director.actions["plan"].config["expand_chunk_size"].value = 8
        assert director.plan_expand_chunk_size == 8

    def test_dialogue_ratio_coerces_int_to_float(self, director):
        director.actions["plan"].config["dialogue_ratio"].value = 1
        assert director.plan_dialogue_ratio == 1.0


# ---------------------------------------------------------------------------
# _plan_revise_narrator_content
# ---------------------------------------------------------------------------


class TestPlanReviseNarratorContent:
    @pytest.mark.asyncio
    async def test_signal_can_modify_response(self, director, narrator):
        signal = async_signals.get("agent.narrator.generated")

        async def listener(emission):
            emission.response = emission.response + " [revised]"

        signal.connect(listener)
        try:
            result = await director._plan_revise_narrator_content(
                narrator, "original text"
            )
            assert result == "original text [revised]"
        finally:
            signal.disconnect(listener)

    @pytest.mark.asyncio
    async def test_no_listeners_keeps_response_unchanged(self, director, narrator):
        # Even with no custom listener, the function should return the input
        # unchanged because emission.response is set to it before sending.
        result = await director._plan_revise_narrator_content(narrator, "untouched")
        assert result == "untouched"


# ---------------------------------------------------------------------------
# _plan_push_and_emit_block
# ---------------------------------------------------------------------------


class TestPlanPushAndEmitBlock:
    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_content(self, scene, director, narrator):
        block = {"type": "narrator", "content": "   "}
        assert await director._plan_push_and_emit_block(scene, block, narrator) == 0
        assert len(scene.history) == 0

    @pytest.mark.asyncio
    async def test_pushes_narrator_block_to_history(self, scene, director, narrator):
        block = {"type": "narrator", "content": "two words here"}
        words = await director._plan_push_and_emit_block(scene, block, narrator)
        assert words == 3
        assert len(scene.history) == 1
        from talemate.scene_message import NarratorMessage

        assert isinstance(scene.history[-1], NarratorMessage)
        assert "two words here" in str(scene.history[-1])

    @pytest.mark.asyncio
    async def test_pushes_character_block_to_history(self, scene, director, narrator):
        block = {"type": "character", "name": "Alice", "content": "hello there"}
        words = await director._plan_push_and_emit_block(scene, block, narrator)
        assert words == 2
        assert len(scene.history) == 1
        from talemate.scene_message import CharacterMessage

        msg = scene.history[-1]
        assert isinstance(msg, CharacterMessage)
        assert msg.character_name == "Alice"

    @pytest.mark.asyncio
    async def test_unknown_block_type_returns_zero(self, scene, director, narrator):
        block = {"type": "weird", "content": "stuff"}
        assert await director._plan_push_and_emit_block(scene, block, narrator) == 0
        assert len(scene.history) == 0


# ---------------------------------------------------------------------------
# plan_critique_expanded_blocks
# ---------------------------------------------------------------------------


class TestPlanCritiqueExpandedBlocks:
    @pytest.mark.asyncio
    async def test_replaces_with_revised_blocks(self, director, narrator, stub_prompt):
        revised_blocks = [
            {"type": "narrator", "content": "revised content"},
        ]
        stub_prompt(
            {
                "narrator.arc-expand-critique": [
                    ("raw response", {"response": revised_blocks})
                ]
            }
        )
        original = [{"type": "narrator", "content": "original"}]
        result = await director.plan_critique_expanded_blocks(original, narrator)
        assert result == revised_blocks

    @pytest.mark.asyncio
    async def test_falls_back_to_originals_when_extraction_empty(
        self, director, narrator, stub_prompt
    ):
        stub_prompt(
            {
                "narrator.arc-expand-critique": [
                    ("raw", {})  # no "response" key — fallback
                ]
            }
        )
        original = [{"type": "narrator", "content": "keep me"}]
        result = await director.plan_critique_expanded_blocks(original, narrator)
        assert result == original

    @pytest.mark.asyncio
    async def test_passes_close_arc_through_vars(self, director, narrator, stub_prompt):
        stub = stub_prompt(
            {
                "narrator.arc-expand-critique": [
                    ("raw", {"response": [{"type": "narrator", "content": "x"}]})
                ]
            }
        )
        await director.plan_critique_expanded_blocks(
            [{"type": "narrator", "content": "y"}], narrator, close_arc=True
        )
        assert stub.calls[0]["vars"]["close_arc"] is True

    @pytest.mark.asyncio
    async def test_passes_close_arc_default_false(
        self, director, narrator, stub_prompt
    ):
        stub = stub_prompt(
            {
                "narrator.arc-expand-critique": [
                    ("raw", {"response": [{"type": "narrator", "content": "x"}]})
                ]
            }
        )
        await director.plan_critique_expanded_blocks(
            [{"type": "narrator", "content": "y"}], narrator
        )
        assert stub.calls[0]["vars"]["close_arc"] is False


# ---------------------------------------------------------------------------
# plan_expand_beats — orchestration paths
# ---------------------------------------------------------------------------


def _block(content: str, type_: str = "narrator", name: str | None = None) -> dict:
    block: dict[str, Any] = {"type": type_, "content": content}
    if name is not None:
        block["name"] = name
    return block


class TestPlanExpandBeats:
    @pytest.mark.asyncio
    async def test_single_chunk_completes_all_beats(
        self, scene, director, narrator, stub_prompt
    ):
        beats = _make_beats([0.3, 0.5, 0.7])
        plan = Plan(
            instructions="x",
            tasks=list(beats),
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)

        # Single chunk — one expand call only; critique disabled (chunks <= 1).
        stub_prompt(
            {
                "narrator.arc-expand": [
                    ("ok", {"response": [_block("scene1 content here")]}),
                ],
            }
        )

        total_blocks, total_words = await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="Third person",
            chunk_size=10,
            critique=False,
        )
        assert total_blocks == 1
        assert total_words == 3
        # Beats marked completed
        loaded = get_plan(scene, plan.id)
        assert all(t.status == "completed" for t in loaded.tasks)
        # Plan auto-completes when all tasks done
        assert loaded.status == PlanStatus.completed

    @pytest.mark.asyncio
    async def test_retries_on_leaked_tags_then_succeeds(
        self, scene, director, narrator, stub_prompt
    ):
        beats = _make_beats([0.3, 0.5, 0.7])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)

        stub = stub_prompt(
            {
                "narrator.arc-expand": [
                    ("first try", {"response": [_block("Hello <NARRATOR> bad")]}),
                    ("second try", {"response": [_block("clean output here")]}),
                ],
            }
        )
        await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="Third",
            chunk_size=10,
            critique=False,
        )
        # Two expand calls — first leaked, second clean.
        expand_calls = [c for c in stub.calls if c["template"] == "narrator.arc-expand"]
        assert len(expand_calls) == 2

    @pytest.mark.asyncio
    async def test_raises_runtime_error_after_3_failed_attempts(
        self, scene, director, narrator, stub_prompt
    ):
        beats = _make_beats([0.3, 0.5, 0.7])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)

        stub_prompt(
            {
                "narrator.arc-expand": [
                    ("a", {"response": []}),  # empty -> retry
                    ("b", {"response": [_block("text <NARRATOR> bad")]}),  # leak
                    ("c", {}),  # no response key -> fallback to []
                ],
            }
        )
        with pytest.raises(RuntimeError, match="Expansion failed"):
            await director.plan_expand_beats(
                scene=scene,
                narrator=narrator,
                beats=beats,
                plan_id=plan.id,
                perspective="x",
                chunk_size=10,
                critique=False,
            )

    @pytest.mark.asyncio
    async def test_invokes_critique_when_multi_chunk(
        self, scene, director, narrator, stub_prompt
    ):
        # 6 beats, chunk_size=3 -> 2 chunks -> critique runs.
        beats = _make_beats([0.2, 0.4, 0.6, 0.5, 0.7, 0.9])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)

        stub = stub_prompt(
            {
                "narrator.arc-expand": [
                    ("c1", {"response": [_block("alpha beta")]}),
                    ("c2", {"response": [_block("gamma delta")]}),
                ],
                "narrator.arc-expand-critique": [
                    (
                        "critique",
                        {"response": [_block("revised one"), _block("revised two")]},
                    )
                ],
            }
        )
        total_blocks, total_words = await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="x",
            chunk_size=3,
            critique=True,
        )
        # The critique replaced both blocks
        assert total_blocks == 2
        # Each "revised" block is 2 words
        assert total_words == 4
        templates = [c["template"] for c in stub.calls]
        assert templates.count("narrator.arc-expand") == 2
        assert templates.count("narrator.arc-expand-critique") == 1

    @pytest.mark.asyncio
    async def test_critique_skipped_when_critique_false(
        self, scene, director, narrator, stub_prompt
    ):
        beats = _make_beats([0.2, 0.4, 0.6, 0.5, 0.7, 0.9])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)
        stub = stub_prompt(
            {
                "narrator.arc-expand": [
                    ("c1", {"response": [_block("alpha")]}),
                    ("c2", {"response": [_block("beta")]}),
                ],
            }
        )
        await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="x",
            chunk_size=3,
            critique=False,
        )
        # No critique call
        assert all(c["template"] != "narrator.arc-expand-critique" for c in stub.calls)

    @pytest.mark.asyncio
    async def test_critique_uses_agent_default_when_critique_none(
        self, scene, director, narrator, stub_prompt
    ):
        # Default config has expand_critique=True; should run critique.
        beats = _make_beats([0.2, 0.4, 0.6, 0.5, 0.7, 0.9])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)
        stub = stub_prompt(
            {
                "narrator.arc-expand": [
                    ("c1", {"response": [_block("alpha")]}),
                    ("c2", {"response": [_block("beta")]}),
                ],
                "narrator.arc-expand-critique": [
                    ("crit", {"response": [_block("revised")]}),
                ],
            }
        )
        await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="x",
            chunk_size=3,
            # critique=None uses agent default (True)
        )
        templates = [c["template"] for c in stub.calls]
        assert "narrator.arc-expand-critique" in templates

    @pytest.mark.asyncio
    async def test_uses_default_chunk_size_when_none(
        self, scene, director, narrator, stub_prompt
    ):
        # Director default expand_chunk_size = 5. Beat list of 4 stays single chunk.
        beats = _make_beats([0.2, 0.4, 0.6, 0.8])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)
        stub = stub_prompt(
            {"narrator.arc-expand": [("ok", {"response": [_block("hi")]})]},
        )
        await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="x",
            critique=False,
        )
        # Only 1 expand call since 4 <= default chunk_size of 5
        assert (
            len([c for c in stub.calls if c["template"] == "narrator.arc-expand"]) == 1
        )

    @pytest.mark.asyncio
    async def test_passes_following_beats_for_non_final_chunk(
        self, scene, director, narrator, stub_prompt
    ):
        # Chunked: 6 beats, chunk_size=3 -> 2 chunks. First chunk should get
        # following_beats from second chunk.
        beats = _make_beats([0.2, 0.4, 0.6, 0.5, 0.7, 0.9])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)
        stub = stub_prompt(
            {
                "narrator.arc-expand": [
                    ("c1", {"response": [_block("a")]}),
                    ("c2", {"response": [_block("b")]}),
                ],
            }
        )
        await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="x",
            chunk_size=3,
            critique=False,
        )
        expand_calls = [c for c in stub.calls if c["template"] == "narrator.arc-expand"]
        # First chunk has 2 following beats; last chunk has none.
        assert len(expand_calls[0]["vars"]["following_beats"]) == 2
        assert len(expand_calls[1]["vars"]["following_beats"]) == 0

    @pytest.mark.asyncio
    async def test_propagates_close_arc_to_expand_call(
        self, scene, director, narrator, stub_prompt
    ):
        beats = _make_beats([0.2, 0.4, 0.6])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)
        stub = stub_prompt(
            {
                "narrator.arc-expand": [("ok", {"response": [_block("a")]})],
            }
        )
        await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="x",
            chunk_size=10,
            critique=False,
            close_arc=True,
        )
        expand_call = stub.calls[0]
        assert expand_call["vars"]["close_arc"] is True
        assert expand_call["vars"]["arc_info"].close_arc is True

    @pytest.mark.asyncio
    async def test_returns_zero_blocks_when_blocks_empty_after_extraction(
        self, scene, director, narrator, stub_prompt
    ):
        # All-blank content: blocks present but content empty -> no history pushes.
        beats = _make_beats([0.2, 0.4, 0.6])
        plan = Plan(instructions="x", tasks=list(beats), status=PlanStatus.ready)
        save_plan(scene, plan)
        stub_prompt(
            {
                "narrator.arc-expand": [
                    ("ok", {"response": [_block("   "), _block("\n\n")]})
                ],
            }
        )
        total_blocks, total_words = await director.plan_expand_beats(
            scene=scene,
            narrator=narrator,
            beats=beats,
            plan_id=plan.id,
            perspective="x",
            chunk_size=10,
            critique=False,
        )
        assert total_blocks == 0
        assert total_words == 0
