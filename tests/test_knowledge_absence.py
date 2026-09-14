"""
The absence block: recent facts minus the bucket minus near-duplicates.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.agents.context import ActiveAgent
from talemate.agents.memory import MemoryAgent
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.absence import absence_facts, render_absence_lines
from talemate.knowledge.chronology import DAY
from talemate.knowledge.schema import Fact, KnowledgeEdge
from talemate.tale_mate import Actor


def fact(id, text, ts, present, **kw):
    return Fact(id=id, text=text, ts=ts, present=present, **kw)


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    s.world_state.facts = {
        "F1": fact("F1", "Edwin keeps the light.", 10, ["Edwin", "Mara"]),
        "F2": fact("F2", "Mara found a sextant.", 20, ["Mara"]),
        "F3": fact(
            "F3", "Mara hid the sextant in her bag.", 30, ["Mara"], restatements=2
        ),
        "F4": fact("F4", "The boat leaks.", 40, ["Mara"]),
        "F5": fact("F5", "Edwin lies about the wreck.", 50, ["Mara"], false=True),
    }
    return s


class FakeMemory:
    def __init__(self, vectors, ready=True):
        self.vectors = vectors
        self.ready = ready

    async def get_embeddings(self, ids):
        return {i: self.vectors[i] for i in ids if i in self.vectors}

    # the real distance step over the fake vectors
    near_duplicates = MemoryAgent.near_duplicates
    _near_duplicates_in = staticmethod(MemoryAgent._near_duplicates_in)


@pytest.fixture
def embeddings():
    # standalone on purpose: a `scene` dependency would re-bootstrap the agents
    vectors = {}
    with patch(
        "talemate.knowledge.absence.get_agent", return_value=FakeMemory(vectors)
    ):
        yield vectors


class TestAbsenceFacts:
    async def test_window_is_newest_pool_before_chronology(self, scene, embeddings):
        scene.ts = 100 * DAY
        scene.active_characters = []
        # witnessed but blocked: the window still governs these
        scene.world_state.facts = {
            "F1": fact("F1", "Old milestone", 10 * DAY, ["Edwin"], importance=3),
            "F2": fact("F2", "Fresh routine", 99 * DAY, ["Edwin"], importance=1),
            "F3": fact("F3", "Fresh state", 99 * DAY, ["Edwin"], importance=2),
        }
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target=identity, kind="revoke")
            for identity in ("F1", "F2", "F3")
        ]
        result = await absence_facts(scene, "Edwin", window=2, limit=2)
        assert [item.id for item in result] == ["F3", "F2"]

    async def test_facts_that_concern_the_character_bypass_the_window(
        self, scene, embeddings
    ):
        scene.ts = 100 * DAY
        scene.active_characters = []
        scene.world_state.facts = {
            # recorded while Edwin was away, long ago
            "F1": fact(
                "F1", "Mara buried the ledger.", 10 * DAY, ["Mara"], importance=3
            ),
            # witnessed but blocked, and about Edwin
            "F2": fact(
                "F2",
                "Edwin is owed money.",
                20 * DAY,
                ["Edwin", "Mara"],
                importance=2,
                subjects=["Edwin"],
            ),
            # witnessed but blocked, not about Edwin: the window governs it
            "F3": fact("F3", "The boat leaks.", 30 * DAY, ["Edwin", "Mara"]),
            "F4": fact("F4", "The tide turned.", 99 * DAY, ["Edwin", "Mara"]),
        }
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target=identity, kind="revoke")
            for identity in ("F2", "F3", "F4")
        ]
        # the concerning facts come first, ranked by score; the window's
        # facts follow
        result = await absence_facts(scene, "Edwin", window=1, limit=5)
        assert [item.id for item in result] == ["F1", "F2", "F4"]
        # the limit cuts the ranked list
        result = await absence_facts(scene, "Edwin", window=1, limit=2)
        assert [item.id for item in result] == ["F1", "F2"]

    async def test_unknown_facts_ordered_by_score_then_recency(self, scene, embeddings):
        result = await absence_facts(scene, "Edwin")
        assert [f.id for f in result] == ["F4", "F3", "F2"]

    async def test_cap_and_window(self, scene, embeddings):
        assert [f.id for f in await absence_facts(scene, "Edwin", limit=1)] == ["F4"]
        # F2-F4 were recorded while Edwin was away: the window does not cut them
        assert [f.id for f in await absence_facts(scene, "Edwin", window=2)] == [
            "F4",
            "F3",
            "F2",
        ]

    async def test_known_character_gets_nothing(self, scene, embeddings):
        assert await absence_facts(scene, "Mara") == []

    async def test_grant_removes_from_the_block(self, scene, embeddings):
        scene.world_state.knowledge = [KnowledgeEdge(character="Edwin", target="F3")]
        assert [f.id for f in await absence_facts(scene, "Edwin")] == ["F4", "F2"]

    async def test_false_fact_is_never_listed(self, scene, embeddings):
        # no edge: outside the bucket, nothing to warn about
        assert "F5" not in [f.id for f in await absence_facts(scene, "Edwin")]
        # a grant puts it in the bucket: known, so not listed
        scene.world_state.knowledge = [KnowledgeEdge(character="Edwin", target="F5")]
        assert "F5" not in [f.id for f in await absence_facts(scene, "Edwin")]
        # grant and revoke on the same target: the revoke wins in the bucket
        # predicate, and a false fact outside the bucket is still not listed
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F5"),
            KnowledgeEdge(character="Edwin", target="F5", kind="revoke"),
        ]
        assert "F5" not in [f.id for f in await absence_facts(scene, "Edwin")]

    async def test_window_and_order_follow_the_numeric_id(self, scene, embeddings):
        # three entries of twelve facts, one ts per entry, ids F1..F36
        scene.world_state.facts = {}
        for n in range(1, 37):
            scene.world_state.facts[f"F{n}"] = fact(
                f"F{n}", f"fact {n}", 10 * ((n - 1) // 12), ["Edwin", "Mara"]
            )
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target=f"F{n}", kind="revoke")
            for n in range(1, 37)
        ]
        result = await absence_facts(scene, "Edwin", window=30, limit=40)
        ids = [f.id for f in result]
        # the window keeps F7..F36: the six oldest by creation order fall out
        assert set(ids) == {f"F{n}" for n in range(7, 37)}
        # newest first, F10 after F9 and before F2 never happens
        assert ids[:3] == ["F36", "F35", "F34"]
        assert ids[-3:] == ["F9", "F8", "F7"]

    def test_render_collapses_newlines(self, scene):
        lines = render_absence_lines(
            [fact("F1", "Mara found\na sextant.", 1, ["Mara"])], scene
        )
        assert lines == ["(Recently) Mara found a sextant."]

    async def test_near_duplicate_of_a_known_fact_is_dropped(self, scene, embeddings):
        # Edwin was told a retelling of F3; the retelling F6 is in his bucket
        scene.world_state.facts["F6"] = fact(
            "F6", "Mara has the sextant in her bag.", 60, ["Edwin", "Mara"]
        )
        embeddings.update(
            {"F3": [1.0, 0.0], "F6": [0.95, 0.05], "F2": [0.0, 1.0], "F4": [0.5, 0.5]}
        )
        result = await absence_facts(scene, "Edwin", dedupe_distance=0.15)
        assert [f.id for f in result] == ["F4", "F2"]

    async def test_missing_embeddings_keep_the_fact(self, scene, embeddings):
        embeddings.update({"F1": [1.0, 0.0]})
        assert "F3" in [f.id for f in await absence_facts(scene, "Edwin")]

    async def test_offscreen_facts_are_never_listed(self, scene, embeddings):
        scene.world_state.facts["F7"] = fact(
            "F7", "Edwin mended nets alone.", 70, ["Edwin"], source="offscreen"
        )
        assert "F7" not in [f.id for f in await absence_facts(scene, "Mara")]

    async def test_backend_not_ready_is_tolerated(self, scene):
        # a backend that is not ready skips the near-duplicate step
        with patch(
            "talemate.knowledge.absence.get_agent",
            return_value=FakeMemory({}, ready=False),
        ):
            assert [f.id for f in await absence_facts(scene, "Edwin")] == [
                "F4",
                "F3",
                "F2",
            ]


class TestConversationContainer:
    async def test_perspective_and_block_follow_the_switches(self, scene, embeddings):
        conversation = get_agent("conversation")
        edwin = Character(name="Edwin")
        with ActiveScene(scene):
            assert await conversation.knowledge_perspective(edwin) == "Edwin"
            assert await conversation.knowledge_perspective(None) is None
            assert conversation.rag_knowledge_filter(edwin) is not None
            lines = await conversation.absence_block(edwin)
            assert lines == [
                "(Recently) The boat leaks.",
                "(Recently) Mara hid the sextant in her bag.",
                "(Recently) Mara found a sextant.",
            ]

            conversation.actions["character_knowledge"].config[
                "perspective_filter"
            ].value = False
            assert await conversation.knowledge_perspective(edwin) is None
            assert conversation.rag_knowledge_filter(edwin) is None

            conversation.actions["character_knowledge"].config[
                "absence_block"
            ].value = False
            assert await conversation.absence_block(edwin) == []

            conversation.actions["character_knowledge"].config[
                "perspective_filter"
            ].value = True
            conversation.actions["character_knowledge"].config[
                "absence_block"
            ].value = True
            conversation.actions["character_knowledge"].enabled = False
            assert await conversation.knowledge_perspective(edwin) is None
            assert await conversation.absence_block(edwin) == []
            conversation.actions["character_knowledge"].enabled = True

    async def test_limit_setting(self, scene, embeddings):
        conversation = get_agent("conversation")
        conversation.actions["character_knowledge"].config["absence_limit"].value = 1
        try:
            with ActiveScene(scene):
                assert await conversation.absence_block(Character(name="Edwin")) == [
                    "(Recently) The boat leaks."
                ]
        finally:
            conversation.actions["character_knowledge"].config[
                "absence_limit"
            ].value = 5


class TestNearDuplicates:
    @pytest.fixture
    def memory(self, scene):
        memory = get_agent("memory")
        memory.db = object()
        memory._get_embeddings = lambda ids: {
            i: v
            for i, v in {
                "A": [1.0, 0.0],
                "B": [0.95, 0.05],
                "C": [0.0, 1.0],
                "D": [0.5, 0.5],
            }.items()
            if i in ids
        }
        yield memory
        memory.db = None

    # a regression of the read path (waiting on the write gate) must fail,
    # not park the worker: every read here is bounded
    @staticmethod
    async def bounded(coro):
        return await asyncio.wait_for(coro, 1)

    async def test_row_minima_against_the_bucket(self, memory):
        assert await self.bounded(
            memory.near_duplicates(["B", "C", "D"], ["A"], 0.15)
        ) == {"B"}
        assert await self.bounded(
            memory.near_duplicates(["B", "C"], ["A", "D"], 0.8)
        ) == {"B", "C"}

    async def test_missing_vectors_are_never_duplicates(self, memory):
        assert await self.bounded(
            memory.near_duplicates(["X", "B"], ["A", "Y"], 0.15)
        ) == {"B"}
        assert await self.bounded(memory.near_duplicates(["X"], ["A"], 0.15)) == set()
        assert await self.bounded(memory.near_duplicates([], ["A"], 0.15)) == set()

    async def test_unset_store_answers_with_nothing(self, memory):
        memory.db = None
        assert await self.bounded(memory.get_embeddings(["A"])) == {}
        assert await self.bounded(memory.near_duplicates(["B"], ["A"], 0.15)) == set()

    async def test_read_path_does_not_wait_for_the_write_gate(self, memory):
        memory._ready_to_add = False
        assert await self.bounded(memory.get_embeddings(["A"])) == {"A": [1.0, 0.0]}


class TestPerspectiveSwitchSites:
    """The switch reaches every filter site, not only the history and retrieval."""

    @pytest.fixture
    def edwin(self, scene):
        conversation = get_agent("conversation")
        edwin = Character(name="Edwin")
        actor = Actor(character=edwin, agent=conversation)
        actor.scene = scene
        scene.actors.append(actor)
        scene.active_characters.append("Edwin")
        scene.character_data["Edwin"] = edwin
        scene.rag_cache = {}
        yield edwin
        conversation.actions["character_knowledge"].config[
            "perspective_filter"
        ].value = True
        conversation.actions["character_knowledge"].enabled = True

    def _off(self, conversation, container=False):
        if container:
            conversation.actions["character_knowledge"].enabled = False
        else:
            conversation.actions["character_knowledge"].config[
                "perspective_filter"
            ].value = False

    async def test_viewer_for_sheets_and_pins(self, scene, edwin):
        conversation = get_agent("conversation")
        with (
            ActiveScene(scene),
            ActiveAgent(conversation, conversation.build_prompt_default),
        ):
            prompt = await conversation.build_prompt_default(edwin)
            assert prompt.vars["knowledge_viewer"] == "Edwin"
            self._off(conversation)
            prompt = await conversation.build_prompt_default(edwin)
            assert prompt.vars["knowledge_viewer"] is None

    async def test_viewer_when_the_container_is_off(self, scene, edwin):
        conversation = get_agent("conversation")
        with (
            ActiveScene(scene),
            ActiveAgent(conversation, conversation.build_prompt_default),
        ):
            self._off(conversation, container=True)
            assert conversation.rag_knowledge_viewer(edwin) is None
            assert conversation.rag_knowledge_filter(edwin) is None
            prompt = await conversation.build_prompt_default(edwin)
            assert prompt.vars["knowledge_viewer"] is None

    @pytest.mark.parametrize("method", ["questions", "queries"])
    async def test_analysis_prompts_follow_the_switch(self, scene, edwin, method):
        conversation = get_agent("conversation")
        world_state = get_agent("world_state")
        conversation.actions["use_long_term_memory"].config["cache"].value = False
        conversation.actions["use_long_term_memory"].config[
            "retrieval_method"
        ].value = method
        name = (
            "analyze_text_and_extract_context"
            if method == "questions"
            else "analyze_text_and_extract_context_via_queries"
        )
        result = "" if method == "questions" else []
        try:
            with ActiveScene(scene):
                with (
                    patch.object(
                        conversation, "semantic_context", AsyncMock(return_value=[])
                    ),
                    patch.object(scene, "context_history", return_value=[]) as history,
                    patch.object(
                        world_state, name, AsyncMock(return_value=result)
                    ) as analysis,
                ):
                    await conversation.rag_build(character=edwin)
                    assert analysis.call_args.kwargs["viewer"] == "Edwin"
                    assert analysis.call_args.kwargs["filter"] is not None
                    assert history.call_args.kwargs["perspective"] == "Edwin"

                    self._off(conversation)
                    await conversation.rag_build(character=edwin)
                    assert analysis.call_args.kwargs["viewer"] is None
                    assert analysis.call_args.kwargs["filter"] is None
                    assert history.call_args.kwargs["perspective"] is None
        finally:
            conversation.actions["use_long_term_memory"].config["cache"].value = True
            conversation.actions["use_long_term_memory"].config[
                "retrieval_method"
            ].value = "direct"

    async def test_cache_key_carries_the_switch(self, scene, edwin):
        conversation = get_agent("conversation")
        with ActiveScene(scene):
            filtered = conversation.long_term_memory_cache_key_for(edwin)
            self._off(conversation)
            shared = conversation.long_term_memory_cache_key_for(edwin)
        assert filtered != shared
        assert shared.endswith("-Edwin-shared")

    async def test_other_agents_keep_the_viewer(self, scene, edwin):
        # the hook is overridden on the conversation agent only
        narrator = get_agent("narrator")
        with ActiveScene(scene):
            assert narrator.rag_knowledge_viewer(edwin) == "Edwin"
            assert narrator.rag_knowledge_viewer(None) is None
